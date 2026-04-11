from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

import numpy as np

from probability_engine.contracts import PathStatsSummary, RecipeSimulationResult, SuccessEventSpec
from probability_engine.jumps import (
    JumpStateSpec,
)
from probability_engine.portfolio_policy import (
    ContributionInstruction,
    CurrentPosition,
    RebalancingPolicySpec,
    WithdrawalInstruction,
)
from probability_engine.recipes import SimulationRecipe
from probability_engine.regime import RegimeStateSpec
from probability_engine.volatility import FactorDynamicsSpec, update_garch_state


_MAPPING_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
T = TypeVar("T")


def _coerce_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return dict(value)


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _quantile(values: np.ndarray, level: float) -> float:
    return float(np.quantile(values, level))


def _trading_step_dates(as_of: str, trading_calendar: list[str], horizon_days: int) -> list[str]:
    if horizon_days <= 0:
        return []
    if not trading_calendar:
        raise ValueError("trading_calendar is required for formal Task 4 runs")
    anchor = date.fromisoformat(as_of)
    normalized: list[str] = []
    previous = anchor
    for raw_date in trading_calendar:
        current = date.fromisoformat(str(raw_date).strip())
        if current <= previous:
            raise ValueError("trading_calendar must be strictly increasing and after as_of")
        normalized.append(current.isoformat())
        previous = current
        if len(normalized) == horizon_days:
            return normalized
    raise ValueError("trading_calendar must provide at least path_horizon_days dates")


def _student_t_scale(rng: np.random.Generator, df: float | None) -> float:
    if df is None or df <= 2.0:
        return 1.0
    return float(np.sqrt((df - 2.0) / rng.chisquare(df)))


def _draw_standardized_scalar(rng: np.random.Generator, innovation_family: str, tail_df: float | None) -> float:
    if str(innovation_family).strip().lower() == "student_t":
        return float(rng.normal() * _student_t_scale(rng, tail_df))
    return float(rng.normal())


def _draw_standardized_factor_vector(
    rng: np.random.Generator,
    correlation_matrix: np.ndarray,
    correlation_identity: np.ndarray,
    factor_is_student_t: bool,
    tail_df: float | None,
) -> np.ndarray:
    cholesky = _safe_cholesky_with_identity(correlation_matrix, correlation_identity)
    gaussian = cholesky @ rng.normal(size=correlation_matrix.shape[0])
    if factor_is_student_t:
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


def _wilson_interval(success_count: int, total_count: int, z_score: float = 1.96) -> tuple[float, float]:
    if total_count <= 0:
        return (0.0, 0.0)
    probability = float(success_count) / float(total_count)
    z_squared = float(z_score**2)
    denominator = 1.0 + (z_squared / float(total_count))
    center = (probability + (z_squared / (2.0 * float(total_count)))) / denominator
    margin = (
        z_score
        * np.sqrt((probability * (1.0 - probability) + (z_squared / (4.0 * float(total_count)))) / float(total_count))
        / denominator
    )
    return (_clamp_probability(center - margin), _clamp_probability(center + margin))


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
    trading_calendar: list[str]
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

    def trading_step_dates(self) -> list[str]:
        return _trading_step_dates(self.as_of, self.trading_calendar, self.path_horizon_days)

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
            trading_calendar=[str(item).strip() for item in list(payload.get("trading_calendar") or []) if str(item).strip()],
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


@dataclass(frozen=True)
class _CompiledRuntimeContext:
    step_dates: list[str]
    contribution_schedule_by_date: dict[str, list[ContributionInstruction]]
    withdrawal_schedule_by_date: dict[str, list[WithdrawalInstruction]]
    factor_names: list[str]
    factor_initial_variances: np.ndarray
    factor_omega: np.ndarray
    factor_alpha: np.ndarray
    factor_beta: np.ndarray
    factor_is_student_t: bool
    factor_tail_df: float | None
    q_bar_matrix: np.ndarray
    dcc_alpha: float
    dcc_beta: float
    correlation_identity: np.ndarray
    product_ids: list[str]
    product_index_by_id: dict[str, int]
    product_beta_matrix: np.ndarray
    initial_product_values: np.ndarray
    target_weights: np.ndarray
    product_initial_variances: np.ndarray
    product_omega: np.ndarray
    product_alpha: np.ndarray
    product_garch_beta: np.ndarray
    product_student_t_mask: np.ndarray
    product_tail_df: np.ndarray
    product_base_jump_probability: np.ndarray
    product_base_jump_loss_mean: np.ndarray
    product_base_jump_loss_std: np.ndarray
    product_jump_profile_from_state: np.ndarray
    product_drags: np.ndarray
    product_systemic_factor_impact: np.ndarray
    regime_names: list[str]
    regime_transition_matrix: np.ndarray
    initial_regime_index: int
    mean_shift_by_regime: np.ndarray
    volatility_multiplier_by_regime: np.ndarray
    systemic_jump_probability_multiplier_by_regime: np.ndarray
    systemic_jump_dispersion_multiplier_by_regime: np.ndarray
    idio_jump_probability_multiplier_by_regime: np.ndarray
    idio_loss_multiplier_by_regime: np.ndarray
    idio_loss_std_multiplier_by_regime: np.ndarray
    systemic_jump_probability_base: float
    systemic_jump_dispersion_base: float
    policy_type: str
    calendar_frequency: str | None
    execution_timing: str
    threshold_band: float | None
    min_trade_amount: float | None
    transaction_cost_rate: float
    daily_calendar_rebalance: bool
    target_value: float
    drawdown_constraint: float | None


def _schedule_by_date(schedule: list[T]) -> dict[str, list[T]]:
    grouped: dict[str, list[T]] = {}
    for instruction in schedule:
        target_date = str(getattr(instruction, "date", "") or "").strip()
        if not target_date:
            continue
        grouped.setdefault(target_date, []).append(instruction)
    return grouped


def _compiled_runtime_context(runtime_input: DailyEngineRuntimeInput) -> _CompiledRuntimeContext:
    factor_names = list(runtime_input.factor_dynamics.factor_names)
    factor_count = len(factor_names)
    factor_garch = runtime_input.factor_dynamics.garch_params_by_factor
    factor_long_run_covariance = runtime_input.factor_dynamics.long_run_covariance
    factor_initial_variances = np.asarray(
        [
            float(
                factor_garch.get(factor_name, {}).get(
                    "long_run_variance",
                    factor_long_run_covariance.get(factor_name, {}).get(factor_name, 1e-6),
                )
            )
            for factor_name in factor_names
        ],
        dtype=float,
    )
    factor_omega = np.asarray(
        [float(factor_garch.get(factor_name, {}).get("omega", 0.0)) for factor_name in factor_names],
        dtype=float,
    )
    factor_alpha = np.asarray(
        [float(factor_garch.get(factor_name, {}).get("alpha", 0.0)) for factor_name in factor_names],
        dtype=float,
    )
    factor_beta = np.asarray(
        [float(factor_garch.get(factor_name, {}).get("beta", 0.0)) for factor_name in factor_names],
        dtype=float,
    )
    q_bar_matrix = np.asarray(_covariance_to_correlation(factor_long_run_covariance, factor_names), dtype=float)

    products = list(runtime_input.products)
    product_ids = [product.product_id for product in products]
    product_index_by_id = {product_id: index for index, product_id in enumerate(product_ids)}
    product_beta_matrix = np.asarray(
        [
            [float(product.factor_betas.get(factor_name, 0.0)) for factor_name in factor_names]
            for product in products
        ],
        dtype=float,
    )
    initial_product_values = np.asarray(
        [max(0.0, float(position.market_value)) for position in runtime_input.current_positions],
        dtype=float,
    )
    target_weights = np.asarray(
        [max(0.0, float(position.weight)) for position in runtime_input.current_positions],
        dtype=float,
    )
    target_weight_sum = float(np.sum(target_weights))
    if target_weight_sum > 0.0:
        target_weights = target_weights / target_weight_sum
    else:
        portfolio_total = float(np.sum(initial_product_values))
        if portfolio_total > 0.0:
            target_weights = initial_product_values / portfolio_total
        elif len(products) > 0:
            target_weights = np.full(len(products), 1.0 / float(len(products)), dtype=float)

    policy = runtime_input.rebalancing_policy
    product_initial_variances = np.asarray(
        [float(product.garch_params.get("long_run_variance", 1e-4)) for product in products],
        dtype=float,
    )
    product_omega = np.asarray(
        [float(product.garch_params.get("omega", 0.0)) for product in products],
        dtype=float,
    )
    product_alpha = np.asarray(
        [float(product.garch_params.get("alpha", 0.0)) for product in products],
        dtype=float,
    )
    product_garch_beta = np.asarray(
        [float(product.garch_params.get("beta", 0.0)) for product in products],
        dtype=float,
    )
    product_student_t_mask = np.asarray(
        [str(product.innovation_family).strip().lower() == "student_t" for product in products],
        dtype=bool,
    )
    product_tail_df = np.asarray(
        [np.nan if product.tail_df is None else float(product.tail_df) for product in products],
        dtype=float,
    )
    jump_profiles = []
    for product in products:
        jump_profile = dict(runtime_input.jump_state.idio_jump_profile_by_product.get(product.product_id, {}))
        if not jump_profile:
            jump_profile = dict(product.idiosyncratic_jump_profile)
        jump_profiles.append(jump_profile)
    product_base_jump_probability = np.asarray(
        [float(profile.get("probability_1d", 0.0)) for profile in jump_profiles],
        dtype=float,
    )
    product_base_jump_loss_mean = np.asarray(
        [float(profile.get("loss_mean", 0.0)) for profile in jump_profiles],
        dtype=float,
    )
    product_base_jump_loss_std = np.asarray(
        [max(float(profile.get("loss_std", 0.0)), 1e-12) for profile in jump_profiles],
        dtype=float,
    )
    product_jump_profile_from_state = np.asarray(
        [product.product_id in runtime_input.jump_state.idio_jump_profile_by_product for product in products],
        dtype=bool,
    )
    product_drags = np.asarray(
        [
            _sum_profile_values(product.carry_profile) + _sum_profile_values(product.valuation_profile)
            for product in products
        ],
        dtype=float,
    )
    factor_jump_impact = np.asarray(
        [float(runtime_input.jump_state.systemic_jump_impact_by_factor.get(factor_name, 0.0)) for factor_name in factor_names],
        dtype=float,
    )
    product_systemic_factor_impact = product_beta_matrix @ factor_jump_impact

    regime_names = list(runtime_input.regime_state.regime_names)
    regime_transition_matrix = np.asarray(runtime_input.regime_state.transition_matrix, dtype=float)
    initial_regime_index = regime_names.index(runtime_input.regime_state.current_regime)
    mean_shift_by_regime = np.asarray(
        [
            float(runtime_input.regime_state.regime_mean_adjustments.get(regime_name, {}).get("mean_shift", 0.0))
            for regime_name in regime_names
        ],
        dtype=float,
    )
    volatility_multiplier_by_regime = np.asarray(
        [
            float(runtime_input.regime_state.regime_vol_adjustments.get(regime_name, {}).get("volatility_multiplier", 1.0))
            for regime_name in regime_names
        ],
        dtype=float,
    )
    systemic_jump_probability_multiplier_by_regime = np.asarray(
        [
            float(
                runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}).get(
                    "systemic_jump_probability_multiplier",
                    1.0,
                )
            )
            for regime_name in regime_names
        ],
        dtype=float,
    )
    systemic_jump_dispersion_multiplier_by_regime = np.asarray(
        [
            float(
                runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}).get(
                    "systemic_jump_dispersion_multiplier",
                    1.0,
                )
            )
            for regime_name in regime_names
        ],
        dtype=float,
    )
    idio_jump_probability_multiplier_by_regime = np.asarray(
        [
            float(
                runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}).get(
                    "idio_jump_probability_multiplier",
                    1.0,
                )
            )
            for regime_name in regime_names
        ],
        dtype=float,
    )
    idio_loss_multiplier_by_regime = np.asarray(
        [
            float(runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}).get("idio_loss_multiplier", 1.0))
            for regime_name in regime_names
        ],
        dtype=float,
    )
    idio_loss_std_multiplier_by_regime = np.asarray(
        [
            float(
                runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}).get(
                    "idio_loss_std_multiplier",
                    1.0,
                )
            )
            for regime_name in regime_names
        ],
        dtype=float,
    )

    return _CompiledRuntimeContext(
        step_dates=runtime_input.trading_step_dates(),
        contribution_schedule_by_date=_schedule_by_date(runtime_input.contribution_schedule),
        withdrawal_schedule_by_date=_schedule_by_date(runtime_input.withdrawal_schedule),
        factor_names=factor_names,
        factor_initial_variances=factor_initial_variances,
        factor_omega=factor_omega,
        factor_alpha=factor_alpha,
        factor_beta=factor_beta,
        factor_is_student_t=str(runtime_input.factor_dynamics.innovation_family).strip().lower() == "student_t",
        factor_tail_df=runtime_input.factor_dynamics.tail_df,
        q_bar_matrix=q_bar_matrix,
        dcc_alpha=float(runtime_input.factor_dynamics.dcc_params.get("alpha", 0.04)),
        dcc_beta=float(runtime_input.factor_dynamics.dcc_params.get("beta", 0.93)),
        correlation_identity=np.eye(factor_count),
        product_ids=product_ids,
        product_index_by_id=product_index_by_id,
        product_beta_matrix=product_beta_matrix,
        initial_product_values=initial_product_values,
        target_weights=target_weights,
        product_initial_variances=product_initial_variances,
        product_omega=product_omega,
        product_alpha=product_alpha,
        product_garch_beta=product_garch_beta,
        product_student_t_mask=product_student_t_mask,
        product_tail_df=product_tail_df,
        product_base_jump_probability=product_base_jump_probability,
        product_base_jump_loss_mean=product_base_jump_loss_mean,
        product_base_jump_loss_std=product_base_jump_loss_std,
        product_jump_profile_from_state=product_jump_profile_from_state,
        product_drags=product_drags,
        product_systemic_factor_impact=product_systemic_factor_impact,
        regime_names=regime_names,
        regime_transition_matrix=regime_transition_matrix,
        initial_regime_index=initial_regime_index,
        mean_shift_by_regime=mean_shift_by_regime,
        volatility_multiplier_by_regime=volatility_multiplier_by_regime,
        systemic_jump_probability_multiplier_by_regime=systemic_jump_probability_multiplier_by_regime,
        systemic_jump_dispersion_multiplier_by_regime=systemic_jump_dispersion_multiplier_by_regime,
        idio_jump_probability_multiplier_by_regime=idio_jump_probability_multiplier_by_regime,
        idio_loss_multiplier_by_regime=idio_loss_multiplier_by_regime,
        idio_loss_std_multiplier_by_regime=idio_loss_std_multiplier_by_regime,
        systemic_jump_probability_base=float(runtime_input.jump_state.systemic_jump_probability_1d),
        systemic_jump_dispersion_base=float(runtime_input.jump_state.systemic_jump_dispersion),
        policy_type=str(policy.policy_type).strip(),
        calendar_frequency=None if policy.calendar_frequency is None else str(policy.calendar_frequency).strip().lower(),
        execution_timing=str(policy.execution_timing).strip(),
        threshold_band=policy.threshold_band,
        min_trade_amount=policy.min_trade_amount,
        transaction_cost_rate=float(policy.transaction_cost_bps) / 10000.0,
        daily_calendar_rebalance=str(policy.calendar_frequency).strip().lower() == "daily",
        target_value=float(runtime_input.success_event_spec.target_value),
        drawdown_constraint=runtime_input.success_event_spec.drawdown_constraint,
    )


def _draw_product_idiosyncratic_shocks(
    rng: np.random.Generator,
    student_t_mask: np.ndarray,
    tail_df: np.ndarray,
) -> np.ndarray:
    draws = rng.normal(size=student_t_mask.shape[0])
    if not np.any(student_t_mask):
        return draws
    masked_df = tail_df[student_t_mask]
    draws = np.array(draws, copy=True)
    valid = masked_df > 2.0
    if np.any(valid):
        valid_df = masked_df[valid]
        scales = np.sqrt((valid_df - 2.0) / valid_df)
        standardized = rng.standard_t(valid_df) * scales
        student_draws = draws[student_t_mask]
        student_draws[valid] = standardized
        draws[student_t_mask] = student_draws
    return draws


def _current_correlation_from_q_matrix(q_matrix: np.ndarray) -> np.ndarray:
    diagonal = np.sqrt(np.maximum(np.diag(q_matrix), 1e-12))
    inverse_diagonal = 1.0 / diagonal
    correlation = q_matrix * inverse_diagonal[:, None] * inverse_diagonal[None, :]
    correlation.flat[:: q_matrix.shape[0] + 1] = 1.0
    return correlation


def _safe_cholesky_with_identity(matrix: np.ndarray, identity: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError:
        pass
    jitter = 1e-10
    while jitter <= 1e-4:
        try:
            return np.linalg.cholesky(matrix + identity * jitter)
        except np.linalg.LinAlgError:
            jitter *= 10.0
    raise ValueError("correlation matrix is not positive definite")


def _calendar_rebalance_triggered(
    *,
    policy_type: str,
    calendar_frequency: str | None,
    current_date: str | None,
    previous_date: str | None,
    daily_calendar_rebalance: bool,
) -> bool:
    if policy_type not in {"calendar", "hybrid"}:
        return False
    if daily_calendar_rebalance:
        return True
    if not current_date or not previous_date or not calendar_frequency:
        return False
    current = date.fromisoformat(current_date)
    previous = date.fromisoformat(previous_date)
    if calendar_frequency == "weekly":
        return current.isocalendar()[:2] != previous.isocalendar()[:2]
    if calendar_frequency == "monthly":
        return (current.year, current.month) != (previous.year, previous.month)
    if calendar_frequency == "quarterly":
        return (current.year, (current.month - 1) // 3) != (previous.year, (previous.month - 1) // 3)
    if calendar_frequency == "annual":
        return current.year != previous.year
    return False


def _normalize_weight_vector(weights: np.ndarray) -> np.ndarray:
    positive = np.maximum(np.asarray(weights, dtype=float), 0.0)
    total = float(np.sum(positive))
    if total <= 0.0:
        return np.zeros_like(positive)
    return positive / total


def _allocation_vector_for_contribution(
    instruction: ContributionInstruction,
    *,
    product_index_by_id: dict[str, int],
    target_weights: np.ndarray,
    current_weights: np.ndarray,
) -> np.ndarray:
    if instruction.allocation_mode == "target_weights" and instruction.target_weights:
        custom = np.zeros_like(target_weights)
        for product_id, weight in instruction.target_weights.items():
            index = product_index_by_id.get(str(product_id))
            if index is not None:
                custom[index] = max(0.0, float(weight))
        normalized = _normalize_weight_vector(custom)
        if float(np.sum(normalized)) > 0.0:
            return normalized
    if float(np.sum(target_weights)) > 0.0:
        return target_weights
    return _normalize_weight_vector(current_weights)


def _apply_contributions_vectorized(
    product_values: np.ndarray,
    cash: float,
    contributions: list[ContributionInstruction],
    *,
    product_index_by_id: dict[str, int],
    target_weights: np.ndarray,
) -> tuple[np.ndarray, float]:
    updated = np.array(product_values, copy=True)
    updated_cash = float(cash)
    for contribution in contributions:
        amount = float(contribution.amount)
        if amount <= 0.0:
            continue
        net_value = float(np.sum(updated) + updated_cash)
        current_weights = (updated / net_value) if net_value > 0.0 else np.zeros_like(updated)
        allocation = _allocation_vector_for_contribution(
            contribution,
            product_index_by_id=product_index_by_id,
            target_weights=target_weights,
            current_weights=current_weights,
        )
        allocations = amount * allocation
        updated = updated + allocations
        updated_cash += amount - float(np.sum(allocations))
    return updated, updated_cash


def _apply_withdrawals_vectorized(
    product_values: np.ndarray,
    cash: float,
    withdrawals: list[WithdrawalInstruction],
    *,
    product_index_by_id: dict[str, int],
) -> tuple[np.ndarray, float]:
    updated = np.array(product_values, copy=True)
    updated_cash = float(cash)
    for withdrawal in withdrawals:
        amount = float(withdrawal.amount)
        if amount <= 0.0:
            continue
        remaining = amount
        if withdrawal.execution_rule in {"cash_first", "custom", "pro_rata_sell"} and updated_cash > 0.0:
            cash_used = min(updated_cash, remaining)
            updated_cash -= cash_used
            remaining -= cash_used
        if remaining > 0.0:
            if withdrawal.target_products:
                target_indices = [product_index_by_id[product_id] for product_id in withdrawal.target_products if product_id in product_index_by_id]
            else:
                target_indices = list(range(updated.shape[0]))
            if target_indices:
                available = updated[target_indices]
                sale_base = float(np.sum(available))
                if sale_base > 0.0:
                    sale_amounts = np.minimum(available, remaining * (available / sale_base))
                    updated[target_indices] = np.maximum(0.0, available - sale_amounts)
                    remaining = max(0.0, remaining - float(np.sum(sale_amounts)))
        if remaining > 0.0:
            updated = np.zeros_like(updated)
            updated_cash = 0.0
    return updated, updated_cash


def _rebalance_vectorized(
    product_values: np.ndarray,
    cash: float,
    *,
    policy_type: str,
    execution_timing: str,
    target_weights: np.ndarray,
    threshold_band: float | None,
    min_trade_amount: float | None,
    transaction_cost_rate: float,
    current_date: str | None,
    previous_date: str | None,
    calendar_frequency: str | None,
    daily_calendar_rebalance: bool,
) -> tuple[np.ndarray, float]:
    if policy_type == "none" or execution_timing != "end_of_day_after_return":
        return product_values, cash
    total_before = float(np.sum(product_values) + cash)
    current_weights = (product_values / total_before) if total_before > 0.0 else np.zeros_like(product_values)
    threshold_triggered = False
    if threshold_band is not None and float(np.sum(target_weights)) > 0.0:
        threshold_triggered = bool(np.any(np.abs(current_weights - target_weights) >= float(threshold_band)))
    calendar_triggered = _calendar_rebalance_triggered(
        policy_type=policy_type,
        calendar_frequency=calendar_frequency,
        current_date=current_date,
        previous_date=previous_date,
        daily_calendar_rebalance=daily_calendar_rebalance,
    )
    if policy_type == "threshold" and not threshold_triggered:
        return product_values, cash
    if policy_type == "calendar" and not calendar_triggered:
        return product_values, cash
    if policy_type == "hybrid" and not (threshold_triggered or calendar_triggered):
        return product_values, cash
    if float(np.sum(target_weights)) <= 0.0:
        return product_values, cash
    desired = target_weights * total_before
    turnover = 0.5 * float(np.sum(np.abs(desired - product_values)))
    if min_trade_amount is not None and turnover < float(min_trade_amount):
        return product_values, cash
    investable = max(0.0, total_before - turnover * transaction_cost_rate)
    return target_weights * investable, 0.0


def _draw_standardized_factor_matrix(
    rng: np.random.Generator,
    correlation_matrices: np.ndarray,
    correlation_identity: np.ndarray,
    *,
    factor_is_student_t: bool,
    tail_df: float | None,
) -> np.ndarray:
    try:
        cholesky = np.linalg.cholesky(correlation_matrices)
    except np.linalg.LinAlgError:
        cholesky = np.asarray(
            [_safe_cholesky_with_identity(matrix, correlation_identity) for matrix in correlation_matrices],
            dtype=float,
        )
    gaussian = rng.normal(size=(correlation_matrices.shape[0], correlation_matrices.shape[1]))
    correlated = np.einsum("pij,pj->pi", cholesky, gaussian)
    if not factor_is_student_t or tail_df is None or tail_df <= 2.0:
        return correlated
    scales = np.sqrt((tail_df - 2.0) / rng.chisquare(tail_df, size=correlated.shape[0]))
    return correlated * scales[:, None]


def _draw_product_idiosyncratic_shocks_batch(
    rng: np.random.Generator,
    *,
    path_count: int,
    student_t_mask: np.ndarray,
    tail_df: np.ndarray,
) -> np.ndarray:
    draws = rng.normal(size=(path_count, student_t_mask.shape[0]))
    if not np.any(student_t_mask):
        return draws
    for product_index, enabled in enumerate(student_t_mask.tolist()):
        if not enabled:
            continue
        df = float(tail_df[product_index])
        if df > 2.0:
            scale = np.sqrt((df - 2.0) / df)
            draws[:, product_index] = rng.standard_t(df, size=path_count) * scale
    return draws


def _apply_contributions_vectorized_batch(
    product_values: np.ndarray,
    cash: np.ndarray,
    contributions: list[ContributionInstruction],
    *,
    product_index_by_id: dict[str, int],
    target_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    updated_values = np.array(product_values, copy=True)
    updated_cash = np.array(cash, copy=True)
    for contribution in contributions:
        amount = float(contribution.amount)
        if amount <= 0.0:
            continue
        current_totals = np.sum(updated_values, axis=1) + updated_cash
        if contribution.allocation_mode == "target_weights" and contribution.target_weights:
            allocation = np.zeros_like(target_weights)
            for product_id, weight in contribution.target_weights.items():
                index = product_index_by_id.get(str(product_id))
                if index is not None:
                    allocation[index] = max(0.0, float(weight))
            allocation = _normalize_weight_vector(allocation)
            if float(np.sum(allocation)) <= 0.0:
                allocation = target_weights
        elif float(np.sum(target_weights)) > 0.0:
            allocation = target_weights
        else:
            allocation = np.divide(
                updated_values,
                current_totals[:, None],
                out=np.zeros_like(updated_values),
                where=current_totals[:, None] > 0.0,
            )
        allocations = amount * allocation
        updated_values = updated_values + allocations
        updated_cash = updated_cash + (amount - float(np.sum(allocation) * amount))
    return updated_values, updated_cash


def _apply_withdrawals_vectorized_batch(
    product_values: np.ndarray,
    cash: np.ndarray,
    withdrawals: list[WithdrawalInstruction],
    *,
    product_index_by_id: dict[str, int],
) -> tuple[np.ndarray, np.ndarray]:
    updated_values = np.array(product_values, copy=True)
    updated_cash = np.array(cash, copy=True)
    for withdrawal in withdrawals:
        amount = float(withdrawal.amount)
        if amount <= 0.0:
            continue
        remaining = np.full(updated_cash.shape[0], amount, dtype=float)
        if withdrawal.execution_rule in {"cash_first", "custom", "pro_rata_sell"}:
            cash_used = np.minimum(updated_cash, remaining)
            updated_cash = updated_cash - cash_used
            remaining = remaining - cash_used
        if np.any(remaining > 0.0):
            if withdrawal.target_products:
                target_indices = [
                    product_index_by_id[product_id]
                    for product_id in withdrawal.target_products
                    if product_id in product_index_by_id
                ]
            else:
                target_indices = list(range(updated_values.shape[1]))
            if target_indices:
                available = updated_values[:, target_indices]
                sale_base = np.sum(available, axis=1)
                ratios = np.divide(
                    available,
                    sale_base[:, None],
                    out=np.zeros_like(available),
                    where=sale_base[:, None] > 0.0,
                )
                sale_amounts = np.minimum(available, remaining[:, None] * ratios)
                updated_values[:, target_indices] = np.maximum(0.0, available - sale_amounts)
                remaining = np.maximum(0.0, remaining - np.sum(sale_amounts, axis=1))
        unresolved = remaining > 0.0
        if np.any(unresolved):
            updated_values[unresolved, :] = 0.0
            updated_cash[unresolved] = 0.0
    return updated_values, updated_cash


def _rebalance_vectorized_batch(
    product_values: np.ndarray,
    cash: np.ndarray,
    *,
    policy_type: str,
    execution_timing: str,
    target_weights: np.ndarray,
    threshold_band: float | None,
    min_trade_amount: float | None,
    transaction_cost_rate: float,
    current_date: str | None,
    previous_date: str | None,
    calendar_frequency: str | None,
    daily_calendar_rebalance: bool,
) -> tuple[np.ndarray, np.ndarray]:
    if policy_type == "none" or execution_timing != "end_of_day_after_return":
        return product_values, cash
    total_before = np.sum(product_values, axis=1) + cash
    current_weights = np.divide(
        product_values,
        total_before[:, None],
        out=np.zeros_like(product_values),
        where=total_before[:, None] > 0.0,
    )
    threshold_triggered = np.zeros(total_before.shape[0], dtype=bool)
    if threshold_band is not None and float(np.sum(target_weights)) > 0.0:
        threshold_triggered = np.any(np.abs(current_weights - target_weights[None, :]) >= float(threshold_band), axis=1)
    calendar_triggered = _calendar_rebalance_triggered(
        policy_type=policy_type,
        calendar_frequency=calendar_frequency,
        current_date=current_date,
        previous_date=previous_date,
        daily_calendar_rebalance=daily_calendar_rebalance,
    )
    if policy_type == "threshold":
        rebalance_mask = threshold_triggered
    elif policy_type == "calendar":
        rebalance_mask = np.full(total_before.shape[0], calendar_triggered, dtype=bool)
    elif policy_type == "hybrid":
        rebalance_mask = threshold_triggered | calendar_triggered
    else:
        rebalance_mask = np.zeros(total_before.shape[0], dtype=bool)
    if not np.any(rebalance_mask) or float(np.sum(target_weights)) <= 0.0:
        return product_values, cash
    desired = total_before[:, None] * target_weights[None, :]
    turnover = 0.5 * np.sum(np.abs(desired - product_values), axis=1)
    if min_trade_amount is not None:
        rebalance_mask &= turnover >= float(min_trade_amount)
    if not np.any(rebalance_mask):
        return product_values, cash
    investable = np.maximum(0.0, total_before - turnover * transaction_cost_rate)
    updated_values = np.array(product_values, copy=True)
    updated_cash = np.array(cash, copy=True)
    updated_values[rebalance_mask] = investable[rebalance_mask, None] * target_weights[None, :]
    updated_cash[rebalance_mask] = 0.0
    return updated_values, updated_cash


def _simulate_paths_batch(
    runtime_input: DailyEngineRuntimeInput,
    compiled: _CompiledRuntimeContext,
    rng: np.random.Generator,
    *,
    path_count: int,
) -> list[PathOutcome]:
    factor_count = compiled.factor_initial_variances.shape[0]
    path_product_values = np.tile(compiled.initial_product_values[None, :], (path_count, 1))
    cash = np.zeros(path_count, dtype=float)
    initial_values = np.sum(path_product_values, axis=1) + cash
    peak_values = np.array(initial_values, copy=True)
    max_drawdowns = np.zeros(path_count, dtype=float)
    factor_variances = np.tile(compiled.factor_initial_variances[None, :], (path_count, 1))
    product_variances = np.tile(compiled.product_initial_variances[None, :], (path_count, 1))
    q_matrix = np.tile(compiled.q_bar_matrix[None, :, :], (path_count, 1, 1))
    regime_indices = np.full(path_count, compiled.initial_regime_index, dtype=int)
    previous_step_date = runtime_input.as_of

    for step_date in compiled.step_dates:
        transition_rows = compiled.regime_transition_matrix[regime_indices]
        cumulative_transitions = np.cumsum(transition_rows, axis=1)
        next_regime_indices = np.sum(
            rng.random(size=(path_count, 1)) > cumulative_transitions,
            axis=1,
        ).astype(int)
        volatility_multiplier = compiled.volatility_multiplier_by_regime[next_regime_indices]
        mean_shift = compiled.mean_shift_by_regime[next_regime_indices]

        diagonal = np.sqrt(np.maximum(np.diagonal(q_matrix, axis1=1, axis2=2), 1e-12))
        inverse_diagonal = 1.0 / diagonal
        correlation = q_matrix * inverse_diagonal[:, :, None] * inverse_diagonal[:, None, :]
        correlation[:, np.arange(factor_count), np.arange(factor_count)] = 1.0

        factor_shocks = _draw_standardized_factor_matrix(
            rng,
            correlation,
            compiled.correlation_identity,
            factor_is_student_t=compiled.factor_is_student_t,
            tail_df=compiled.factor_tail_df,
        )
        previous_factor_variances = np.array(factor_variances, copy=True)
        factor_sigmas = np.sqrt(np.maximum(previous_factor_variances, 1e-12)) * volatility_multiplier[:, None]
        factor_residuals = factor_sigmas * factor_shocks
        factor_returns = factor_residuals + mean_shift[:, None]

        systemic_jump_probability = np.clip(
            compiled.systemic_jump_probability_base
            * compiled.systemic_jump_probability_multiplier_by_regime[next_regime_indices],
            0.0,
            1.0,
        )
        systemic_jump_fired = rng.random(size=path_count) < systemic_jump_probability
        systemic_dispersion = np.maximum(
            0.0,
            compiled.systemic_jump_dispersion_base
            * compiled.systemic_jump_dispersion_multiplier_by_regime[next_regime_indices],
        )

        previous_product_variances = np.array(product_variances, copy=True)
        product_sigmas = np.sqrt(np.maximum(previous_product_variances, 1e-12)) * volatility_multiplier[:, None]
        product_idio_residuals = product_sigmas * _draw_product_idiosyncratic_shocks_batch(
            rng,
            path_count=path_count,
            student_t_mask=compiled.product_student_t_mask,
            tail_df=compiled.product_tail_df,
        )
        pre_jump_returns = factor_returns @ compiled.product_beta_matrix.T + product_idio_residuals

        systemic_components = np.zeros_like(pre_jump_returns)
        if np.any(systemic_jump_fired):
            systemic_noise = rng.normal(loc=0.0, scale=1.0, size=pre_jump_returns.shape) * (
                systemic_dispersion[:, None] * 0.25
            )
            systemic_components = np.where(
                systemic_jump_fired[:, None],
                compiled.product_systemic_factor_impact[None, :] + systemic_noise,
                0.0,
            )

        idio_jump_probabilities = np.broadcast_to(
            compiled.product_base_jump_probability[None, :],
            pre_jump_returns.shape,
        ).copy()
        idio_jump_means = np.broadcast_to(compiled.product_base_jump_loss_mean[None, :], pre_jump_returns.shape).copy()
        idio_jump_stds = np.broadcast_to(compiled.product_base_jump_loss_std[None, :], pre_jump_returns.shape).copy()
        if np.any(compiled.product_jump_profile_from_state):
            state_mask = compiled.product_jump_profile_from_state[None, :]
            idio_jump_probabilities = np.where(
                state_mask,
                np.clip(
                    idio_jump_probabilities
                    * compiled.idio_jump_probability_multiplier_by_regime[next_regime_indices][:, None],
                    0.0,
                    1.0,
                ),
                idio_jump_probabilities,
            )
            idio_jump_means = np.where(
                state_mask,
                idio_jump_means * compiled.idio_loss_multiplier_by_regime[next_regime_indices][:, None],
                idio_jump_means,
            )
            idio_jump_stds = np.where(
                state_mask,
                np.maximum(
                    idio_jump_stds * compiled.idio_loss_std_multiplier_by_regime[next_regime_indices][:, None],
                    1e-12,
                ),
                idio_jump_stds,
            )
        idio_jump_mask = rng.random(size=pre_jump_returns.shape) < idio_jump_probabilities
        idio_draws = rng.normal(loc=idio_jump_means, scale=idio_jump_stds)
        idio_components = np.where(idio_jump_mask, idio_draws, 0.0)

        product_returns_array = pre_jump_returns + systemic_components + idio_components + compiled.product_drags[None, :]
        path_product_values = np.maximum(0.0, path_product_values * (1.0 + product_returns_array))
        contributions = compiled.contribution_schedule_by_date.get(step_date, [])
        withdrawals = compiled.withdrawal_schedule_by_date.get(step_date, [])
        if contributions:
            path_product_values, cash = _apply_contributions_vectorized_batch(
                path_product_values,
                cash,
                contributions,
                product_index_by_id=compiled.product_index_by_id,
                target_weights=compiled.target_weights,
            )
        if withdrawals:
            path_product_values, cash = _apply_withdrawals_vectorized_batch(
                path_product_values,
                cash,
                withdrawals,
                product_index_by_id=compiled.product_index_by_id,
            )
        path_product_values, cash = _rebalance_vectorized_batch(
            path_product_values,
            cash,
            policy_type=compiled.policy_type,
            execution_timing=compiled.execution_timing,
            target_weights=compiled.target_weights,
            threshold_band=compiled.threshold_band,
            min_trade_amount=compiled.min_trade_amount,
            transaction_cost_rate=compiled.transaction_cost_rate,
            current_date=step_date,
            previous_date=previous_step_date,
            calendar_frequency=compiled.calendar_frequency,
            daily_calendar_rebalance=compiled.daily_calendar_rebalance,
        )
        current_net_values = np.sum(path_product_values, axis=1) + cash
        peak_values = np.maximum(peak_values, current_net_values)
        max_drawdowns = np.maximum(
            max_drawdowns,
            1.0 - np.divide(current_net_values, peak_values, out=np.ones_like(current_net_values), where=peak_values > 0.0),
        )

        factor_variances = np.maximum(
            (compiled.factor_omega[None, :] * (volatility_multiplier[:, None] ** 2))
            + (compiled.factor_alpha[None, :] * np.square(factor_residuals))
            + (compiled.factor_beta[None, :] * previous_factor_variances),
            1e-12,
        )
        q_matrix = (
            (1.0 - compiled.dcc_alpha - compiled.dcc_beta) * compiled.q_bar_matrix[None, :, :]
            + compiled.dcc_alpha * np.einsum("pi,pj->pij", factor_shocks, factor_shocks)
            + compiled.dcc_beta * q_matrix
        )
        product_variances = np.maximum(
            (compiled.product_omega[None, :] * (volatility_multiplier[:, None] ** 2))
            + (compiled.product_alpha[None, :] * np.square(product_idio_residuals))
            + (compiled.product_garch_beta[None, :] * previous_product_variances),
            1e-12,
        )
        regime_indices = next_regime_indices
        previous_step_date = step_date

    terminal_values = np.sum(path_product_values, axis=1) + cash
    successes = terminal_values >= compiled.target_value
    if compiled.drawdown_constraint is not None:
        successes &= max_drawdowns <= float(compiled.drawdown_constraint)
    return [
        PathOutcome(
            terminal_value=float(terminal_values[index]),
            cagr=_annualized_cagr(float(initial_values[index]), float(terminal_values[index]), runtime_input.path_horizon_days),
            max_drawdown=float(max_drawdowns[index]),
            success=bool(successes[index]),
        )
        for index in range(path_count)
    ]


def simulate_primary_paths(
    runtime_input: DailyEngineRuntimeInput,
    recipe: SimulationRecipe,
) -> RecipeSimulationResult:
    if runtime_input.factor_dynamics is None or runtime_input.regime_state is None or runtime_input.jump_state is None:
        raise ValueError("factor_dynamics, regime_state, and jump_state are required")
    compiled = _compiled_runtime_context(runtime_input)
    rng = np.random.default_rng(runtime_input.random_seed)
    outcomes = _simulate_paths_batch(runtime_input, compiled, rng, path_count=recipe.path_count)
    return _summarize_outcomes(runtime_input, recipe, outcomes)


def probability_engine_confidence_level(runtime_input: DailyEngineRuntimeInput) -> str:
    return _confidence_level(runtime_input.products)


def _simulate_single_path(
    runtime_input: DailyEngineRuntimeInput,
    compiled: _CompiledRuntimeContext,
    rng: np.random.Generator,
) -> PathOutcome:
    product_values = np.array(compiled.initial_product_values, copy=True)
    cash = 0.0
    initial_value = float(np.sum(product_values) + cash)
    peak_value = initial_value
    max_drawdown = 0.0

    factor_variances = np.array(compiled.factor_initial_variances, copy=True)
    product_variances = np.array(compiled.product_initial_variances, copy=True)
    q_matrix = np.array(compiled.q_bar_matrix, copy=True)
    regime_index = compiled.initial_regime_index
    previous_step_date = runtime_input.as_of

    for step_date in compiled.step_dates:
        next_regime_index = int(rng.choice(len(compiled.regime_names), p=compiled.regime_transition_matrix[regime_index]))
        volatility_multiplier = float(compiled.volatility_multiplier_by_regime[next_regime_index])
        mean_shift = float(compiled.mean_shift_by_regime[next_regime_index])

        current_correlation = _current_correlation_from_q_matrix(q_matrix)
        factor_shocks = _draw_standardized_factor_vector(
            rng,
            current_correlation,
            compiled.correlation_identity,
            compiled.factor_is_student_t,
            compiled.factor_tail_df,
        )
        previous_factor_variances = np.array(factor_variances, copy=True)
        factor_sigmas = np.sqrt(np.maximum(previous_factor_variances, 1e-12)) * volatility_multiplier
        factor_residuals = factor_sigmas * factor_shocks
        factor_returns = factor_residuals + mean_shift

        systemic_jump_probability = _clamp_probability(
            compiled.systemic_jump_probability_base
            * float(compiled.systemic_jump_probability_multiplier_by_regime[next_regime_index])
        )
        systemic_jump_fired = bool(rng.random() < systemic_jump_probability)
        systemic_dispersion = max(
            0.0,
            compiled.systemic_jump_dispersion_base
            * float(compiled.systemic_jump_dispersion_multiplier_by_regime[next_regime_index]),
        )

        previous_product_variances = np.array(product_variances, copy=True)
        product_sigmas = np.sqrt(np.maximum(previous_product_variances, 1e-12)) * volatility_multiplier
        product_idio_residuals = product_sigmas * _draw_product_idiosyncratic_shocks(
            rng,
            compiled.product_student_t_mask,
            compiled.product_tail_df,
        )
        pre_jump_returns = compiled.product_beta_matrix @ factor_returns + product_idio_residuals

        systemic_components = np.zeros_like(pre_jump_returns)
        if systemic_jump_fired:
            systemic_components = compiled.product_systemic_factor_impact + rng.normal(
                0.0,
                systemic_dispersion * 0.25,
                size=compiled.product_systemic_factor_impact.shape[0],
            )

        idio_jump_probabilities = np.array(compiled.product_base_jump_probability, copy=True)
        idio_jump_means = np.array(compiled.product_base_jump_loss_mean, copy=True)
        idio_jump_stds = np.array(compiled.product_base_jump_loss_std, copy=True)
        if np.any(compiled.product_jump_profile_from_state):
            state_mask = compiled.product_jump_profile_from_state
            idio_jump_probabilities[state_mask] = np.clip(
                idio_jump_probabilities[state_mask]
                * float(compiled.idio_jump_probability_multiplier_by_regime[next_regime_index]),
                0.0,
                1.0,
            )
            idio_jump_means[state_mask] = (
                idio_jump_means[state_mask] * float(compiled.idio_loss_multiplier_by_regime[next_regime_index])
            )
            idio_jump_stds[state_mask] = np.maximum(
                idio_jump_stds[state_mask] * float(compiled.idio_loss_std_multiplier_by_regime[next_regime_index]),
                1e-12,
            )
        idio_jump_mask = rng.random(size=compiled.product_base_jump_probability.shape[0]) < idio_jump_probabilities
        idio_components = np.zeros_like(pre_jump_returns)
        if np.any(idio_jump_mask):
            idio_components[idio_jump_mask] = rng.normal(
                loc=idio_jump_means[idio_jump_mask],
                scale=idio_jump_stds[idio_jump_mask],
            )

        product_returns_array = pre_jump_returns + systemic_components + idio_components + compiled.product_drags
        product_values = np.maximum(0.0, product_values * (1.0 + product_returns_array))
        contributions = compiled.contribution_schedule_by_date.get(step_date, [])
        withdrawals = compiled.withdrawal_schedule_by_date.get(step_date, [])
        if contributions:
            product_values, cash = _apply_contributions_vectorized(
                product_values,
                cash,
                contributions,
                product_index_by_id=compiled.product_index_by_id,
                target_weights=compiled.target_weights,
            )
        if withdrawals:
            product_values, cash = _apply_withdrawals_vectorized(
                product_values,
                cash,
                withdrawals,
                product_index_by_id=compiled.product_index_by_id,
            )
        product_values, cash = _rebalance_vectorized(
            product_values,
            cash,
            policy_type=compiled.policy_type,
            execution_timing=compiled.execution_timing,
            target_weights=compiled.target_weights,
            threshold_band=compiled.threshold_band,
            min_trade_amount=compiled.min_trade_amount,
            transaction_cost_rate=compiled.transaction_cost_rate,
            current_date=step_date,
            previous_date=previous_step_date,
            calendar_frequency=compiled.calendar_frequency,
            daily_calendar_rebalance=compiled.daily_calendar_rebalance,
        )
        current_net_value = float(np.sum(product_values) + cash)
        peak_value = max(peak_value, current_net_value)
        if peak_value > 0.0:
            max_drawdown = max(max_drawdown, 1.0 - (current_net_value / peak_value))

        factor_variances = np.maximum(
            (compiled.factor_omega * (volatility_multiplier**2))
            + (compiled.factor_alpha * np.square(factor_residuals))
            + (compiled.factor_beta * previous_factor_variances),
            1e-12,
        )
        q_matrix = (
            (1.0 - compiled.dcc_alpha - compiled.dcc_beta) * compiled.q_bar_matrix
            + compiled.dcc_alpha * np.outer(factor_shocks, factor_shocks)
            + compiled.dcc_beta * q_matrix
        )
        product_variances = np.maximum(
            (compiled.product_omega * (volatility_multiplier**2))
            + (compiled.product_alpha * np.square(product_idio_residuals))
            + (compiled.product_garch_beta * previous_product_variances),
            1e-12,
        )
        regime_index = next_regime_index
        previous_step_date = step_date

    terminal_value = float(np.sum(product_values) + cash)
    success = terminal_value >= compiled.target_value
    if compiled.drawdown_constraint is not None:
        success = success and max_drawdown <= float(compiled.drawdown_constraint)
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

    success_count = int(np.sum(successes))
    success_probability = float(success_count / max(len(outcomes), 1))
    success_range = _wilson_interval(success_count, len(outcomes))

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
            success_count=success_count,
            path_count=len(outcomes),
        ),
        calibration_link_ref=runtime_input.evidence_bundle_ref or None,
    )
