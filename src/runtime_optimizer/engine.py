from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from calibration.types import EVParams, MarketState, BehaviorState, ConstraintState, RuntimeOptimizerParams
from goal_solver.types import GoalSolverInput, GoalSolverOutput
from runtime_optimizer.candidates import ActionType, generate_candidates
from runtime_optimizer.ev_engine.engine import run_ev_engine
from runtime_optimizer.state_builder import build_ev_state, validate_ev_state_inputs
from runtime_optimizer.types import LivePortfolioSnapshot, RuntimeOptimizerMode, RuntimeOptimizerResult


def run_runtime_optimizer(
    solver_output: GoalSolverOutput | dict[str, Any],
    solver_baseline_inp: GoalSolverInput | dict[str, Any],
    live_portfolio: LivePortfolioSnapshot | dict[str, Any],
    market_state: MarketState | dict[str, Any],
    behavior_state: BehaviorState | dict[str, Any],
    constraint_state: ConstraintState | dict[str, Any],
    ev_params: EVParams | dict[str, Any],
    optimizer_params: RuntimeOptimizerParams | dict[str, Any],
    mode: RuntimeOptimizerMode,
    structural_event: bool = False,
    behavior_event: bool = False,
    drawdown_event: bool = False,
    satellite_event: bool = False,
) -> RuntimeOptimizerResult:
    validate_ev_state_inputs(
        live_portfolio=live_portfolio,
        constraint_state=constraint_state,
        solver_output=solver_output,
        solver_baseline_inp=solver_baseline_inp,
        optimizer_params=optimizer_params,
    )
    ev_state = build_ev_state(
        solver_output=solver_output,
        solver_baseline_inp=solver_baseline_inp,
        live_portfolio=live_portfolio,
        market_state=market_state,
        behavior_state=behavior_state,
        constraint_state=constraint_state,
        ev_params=ev_params,
    )
    candidates = generate_candidates(
        state=ev_state,
        params=optimizer_params,
        mode=mode,
        structural_event=structural_event,
        behavior_event=behavior_event,
        drawdown_event=drawdown_event,
        satellite_event=satellite_event,
    )
    ev_report = run_ev_engine(state=ev_state, candidate_actions=candidates, trigger_type=mode.value)
    ev_report, candidate_poverty = _apply_poverty_protocol(ev_report)
    result = RuntimeOptimizerResult(
        mode=mode,
        ev_report=ev_report,
        state_snapshot=ev_state,
        candidates_generated=len(candidates),
        candidates_after_filter=len(ev_report.ranked_actions),
        candidate_poverty=candidate_poverty,
        run_timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        optimizer_params_version=str(_obj(optimizer_params).get("version", "")),
        goal_solver_params_version=str(_obj(solver_output).get("params_version", "")),
    )
    return result


def _apply_poverty_protocol(ev_report: Any) -> tuple[Any, bool]:
    if len(getattr(ev_report, "ranked_actions", [])) >= 2:
        return ev_report, False

    safe_types = {ActionType.FREEZE, ActionType.OBSERVE}
    safe_results = [
        result
        for result in getattr(ev_report, "ranked_actions", [])
        if getattr(getattr(result, "action", None), "type", None) in safe_types
    ]

    ev_report.confidence_flag = "low"
    ev_report.goal_solver_after_recommended = ev_report.goal_solver_baseline
    if safe_results:
        safe_result = safe_results[0]
        ev_report.recommended_action = safe_result.action
        ev_report.recommended_score = safe_result.score
        ev_report.confidence_reason = "候选通过过滤数量过少，已降级为安全动作优先"
        return ev_report, True

    ev_report.recommended_action = None
    ev_report.recommended_score = None
    ev_report.confidence_reason = "候选通过过滤数量过少，且不存在安全动作可推荐"
    return ev_report, True


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value
