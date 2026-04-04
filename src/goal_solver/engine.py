from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import inspect
import math
from typing import Any

import numpy as np

from goal_solver.types import (
    AccountConstraints,
    CashFlowEvent,
    CashFlowPlan,
    FrontierAnalysis,
    FrontierScenario,
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


_SIMULATION_MODE_ORDER = {
    "static_gaussian": 0,
    "garch_t": 1,
    "garch_t_dcc": 2,
    "garch_t_dcc_jump": 3,
}


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
        shrinkage_factor=float(data["solver_params"].get("shrinkage_factor", 0.85)),
        ranking_mode_default=RankingMode(str(getattr(ranking_mode_raw, "value", ranking_mode_raw))),
        simulation_mode_requested=str(
            data["solver_params"].get("simulation_mode_requested", "static_gaussian")
        ),
        simulation_frequency=str(data["solver_params"].get("simulation_frequency", "monthly")),
        regime_sensitive=bool(data["solver_params"].get("regime_sensitive", False)),
        jump_overlay_enabled=bool(data["solver_params"].get("jump_overlay_enabled", False)),
        distribution_model_state=_obj(data["solver_params"].get("distribution_model_state")),
        simulation_mode_auto_selected=bool(
            data["solver_params"].get("simulation_mode_auto_selected", False)
        ),
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


def _mode_rank(mode: str) -> int:
    return _SIMULATION_MODE_ORDER.get(str(mode or "static_gaussian").strip().lower(), 0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _project_terminal_value(
    *,
    initial_value: float,
    cashflow_schedule: list[float],
    monthly_rate: float,
) -> float:
    value = float(initial_value)
    horizon = max(len(cashflow_schedule), 1)
    for month in range(horizon):
        month_cf = float(cashflow_schedule[month] if month < len(cashflow_schedule) else 0.0)
        value = value * (1.0 + monthly_rate) + month_cf
    return float(value)


def _effective_success_probability(result: SuccessProbabilityResult) -> float:
    adjusted = result.product_adjusted_success_probability
    if adjusted is not None:
        return float(adjusted)
    return float(result.success_probability)


def _solve_implied_required_annual_return(
    *,
    initial_value: float,
    cashflow_schedule: list[float],
    goal_amount: float,
) -> float | None:
    target = float(goal_amount)
    if target <= 0.0:
        return None

    lower = -0.999
    upper = 0.02
    lower_value = _project_terminal_value(
        initial_value=float(initial_value),
        cashflow_schedule=cashflow_schedule,
        monthly_rate=lower,
    )
    upper_value = _project_terminal_value(
        initial_value=float(initial_value),
        cashflow_schedule=cashflow_schedule,
        monthly_rate=upper,
    )
    while upper_value < target and upper < 5.0:
        upper = upper * 2.0 + 0.01
        upper_value = _project_terminal_value(
            initial_value=float(initial_value),
            cashflow_schedule=cashflow_schedule,
            monthly_rate=upper,
        )

    if lower_value > target:
        return (1.0 + lower) ** 12 - 1.0
    if upper_value < target:
        return None

    for _ in range(100):
        mid = (lower + upper) / 2.0
        mid_value = _project_terminal_value(
            initial_value=float(initial_value),
            cashflow_schedule=cashflow_schedule,
            monthly_rate=mid,
        )
        if mid_value >= target:
            upper = mid
        else:
            lower = mid
    return (1.0 + upper) ** 12 - 1.0


def _scenario_expected_annual_return(
    *,
    initial_value: float,
    cashflow_schedule: list[float],
    expected_terminal_value: float,
) -> float | None:
    return _solve_implied_required_annual_return(
        initial_value=initial_value,
        cashflow_schedule=cashflow_schedule,
        goal_amount=expected_terminal_value,
    )


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


def _resolve_simulation_mode(params: GoalSolverParams) -> tuple[str, bool, str | None]:
    requested = str(params.simulation_mode_requested or "static_gaussian").strip().lower() or "static_gaussian"
    distribution_state = _obj(params.distribution_model_state or {})
    available_modes = [str(mode).strip().lower() for mode in list(distribution_state.get("available_modes") or []) if str(mode).strip()]

    if requested == "static_gaussian":
        return "static_gaussian", bool(params.simulation_mode_auto_selected), None

    if not available_modes:
        return "static_gaussian", True, "distribution_model_state_missing"

    compatible = [mode for mode in available_modes if _mode_rank(mode) <= _mode_rank(requested)]
    if compatible:
        used = max(compatible, key=_mode_rank)
        return used, bool(params.simulation_mode_auto_selected or used != requested), None
    return "static_gaussian", True, "requested_mode_unsupported"


def _regime_sigma_multiplier(distribution_model_state: dict[str, Any] | None) -> float:
    state = _obj(distribution_model_state or {})
    overrides = _obj(state.get("regime_overrides") or {})
    return float(overrides.get("risk_multiplier", 1.0) or 1.0)


def _regime_corr_multiplier(distribution_model_state: dict[str, Any] | None) -> float:
    state = _obj(distribution_model_state or {})
    overrides = _obj(state.get("regime_overrides") or {})
    return float(overrides.get("correlation_multiplier", 1.0) or 1.0)


def _regime_jump_multiplier(distribution_model_state: dict[str, Any] | None) -> float:
    state = _obj(distribution_model_state or {})
    overrides = _obj(state.get("regime_overrides") or {})
    return float(overrides.get("jump_intensity_multiplier", 1.0) or 1.0)


def _t_scale(df: float) -> float:
    if df <= 2.0:
        return 1.0
    return math.sqrt((df - 2.0) / df)


def _distribution_garch_state_map(distribution_model_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    state = _obj(distribution_model_state or {})
    return {
        str(item.get("bucket_id")): _obj(item)
        for item in list(state.get("garch_states") or [])
        if _obj(item).get("bucket_id") is not None
    }


def _distribution_dcc_state(distribution_model_state: dict[str, Any] | None) -> dict[str, Any]:
    state = _obj(distribution_model_state or {})
    return _obj(state.get("dcc_state") or {})


def _distribution_jump_state(distribution_model_state: dict[str, Any] | None) -> dict[str, Any]:
    state = _obj(distribution_model_state or {})
    return _obj(state.get("jump_state") or {})


def _multivariate_normal_with_corr(
    rng: np.random.Generator,
    corr_matrix: np.ndarray,
    size: tuple[int, int],
) -> np.ndarray:
    safe_corr = np.array(corr_matrix, dtype=float)
    safe_corr = (safe_corr + safe_corr.T) / 2.0
    np.fill_diagonal(safe_corr, 1.0)
    try:
        return rng.multivariate_normal(mean=np.zeros(safe_corr.shape[0]), cov=safe_corr, size=size)
    except np.linalg.LinAlgError:
        safe_corr = safe_corr + np.eye(safe_corr.shape[0]) * 1e-6
        return rng.multivariate_normal(mean=np.zeros(safe_corr.shape[0]), cov=safe_corr, size=size)


def _run_monte_carlo_dispatch(
    weights: dict[str, float],
    cashflow_schedule: list[float],
    initial_value: float,
    goal_amount: float,
    market_state: MarketAssumptions,
    n_paths: int,
    seed: int,
    *,
    simulation_mode: str,
    distribution_model_state: dict[str, Any] | None,
) -> tuple[float, dict[str, float], RiskSummary]:
    signature = inspect.signature(_run_monte_carlo)
    if "simulation_mode" in signature.parameters:
        return _run_monte_carlo(
            weights,
            cashflow_schedule,
            initial_value,
            goal_amount,
            market_state,
            n_paths,
            seed,
            simulation_mode=simulation_mode,
            distribution_model_state=distribution_model_state,
        )
    return _run_monte_carlo(
        weights,
        cashflow_schedule,
        initial_value,
        goal_amount,
        market_state,
        n_paths,
        seed,
    )


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
    simulation_mode: str = "static_gaussian",
    distribution_model_state: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float], RiskSummary]:
    horizon = max(len(cashflow_schedule), 1)
    paths = max(int(n_paths), 1)
    rng = np.random.default_rng(int(seed))
    simulation_mode = str(simulation_mode or "static_gaussian").strip().lower() or "static_gaussian"

    if simulation_mode == "static_gaussian":
        mu_monthly, sigma_monthly = _monthly_return_params(weights, market_state)
        monthly_returns = rng.normal(
            loc=mu_monthly,
            scale=max(sigma_monthly, 0.0),
            size=(paths, horizon),
        )
    else:
        ordered_buckets = [bucket for bucket in sorted(weights) if float(weights.get(bucket, 0.0)) > 0.0]
        monthly_returns = np.zeros((paths, horizon), dtype=float)
        if ordered_buckets:
            bucket_weights = np.array([float(weights[bucket]) for bucket in ordered_buckets], dtype=float)
            garch_state_map = _distribution_garch_state_map(distribution_model_state)
            dcc_state = _distribution_dcc_state(distribution_model_state)
            jump_state = _distribution_jump_state(distribution_model_state)
            risk_multiplier = _regime_sigma_multiplier(distribution_model_state)
            corr_multiplier = _regime_corr_multiplier(distribution_model_state)
            jump_multiplier = _regime_jump_multiplier(distribution_model_state)

            mu_vec = np.array(
                [
                    ((1.0 + _bucket_expected_return(bucket, market_state)) ** (1.0 / 12.0) - 1.0)
                    if _bucket_expected_return(bucket, market_state) > -0.999
                    else -0.99
                    for bucket in ordered_buckets
                ],
                dtype=float,
            )
            sigma2_vec = np.array(
                [
                    max(
                        float(_obj(garch_state_map.get(bucket, {})).get("last_sigma2", (_bucket_volatility(bucket, market_state) / math.sqrt(12.0)) ** 2)),
                        1e-8,
                    )
                    * risk_multiplier
                    for bucket in ordered_buckets
                ],
                dtype=float,
            )
            corr_base = np.array(
                [
                    [
                        float(_bucket_correlation(bucket, peer, market_state))
                        for peer in ordered_buckets
                    ]
                    for bucket in ordered_buckets
                ],
                dtype=float,
            )
            if dcc_state:
                corr_base = np.array(
                    [
                        [
                            float(_obj(dcc_state.get("last_corr", {})).get(bucket, {}).get(peer, corr_base[row_idx, col_idx]))
                            for col_idx, peer in enumerate(ordered_buckets)
                        ]
                        for row_idx, bucket in enumerate(ordered_buckets)
                    ],
                    dtype=float,
                )
            np.fill_diagonal(corr_base, 1.0)
            q_bar = np.array(
                [
                    [
                        float(_obj(dcc_state.get("long_run_corr", {})).get(bucket, {}).get(peer, corr_base[row_idx, col_idx]))
                        for col_idx, peer in enumerate(ordered_buckets)
                    ]
                    for row_idx, bucket in enumerate(ordered_buckets)
                ],
                dtype=float,
            ) if dcc_state else corr_base.copy()
            q_current = np.array(
                [
                    [
                        float(_obj(dcc_state.get("last_q", {})).get(bucket, {}).get(peer, corr_base[row_idx, col_idx]))
                        for col_idx, peer in enumerate(ordered_buckets)
                    ]
                    for row_idx, bucket in enumerate(ordered_buckets)
                ],
                dtype=float,
            ) if dcc_state else corr_base.copy()
            dcc_a = float(dcc_state.get("a", 0.03) or 0.03) if dcc_state else 0.03
            dcc_b = float(dcc_state.get("b", 0.94) or 0.94) if dcc_state else 0.94
            prev_std_shocks = np.zeros((paths, len(ordered_buckets)), dtype=float)
            t_df = float(
                min(
                    max(
                        [
                            float(_obj(garch_state_map.get(bucket, {})).get("nu", 7.0) or 7.0)
                            for bucket in ordered_buckets
                        ]
                        or [7.0]
                    ),
                    30.0,
                )
            )
            t_df = max(t_df, 4.0)

            for month in range(horizon):
                if simulation_mode in {"garch_t_dcc", "garch_t_dcc_jump"}:
                    if month > 0:
                        sample_cov = (prev_std_shocks.T @ prev_std_shocks) / max(paths, 1)
                        q_current = (1.0 - dcc_a - dcc_b) * q_bar + dcc_a * sample_cov + dcc_b * q_current
                    diag = np.sqrt(np.maximum(np.diag(q_current), 1e-8))
                    corr_matrix = q_current / np.outer(diag, diag)
                else:
                    corr_matrix = corr_base
                corr_matrix = np.clip(corr_matrix * corr_multiplier, -0.95, 0.95)
                np.fill_diagonal(corr_matrix, 1.0)
                normals = _multivariate_normal_with_corr(rng, corr_matrix, (paths,))
                t_scale = np.sqrt(t_df / rng.chisquare(t_df, size=paths))[:, None] * _t_scale(t_df)
                std_shocks = normals * t_scale
                sigma_vec = np.sqrt(np.maximum(sigma2_vec, 1e-8))
                bucket_returns = mu_vec + std_shocks * sigma_vec

                if simulation_mode == "garch_t_dcc_jump" and jump_state:
                    systemic = _obj(jump_state.get("systemic_jump", {}))
                    systemic_intensity = float(systemic.get("intensity", 0.0) or 0.0) * jump_multiplier
                    systemic_flags = rng.random(paths) < systemic_intensity
                    scale = float(_obj(systemic.get("jump_size_dist", {})).get("scale", 0.05) or 0.05)
                    systemic_sizes = rng.normal(loc=-abs(scale), scale=max(scale / 2.0, 1e-6), size=paths)
                    loadings = _obj(systemic.get("loading", {}))
                    for bucket_idx, bucket in enumerate(ordered_buckets):
                        loading = float(loadings.get(bucket, -1.0 if _is_equity_like(bucket) or bucket == "satellite" else 0.25))
                        bucket_returns[:, bucket_idx] += systemic_flags * systemic_sizes * loading
                    for bucket_idx, bucket in enumerate(ordered_buckets):
                        bucket_jump_model = _obj(_obj(jump_state.get("bucket_jump_models", {})).get(bucket, {}))
                        if not bucket_jump_model:
                            continue
                        jump_intensity = float(bucket_jump_model.get("jump_intensity", 0.0) or 0.0) * jump_multiplier
                        jump_flags = rng.random(paths) < jump_intensity
                        jump_mean = float(bucket_jump_model.get("jump_mean", 0.0) or 0.0)
                        jump_vol = float(bucket_jump_model.get("jump_vol", 0.01) or 0.01)
                        bucket_returns[:, bucket_idx] += jump_flags * rng.normal(jump_mean, max(jump_vol, 1e-6), size=paths)

                monthly_returns[:, month] = bucket_returns @ bucket_weights

                for bucket_idx, bucket in enumerate(ordered_buckets):
                    state = _obj(garch_state_map.get(bucket, {}))
                    alpha = float(state.get("alpha", 0.08) or 0.08)
                    beta = float(state.get("beta", 0.90) or 0.90)
                    omega = float(state.get("omega", 1e-6) or 1e-6)
                    residual_sq = float(np.mean((bucket_returns[:, bucket_idx] - mu_vec[bucket_idx]) ** 2))
                    sigma2_vec[bucket_idx] = max(omega + alpha * residual_sq + beta * sigma2_vec[bucket_idx], 1e-8)
                prev_std_shocks = std_shocks

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
    success_probability = _effective_success_probability(result)
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


def _frontier_gap_score(
    *,
    scenario_expected_annual_return: float | None,
    effective_success_probability: float,
    required_annual_return: float | None,
    max_drawdown_90pct: float,
    drawdown_tolerance: float,
) -> tuple[float, float, float]:
    target_return_gap = 0.0
    if required_annual_return is not None and scenario_expected_annual_return is not None:
        target_return_gap = max(required_annual_return - scenario_expected_annual_return, 0.0)
    drawdown_gap = max(max_drawdown_90pct - drawdown_tolerance, 0.0)
    success_gap = max(1.0 - effective_success_probability, 0.0)
    return target_return_gap, drawdown_gap, success_gap


def _build_unavailable_frontier_scenario(
    *,
    scenario_id: str,
    rationale: str,
) -> FrontierScenario:
    return FrontierScenario(
        scenario_id=scenario_id,
        allocation_name="",
        weights={},
        success_probability=0.0,
        expected_terminal_value=0.0,
        max_drawdown_90pct=0.0,
        product_adjusted_success_probability=None,
        expected_annual_return=None,
        meets_success_threshold=False,
        drawdown_gap=0.0,
        target_return_gap=0.0,
        rationale=rationale,
    )


def _build_frontier_scenario(
    *,
    scenario_id: str,
    result: SuccessProbabilityResult,
    allocation: StrategicAllocation,
    scenario_expected_annual_return: float | None,
    required_annual_return: float | None,
    success_probability_threshold: float,
    max_drawdown_tolerance: float,
) -> FrontierScenario:
    expected_annual_return = scenario_expected_annual_return
    effective_success_probability = _effective_success_probability(result)
    target_return_gap, drawdown_gap, _success_gap = _frontier_gap_score(
        scenario_expected_annual_return=expected_annual_return,
        effective_success_probability=effective_success_probability,
        required_annual_return=required_annual_return,
        max_drawdown_90pct=result.risk_summary.max_drawdown_90pct,
        drawdown_tolerance=max_drawdown_tolerance,
    )
    if scenario_id == "recommended":
        rationale = "当前推荐方案，同时权衡达成率、回撤和执行复杂度。"
    elif scenario_id == "highest_probability":
        rationale = "当前候选里，这个方案的产品修正后达成率最高。"
    elif scenario_id == "target_return_priority":
        rationale = "如果优先贴近目标收益，这个方案最接近隐含所需年化。"
    elif scenario_id == "drawdown_priority":
        rationale = "如果优先守住回撤约束，这个方案更稳。"
    else:
        rationale = "这个方案在达成率与回撤之间更均衡。"
    return FrontierScenario(
        scenario_id=scenario_id,
        allocation_name=allocation.name,
        weights=dict(result.weights),
        success_probability=result.success_probability,
        product_adjusted_success_probability=result.product_adjusted_success_probability,
        expected_terminal_value=result.expected_terminal_value,
        max_drawdown_90pct=result.risk_summary.max_drawdown_90pct,
        expected_annual_return=expected_annual_return,
        meets_success_threshold=effective_success_probability >= success_probability_threshold,
        drawdown_gap=drawdown_gap,
        target_return_gap=target_return_gap,
        rationale=rationale,
    )


def _build_frontier_analysis(
    *,
    inp: GoalSolverInput,
    recommended_result: SuccessProbabilityResult,
    all_results: list[SuccessProbabilityResult],
    cashflow_schedule: list[float],
) -> FrontierAnalysis | None:
    if not all_results:
        return None

    allocation_map = {allocation.name: allocation for allocation in inp.candidate_allocations}
    required_annual_return = _solve_implied_required_annual_return(
        initial_value=inp.current_portfolio_value,
        cashflow_schedule=cashflow_schedule,
        goal_amount=inp.goal.goal_amount,
    )
    scenario_expected_returns = {
        result.allocation_name: _scenario_expected_annual_return(
            initial_value=inp.current_portfolio_value,
            cashflow_schedule=cashflow_schedule,
            expected_terminal_value=result.expected_terminal_value,
        )
        for result in all_results
    }

    target_return_eligible = [
        item
        for item in all_results
        if required_annual_return is None
        or (
            scenario_expected_returns.get(item.allocation_name) is not None
            and (scenario_expected_returns.get(item.allocation_name) or 0.0) >= required_annual_return
        )
    ]
    drawdown_eligible = [
        item
        for item in all_results
        if item.risk_summary.max_drawdown_90pct <= inp.constraints.max_drawdown_tolerance
    ]

    highest_probability = max(
        all_results,
        key=lambda item: (
            _effective_success_probability(item),
            -item.risk_summary.max_drawdown_90pct,
            item.expected_terminal_value,
        ),
    )
    target_return_priority = (
        min(
            target_return_eligible,
            key=lambda item: (
                max((required_annual_return or 0.0) - (scenario_expected_returns.get(item.allocation_name) or -999.0), 0.0),
                item.risk_summary.max_drawdown_90pct,
                -_effective_success_probability(item),
            ),
        )
        if target_return_eligible
        else None
    )
    drawdown_priority = (
        min(
            drawdown_eligible,
            key=lambda item: (
                max(item.risk_summary.max_drawdown_90pct - inp.constraints.max_drawdown_tolerance, 0.0),
                item.risk_summary.max_drawdown_90pct,
                -_effective_success_probability(item),
            ),
        )
        if drawdown_eligible
        else None
    )

    success_values = [_effective_success_probability(item) for item in all_results]
    return_gaps = [
        max((required_annual_return or 0.0) - ((scenario_expected_returns.get(item.allocation_name) or -999.0)), 0.0)
        for item in all_results
    ]
    drawdown_gaps = [
        max(item.risk_summary.max_drawdown_90pct - inp.constraints.max_drawdown_tolerance, 0.0)
        for item in all_results
    ]
    success_span = max(max(success_values) - min(success_values), 1e-6)
    return_span = max(max(return_gaps) - min(return_gaps), 1e-6)
    drawdown_span = max(max(drawdown_gaps) - min(drawdown_gaps), 1e-6)

    balanced_tradeoff = min(
        all_results,
        key=lambda item: (
            (
                (max(success_values) - _effective_success_probability(item)) / success_span
                + (max((required_annual_return or 0.0) - ((scenario_expected_returns.get(item.allocation_name) or -999.0)), 0.0) - min(return_gaps)) / return_span
                + (max(item.risk_summary.max_drawdown_90pct - inp.constraints.max_drawdown_tolerance, 0.0) - min(drawdown_gaps)) / drawdown_span
            ),
            item.risk_summary.max_drawdown_90pct,
            -_effective_success_probability(item),
        ),
    )

    scenario_status = {
        "recommended": {
            "available": True,
            "constraint_met": _effective_success_probability(recommended_result) >= inp.goal.success_prob_threshold,
            "reason": "selected_by_goal_solver_ranking",
        },
        "highest_probability": {
            "available": True,
            "constraint_met": _effective_success_probability(highest_probability) >= inp.goal.success_prob_threshold,
            "reason": "selected_by_max_effective_success_probability",
        },
        "target_return_priority": {
            "available": bool(target_return_eligible),
            "constraint_met": bool(target_return_eligible),
            "reason": (
                "selected_by_required_annual_return"
                if target_return_eligible
                else "no_candidate_meets_required_annual_return"
            ),
        },
        "drawdown_priority": {
            "available": bool(drawdown_eligible),
            "constraint_met": bool(drawdown_eligible),
            "reason": (
                "selected_by_max_drawdown_tolerance"
                if drawdown_eligible
                else "no_candidate_meets_max_drawdown_tolerance"
            ),
        },
        "balanced_tradeoff": {
            "available": True,
            "constraint_met": _effective_success_probability(balanced_tradeoff) >= inp.goal.success_prob_threshold,
            "reason": "selected_by_balanced_frontier_score",
        },
    }

    def _allocation_for(result: SuccessProbabilityResult) -> StrategicAllocation:
        return allocation_map.get(
            result.allocation_name,
            StrategicAllocation(
                name=result.allocation_name,
                weights=dict(result.weights),
                complexity_score=0.0,
                description="derived frontier allocation",
            ),
        )

    return FrontierAnalysis(
        implied_required_annual_return=required_annual_return,
        success_probability_threshold=inp.goal.success_prob_threshold,
        max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
        recommended=_build_frontier_scenario(
            scenario_id="recommended",
            result=recommended_result,
            allocation=_allocation_for(recommended_result),
            scenario_expected_annual_return=scenario_expected_returns.get(recommended_result.allocation_name),
            required_annual_return=required_annual_return,
            success_probability_threshold=inp.goal.success_prob_threshold,
            max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
        ),
        highest_probability=_build_frontier_scenario(
            scenario_id="highest_probability",
            result=highest_probability,
            allocation=_allocation_for(highest_probability),
            scenario_expected_annual_return=scenario_expected_returns.get(highest_probability.allocation_name),
            required_annual_return=required_annual_return,
            success_probability_threshold=inp.goal.success_prob_threshold,
            max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
        ),
        target_return_priority=(
            _build_frontier_scenario(
                scenario_id="target_return_priority",
                result=target_return_priority,
                allocation=_allocation_for(target_return_priority),
                scenario_expected_annual_return=scenario_expected_returns.get(target_return_priority.allocation_name),
                required_annual_return=required_annual_return,
                success_probability_threshold=inp.goal.success_prob_threshold,
                max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
            )
            if target_return_priority is not None
            else _build_unavailable_frontier_scenario(
                scenario_id="target_return_priority",
                rationale="当前候选里没有方案满足目标收益约束。",
            )
        ),
        drawdown_priority=(
            _build_frontier_scenario(
                scenario_id="drawdown_priority",
                result=drawdown_priority,
                allocation=_allocation_for(drawdown_priority),
                scenario_expected_annual_return=scenario_expected_returns.get(drawdown_priority.allocation_name),
                required_annual_return=required_annual_return,
                success_probability_threshold=inp.goal.success_prob_threshold,
                max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
            )
            if drawdown_priority is not None
            else _build_unavailable_frontier_scenario(
                scenario_id="drawdown_priority",
                rationale="当前候选里没有方案满足最大回撤约束。",
            )
        ),
        balanced_tradeoff=_build_frontier_scenario(
            scenario_id="balanced_tradeoff",
            result=balanced_tradeoff,
            allocation=_allocation_for(balanced_tradeoff),
            scenario_expected_annual_return=scenario_expected_returns.get(balanced_tradeoff.allocation_name),
            required_annual_return=required_annual_return,
            success_probability_threshold=inp.goal.success_prob_threshold,
            max_drawdown_tolerance=inp.constraints.max_drawdown_tolerance,
        ),
        scenario_status=scenario_status,
    )


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
    recommended_probability = _effective_success_probability(recommended_result)
    threshold_gap = max(inp.goal.success_prob_threshold - recommended_probability, 0.0)
    notes.append(
        "monte_carlo "
        f"paths={inp.solver_params.n_paths} "
        f"seed={inp.solver_params.seed} "
        f"horizon_months={inp.goal.horizon_months}"
    )
    notes.append(
        "success_threshold "
        f"threshold={inp.goal.success_prob_threshold:.4f} "
        f"recommended={recommended_probability:.4f} "
        f"gap={threshold_gap:.4f} "
        f"met={'true' if threshold_gap <= 1e-9 else 'false'}"
    )
    notes.append(
        "recommended_feasibility "
        f"allocation={recommended_result.allocation_name} "
        f"is_feasible={'true' if recommended_result.is_feasible else 'false'} "
        f"shortfall_probability={recommended_result.risk_summary.shortfall_probability:.4f}"
    )
    notes.append(
        "simulation_mode "
        f"requested={recommended_result.simulation_mode_requested} "
        f"used={recommended_result.simulation_mode_used} "
        f"auto_selected={'true' if inp.solver_params.simulation_mode_auto_selected else 'false'}"
    )


def _append_model_honesty_notes(
    notes: list[str],
    inp: GoalSolverInput,
    shrinkage_factor_note_value: str,
    simulation_mode_used: str,
) -> None:
    historical_backtest_used = bool(inp.solver_params.market_assumptions.historical_backtest_used)
    simulation_mode = simulation_mode_used or inp.solver_params.simulation_mode_requested or "static_gaussian"
    distribution_label = "normal"
    if simulation_mode in {"garch_t", "garch_t_dcc", "garch_t_dcc_jump"}:
        distribution_label = "student_t"
    method_label = simulation_mode if simulation_mode != "static_gaussian" else "parametric_monte_carlo"
    notes.append(
        "probability_model "
        f"method={method_label} "
        f"distribution={distribution_label} "
        f"historical_backtest_used={'true' if historical_backtest_used else 'false'}"
    )
    notes.append(f"simulation_mode_used={simulation_mode}")
    if historical_backtest_used:
        notes.append(
            "historical_dataset "
            f"source={inp.solver_params.market_assumptions.source_name or 'unknown'} "
            f"version={inp.solver_params.market_assumptions.dataset_version or 'unknown'} "
            f"frequency={inp.solver_params.market_assumptions.frequency or 'unknown'} "
            f"lookback_days={inp.solver_params.market_assumptions.lookback_days or 0} "
            f"lookback_months={inp.solver_params.market_assumptions.lookback_months or 0}"
        )
        notes.append(
            "historical_dataset_cycle "
            f"coverage_status={inp.solver_params.market_assumptions.coverage_status or 'unknown'} "
            f"observed_history_days={inp.solver_params.market_assumptions.observed_history_days} "
            f"inferred_history_days={inp.solver_params.market_assumptions.inferred_history_days} "
            f"inference_method={inp.solver_params.market_assumptions.inference_method or 'none'} "
            f"cycle_reasons={','.join(inp.solver_params.market_assumptions.cycle_reasons) or 'none'}"
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
    all_results: list[SuccessProbabilityResult] = []
    implied_required_annual_return = _solve_implied_required_annual_return(
        initial_value=inp.current_portfolio_value,
        cashflow_schedule=cashflow_schedule,
        goal_amount=inp.goal.goal_amount,
    )
    simulation_mode_requested = params.simulation_mode_requested or "static_gaussian"
    simulation_mode_used, simulation_mode_auto_selected, fallback_reason = _resolve_simulation_mode(params)
    params.simulation_mode_auto_selected = simulation_mode_auto_selected
    if simulation_mode_auto_selected and simulation_mode_requested != simulation_mode_used:
        notes.append(
            "simulation_mode_fallback "
            f"requested={simulation_mode_requested} used={simulation_mode_used} "
            f"reason={fallback_reason or 'requested_mode_unavailable'}"
        )

    for allocation in inp.candidate_allocations:
        probability, extra, risk = _run_monte_carlo_dispatch(
            allocation.weights,
            cashflow_schedule,
            inp.current_portfolio_value,
            inp.goal.goal_amount,
            params.market_assumptions,
            params.n_paths,
            params.seed,
            simulation_mode=simulation_mode_used,
            distribution_model_state=params.distribution_model_state,
        )
        interim_result = SuccessProbabilityResult(
            allocation_name=allocation.name,
            weights=allocation.weights,
            success_probability=probability,
            bucket_success_probability=probability,
            product_adjusted_success_probability=probability,
            expected_terminal_value=extra["expected_terminal_value"],
            implied_required_annual_return=implied_required_annual_return,
            risk_summary=risk,
            is_feasible=True,
            simulation_mode_requested=simulation_mode_requested,
            simulation_mode_used=simulation_mode_used,
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
                bucket_success_probability=probability,
                product_adjusted_success_probability=probability,
                expected_terminal_value=extra["expected_terminal_value"],
                implied_required_annual_return=implied_required_annual_return,
                risk_summary=risk,
                is_feasible=is_feasible,
                simulation_mode_requested=simulation_mode_requested,
                simulation_mode_used=simulation_mode_used,
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
        probability, extra, risk = _run_monte_carlo_dispatch(
            fallback.weights,
            cashflow_schedule,
            inp.current_portfolio_value,
            inp.goal.goal_amount,
            params.market_assumptions,
            params.n_paths,
            params.seed,
            simulation_mode=simulation_mode_used,
            distribution_model_state=params.distribution_model_state,
        )
        fallback_result = SuccessProbabilityResult(
            allocation_name=fallback.name,
            weights=fallback.weights,
            success_probability=probability,
            bucket_success_probability=probability,
            product_adjusted_success_probability=probability,
            expected_terminal_value=extra["expected_terminal_value"],
            implied_required_annual_return=implied_required_annual_return,
            risk_summary=risk,
            is_feasible=True,
            simulation_mode_requested=simulation_mode_requested,
            simulation_mode_used=simulation_mode_used,
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
            effective_probability = _effective_success_probability(best_result)
            if effective_probability < inp.goal.success_prob_threshold:
                notes.append(
                    "warning=success_probability_below_threshold "
                    f"threshold={inp.goal.success_prob_threshold:.4f} "
                    f"recommended={effective_probability:.4f}"
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
    frontier_analysis = _build_frontier_analysis(
        inp=inp,
        recommended_result=best_result,
        all_results=all_results,
        cashflow_schedule=cashflow_schedule,
    )
    _append_solver_context_notes(notes, inp, best_result)
    _append_model_honesty_notes(notes, inp, shrinkage_factor_note_value, simulation_mode_used)
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
        simulation_mode_requested=simulation_mode_requested,
        simulation_mode_used=simulation_mode_used,
        simulation_mode_auto_selected=simulation_mode_auto_selected,
        frontier_analysis=frontier_analysis,
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
    probability, _extra, risk = _run_monte_carlo_dispatch(
        weights,
        cashflow_schedule,
        baseline_inp.current_portfolio_value,
        baseline_inp.goal.goal_amount,
        baseline_inp.solver_params.market_assumptions,
        baseline_inp.solver_params.n_paths_lightweight,
        baseline_inp.solver_params.seed,
        simulation_mode=_resolve_simulation_mode(baseline_inp.solver_params)[0],
        distribution_model_state=baseline_inp.solver_params.distribution_model_state,
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
