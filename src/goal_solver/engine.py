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
    GoalCard,
    GoalSolverInput,
    GoalSolverOutput,
    GoalSolverParams,
    MarketAssumptions,
    RANKING_MODE_MATRIX,
    RankingMode,
    RiskBudget,
    RiskSummary,
    StrategicAllocation,
    StructureBudget,
    SuccessProbabilityResult,
    infer_ranking_mode,
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
    solver_params = GoalSolverParams(
        version=str(data["solver_params"]["version"]),
        n_paths=int(data["solver_params"]["n_paths"]),
        n_paths_lightweight=int(data["solver_params"]["n_paths_lightweight"]),
        seed=int(data["solver_params"]["seed"]),
        market_assumptions=market_assumptions,
        ranking_mode_default=RankingMode(str(getattr(ranking_mode_raw, "value", ranking_mode_raw))),
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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _append_model_honesty_notes(notes: list[str], inp: GoalSolverInput) -> None:
    notes.append(
        "probability_model "
        "method=parametric_monte_carlo "
        "distribution=normal "
        "historical_backtest_used=false"
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
    inp = _goal_solver_input_from_any(inp)
    params = inp.solver_params
    cashflow_schedule = _build_cashflow_schedule(inp.cashflow_plan, inp.goal.horizon_months)
    notes: list[str] = []
    ranking_mode = _resolve_ranking_mode(inp, notes)
    all_results: list[SuccessProbabilityResult] = []

    for allocation in inp.candidate_allocations:
        probability, extra, risk = _run_monte_carlo(
            allocation.weights,
            cashflow_schedule,
            inp.current_portfolio_value,
            inp.goal.goal_amount,
            params.market_assumptions,
            params.n_paths,
            params.seed,
        )
        interim_result = SuccessProbabilityResult(
            allocation_name=allocation.name,
            weights=allocation.weights,
            success_probability=probability,
            expected_terminal_value=extra["expected_terminal_value"],
            risk_summary=risk,
            is_feasible=True,
            infeasibility_reasons=[],
        )
        is_feasible, infeasibility_reasons = _check_allocation_feasibility(
            allocation,
            interim_result,
            inp.constraints,
        )
        all_results.append(
            SuccessProbabilityResult(
                allocation_name=allocation.name,
                weights=allocation.weights,
                success_probability=probability,
                expected_terminal_value=extra["expected_terminal_value"],
                risk_summary=risk,
                is_feasible=is_feasible,
                infeasibility_reasons=infeasibility_reasons,
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
            params.market_assumptions,
            params.n_paths,
            params.seed,
        )
        fallback_result = SuccessProbabilityResult(
            allocation_name=fallback.name,
            weights=fallback.weights,
            success_probability=probability,
            expected_terminal_value=extra["expected_terminal_value"],
            risk_summary=risk,
            is_feasible=True,
            infeasibility_reasons=[],
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

    structure_budget = _build_structure_budget(best_allocation, inp.constraints)
    risk_budget = _build_risk_budget(best_result, inp.constraints)
    _append_solver_context_notes(notes, inp, best_result)
    _append_model_honesty_notes(notes, inp)
    return GoalSolverOutput(
        input_snapshot_id=inp.snapshot_id,
        generated_at=_now_iso(),
        recommended_allocation=best_allocation,
        recommended_result=best_result,
        all_results=all_results,
        ranking_mode_used=ranking_mode,
        structure_budget=structure_budget,
        risk_budget=risk_budget,
        solver_notes=notes,
        params_version=params.version,
    )


def run_goal_solver_lightweight(
    weights: dict[str, float],
    baseline_inp: GoalSolverInput | dict[str, Any],
) -> tuple[float, RiskSummary]:
    baseline_inp = _goal_solver_input_from_any(baseline_inp)
    cashflow_schedule = _build_cashflow_schedule(
        baseline_inp.cashflow_plan,
        baseline_inp.goal.horizon_months,
    )
    probability, _extra, risk = _run_monte_carlo(
        weights,
        cashflow_schedule,
        baseline_inp.current_portfolio_value,
        baseline_inp.goal.goal_amount,
        baseline_inp.solver_params.market_assumptions,
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
