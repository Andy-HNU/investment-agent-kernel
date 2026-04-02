from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np

from goal_solver.types import (
    AccountConstraints,
    CashFlowEvent,
    CashFlowPlan,
    DistributionInput,
    GoalCard,
    GoalSolverInput,
    GoalSolverOutput,
    GoalSolverParams,
    MarketAssumptions,
    RANKING_MODE_MATRIX,
    RankingMode,
    RiskBudget,
    RiskSummary,
    SimulationMode,
    StrategicAllocation,
    StructureBudget,
    SuccessProbabilityResult,
    infer_ranking_mode,
)


_SIMULATION_MODE_REQUIREMENTS: dict[SimulationMode, tuple[str, ...]] = {
    SimulationMode.STATIC_GAUSSIAN: (),
    SimulationMode.GARCH_T: ("garch_t_state",),
    SimulationMode.GARCH_T_DCC: ("garch_t_state", "dcc_state"),
    SimulationMode.GARCH_T_DCC_JUMP: ("garch_t_state", "dcc_state", "jump_state"),
}
_SIMULATION_MODE_ORDER = (
    SimulationMode.STATIC_GAUSSIAN,
    SimulationMode.GARCH_T,
    SimulationMode.GARCH_T_DCC,
    SimulationMode.GARCH_T_DCC_JUMP,
)


def _obj(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _goal_solver_input_from_any(value: GoalSolverInput | dict[str, Any]) -> GoalSolverInput:
    if isinstance(value, GoalSolverInput):
        return value
    data = _obj(value)
    goal = GoalCard(**dict(data["goal"]))
    cashflow_events = [
        CashFlowEvent(**dict(event))
        for event in data.get("cashflow_plan", {}).get("cashflow_events", [])
    ]
    cashflow_plan = CashFlowPlan(
        monthly_contribution=float(data["cashflow_plan"]["monthly_contribution"]),
        annual_step_up_rate=float(data["cashflow_plan"]["annual_step_up_rate"]),
        cashflow_events=cashflow_events,
    )
    constraints = AccountConstraints(
        max_drawdown_tolerance=float(data["constraints"]["max_drawdown_tolerance"]),
        ips_bucket_boundaries={
            key: tuple(item)
            for key, item in dict(data["constraints"]["ips_bucket_boundaries"]).items()
        },
        satellite_cap=float(data["constraints"]["satellite_cap"]),
        theme_caps=dict(data["constraints"]["theme_caps"]),
        qdii_cap=float(data["constraints"]["qdii_cap"]),
        liquidity_reserve_min=float(data["constraints"]["liquidity_reserve_min"]),
        bucket_category=dict(data["constraints"].get("bucket_category", {})),
        bucket_to_theme=dict(data["constraints"].get("bucket_to_theme", {})),
    )
    market_assumptions = MarketAssumptions(**dict(data["solver_params"]["market_assumptions"]))
    ranking_mode_raw = data["solver_params"].get(
        "ranking_mode_default",
        RankingMode.SUFFICIENCY_FIRST.value,
    )
    simulation_mode_raw = data["solver_params"].get(
        "simulation_mode",
        SimulationMode.STATIC_GAUSSIAN.value,
    )
    distribution_input_raw = data["solver_params"].get("distribution_input")
    distribution_input = None
    if distribution_input_raw is not None:
        distribution_input = DistributionInput(**dict(distribution_input_raw))
    solver_params = GoalSolverParams(
        version=str(data["solver_params"]["version"]),
        n_paths=int(data["solver_params"]["n_paths"]),
        n_paths_lightweight=int(data["solver_params"]["n_paths_lightweight"]),
        seed=int(data["solver_params"]["seed"]),
        market_assumptions=market_assumptions,
        shrinkage_factor=float(data["solver_params"].get("shrinkage_factor", 0.85)),
        ranking_mode_default=RankingMode(str(getattr(ranking_mode_raw, "value", ranking_mode_raw))),
        simulation_mode=SimulationMode(str(getattr(simulation_mode_raw, "value", simulation_mode_raw))),
        distribution_input=distribution_input,
    )
    candidate_allocations = [
        StrategicAllocation(**dict(item))
        for item in data.get("candidate_allocations", [])
    ]
    override_raw = data.get("ranking_mode_override")
    ranking_mode_override = None
    if override_raw is not None:
        ranking_mode_override = RankingMode(str(getattr(override_raw, "value", override_raw)))
    return GoalSolverInput(
        snapshot_id=str(data["snapshot_id"]),
        account_profile_id=str(data["account_profile_id"]),
        goal=goal,
        cashflow_plan=cashflow_plan,
        current_portfolio_value=float(data["current_portfolio_value"]),
        candidate_allocations=candidate_allocations,
        constraints=constraints,
        solver_params=solver_params,
        ranking_mode_override=ranking_mode_override,
    )


def _solver_param_note_value(
    value: GoalSolverInput | dict[str, Any],
    key: str,
) -> str:
    if isinstance(value, GoalSolverInput):
        params = value.solver_params
        raw = getattr(params, key, None)
    else:
        raw = _obj(value).get("solver_params", {}).get(key)
    if raw is None:
        return "unavailable"
    if isinstance(raw, (int, float)):
        return f"{float(raw):.4f}"
    return str(raw)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _distribution_input_availability(distribution_input: DistributionInput | None) -> dict[str, bool]:
    def _has_non_empty_mapping(value: Any) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        return any(
            isinstance(item, dict) and bool(item)
            for item in value.values()
        )

    def _has_non_empty_state(value: Any) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        return any(bool(item) for item in value.values())

    if distribution_input is None:
        return {"garch_t_state": False, "dcc_state": False, "jump_state": False}
    return {
        "garch_t_state": _has_non_empty_mapping(distribution_input.garch_t_state),
        "dcc_state": _has_non_empty_mapping(distribution_input.dcc_state),
        "jump_state": _has_non_empty_state(distribution_input.jump_state),
    }


def _supports_simulation_mode(
    mode: SimulationMode,
    distribution_input: DistributionInput | None,
) -> bool:
    availability = _distribution_input_availability(distribution_input)
    return all(availability.get(key, False) for key in _SIMULATION_MODE_REQUIREMENTS[mode])


def _resolve_simulation_mode(
    params: GoalSolverParams,
    notes: list[str] | None = None,
) -> tuple[SimulationMode, SimulationMode]:
    requested_mode = params.simulation_mode
    if _supports_simulation_mode(requested_mode, params.distribution_input):
        used_mode = requested_mode
    else:
        requested_index = _SIMULATION_MODE_ORDER.index(requested_mode)
        used_mode = SimulationMode.STATIC_GAUSSIAN
        for mode in reversed(_SIMULATION_MODE_ORDER[: requested_index + 1]):
            if _supports_simulation_mode(mode, params.distribution_input):
                used_mode = mode
                break
    if notes is not None:
        availability = _distribution_input_availability(params.distribution_input)
        missing = [
            key for key in _SIMULATION_MODE_REQUIREMENTS[requested_mode] if not availability.get(key, False)
        ]
        notes.append(
            "simulation_mode "
            f"requested={requested_mode.value} "
            f"used={used_mode.value} "
            f"downgrade={'true' if used_mode != requested_mode else 'false'} "
            f"missing={','.join(missing) if missing else 'none'}"
        )
    return requested_mode, used_mode


def _build_cashflow_schedule(plan: CashFlowPlan, horizon_months: int) -> list[float]:
    schedule: list[float] = []
    contribution = plan.monthly_contribution
    paused = False
    events_by_month: dict[int, list[CashFlowEvent]] = {}
    for event in plan.cashflow_events:
        events_by_month.setdefault(event.month_index, []).append(event)

    for month in range(horizon_months):
        if month > 0 and month % 12 == 0:
            contribution *= 1 + plan.annual_step_up_rate
        month_cf = 0.0 if paused else contribution
        for event in events_by_month.get(month, []):
            if event.event_type == "contribution_pause":
                paused = True
                month_cf = 0.0
            elif event.event_type == "contribution_resume":
                paused = False
                month_cf = contribution
            else:
                month_cf += event.amount
        schedule.append(month_cf)
    return schedule


def _is_equity_like(bucket: str) -> bool:
    return bucket.startswith("equity") or bucket in {"satellite", "technology", "growth"}


def _bucket_expected_return(bucket: str, market_state: MarketAssumptions) -> float:
    if bucket in market_state.expected_returns:
        return float(market_state.expected_returns[bucket])
    if "bond" in bucket:
        return 0.03
    if bucket in {"cash", "money_market"}:
        return 0.02
    if bucket == "gold":
        return 0.04
    if bucket == "satellite":
        return 0.09
    if _is_equity_like(bucket):
        return 0.08
    return 0.05


def _bucket_volatility(bucket: str, market_state: MarketAssumptions) -> float:
    if bucket in market_state.volatility:
        return float(market_state.volatility[bucket])
    if "bond" in bucket:
        return 0.04
    if bucket in {"cash", "money_market"}:
        return 0.01
    if bucket == "gold":
        return 0.12
    if bucket == "satellite":
        return 0.24
    if _is_equity_like(bucket):
        return 0.18
    return 0.10


def _bucket_correlation(bucket_a: str, bucket_b: str, market_state: MarketAssumptions) -> float:
    if bucket_a == bucket_b:
        return 1.0
    row = market_state.correlation_matrix.get(bucket_a, {})
    if bucket_b in row:
        return float(row[bucket_b])
    reverse_row = market_state.correlation_matrix.get(bucket_b, {})
    if bucket_a in reverse_row:
        return float(reverse_row[bucket_a])
    if "bond" in bucket_a or "bond" in bucket_b:
        return 0.15
    if bucket_a == "gold" or bucket_b == "gold":
        return 0.20
    if _is_equity_like(bucket_a) and _is_equity_like(bucket_b):
        return 0.75
    return 0.30


def _mode_adjusted_market_assumptions(
    market_state: MarketAssumptions,
    mode: SimulationMode,
    distribution_input: DistributionInput | None,
) -> MarketAssumptions:
    expected_returns = {key: float(value) for key, value in market_state.expected_returns.items()}
    volatility = {key: float(value) for key, value in market_state.volatility.items()}
    correlation_matrix = {
        key: {sub_key: float(sub_value) for sub_key, sub_value in row.items()}
        for key, row in market_state.correlation_matrix.items()
    }
    if mode == SimulationMode.STATIC_GAUSSIAN:
        return MarketAssumptions(
            expected_returns=expected_returns,
            volatility=volatility,
            correlation_matrix=correlation_matrix,
            source_name=market_state.source_name,
            dataset_version=market_state.dataset_version,
            lookback_months=market_state.lookback_months,
            historical_backtest_used=market_state.historical_backtest_used,
        )

    garch_state = distribution_input.garch_t_state if distribution_input is not None else {}
    dcc_state = distribution_input.dcc_state if distribution_input is not None else {}
    jump_state = distribution_input.jump_state if distribution_input is not None else {}

    volatility_multiplier = 1.10
    if garch_state:
        multipliers = [
            1.0 + max(0.0, float(item.get("alpha", 0.0)) + float(item.get("beta", 0.0)) - 0.80)
            for item in garch_state.values()
        ]
        volatility_multiplier = max(sum(multipliers) / len(multipliers), volatility_multiplier)
    for bucket, value in list(volatility.items()):
        volatility[bucket] = _clamp(float(value) * volatility_multiplier, 0.0, 1.50)
    for bucket, value in list(expected_returns.items()):
        expected_returns[bucket] = float(value) - 0.003

    if mode in {SimulationMode.GARCH_T_DCC, SimulationMode.GARCH_T_DCC_JUMP} and dcc_state:
        for bucket_a, row in dcc_state.items():
            target_row = correlation_matrix.setdefault(bucket_a, {})
            for bucket_b, value in row.items():
                target_row[bucket_b] = _clamp(float(value), -0.95, 0.95)
                correlation_matrix.setdefault(bucket_b, {})[bucket_a] = target_row[bucket_b]

    if mode == SimulationMode.GARCH_T_DCC_JUMP:
        jump_penalty = float(jump_state.get("expected_jump_drag", 0.01))
        jump_vol_multiplier = 1.0 + float(jump_state.get("jump_vol_multiplier", 0.15))
        for bucket, value in list(expected_returns.items()):
            expected_returns[bucket] = float(value) - jump_penalty
        for bucket, value in list(volatility.items()):
            volatility[bucket] = _clamp(float(value) * jump_vol_multiplier, 0.0, 1.50)

    return MarketAssumptions(
        expected_returns=expected_returns,
        volatility=volatility,
        correlation_matrix=correlation_matrix,
        source_name=market_state.source_name,
        dataset_version=market_state.dataset_version,
        lookback_months=market_state.lookback_months,
        historical_backtest_used=market_state.historical_backtest_used,
    )


def _portfolio_params(weights: dict[str, float], market_state: MarketAssumptions) -> tuple[float, float]:
    mu_annual = 0.0
    variance_annual = 0.0
    buckets = list(weights)
    for bucket, weight in weights.items():
        mu_annual += weight * _bucket_expected_return(bucket, market_state)
    for bucket_a in buckets:
        for bucket_b in buckets:
            variance_annual += (
                weights[bucket_a]
                * weights[bucket_b]
                * _bucket_volatility(bucket_a, market_state)
                * _bucket_volatility(bucket_b, market_state)
                * _bucket_correlation(bucket_a, bucket_b, market_state)
            )
    sigma_annual = math.sqrt(max(variance_annual, 0.0))
    return mu_annual, sigma_annual


def _monthly_return_params(weights: dict[str, float], market_state: MarketAssumptions) -> tuple[float, float]:
    mu_annual, sigma_annual = _portfolio_params(weights, market_state)
    mu_monthly = (1.0 + mu_annual) ** (1.0 / 12.0) - 1.0 if mu_annual > -0.999 else -0.99
    sigma_monthly = sigma_annual / math.sqrt(12.0)
    return mu_monthly, sigma_monthly


def _compute_path_drawdowns(values: np.ndarray) -> np.ndarray:
    running_max = np.maximum.accumulate(values, axis=1)
    safe_running_max = np.maximum(running_max, 1e-9)
    drawdowns = (running_max - values) / safe_running_max
    return np.max(drawdowns, axis=1)


def _liquid_weight(weights: dict[str, float]) -> float:
    explicit = weights.get("cash", 0.0) + weights.get("money_market", 0.0)
    if explicit > 0.0:
        return explicit
    return sum(
        weight
        for bucket, weight in weights.items()
        if "bond" in bucket or bucket in {"cash", "money_market"}
    )


def _is_satellite_bucket(bucket: str, constraints: AccountConstraints) -> bool:
    category = constraints.bucket_category.get(bucket)
    if category is not None:
        return category == "satellite"
    return bucket == "satellite" or bucket.endswith("_satellite")


def _satellite_weight(weights: dict[str, float], constraints: AccountConstraints) -> float:
    return sum(weight for bucket, weight in weights.items() if _is_satellite_bucket(bucket, constraints))


def _theme_weight(weights: dict[str, float], theme: str, constraints: AccountConstraints) -> float:
    if constraints.bucket_to_theme:
        return sum(
            weight
            for bucket, weight in weights.items()
            if constraints.bucket_to_theme.get(bucket) == theme
        )
    return sum(
        weight
        for bucket, weight in weights.items()
        if bucket == theme or bucket.endswith(f"_{theme}")
    )


def _core_weight(weights: dict[str, float], constraints: AccountConstraints) -> float:
    if constraints.bucket_category:
        return sum(
            weight for bucket, weight in weights.items() if constraints.bucket_category.get(bucket) == "core"
        )
    return sum(weight for bucket, weight in weights.items() if bucket.startswith("equity"))


def _defense_weight(weights: dict[str, float], constraints: AccountConstraints) -> float:
    if constraints.bucket_category:
        return sum(
            weight
            for bucket, weight in weights.items()
            if constraints.bucket_category.get(bucket) == "defense"
        )
    return sum(
        weight
        for bucket, weight in weights.items()
        if "bond" in bucket or bucket in {"gold", "cash", "money_market"}
    )


def _run_monte_carlo(
    weights: dict[str, float],
    cashflow_schedule: list[float],
    initial_value: float,
    goal_amount: float,
    market_state: MarketAssumptions,
    n_paths: int,
    seed: int,
) -> tuple[float, dict[str, float], RiskSummary]:
    horizon = max(len(cashflow_schedule), 1)
    paths = max(int(n_paths), 1)
    rng = np.random.default_rng(int(seed))
    mu_monthly, sigma_monthly = _monthly_return_params(weights, market_state)

    monthly_returns = rng.normal(
        loc=mu_monthly,
        scale=max(sigma_monthly, 0.0),
        size=(paths, horizon),
    )
    monthly_returns = np.clip(monthly_returns, -0.99, None)

    values = np.zeros((paths, horizon + 1), dtype=float)
    values[:, 0] = float(initial_value)
    cashflows = list(cashflow_schedule) if cashflow_schedule else [0.0]
    for month in range(horizon):
        month_cf = float(cashflows[month] if month < len(cashflows) else 0.0)
        values[:, month + 1] = values[:, month] * (1.0 + monthly_returns[:, month]) + month_cf
        values[:, month + 1] = np.maximum(values[:, month + 1], 0.0)

    terminal_values = values[:, -1]
    expected_terminal_value = float(np.mean(terminal_values))
    probability = float(np.mean(terminal_values >= float(goal_amount)))
    drawdowns = _compute_path_drawdowns(values)
    max_drawdown_90pct = float(np.percentile(drawdowns, 90))
    p5_terminal = float(np.percentile(terminal_values, 5))
    tail_mask = terminal_values <= p5_terminal
    terminal_value_tail_mean_95 = float(np.mean(terminal_values[tail_mask])) if np.any(tail_mask) else p5_terminal
    risk = RiskSummary(
        max_drawdown_90pct=_clamp(max_drawdown_90pct, 0.0, 0.99),
        terminal_value_tail_mean_95=max(terminal_value_tail_mean_95, 0.0),
        shortfall_probability=float(np.mean(terminal_values < float(goal_amount))),
        terminal_shortfall_p5_vs_initial=_clamp(
            (float(initial_value) - p5_terminal) / max(float(initial_value), 1.0),
            -1.0,
            5.0,
        ),
    )
    extra = {"expected_terminal_value": expected_terminal_value}
    return probability, extra, risk


def _check_allocation_feasibility(
    allocation: StrategicAllocation,
    result: SuccessProbabilityResult,
    constraints: AccountConstraints,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    weights = allocation.weights
    for bucket, (lower, upper) in constraints.ips_bucket_boundaries.items():
        bucket_weight = weights.get(bucket, 0.0)
        if bucket_weight < lower - 1e-4 or bucket_weight > upper + 1e-4:
            reasons.append(
                f"ips_boundary_violation bucket={bucket} weight={bucket_weight:.4f} lower={lower:.4f} upper={upper:.4f}"
            )

    sat_weight = _satellite_weight(weights, constraints)
    if sat_weight > constraints.satellite_cap + 1e-4:
        reasons.append(
            f"satellite_cap_violation weight={sat_weight:.4f} cap={constraints.satellite_cap:.4f}"
        )

    for theme, cap in constraints.theme_caps.items():
        theme_used = _theme_weight(weights, theme, constraints)
        if theme_used > cap + 1e-4:
            reasons.append(f"theme_cap_violation theme={theme} weight={theme_used:.4f} cap={cap:.4f}")

    if result.risk_summary.max_drawdown_90pct > constraints.max_drawdown_tolerance:
        reasons.append(
            "drawdown_violation "
            f"drawdown={result.risk_summary.max_drawdown_90pct:.4f} "
            f"tolerance={constraints.max_drawdown_tolerance:.4f}"
        )

    liquid_weight = _liquid_weight(weights)
    if liquid_weight < constraints.liquidity_reserve_min - 1e-4:
        reasons.append(
            f"liquidity_violation weight={liquid_weight:.4f} min={constraints.liquidity_reserve_min:.4f}"
        )

    return len(reasons) == 0, reasons


def _ranking_score(
    result: SuccessProbabilityResult,
    allocation: StrategicAllocation,
    threshold: float,
    mode: RankingMode,
) -> tuple[float | bool, ...]:
    success_probability = result.success_probability
    max_drawdown = result.risk_summary.max_drawdown_90pct
    complexity = -allocation.complexity_score

    if mode == RankingMode.SUFFICIENCY_FIRST:
        meets_threshold = success_probability >= threshold
        return (meets_threshold, -max_drawdown, success_probability, complexity)
    if mode == RankingMode.PROBABILITY_MAX:
        return (success_probability, -max_drawdown, complexity)
    if mode == RankingMode.BALANCED:
        weighted = 0.6 * success_probability + 0.4 * (1.0 - max_drawdown)
        return (weighted, complexity)
    return (success_probability, -max_drawdown, complexity)


def _find_allocation(candidates: list[StrategicAllocation], name: str) -> StrategicAllocation:
    for allocation in candidates:
        if allocation.name == name:
            return allocation
    raise ValueError(f"allocation_not_found name={name}")


def _infeasibility_score(
    result: SuccessProbabilityResult,
    allocation: StrategicAllocation,
    constraints: AccountConstraints,
) -> float:
    weights = allocation.weights
    score = 0.0

    drawdown = result.risk_summary.max_drawdown_90pct
    if drawdown > constraints.max_drawdown_tolerance:
        score += 2.0 * (drawdown - constraints.max_drawdown_tolerance) / max(
            constraints.max_drawdown_tolerance,
            1e-6,
        )

    for bucket, (lower, upper) in constraints.ips_bucket_boundaries.items():
        bucket_weight = weights.get(bucket, 0.0)
        if bucket_weight > upper:
            score += 1.5 * (bucket_weight - upper) / max(upper, 1e-6)
        elif bucket_weight < lower and lower > 0.0:
            score += 1.5 * (lower - bucket_weight) / lower

    sat_weight = _satellite_weight(weights, constraints)
    if sat_weight > constraints.satellite_cap:
        score += (sat_weight - constraints.satellite_cap) / max(constraints.satellite_cap, 1e-6)

    for theme, cap in constraints.theme_caps.items():
        theme_used = _theme_weight(weights, theme, constraints)
        if theme_used > cap:
            score += (theme_used - cap) / max(cap, 1e-6)

    liquid_weight = _liquid_weight(weights)
    if liquid_weight < constraints.liquidity_reserve_min and constraints.liquidity_reserve_min > 0.0:
        score += 0.5 * (constraints.liquidity_reserve_min - liquid_weight) / constraints.liquidity_reserve_min

    return score


def _handle_no_feasible_allocation(
    all_results: list[SuccessProbabilityResult],
    candidates: list[StrategicAllocation],
    constraints: AccountConstraints,
) -> tuple[StrategicAllocation, SuccessProbabilityResult, list[str]]:
    scored = [
        (
            result,
            _find_allocation(candidates, result.allocation_name),
            _infeasibility_score(result, _find_allocation(candidates, result.allocation_name), constraints),
        )
        for result in all_results
    ]
    best_result, best_allocation, best_score = min(scored, key=lambda item: item[2])
    dominant_reasons = _summarize_infeasibility_reasons(all_results)
    notes = [
        "warning=no_feasible_allocation",
        f"fallback=closest_feasible_candidate allocation={best_allocation.name}",
        f"fallback_pressure_score allocation={best_allocation.name} score={best_score:.4f}",
        f"fallback_dominant_constraints reasons={dominant_reasons}",
        _selected_fallback_context_note(best_result),
        "action_required=reassess_goal_amount_or_horizon_or_drawdown_or_candidate_allocations",
    ]
    return best_allocation, best_result, notes


def _summarize_infeasibility_reasons(all_results: list[SuccessProbabilityResult]) -> str:
    reason_counts: dict[str, int] = {}
    for result in all_results:
        for reason in result.infeasibility_reasons:
            reason_key = reason.split()[0]
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
    if not reason_counts:
        return "unknown"
    ordered = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    return ",".join(reason for reason, _count in ordered[:3])


def _selected_fallback_context_note(result: SuccessProbabilityResult) -> str:
    reason_to_input = {
        "drawdown_violation": "drawdown_tolerance",
        "ips_boundary_violation": "ips_bucket_boundaries",
        "satellite_cap_violation": "satellite_cap",
        "theme_cap_violation": "theme_caps",
        "liquidity_violation": "liquidity_reserve_min",
    }
    reason_keys: list[str] = []
    score_inputs: list[str] = []
    for reason in result.infeasibility_reasons:
        reason_key = reason.split()[0]
        if reason_key not in reason_keys:
            reason_keys.append(reason_key)
        score_input = reason_to_input.get(reason_key, "other_constraints")
        if score_input not in score_inputs:
            score_inputs.append(score_input)
    reasons_summary = ",".join(reason_keys[:3]) if reason_keys else "unknown"
    score_inputs_summary = ",".join(score_inputs[:3]) if score_inputs else "other_constraints"
    return (
        "fallback_selected_context "
        f"allocation={result.allocation_name} "
        f"reasons={reasons_summary} "
        f"score_inputs={score_inputs_summary}"
    )


def _build_structure_budget(
    allocation: StrategicAllocation,
    constraints: AccountConstraints,
) -> StructureBudget:
    weights = allocation.weights
    theme_remaining_budget = {
        theme: cap - _theme_weight(weights, theme, constraints)
        for theme, cap in constraints.theme_caps.items()
    }
    satellite_weight = _satellite_weight(weights, constraints)
    return StructureBudget(
        core_weight=_core_weight(weights, constraints),
        defense_weight=_defense_weight(weights, constraints),
        satellite_weight=satellite_weight,
        theme_remaining_budget=theme_remaining_budget,
        satellite_remaining_cap=constraints.satellite_cap - satellite_weight,
    )


def _build_risk_budget(
    result: SuccessProbabilityResult,
    constraints: AccountConstraints,
) -> RiskBudget:
    return RiskBudget(
        drawdown_budget_used_pct=_clamp(
            result.risk_summary.max_drawdown_90pct / max(constraints.max_drawdown_tolerance, 1e-9),
            0.0,
            10.0,
        )
    )


def _terminal_value_at_monthly_rate(
    initial_value: float,
    cashflow_schedule: list[float],
    monthly_rate: float,
) -> float:
    terminal_value = float(initial_value)
    for contribution in cashflow_schedule:
        terminal_value = terminal_value * (1.0 + monthly_rate) + float(contribution)
    return terminal_value


def _implied_required_annual_return(
    *,
    initial_value: float,
    cashflow_schedule: list[float],
    goal_amount: float,
) -> float | None:
    target = float(goal_amount)
    if target <= 0.0:
        return 0.0

    low = -0.95
    high = 0.10
    if _terminal_value_at_monthly_rate(initial_value, cashflow_schedule, low) >= target:
        return (1.0 + low) ** 12 - 1.0

    while _terminal_value_at_monthly_rate(initial_value, cashflow_schedule, high) < target and high < 1.0:
        high = high * 2.0 + 0.05
    if _terminal_value_at_monthly_rate(initial_value, cashflow_schedule, high) < target:
        return None

    for _ in range(80):
        mid = (low + high) / 2.0
        if _terminal_value_at_monthly_rate(initial_value, cashflow_schedule, mid) >= target:
            high = mid
        else:
            low = mid
    return (1.0 + high) ** 12 - 1.0


def _complexity_label(score: float) -> str:
    if score <= 0.15:
        return "low"
    if score <= 0.30:
        return "medium"
    return "high"


def _decorate_result(
    allocation: StrategicAllocation,
    result: SuccessProbabilityResult,
    implied_required_annual_return: float | None,
) -> SuccessProbabilityResult:
    return SuccessProbabilityResult(
        allocation_name=result.allocation_name,
        weights=result.weights,
        success_probability=result.success_probability,
        expected_terminal_value=result.expected_terminal_value,
        risk_summary=result.risk_summary,
        is_feasible=result.is_feasible,
        implied_required_annual_return=implied_required_annual_return,
        display_name=allocation.display_name or allocation.name,
        summary=allocation.user_summary or allocation.description,
        complexity_label=_complexity_label(allocation.complexity_score),
        infeasibility_reasons=list(result.infeasibility_reasons),
    )


def _highest_probability_result(all_results: list[SuccessProbabilityResult]) -> SuccessProbabilityResult | None:
    if not all_results:
        return None
    return max(
        all_results,
        key=lambda result: (
            result.success_probability,
            -result.risk_summary.max_drawdown_90pct,
            result.expected_terminal_value,
        ),
    )


def _resolve_ranking_mode(inp: GoalSolverInput, notes: list[str]) -> RankingMode:
    if inp.ranking_mode_override is not None:
        mode = inp.ranking_mode_override
        notes.append(
            "ranking_mode="
            f"{mode.value} "
            f"priority={inp.goal.priority} "
            f"risk_preference={inp.goal.risk_preference} "
            f"source=override"
        )
        return mode
    mode = infer_ranking_mode(inp.goal.priority, inp.goal.risk_preference)
    notes.append(
        "ranking_mode="
        f"{mode.value} "
        f"priority={inp.goal.priority} "
        f"risk_preference={inp.goal.risk_preference} "
        "source=matrix"
    )
    return mode


def _append_solver_context_notes(
    notes: list[str],
    inp: GoalSolverInput,
    recommended_result: SuccessProbabilityResult,
) -> None:
    threshold_gap = max(inp.goal.success_prob_threshold - recommended_result.success_probability, 0.0)
    notes.append(
        "monte_carlo "
        f"paths={inp.solver_params.n_paths} "
        f"seed={inp.solver_params.seed} "
        f"horizon_months={inp.goal.horizon_months}"
    )
    notes.append(
        "success_threshold "
        f"threshold={inp.goal.success_prob_threshold:.4f} "
        f"recommended={recommended_result.success_probability:.4f} "
        f"gap={threshold_gap:.4f} "
        f"met={'true' if threshold_gap <= 1e-9 else 'false'}"
    )
    notes.append(
        "recommended_feasibility "
        f"allocation={recommended_result.allocation_name} "
        f"is_feasible={'true' if recommended_result.is_feasible else 'false'} "
        f"shortfall_probability={recommended_result.risk_summary.shortfall_probability:.4f}"
    )


def _append_model_honesty_notes(
    notes: list[str],
    inp: GoalSolverInput,
    shrinkage_factor_note_value: str,
    requested_mode: SimulationMode,
    used_mode: SimulationMode,
) -> None:
    historical_backtest_used = bool(inp.solver_params.market_assumptions.historical_backtest_used)
    if requested_mode == SimulationMode.STATIC_GAUSSIAN and used_mode == SimulationMode.STATIC_GAUSSIAN:
        notes.append(
            "probability_model "
            "method=parametric_monte_carlo "
            "distribution=normal "
            f"historical_backtest_used={'true' if historical_backtest_used else 'false'}"
        )
    else:
        notes.append(
            "probability_model "
            "method=parametric_monte_carlo "
            f"distribution={used_mode.value} "
            f"requested_mode={requested_mode.value} "
            f"historical_backtest_used={'true' if historical_backtest_used else 'false'}"
        )
    if historical_backtest_used:
        notes.append(
            "historical_dataset "
            f"source={inp.solver_params.market_assumptions.source_name or 'unknown'} "
            f"version={inp.solver_params.market_assumptions.dataset_version or 'unknown'} "
            f"lookback_months={inp.solver_params.market_assumptions.lookback_months or 0}"
        )
    else:
        notes.append(
            "monte_carlo_limitations "
            f"shrinkage_factor={shrinkage_factor_note_value} "
            "limitation=static_parametric_inputs_non_historical"
        )
    notes.append(
        "goal_semantics "
        f"basis={inp.goal.goal_amount_basis} "
        f"scope={inp.goal.goal_amount_scope} "
        f"tax={inp.goal.tax_assumption} "
        f"fee={inp.goal.fee_assumption}"
    )
    notes.append(
        "contribution_confidence "
        f"value={inp.goal.contribution_commitment_confidence:.4f} "
        "absorbed_into_solver=false"
    )


def run_goal_solver(inp: GoalSolverInput | dict[str, Any]) -> GoalSolverOutput:
    shrinkage_factor_note_value = _solver_param_note_value(inp, "shrinkage_factor")
    inp = _goal_solver_input_from_any(inp)
    params = inp.solver_params
    cashflow_schedule = _build_cashflow_schedule(inp.cashflow_plan, inp.goal.horizon_months)
    notes: list[str] = []
    ranking_mode = _resolve_ranking_mode(inp, notes)
    requested_mode, used_mode = _resolve_simulation_mode(params, notes)
    simulation_market_state = _mode_adjusted_market_assumptions(
        params.market_assumptions,
        used_mode,
        params.distribution_input,
    )
    implied_required_annual_return = _implied_required_annual_return(
        initial_value=inp.current_portfolio_value,
        cashflow_schedule=cashflow_schedule,
        goal_amount=inp.goal.goal_amount,
    )
    all_results: list[SuccessProbabilityResult] = []

    for allocation in inp.candidate_allocations:
        probability, extra, risk = _run_monte_carlo(
            allocation.weights,
            cashflow_schedule,
            inp.current_portfolio_value,
            inp.goal.goal_amount,
            simulation_market_state,
            params.n_paths,
            params.seed,
        )
        interim_result = _decorate_result(
            allocation,
            SuccessProbabilityResult(
                allocation_name=allocation.name,
                weights=allocation.weights,
                success_probability=probability,
                expected_terminal_value=extra["expected_terminal_value"],
                risk_summary=risk,
                is_feasible=True,
                infeasibility_reasons=[],
            ),
            implied_required_annual_return,
        )
        is_feasible, infeasibility_reasons = _check_allocation_feasibility(
            allocation,
            interim_result,
            inp.constraints,
        )
        all_results.append(
            _decorate_result(
                allocation,
                SuccessProbabilityResult(
                    allocation_name=allocation.name,
                    weights=allocation.weights,
                    success_probability=probability,
                    expected_terminal_value=extra["expected_terminal_value"],
                    risk_summary=risk,
                    is_feasible=is_feasible,
                    infeasibility_reasons=infeasibility_reasons,
                ),
                implied_required_annual_return,
            )
        )

    if not all_results:
        fallback = StrategicAllocation(
            name="fallback",
            weights={"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
            complexity_score=0.10,
            description="synthetic fallback allocation",
        )
        probability, extra, risk = _run_monte_carlo(
            fallback.weights,
            cashflow_schedule,
            inp.current_portfolio_value,
            inp.goal.goal_amount,
            simulation_market_state,
            params.n_paths,
            params.seed,
        )
        fallback_result = _decorate_result(
            fallback,
            SuccessProbabilityResult(
                allocation_name=fallback.name,
                weights=fallback.weights,
                success_probability=probability,
                expected_terminal_value=extra["expected_terminal_value"],
                risk_summary=risk,
                is_feasible=True,
                infeasibility_reasons=[],
            ),
            implied_required_annual_return,
        )
        all_results = [fallback_result]
        best_allocation = fallback
        best_result = fallback_result
        notes.append("warning=empty_candidate_allocations synthetic_fallback_used")
    else:
        feasible_results = [result for result in all_results if result.is_feasible]
        if feasible_results:
            best_result = max(
                feasible_results,
                key=lambda result: _ranking_score(
                    result,
                    _find_allocation(inp.candidate_allocations, result.allocation_name),
                    inp.goal.success_prob_threshold,
                    ranking_mode,
                ),
            )
            best_allocation = _find_allocation(inp.candidate_allocations, best_result.allocation_name)
            if best_result.success_probability < inp.goal.success_prob_threshold:
                notes.append(
                    "warning=success_probability_below_threshold "
                    f"threshold={inp.goal.success_prob_threshold:.4f} "
                    f"recommended={best_result.success_probability:.4f}"
                )
        else:
            best_allocation, best_result, fallback_notes = _handle_no_feasible_allocation(
                all_results,
                inp.candidate_allocations,
                inp.constraints,
            )
            notes.extend(fallback_notes)

    highest_probability_result = _highest_probability_result(all_results)
    structure_budget = _build_structure_budget(best_allocation, inp.constraints)
    risk_budget = _build_risk_budget(best_result, inp.constraints)
    _append_solver_context_notes(notes, inp, best_result)
    _append_model_honesty_notes(
        notes,
        inp,
        shrinkage_factor_note_value,
        requested_mode,
        used_mode,
    )
    return GoalSolverOutput(
        input_snapshot_id=inp.snapshot_id,
        generated_at=_now_iso(),
        recommended_allocation=best_allocation,
        recommended_result=best_result,
        all_results=all_results,
        ranking_mode_used=ranking_mode,
        structure_budget=structure_budget,
        risk_budget=risk_budget,
        simulation_mode_used=used_mode,
        highest_probability_result=highest_probability_result,
        solver_notes=notes,
        params_version=params.version,
        candidate_menu=[item.to_dict() for item in all_results],
    )


def run_goal_solver_lightweight(
    weights: dict[str, float],
    baseline_inp: GoalSolverInput | dict[str, Any],
) -> tuple[float, RiskSummary]:
    baseline_inp = _goal_solver_input_from_any(baseline_inp)
    _requested_mode, used_mode = _resolve_simulation_mode(baseline_inp.solver_params)
    cashflow_schedule = _build_cashflow_schedule(
        baseline_inp.cashflow_plan,
        baseline_inp.goal.horizon_months,
    )
    probability, _extra, risk = _run_monte_carlo(
        weights,
        cashflow_schedule,
        baseline_inp.current_portfolio_value,
        baseline_inp.goal.goal_amount,
        _mode_adjusted_market_assumptions(
            baseline_inp.solver_params.market_assumptions,
            used_mode,
            baseline_inp.solver_params.distribution_input,
        ),
        baseline_inp.solver_params.n_paths_lightweight,
        baseline_inp.solver_params.seed,
    )
    return probability, risk


def build_account_state_baseline(
    solver_output: GoalSolverOutput | dict[str, Any],
    live_portfolio: Any,
    current_portfolio_value: float,
) -> dict[str, Any]:
    solver_output_dict = _obj(solver_output)
    live = _obj(live_portfolio)
    recommended = solver_output_dict["recommended_allocation"]
    structure_budget = solver_output_dict["structure_budget"]
    return {
        "current_weights": dict(live["weights"]),
        "target_weights": dict(recommended["weights"]),
        "goal_gap": float(
            live.get(
                "goal_gap",
                max(
                    0.0,
                    solver_output_dict["recommended_result"]["expected_terminal_value"] - current_portfolio_value,
                ),
            )
        ),
        "success_prob_baseline": float(solver_output_dict["recommended_result"]["success_probability"]),
        "horizon_months": int(live["remaining_horizon_months"]),
        "available_cash": float(live["available_cash"]),
        "total_portfolio_value": float(live["total_value"]),
        "theme_remaining_budget": dict(structure_budget.get("theme_remaining_budget", {})),
    }
