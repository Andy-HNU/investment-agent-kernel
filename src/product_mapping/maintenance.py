from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from product_mapping.types import BudgetStructure, ExecutionPlan, QuarterlyExecutionPolicy, TriggerRule


_BUCKET_TO_SCOPE = {
    "equity_cn": "core",
    "bond_cn": "bond",
    "gold": "gold",
    "cash_liquidity": "cash",
    "satellite": "satellite",
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _plan_payload(execution_plan: ExecutionPlan | dict[str, Any]) -> dict[str, Any]:
    if isinstance(execution_plan, dict):
        return execution_plan
    if hasattr(execution_plan, "to_dict"):
        return execution_plan.to_dict()
    return asdict(execution_plan)


def _bucket_weights(execution_plan: ExecutionPlan) -> dict[str, float]:
    payload = _plan_payload(execution_plan)
    return {
        str((item or {}).get("asset_bucket") or ""): float((item or {}).get("target_weight") or 0.0)
        for item in list(payload.get("items") or [])
        if str((item or {}).get("asset_bucket") or "").strip()
    }


def derive_budget_structure(
    *,
    execution_plan: ExecutionPlan,
    implied_required_annual_return: float | None,
    product_adjusted_success_probability: float | None,
    target_success_probability: float,
    risk_tolerance_score: float,
    horizon_months: int,
) -> BudgetStructure:
    bucket_weights = _bucket_weights(execution_plan)
    base_core = bucket_weights.get("equity_cn", 0.0)
    base_defense = bucket_weights.get("bond_cn", 0.0) + bucket_weights.get("gold", 0.0)
    base_satellite = bucket_weights.get("satellite", 0.0)
    base_cash = bucket_weights.get("cash_liquidity", 0.0)

    success_gap = max(float(target_success_probability) - float(product_adjusted_success_probability or 0.0), 0.0)
    return_pressure = max(float(implied_required_annual_return or 0.0) - 0.06, 0.0)
    short_horizon_pressure = max((36.0 - float(horizon_months)) / 36.0, 0.0)
    risk_score = _clamp(float(risk_tolerance_score), 0.0, 1.0)

    satellite_budget = _clamp(
        base_satellite
        + success_gap * 0.14
        + return_pressure * 0.60
        + risk_score * 0.06
        + short_horizon_pressure * 0.03,
        0.02,
        0.30,
    )
    cash_budget = _clamp(
        base_cash
        - success_gap * 0.05
        - return_pressure * 0.20
        - risk_score * 0.04,
        0.03,
        0.25,
    )

    remaining = max(1.0 - satellite_budget - cash_budget, 0.0)
    base_core_defense = max(base_core + base_defense, 1e-6)
    core_share = base_core / base_core_defense
    defense_share = base_defense / base_core_defense
    core_budget = round(remaining * core_share, 6)
    defense_budget = round(remaining * defense_share, 6)
    satellite_budget = round(satellite_budget, 6)
    cash_budget = round(cash_budget, 6)

    correction = round(1.0 - (core_budget + defense_budget + satellite_budget + cash_budget), 6)
    defense_budget = round(defense_budget + correction, 6)

    selection_reason = [
        "预算先承接当前执行计划的桶级目标权重。",
        "卫星预算根据目标成功率缺口、隐含所需年化、剩余期限和风险承受能力动态调整。",
        "现金预留会在追求更高目标成功率时收缩，但保留最低缓冲。",
    ]
    return BudgetStructure(
        core_budget=core_budget,
        defense_budget=defense_budget,
        satellite_budget=satellite_budget,
        cash_reserve_budget=cash_budget,
        selection_reason=selection_reason,
    )


def _build_initial_actions(execution_plan: ExecutionPlan) -> list[dict[str, Any]]:
    payload = _plan_payload(execution_plan)
    actions: list[dict[str, Any]] = []
    for item in list(payload.get("items") or []):
        item_payload = dict(item or {})
        for recommended in list(item_payload.get("recommended_products") or []):
            recommended_payload = dict(recommended or {})
            product = dict(recommended_payload.get("product") or {})
            wrapper_type = str(recommended_payload.get("wrapper_type") or "")
            intraday_estimated = wrapper_type == "fund"
            action = {
                "asset_bucket": item_payload.get("asset_bucket"),
                "scope": _BUCKET_TO_SCOPE.get(str(item_payload.get("asset_bucket") or ""), "core"),
                "product_id": recommended_payload.get("product_id"),
                "product_name": recommended_payload.get("product_name"),
                "wrapper_type": wrapper_type,
                "target_portfolio_weight": recommended_payload.get("target_portfolio_weight"),
                "target_weight_within_bucket": recommended_payload.get("target_weight_within_bucket"),
                "core_or_satellite": recommended_payload.get("core_or_satellite"),
                "intraday_estimated": intraday_estimated,
                "close_reconcile_required": intraday_estimated,
                "selection_reason": list(recommended_payload.get("selection_reason") or []),
                "market": recommended_payload.get("market"),
            }
            if product:
                action["style_tags"] = list(product.get("style_tags") or [])
            actions.append(action)
    return actions


def _build_trigger_rules(
    *,
    budget_structure: BudgetStructure,
    implied_required_annual_return: float | None,
) -> list[TriggerRule]:
    profit_take_threshold = 0.15 if (implied_required_annual_return or 0.0) >= 0.10 else 0.12
    rules = [
        TriggerRule(
            rule_id="core_drawdown_add",
            scope="core",
            trigger_type="drawdown",
            threshold=0.10,
            action="add_core_on_weakness",
            size_rule="每跌10%递增买入1.0x/1.1x/1.2x",
            note="核心仓也进入管理，不再完全静态。",
        ),
        TriggerRule(
            rule_id="core_profit_take",
            scope="core",
            trigger_type="profit_take",
            threshold=profit_take_threshold,
            action="trim_core_into_cash",
            size_rule="每达到目标收益阈值卖出1/3并回补现金储备",
            note="大行情跟上，但通过分段止盈控制回撤。",
        ),
        TriggerRule(
            rule_id="core_regime_shift",
            scope="core",
            trigger_type="regime_shift",
            threshold=1.0,
            action="rotate_core_toward_defense",
            size_rule="高波动/高相关性 regime 下收缩进攻核心暴露",
            note="regime 变化会改变核心仓维护带宽。",
        ),
        TriggerRule(
            rule_id="satellite_drawdown_scale_in",
            scope="satellite",
            trigger_type="drawdown",
            threshold=0.10,
            action="scale_into_satellite",
            size_rule="每跌10%按1.1x/1.2x/1.3x递增买入",
            note="卫星仓用于增强，但必须按预算推进，不得满仓冲动交易。",
        ),
        TriggerRule(
            rule_id="satellite_profit_take",
            scope="satellite",
            trigger_type="profit_take",
            threshold=max(profit_take_threshold, 0.15),
            action="take_profit_to_core",
            size_rule="达到收益目标后分批兑现回核心/现金",
            note="卫星仓收益优先回流核心仓与现金储备。",
        ),
        TriggerRule(
            rule_id="defense_rebalance_band",
            scope="bond",
            trigger_type="rebalance_band",
            threshold=0.05,
            action="rebalance_defense",
            size_rule="偏离目标带宽5%时回调到中枢",
            note="债券防守仓保持期限与信用结构稳定。",
        ),
        TriggerRule(
            rule_id="gold_rebalance_band",
            scope="gold",
            trigger_type="rebalance_band",
            threshold=0.04,
            action="rebalance_gold",
            size_rule="黄金偏离带宽4%时回到目标区间",
            note="黄金更多承担对冲而非追涨角色。",
        ),
        TriggerRule(
            rule_id="cash_reserve_guardrail",
            scope="cash",
            trigger_type="rebalance_band",
            threshold=max(budget_structure.cash_reserve_budget, 0.03),
            action="restore_cash_buffer",
            size_rule="现金低于目标缓冲时优先回补",
            note="现金仓用于低位补仓和执行机动性。",
        ),
    ]
    return rules


def build_quarterly_execution_policy(
    *,
    execution_plan: ExecutionPlan | dict[str, Any],
    quarter_start_date: str,
    implied_required_annual_return: float | None,
    product_adjusted_success_probability: float | None,
    target_success_probability: float,
    risk_tolerance_score: float,
    horizon_months: int,
) -> QuarterlyExecutionPolicy:
    budget_structure = derive_budget_structure(
        execution_plan=execution_plan,
        implied_required_annual_return=implied_required_annual_return,
        product_adjusted_success_probability=product_adjusted_success_probability,
        target_success_probability=target_success_probability,
        risk_tolerance_score=risk_tolerance_score,
        horizon_months=horizon_months,
    )
    initial_actions = _build_initial_actions(execution_plan)
    trigger_rules = _build_trigger_rules(
        budget_structure=budget_structure,
        implied_required_annual_return=implied_required_annual_return,
    )
    review_date = (date.fromisoformat(quarter_start_date) + timedelta(days=90)).isoformat()
    return QuarterlyExecutionPolicy(
        plan_id=str(_plan_payload(execution_plan).get("plan_id") or ""),
        quarter_start_date=quarter_start_date,
        budget_structure=budget_structure,
        initial_actions=initial_actions,
        trigger_rules=trigger_rules,
        cash_reserve_target=budget_structure.cash_reserve_budget,
        review_date=review_date,
    )
