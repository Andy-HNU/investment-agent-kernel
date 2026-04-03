from __future__ import annotations

import pytest

from product_mapping import build_execution_plan
from tests.helpers.contracts import assert_has_keys


def _build_base_plan(*, restrictions: list[str] | None = None):
    return build_execution_plan(
        source_run_id="run_product_maintenance",
        source_allocation_id="allocation_product_maintenance",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.25,
            "gold": 0.15,
            "cash_liquidity": 0.10,
            "satellite": 0.05,
        },
        restrictions=restrictions or [],
    )


@pytest.mark.contract
def test_derive_budget_structure_surfaces_all_budget_buckets_and_sums_to_one():
    from product_mapping import derive_budget_structure

    budget = derive_budget_structure(
        execution_plan=_build_base_plan(),
        implied_required_annual_return=0.08,
        product_adjusted_success_probability=0.52,
        target_success_probability=0.80,
        risk_tolerance_score=0.60,
        horizon_months=36,
    )

    payload = budget.to_dict()
    assert_has_keys(
        payload,
        ["core_budget", "defense_budget", "satellite_budget", "cash_reserve_budget", "selection_reason"],
    )
    total = (
        payload["core_budget"]
        + payload["defense_budget"]
        + payload["satellite_budget"]
        + payload["cash_reserve_budget"]
    )
    assert total == pytest.approx(1.0, abs=1e-6)
    assert payload["core_budget"] > 0
    assert payload["defense_budget"] > 0
    assert payload["cash_reserve_budget"] > 0


@pytest.mark.contract
def test_satellite_budget_expands_when_gap_is_large_and_risk_capacity_is_higher():
    from product_mapping import derive_budget_structure

    conservative = derive_budget_structure(
        execution_plan=_build_base_plan(),
        implied_required_annual_return=0.06,
        product_adjusted_success_probability=0.74,
        target_success_probability=0.80,
        risk_tolerance_score=0.35,
        horizon_months=48,
    )
    stretched = derive_budget_structure(
        execution_plan=_build_base_plan(),
        implied_required_annual_return=0.12,
        product_adjusted_success_probability=0.38,
        target_success_probability=0.80,
        risk_tolerance_score=0.72,
        horizon_months=24,
    )

    assert stretched.satellite_budget > conservative.satellite_budget
    assert stretched.cash_reserve_budget < conservative.cash_reserve_budget


@pytest.mark.contract
def test_build_quarterly_execution_policy_emits_core_and_satellite_trigger_rules():
    from product_mapping import build_quarterly_execution_policy

    policy = build_quarterly_execution_policy(
        execution_plan=_build_base_plan(),
        quarter_start_date="2026-04-01",
        implied_required_annual_return=0.09,
        product_adjusted_success_probability=0.44,
        target_success_probability=0.80,
        risk_tolerance_score=0.58,
        horizon_months=30,
    )

    payload = policy.to_dict()
    assert_has_keys(payload, ["budget_structure", "initial_actions", "trigger_rules", "cash_reserve_target", "review_date"])
    scopes = {rule["scope"] for rule in payload["trigger_rules"]}
    trigger_types = {rule["trigger_type"] for rule in payload["trigger_rules"]}
    assert "core" in scopes
    assert "satellite" in scopes
    assert {"drawdown", "profit_take", "rebalance_band"}.issubset(trigger_types)


@pytest.mark.contract
def test_build_quarterly_execution_policy_marks_fund_estimates_for_intraday_monitoring():
    from product_mapping import build_quarterly_execution_policy

    plan = _build_base_plan(restrictions=["不买股票"])
    policy = build_quarterly_execution_policy(
        execution_plan=plan,
        quarter_start_date="2026-04-01",
        implied_required_annual_return=0.08,
        product_adjusted_success_probability=0.61,
        target_success_probability=0.80,
        risk_tolerance_score=0.55,
        horizon_months=36,
    )

    estimated_actions = [
        action for action in policy.initial_actions if action.get("wrapper_type") == "fund"
    ]
    assert estimated_actions, "场外基金/联接基金应进入盘中估算监控路径"
    assert all(action["intraday_estimated"] is True for action in estimated_actions)
    assert all(action["close_reconcile_required"] is True for action in estimated_actions)


@pytest.mark.contract
def test_build_quarterly_execution_policy_keeps_core_bucket_under_management_actions():
    from product_mapping import build_quarterly_execution_policy

    policy = build_quarterly_execution_policy(
        execution_plan=_build_base_plan(),
        quarter_start_date="2026-04-01",
        implied_required_annual_return=0.11,
        product_adjusted_success_probability=0.41,
        target_success_probability=0.80,
        risk_tolerance_score=0.68,
        horizon_months=24,
    )

    core_rules = [rule for rule in policy.trigger_rules if rule.scope == "core"]
    assert core_rules, "核心仓也必须进入维护策略，而不是完全静态"
    assert any(rule.trigger_type in {"drawdown", "profit_take", "regime_shift"} for rule in core_rules)
