from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
import re
from typing import Any

from calibration.types import BehaviorState, ConstraintState, EVParams, MarketState, RuntimeOptimizerParams
from goal_solver.engine import build_account_state_baseline
from goal_solver.types import GoalSolverInput, GoalSolverOutput
from runtime_optimizer.ev_engine.types import EVState
from runtime_optimizer.types import LivePortfolioSnapshot


def _obj(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _is_idle_cash_bucket(bucket: str | None) -> bool:
    normalized = str(bucket or "").strip().lower()
    return normalized in {"cash", "cash_liquidity", "cash / liquidity", "cash/liquidity", "liquidity"}


def _reference_snapshot_date(output: dict[str, Any], baseline: dict[str, Any]) -> date:
    snapshot_ref = str(output.get("input_snapshot_id") or baseline.get("snapshot_id") or "")
    match = re.search(r"(20\d{2})(\d{2})(\d{2})T", snapshot_ref)
    if match:
        return date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
    return date.fromisoformat(str(output["generated_at"])[:10])


def validate_ev_state_inputs(
    live_portfolio: LivePortfolioSnapshot | dict[str, Any],
    constraint_state: ConstraintState | dict[str, Any],
    solver_output: GoalSolverOutput | dict[str, Any],
    solver_baseline_inp: GoalSolverInput | dict[str, Any],
    optimizer_params: RuntimeOptimizerParams | dict[str, Any],
) -> None:
    live = _obj(live_portfolio)
    constraints = _obj(constraint_state)
    output = _obj(solver_output)
    baseline = _obj(solver_baseline_inp)
    params = _obj(optimizer_params)

    total = sum(float(v) for v in live["weights"].values())
    all_cash_snapshot = (
        total <= 1e-9
        and float(live.get("total_value", 0.0)) > 0.0
        and float(live.get("available_cash", 0.0)) >= float(live.get("total_value", 0.0)) - 1e-6
    )
    assert abs(total - 1.0) < 0.01 or all_cash_snapshot, f"weights 合计 {total:.4f}，应接近 1.0"
    assert constraints.get("bucket_category"), "bucket_category 不能为空；必须显式提供，禁止字符串推断"
    unmapped = [
        bucket
        for bucket in live["weights"]
        if bucket not in constraints["bucket_category"] and not _is_idle_cash_bucket(bucket)
    ]
    assert not unmapped, f"以下资产桶未在 bucket_category 中映射：{unmapped}"
    assert live["remaining_horizon_months"] > 0
    assert live["available_cash"] >= 0
    assert 0.0 <= live["current_drawdown"] <= 1.0
    assert output["input_snapshot_id"] == baseline["snapshot_id"], (
        f"solver_output.input_snapshot_id ({output['input_snapshot_id']!r}) 与 "
        f"solver_baseline_inp.snapshot_id ({baseline['snapshot_id']!r}) 不匹配"
    )
    try:
        snapshot_date = date.fromisoformat(live["as_of_date"])
        baseline_date = _reference_snapshot_date(output, baseline)
        age_days = abs((baseline_date - snapshot_date).days)
        assert age_days <= params["max_portfolio_snapshot_age_days"], (
            f"live_portfolio.as_of_date ({live['as_of_date']}) 与基线生成日期 "
            f"({baseline_date.isoformat()}) 相差 {age_days} 天，超过允许时效"
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise AssertionError(f"日期字段格式错误，无法校验时效：{exc}") from exc
    target_buckets = set(output["recommended_allocation"]["weights"].keys())
    unknown_buckets = {
        bucket
        for bucket in live["weights"].keys()
        if bucket not in target_buckets and not _is_idle_cash_bucket(bucket)
    }
    if unknown_buckets:
        unknown_weight = sum(float(live["weights"].get(bucket, 0.0)) for bucket in unknown_buckets)
        assert unknown_weight <= 0.05, (
            f"基线目标桶外的持仓 {unknown_buckets} 权重合计 {unknown_weight:.1%}，超过 5% 容忍上限"
        )


def build_ev_state(
    solver_output: GoalSolverOutput | dict[str, Any],
    solver_baseline_inp: GoalSolverInput | dict[str, Any],
    live_portfolio: LivePortfolioSnapshot | dict[str, Any],
    market_state: MarketState | dict[str, Any],
    behavior_state: BehaviorState | dict[str, Any],
    constraint_state: ConstraintState | dict[str, Any],
    ev_params: EVParams | dict[str, Any],
) -> EVState:
    account_state = build_account_state_baseline(
        solver_output=solver_output,
        live_portfolio=live_portfolio,
        current_portfolio_value=_obj(live_portfolio)["total_value"],
    )
    return EVState.from_any(
        {
            "account": account_state,
            "market": _obj(market_state),
            "constraints": _obj(constraint_state),
            "behavior": _obj(behavior_state),
            "ev_params": _obj(ev_params),
            "goal_solver_baseline_inp": _obj(solver_baseline_inp),
        }
    )
