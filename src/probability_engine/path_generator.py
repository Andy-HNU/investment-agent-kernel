from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from probability_engine.contracts import PathStatsSummary, RecipeSimulationResult, SuccessEventSpec
from probability_engine.dependence import FactorLevelDccProvider
from probability_engine.jumps import (
    JumpStateSpec,
    draw_systemic_jump,
    idiosyncratic_jump_profile,
    regime_adjusted_systemic_jump_dispersion,
    systemic_jump_impact_by_factor,
)
from probability_engine.portfolio_policy import (
    ContributionInstruction,
    CurrentPosition,
    RebalancingPolicySpec,
    WithdrawalInstruction,
    apply_daily_cashflows_and_rebalance,
    initialize_portfolio_state,
    instructions_for_date,
)
from probability_engine.recipes import SimulationRecipe
from probability_engine.regime import RegimeStateSpec, regime_adjustments, sample_next_regime
from probability_engine.volatility import FactorDynamicsSpec, update_garch_state


_MAPPING_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _coerce_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return dict(value)


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _quantile(values: np.ndarray, level: float) -> float:
    return float(np.quantile(values, level))


def _student_t_scale(rng: np.random.Generator, df: float | None) -> float:
    if df is None or df <= 2.0:
        return 1.0
    return float(np.sqrt(df / rng.chisquare(df)))


def _draw_standardized_scalar(rng: np.random.Generator, innovation_family: str, tail_df: float | None) -> float:
    if str(innovation_family).strip().lower() == "student_t":
        return float(rng.normal() * _student_t_scale(rng, tail_df))
    return float(rng.normal())


def _safe_cholesky(matrix: np.ndarray) -> np.ndarray:
    jitter = 1e-10
    while jitter <= 1e-4:
        try:
            return np.linalg.cholesky(matrix + np.identity(matrix.shape[0]) * jitter)
        except np.linalg.LinAlgError:
            jitter *= 10.0
    raise ValueError("correlation matrix is not positive definite")


def _draw_standardized_factor_vector(
    rng: np.random.Generator,
    correlation: list[list[float]],
    innovation_family: str,
    tail_df: float | None,
) -> np.ndarray:
    correlation_matrix = np.asarray(correlation, dtype=float)
    cholesky = _safe_cholesky(correlation_matrix)
    gaussian = cholesky @ rng.normal(size=correlation_matrix.shape[0])
    if str(innovation_family).strip().lower() == "student_t":
        gaussian = gaussian * _student_t_scale(rng, tail_df)
    return gaussian


def _covariance_to_correlation(
    covariance: dict[str, dict[str, float]],
    factor_names: list[str],
) -> list[list[float]]:
    matrix = np.asarray(
        [
            [float(covariance.get(factor, {}).get(peer, 0.0)) for peer in factor_names]
            for factor in factor_names
        ],
        dtype=float,
    )
    diagonal = np.sqrt(np.maximum(np.diag(matrix), 1e-12))
    scale = np.outer(diagonal, diagonal)
    correlation = np.divide(matrix, scale, out=np.zeros_like(matrix), where=scale > 0.0)
    np.fill_diagonal(correlation, 1.0)
    return correlation.tolist()


def _sum_profile_values(profile: dict[str, float]) -> float:
    return float(sum(float(value) for value in dict(profile).values()))


def _annualized_cagr(initial_value: float, terminal_value: float, horizon_days: int) -> float:
    if initial_value <= 0.0 or terminal_value <= 0.0 or horizon_days <= 0:
        return -1.0
    return float((terminal_value / initial_value) ** (252.0 / horizon_days) - 1.0)


def _confidence_rank(value: str) -> int:
    return _MAPPING_CONFIDENCE_RANK.get(str(value).strip().lower(), -1)


def _confidence_level(products: list["ProductMarginalSpec"]) -> str:
    minimum = min((_confidence_rank(product.mapping_confidence) for product in products), default=1)
    if minimum >= _MAPPING_CONFIDENCE_RANK["high"]:
        return "high"
    if minimum >= _MAPPING_CONFIDENCE_RANK["medium"]:
        return "medium"
    return "low"


@dataclass(frozen=True)
class ProductMarginalSpec:
    product_id: str
    asset_bucket: str
    factor_betas: dict[str, float]
    innovation_family: str
    tail_df: float | None
    volatility_process: str
    garch_params: dict[str, float]
    idiosyncratic_jump_profile: dict[str, float]
    carry_profile: dict[str, float]
    valuation_profile: dict[str, float]
    mapping_confidence: str
    factor_mapping_source: str
    factor_mapping_evidence: list[Any]
    observed_series_ref: str

    @classmethod
    def from_any(cls, value: "ProductMarginalSpec | dict[str, Any]") -> "ProductMarginalSpec":
        if isinstance(value, cls):
            return value
        payload = _coerce_mapping(value, context="product")
        return cls(
            product_id=str(payload.get("product_id", "")).strip(),
            asset_bucket=str(payload.get("asset_bucket", "")).strip(),
            factor_betas={str(key): float(item) for key, item in dict(payload.get("factor_betas") or {}).items()},
            innovation_family=str(payload.get("innovation_family", "student_t")).strip(),
            tail_df=None if payload.get("tail_df") is None else float(payload.get("tail_df")),
            volatility_process=str(payload.get("volatility_process", "")).strip(),
            garch_params={str(key): float(item) for key, item in dict(payload.get("garch_params") or {}).items()},
            idiosyncratic_jump_profile={str(key): float(item) for key, item in dict(payload.get("idiosyncratic_jump_profile") or {}).items()},
            carry_profile={str(key): float(item) for key, item in dict(payload.get("carry_profile") or {}).items()},
            valuation_profile={str(key): float(item) for key, item in dict(payload.get("valuation_profile") or {}).items()},
            mapping_confidence=str(payload.get("mapping_confidence", "")).strip().lower(),
            factor_mapping_source=str(payload.get("factor_mapping_source", "")).strip(),
            factor_mapping_evidence=list(payload.get("factor_mapping_evidence") or []),
            observed_series_ref=str(payload.get("observed_series_ref", "")).strip(),
        )


@dataclass(frozen=True)
class DailyEngineRuntimeInput:
    as_of: str
    path_horizon_days: int
    products: list[ProductMarginalSpec]
    factor_dynamics: FactorDynamicsSpec
    regime_state: RegimeStateSpec
    jump_state: JumpStateSpec
    current_positions: list[CurrentPosition]
    contribution_schedule: list[ContributionInstruction]
    withdrawal_schedule: list[WithdrawalInstruction]
    rebalancing_policy: RebalancingPolicySpec
    success_event_spec: SuccessEventSpec
    recipes: list[Any]
    evidence_bundle_ref: str
    random_seed: int

    @classmethod
    def from_any(cls, value: "DailyEngineRuntimeInput | dict[str, Any]") -> "DailyEngineRuntimeInput":
        if isinstance(value, cls):
            return value
        payload = _coerce_mapping(value, context="daily probability engine input")
        success_event_payload = payload.get("success_event_spec")
        if isinstance(success_event_payload, SuccessEventSpec):
            success_event_spec = success_event_payload
        else:
            success_event_spec = SuccessEventSpec(**dict(success_event_payload or {}))
        return cls(
            as_of=str(payload.get("as_of", "")).strip(),
            path_horizon_days=int(payload.get("path_horizon_days", 0)),
            products=[ProductMarginalSpec.from_any(item) for item in list(payload.get("products") or [])],
            factor_dynamics=FactorDynamicsSpec.from_any(payload.get("factor_dynamics")),
            regime_state=RegimeStateSpec.from_any(payload.get("regime_state")),
            jump_state=JumpStateSpec.from_any(payload.get("jump_state")),
            current_positions=[CurrentPosition.from_any(item) for item in list(payload.get("current_positions") or [])],
            contribution_schedule=[ContributionInstruction.from_any(item) for item in list(payload.get("contribution_schedule") or [])],
            withdrawal_schedule=[WithdrawalInstruction.from_any(item) for item in list(payload.get("withdrawal_schedule") or [])],
            rebalancing_policy=RebalancingPolicySpec.from_any(payload.get("rebalancing_policy") or {}),
            success_event_spec=success_event_spec,
            recipes=list(payload.get("recipes") or []),
            evidence_bundle_ref=str(payload.get("evidence_bundle_ref", "")).strip(),
            random_seed=int(payload.get("random_seed", 17)),
        )


@dataclass(frozen=True)
class PathOutcome:
    terminal_value: float
    cagr: float
    max_drawdown: float
    success: bool


def simulate_primary_paths(
    runtime_input: DailyEngineRuntimeInput,
    recipe: SimulationRecipe,
) -> RecipeSimulationResult:
    if runtime_input.factor_dynamics is None or runtime_input.regime_state is None or runtime_input.jump_state is None:
        raise ValueError("factor_dynamics, regime_state, and jump_state are required")
    rng = np.random.default_rng(runtime_input.random_seed)
    outcomes = [_simulate_single_path(runtime_input, recipe, rng) for _ in range(recipe.path_count)]
    return _summarize_outcomes(runtime_input, recipe, outcomes)


def probability_engine_confidence_level(runtime_input: DailyEngineRuntimeInput) -> str:
    return _confidence_level(runtime_input.products)


def _simulate_single_path(
    runtime_input: DailyEngineRuntimeInput,
    recipe: SimulationRecipe,
    rng: np.random.Generator,
) -> PathOutcome:
    portfolio_state = initialize_portfolio_state(runtime_input.current_positions)
    initial_value = portfolio_state.net_value
    peak_value = initial_value
    max_drawdown = 0.0

    factor_names = list(runtime_input.factor_dynamics.factor_names)
    factor_variances = {
        factor_name: float(
            runtime_input.factor_dynamics.garch_params_by_factor.get(factor_name, {}).get(
                "long_run_variance",
                runtime_input.factor_dynamics.long_run_covariance.get(factor_name, {}).get(factor_name, 1e-6),
            )
        )
        for factor_name in factor_names
    }
    product_variances = {
        product.product_id: float(product.garch_params.get("long_run_variance", 1e-4))
        for product in runtime_input.products
    }

    dcc_provider = FactorLevelDccProvider(
        alpha=float(runtime_input.factor_dynamics.dcc_params.get("alpha", 0.04)),
        beta=float(runtime_input.factor_dynamics.dcc_params.get("beta", 0.93)),
    )
    dcc_state = dcc_provider.initialize(
        factor_names,
        {"long_run_correlation": _covariance_to_correlation(runtime_input.factor_dynamics.long_run_covariance, factor_names)},
    )
    regime_state = RegimeStateSpec.from_any(runtime_input.regime_state.to_dict())
    if regime_state is None:
        raise ValueError("regime_state is required")
    calendar_anchor = date.fromisoformat(runtime_input.as_of)

    for offset in range(runtime_input.path_horizon_days):
        current_regime = regime_state.current_regime
        next_regime = sample_next_regime(regime_state, random_state=rng, regime_name=current_regime)
        adjustments = regime_adjustments(regime_state, regime_name=next_regime)
        volatility_multiplier = float(adjustments["vol"].get("volatility_multiplier", 1.0))
        mean_shift = float(adjustments["mean"].get("mean_shift", 0.0))

        current_correlation = dcc_provider.current_correlation(dcc_state)
        factor_shocks = _draw_standardized_factor_vector(
            rng,
            current_correlation,
            runtime_input.factor_dynamics.innovation_family,
            runtime_input.factor_dynamics.tail_df,
        )
        factor_residuals: dict[str, float] = {}
        factor_returns: dict[str, float] = {}
        previous_factor_variances = dict(factor_variances)
        for index, factor_name in enumerate(factor_names):
            sigma = np.sqrt(max(previous_factor_variances[factor_name], 1e-12)) * volatility_multiplier
            residual = sigma * float(factor_shocks[index])
            factor_residuals[factor_name] = residual
            factor_returns[factor_name] = mean_shift + residual

        systemic_jump_fired = draw_systemic_jump(
            runtime_input.jump_state,
            regime_state=regime_state,
            regime_name=next_regime,
            random_state=rng,
        )
        systemic_dispersion = regime_adjusted_systemic_jump_dispersion(
            runtime_input.jump_state,
            regime_state=regime_state,
            regime_name=next_regime,
        )

        product_returns: dict[str, float] = {}
        previous_product_variances = dict(product_variances)
        product_idio_residuals: dict[str, float] = {}
        for product in runtime_input.products:
            sigma = np.sqrt(max(previous_product_variances[product.product_id], 1e-12)) * volatility_multiplier
            standardized_idio = _draw_standardized_scalar(rng, product.innovation_family, product.tail_df)
            idio_residual = sigma * standardized_idio
            product_idio_residuals[product.product_id] = idio_residual
            pre_jump_return = sum(
                float(product.factor_betas.get(factor_name, 0.0)) * factor_returns[factor_name]
                for factor_name in factor_names
            ) + idio_residual

            systemic_component = 0.0
            if systemic_jump_fired:
                base_jump = sum(
                    float(product.factor_betas.get(factor_name, 0.0))
                    * systemic_jump_impact_by_factor(runtime_input.jump_state, factor_name)
                    for factor_name in factor_names
                )
                systemic_component = float(base_jump + rng.normal(0.0, systemic_dispersion * 0.25))

            jump_profile = idiosyncratic_jump_profile(
                runtime_input.jump_state,
                product.product_id,
                regime_state=regime_state,
                regime_name=next_regime,
            )
            if not jump_profile:
                jump_profile = dict(product.idiosyncratic_jump_profile)
            idio_component = 0.0
            jump_probability = _clamp_probability(float(jump_profile.get("probability_1d", 0.0)))
            if jump_probability > 0.0 and float(rng.random()) < jump_probability:
                idio_component = float(
                    rng.normal(
                        float(jump_profile.get("loss_mean", 0.0)),
                        max(float(jump_profile.get("loss_std", 0.0)), 1e-12),
                    )
                )

            drag = _sum_profile_values(product.carry_profile) + _sum_profile_values(product.valuation_profile)
            product_returns[product.product_id] = pre_jump_return + systemic_component + idio_component + drag

        step_date = (calendar_anchor + timedelta(days=offset + 1)).isoformat()
        portfolio_state = apply_daily_cashflows_and_rebalance(
            portfolio_state=portfolio_state,
            product_returns=product_returns,
            contributions=instructions_for_date(runtime_input.contribution_schedule, step_date),
            withdrawals=instructions_for_date(runtime_input.withdrawal_schedule, step_date),
            policy=runtime_input.rebalancing_policy,
        )
        peak_value = max(peak_value, portfolio_state.net_value)
        if peak_value > 0.0:
            max_drawdown = max(max_drawdown, 1.0 - (portfolio_state.net_value / peak_value))

        for factor_name in factor_names:
            params = runtime_input.factor_dynamics.garch_params_by_factor.get(factor_name, {})
            factor_variances[factor_name] = max(
                update_garch_state(
                    previous_variance=previous_factor_variances[factor_name],
                    pre_jump_residual=factor_residuals[factor_name],
                    omega=float(params.get("omega", 0.0)) * (volatility_multiplier**2),
                    alpha=float(params.get("alpha", 0.0)),
                    beta=float(params.get("beta", 0.0)),
                ),
                1e-12,
            )
        dcc_state = dcc_provider.update(factor_shocks.tolist(), dcc_state)
        for product in runtime_input.products:
            params = product.garch_params
            product_variances[product.product_id] = max(
                update_garch_state(
                    previous_variance=previous_product_variances[product.product_id],
                    pre_jump_residual=product_idio_residuals[product.product_id],
                    omega=float(params.get("omega", 0.0)) * (volatility_multiplier**2),
                    alpha=float(params.get("alpha", 0.0)),
                    beta=float(params.get("beta", 0.0)),
                ),
                1e-12,
            )
        regime_state.current_regime = next_regime

    terminal_value = portfolio_state.net_value
    success = terminal_value >= float(runtime_input.success_event_spec.target_value)
    if runtime_input.success_event_spec.drawdown_constraint is not None:
        success = success and max_drawdown <= float(runtime_input.success_event_spec.drawdown_constraint)
    return PathOutcome(
        terminal_value=terminal_value,
        cagr=_annualized_cagr(initial_value, terminal_value, runtime_input.path_horizon_days),
        max_drawdown=max_drawdown,
        success=success,
    )


def _summarize_outcomes(
    runtime_input: DailyEngineRuntimeInput,
    recipe: SimulationRecipe,
    outcomes: list[PathOutcome],
) -> RecipeSimulationResult:
    terminal_values = np.asarray([outcome.terminal_value for outcome in outcomes], dtype=float)
    cagrs = np.asarray([outcome.cagr for outcome in outcomes], dtype=float)
    drawdowns = np.asarray([outcome.max_drawdown for outcome in outcomes], dtype=float)
    successes = np.asarray([1.0 if outcome.success else 0.0 for outcome in outcomes], dtype=float)

    success_probability = float(np.mean(successes))
    margin = 1.96 * np.sqrt(max(success_probability * (1.0 - success_probability), 1e-12) / max(len(outcomes), 1))
    success_range = (
        max(0.0, success_probability - margin),
        min(1.0, success_probability + margin),
    )

    return RecipeSimulationResult(
        recipe_name=recipe.recipe_name,
        role=recipe.role,
        success_probability=success_probability,
        success_probability_range=success_range,
        cagr_range=(_quantile(cagrs, 0.05), _quantile(cagrs, 0.95)),
        drawdown_range=(_quantile(drawdowns, 0.05), _quantile(drawdowns, 0.95)),
        sample_count=len(outcomes),
        path_stats=PathStatsSummary(
            terminal_value_mean=float(np.mean(terminal_values)),
            terminal_value_p05=_quantile(terminal_values, 0.05),
            terminal_value_p50=_quantile(terminal_values, 0.50),
            terminal_value_p95=_quantile(terminal_values, 0.95),
            cagr_p05=_quantile(cagrs, 0.05),
            cagr_p50=_quantile(cagrs, 0.50),
            cagr_p95=_quantile(cagrs, 0.95),
            max_drawdown_p05=_quantile(drawdowns, 0.05),
            max_drawdown_p50=_quantile(drawdowns, 0.50),
            max_drawdown_p95=_quantile(drawdowns, 0.95),
            success_count=int(np.sum(successes)),
            path_count=len(outcomes),
        ),
        calibration_link_ref=runtime_input.evidence_bundle_ref or None,
    )
