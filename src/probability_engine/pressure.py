from __future__ import annotations

from dataclasses import replace
from typing import Any

from probability_engine.contracts import MarketPressureSnapshot
from probability_engine.jumps import JumpStateSpec
from probability_engine.path_generator import DailyEngineRuntimeInput
from probability_engine.regime import RegimeStateSpec
from probability_engine.volatility import FactorDynamicsSpec


_SCENARIO_LEVEL_THRESHOLDS = (
    (25.0, "L0_宽松"),
    (50.0, "L1_中性偏紧"),
    (75.0, "L2_风险偏高"),
)

_DETERIORATION_OVERLAYS: dict[str, dict[str, float]] = {
    "mild": {
        "expected_return_multiplier": 0.90,
        "variance_multiplier": 1.12,
        "tail_df_multiplier": 0.92,
        "systemic_jump_probability_multiplier": 1.12,
        "systemic_jump_dispersion_multiplier": 1.06,
        "idio_jump_probability_multiplier": 1.08,
        "idio_loss_multiplier": 1.03,
        "idio_loss_std_multiplier": 1.06,
        "regime_stay_multiplier": 0.96,
        "regime_off_diagonal_multiplier": 1.04,
        "regime_risk_off_multiplier": 1.03,
        "regime_stress_multiplier": 1.05,
        "regime_mean_shift_delta": -0.00025,
        "regime_volatility_multiplier": 1.06,
        "regime_systemic_jump_probability_multiplier": 1.08,
        "regime_systemic_jump_dispersion_multiplier": 1.04,
        "regime_idio_jump_probability_multiplier": 1.05,
    },
    "moderate": {
        "expected_return_multiplier": 0.75,
        "variance_multiplier": 1.28,
        "tail_df_multiplier": 0.84,
        "systemic_jump_probability_multiplier": 1.28,
        "systemic_jump_dispersion_multiplier": 1.12,
        "idio_jump_probability_multiplier": 1.16,
        "idio_loss_multiplier": 1.06,
        "idio_loss_std_multiplier": 1.12,
        "regime_stay_multiplier": 0.91,
        "regime_off_diagonal_multiplier": 1.09,
        "regime_risk_off_multiplier": 1.06,
        "regime_stress_multiplier": 1.10,
        "regime_mean_shift_delta": -0.00050,
        "regime_volatility_multiplier": 1.12,
        "regime_systemic_jump_probability_multiplier": 1.15,
        "regime_systemic_jump_dispersion_multiplier": 1.08,
        "regime_idio_jump_probability_multiplier": 1.10,
    },
    "severe": {
        "expected_return_multiplier": 0.60,
        "variance_multiplier": 1.48,
        "tail_df_multiplier": 0.74,
        "systemic_jump_probability_multiplier": 1.48,
        "systemic_jump_dispersion_multiplier": 1.22,
        "idio_jump_probability_multiplier": 1.30,
        "idio_loss_multiplier": 1.10,
        "idio_loss_std_multiplier": 1.20,
        "regime_stay_multiplier": 0.84,
        "regime_off_diagonal_multiplier": 1.16,
        "regime_risk_off_multiplier": 1.10,
        "regime_stress_multiplier": 1.18,
        "regime_mean_shift_delta": -0.00080,
        "regime_volatility_multiplier": 1.20,
        "regime_systemic_jump_probability_multiplier": 1.22,
        "regime_systemic_jump_dispersion_multiplier": 1.12,
        "regime_idio_jump_probability_multiplier": 1.16,
    },
}


def _clamp(value: float, *, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, float(value)))


def _normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _select_weight_map(
    runtime_input: DailyEngineRuntimeInput,
    *,
    key_getter,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    for position in runtime_input.current_positions:
        weight = max(0.0, float(getattr(position, "weight", 0.0) or 0.0))
        key = str(key_getter(position)).strip()
        if key and weight > 0.0:
            weights[key] = weights.get(key, 0.0) + weight
    total = sum(weights.values())
    if total <= 0.0:
        return {}
    return {key: value / total for key, value in weights.items()}


def _weighted_average(mapping: dict[str, float], weights: dict[str, float]) -> float:
    if not mapping:
        return 0.0
    if not weights:
        return float(sum(float(value) for value in mapping.values()) / float(len(mapping)))
    total = 0.0
    total_weight = 0.0
    for key, value in mapping.items():
        weight = float(weights.get(str(key), 0.0))
        if weight <= 0.0:
            continue
        total += weight * float(value)
        total_weight += weight
    if total_weight <= 0.0:
        return float(sum(float(value) for value in mapping.values()) / float(len(mapping)))
    return total / total_weight


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / float(len(values)))


def _get_regime_row(regime_state: RegimeStateSpec, regime_name: str) -> list[float]:
    index = regime_state.regime_names.index(regime_name)
    return [float(value) for value in regime_state.transition_matrix[index]]


def _regime_pressure_component(regime_state: RegimeStateSpec, regime_name: str) -> float:
    row = _get_regime_row(regime_state, regime_name)
    regime_weights = {name: float(probability) for name, probability in zip(regime_state.regime_names, row, strict=True)}
    stay_probability = float(regime_weights.get(regime_name, 0.0))
    component = 100.0 * (1.0 - stay_probability)
    for stressed_regime, multiplier in (("risk_off", 0.5), ("stress", 0.75)):
        if stressed_regime in regime_weights:
            component += 100.0 * float(regime_weights[stressed_regime]) * multiplier
    return _clamp(component)


def _effective_daily_drift(runtime_input: DailyEngineRuntimeInput) -> float:
    factor_weights = _select_weight_map(runtime_input, key_getter=lambda position: getattr(position, "product_id", ""))
    factor_returns: list[float] = []
    if runtime_input.factor_dynamics.expected_return_by_factor:
        factor_returns.append(
            _weighted_average(
                {str(key): float(value) for key, value in runtime_input.factor_dynamics.expected_return_by_factor.items()},
                factor_weights,
            )
        )
    else:
        factor_returns.append(0.0)

    product_drags: list[float] = []
    for product in runtime_input.products:
        carry_profile = _normalize_mapping(product.carry_profile)
        valuation_profile = _normalize_mapping(product.valuation_profile)
        product_drags.append(
            float(carry_profile.get("carry_drag", 0.0))
            + float(carry_profile.get("tracking_drag", 0.0))
            + float(valuation_profile.get("valuation_drag", 0.0))
        )

    annual_return = _mean(factor_returns)
    daily_return = annual_return / 252.0
    drag = _mean(product_drags)
    return float(daily_return - drag)


def _drift_haircut_component(runtime_input: DailyEngineRuntimeInput) -> float:
    effective_daily_drift = _effective_daily_drift(runtime_input)
    return _clamp(50.0 - 100000.0 * effective_daily_drift)


def _volatility_component(runtime_input: DailyEngineRuntimeInput) -> float:
    factor_weights = _select_weight_map(runtime_input, key_getter=lambda position: getattr(position, "product_id", ""))
    weighted_variances: list[float] = []
    for factor_name, params in runtime_input.factor_dynamics.garch_params_by_factor.items():
        variance = float(params.get("long_run_variance", 0.0))
        if variance <= 0.0:
            variance = float(params.get("omega", 0.0))
        weighted_variances.append(variance * float(factor_weights.get(str(factor_name), 1.0)))
    average_variance = _mean(weighted_variances)
    average_sigma = average_variance ** 0.5 if average_variance > 0.0 else 0.0
    return _clamp(average_sigma * 5000.0)


def _jump_probability_component(runtime_input: DailyEngineRuntimeInput) -> float:
    systemic = float(runtime_input.jump_state.systemic_jump_probability_1d)
    idio_probabilities = [
        float(profile.get("probability_1d", 0.0))
        for profile in runtime_input.jump_state.idio_jump_profile_by_product.values()
    ]
    return _clamp((systemic * 100.0) + (_mean(idio_probabilities) * 100.0))


def _tail_severity_component(runtime_input: DailyEngineRuntimeInput) -> float:
    tail_df = runtime_input.factor_dynamics.tail_df
    tail_pressure = 0.0 if tail_df is None else 100.0 / max(float(tail_df), 2.000001)
    dispersion_pressure = float(runtime_input.jump_state.systemic_jump_dispersion) * 100000.0
    return _clamp(tail_pressure + dispersion_pressure)


def scenario_pressure_level(score: float | None) -> str | None:
    if score is None:
        return None
    numeric_score = float(score)
    for threshold, label in _SCENARIO_LEVEL_THRESHOLDS:
        if numeric_score < threshold:
            return label
    return "L3_高压"


def compute_market_pressure_snapshot(
    runtime_input: DailyEngineRuntimeInput | dict[str, Any],
    *,
    scenario_kind: str,
) -> MarketPressureSnapshot:
    runtime = DailyEngineRuntimeInput.from_any(runtime_input)
    scenario_kind = str(scenario_kind).strip()
    if scenario_kind == "historical_replay":
        return MarketPressureSnapshot(
            scenario_kind=scenario_kind,
            market_pressure_score=None,
            market_pressure_level=None,
            current_regime=None,
            regime_component=None,
            drift_haircut_component=None,
            volatility_component=None,
            jump_probability_component=None,
            tail_severity_component=None,
            effective_daily_drift=None,
            volatility_multiplier=None,
            systemic_jump_probability_multiplier=None,
            idio_jump_probability_multiplier=None,
            systemic_jump_dispersion_multiplier=None,
        )

    current_regime = str(runtime.regime_state.current_regime).strip()
    regime_component = _regime_pressure_component(runtime.regime_state, current_regime)
    effective_daily_drift = _effective_daily_drift(runtime)
    drift_haircut_component = _drift_haircut_component(runtime)
    volatility_component = _volatility_component(runtime)
    jump_probability_component = _jump_probability_component(runtime)
    tail_severity_component = _tail_severity_component(runtime)

    score = (
        0.20 * regime_component
        + 0.20 * drift_haircut_component
        + 0.25 * volatility_component
        + 0.20 * jump_probability_component
        + 0.15 * tail_severity_component
    )

    return MarketPressureSnapshot(
        scenario_kind=scenario_kind,
        market_pressure_score=_clamp(score),
        market_pressure_level=scenario_pressure_level(_clamp(score)),
        current_regime=current_regime,
        regime_component=regime_component,
        drift_haircut_component=drift_haircut_component,
        volatility_component=volatility_component,
        jump_probability_component=jump_probability_component,
        tail_severity_component=tail_severity_component,
        effective_daily_drift=effective_daily_drift,
        volatility_multiplier=float(runtime.regime_state.regime_vol_adjustments.get(current_regime, {}).get("volatility_multiplier", 1.0)),
        systemic_jump_probability_multiplier=float(
            runtime.regime_state.regime_jump_adjustments.get(current_regime, {}).get("systemic_jump_probability_multiplier", 1.0)
        ),
        idio_jump_probability_multiplier=float(
            runtime.regime_state.regime_jump_adjustments.get(current_regime, {}).get("idio_jump_probability_multiplier", 1.0)
        ),
        systemic_jump_dispersion_multiplier=float(
            runtime.regime_state.regime_jump_adjustments.get(current_regime, {}).get("systemic_jump_dispersion_multiplier", 1.0)
        ),
    )


def _scale_transition_matrix(
    regime_state: RegimeStateSpec,
    *,
    stay_multiplier: float,
    off_diagonal_multiplier: float,
    risk_off_multiplier: float,
    stress_multiplier: float,
) -> list[list[float]]:
    adjusted_matrix: list[list[float]] = []
    for row_index, row in enumerate(regime_state.transition_matrix):
        adjusted_row: list[float] = []
        for col_index, probability in enumerate(row):
            multiplier = off_diagonal_multiplier
            if row_index == col_index:
                multiplier = stay_multiplier
            target_regime = regime_state.regime_names[col_index]
            if target_regime == "risk_off":
                multiplier *= risk_off_multiplier
            elif target_regime == "stress":
                multiplier *= stress_multiplier
            adjusted_row.append(max(0.0, float(probability) * float(multiplier)))
        total = sum(adjusted_row)
        if total <= 0.0:
            adjusted_row = [1.0 if idx == row_index else 0.0 for idx in range(len(row))]
            total = 1.0
        adjusted_matrix.append([value / total for value in adjusted_row])
    return adjusted_matrix


def _scale_factor_dynamics(
    factor_dynamics: FactorDynamicsSpec,
    *,
    expected_return_multiplier: float,
    variance_multiplier: float,
    tail_df_multiplier: float,
) -> FactorDynamicsSpec:
    scaled_garch_params: dict[str, dict[str, float]] = {}
    for factor_name, params in factor_dynamics.garch_params_by_factor.items():
        scaled_params = dict(params)
        if "omega" in scaled_params:
            scaled_params["omega"] = max(0.0, float(scaled_params["omega"]) * float(variance_multiplier))
        if "alpha" in scaled_params:
            scaled_params["alpha"] = min(0.999, float(scaled_params["alpha"]) * (1.0 + (variance_multiplier - 1.0) * 0.5))
        if "beta" in scaled_params:
            scaled_params["beta"] = min(0.999, float(scaled_params["beta"]) * (1.0 + (variance_multiplier - 1.0) * 0.25))
        if "long_run_variance" in scaled_params:
            scaled_params["long_run_variance"] = max(1e-12, float(scaled_params["long_run_variance"]) * float(variance_multiplier))
        scaled_garch_params[str(factor_name)] = scaled_params

    return replace(
        factor_dynamics,
        tail_df=None if factor_dynamics.tail_df is None else max(2.000001, float(factor_dynamics.tail_df) * float(tail_df_multiplier)),
        garch_params_by_factor=scaled_garch_params,
        expected_return_by_factor={
            str(factor_name): float(value) * float(expected_return_multiplier)
            for factor_name, value in factor_dynamics.expected_return_by_factor.items()
        },
    )


def _scale_jump_state(
    jump_state: JumpStateSpec,
    *,
    systemic_jump_probability_multiplier: float,
    systemic_jump_dispersion_multiplier: float,
    idio_jump_probability_multiplier: float,
    idio_loss_multiplier: float,
    idio_loss_std_multiplier: float,
) -> JumpStateSpec:
    scaled_profiles: dict[str, dict[str, float]] = {}
    for product_id, profile in jump_state.idio_jump_profile_by_product.items():
        scaled_profile = dict(profile)
        if "probability_1d" in scaled_profile:
            scaled_profile["probability_1d"] = min(1.0, float(scaled_profile["probability_1d"]) * float(idio_jump_probability_multiplier))
        if "loss_mean" in scaled_profile:
            scaled_profile["loss_mean"] = float(scaled_profile["loss_mean"]) * float(idio_loss_multiplier)
        if "loss_std" in scaled_profile:
            scaled_profile["loss_std"] = max(1e-12, float(scaled_profile["loss_std"]) * float(idio_loss_std_multiplier))
        scaled_profiles[str(product_id)] = scaled_profile

    return replace(
        jump_state,
        systemic_jump_probability_1d=min(1.0, float(jump_state.systemic_jump_probability_1d) * float(systemic_jump_probability_multiplier)),
        systemic_jump_dispersion=max(1e-12, float(jump_state.systemic_jump_dispersion) * float(systemic_jump_dispersion_multiplier)),
        idio_jump_profile_by_product=scaled_profiles,
    )


def _scale_regime_state(
    regime_state: RegimeStateSpec,
    *,
    stay_multiplier: float,
    off_diagonal_multiplier: float,
    risk_off_multiplier: float,
    stress_multiplier: float,
    mean_shift_delta: float,
    volatility_multiplier: float,
    systemic_jump_probability_multiplier: float,
    systemic_jump_dispersion_multiplier: float,
    idio_jump_probability_multiplier: float,
) -> RegimeStateSpec:
    adjusted_mean: dict[str, dict[str, float]] = {}
    adjusted_vol: dict[str, dict[str, float]] = {}
    adjusted_jump: dict[str, dict[str, float]] = {}
    for regime_name in regime_state.regime_names:
        mean_adjustments = dict(regime_state.regime_mean_adjustments.get(regime_name, {}))
        mean_adjustments["mean_shift"] = float(mean_adjustments.get("mean_shift", 0.0)) + float(mean_shift_delta)
        adjusted_mean[regime_name] = mean_adjustments

        vol_adjustments = dict(regime_state.regime_vol_adjustments.get(regime_name, {}))
        vol_adjustments["volatility_multiplier"] = float(vol_adjustments.get("volatility_multiplier", 1.0)) * float(volatility_multiplier)
        adjusted_vol[regime_name] = vol_adjustments

        jump_adjustments = dict(regime_state.regime_jump_adjustments.get(regime_name, {}))
        jump_adjustments["systemic_jump_probability_multiplier"] = float(
            jump_adjustments.get("systemic_jump_probability_multiplier", 1.0)
        ) * float(systemic_jump_probability_multiplier)
        jump_adjustments["systemic_jump_dispersion_multiplier"] = float(
            jump_adjustments.get("systemic_jump_dispersion_multiplier", 1.0)
        ) * float(systemic_jump_dispersion_multiplier)
        jump_adjustments["idio_jump_probability_multiplier"] = float(
            jump_adjustments.get("idio_jump_probability_multiplier", 1.0)
        ) * float(idio_jump_probability_multiplier)
        adjusted_jump[regime_name] = jump_adjustments

    return replace(
        regime_state,
        transition_matrix=_scale_transition_matrix(
            regime_state,
            stay_multiplier=stay_multiplier,
            off_diagonal_multiplier=off_diagonal_multiplier,
            risk_off_multiplier=risk_off_multiplier,
            stress_multiplier=stress_multiplier,
        ),
        regime_mean_adjustments=adjusted_mean,
        regime_vol_adjustments=adjusted_vol,
        regime_jump_adjustments=adjusted_jump,
    )


def build_deteriorated_runtime_input(
    runtime_input: DailyEngineRuntimeInput | dict[str, Any],
    *,
    level: str,
) -> DailyEngineRuntimeInput:
    runtime = DailyEngineRuntimeInput.from_any(runtime_input)
    normalized_level = str(level).strip().lower()
    if normalized_level not in _DETERIORATION_OVERLAYS:
        raise ValueError(f"unknown pressure deterioration level: {level}")
    overlay = _DETERIORATION_OVERLAYS[normalized_level]
    return replace(
        runtime,
        factor_dynamics=_scale_factor_dynamics(
            runtime.factor_dynamics,
            expected_return_multiplier=float(overlay["expected_return_multiplier"]),
            variance_multiplier=float(overlay["variance_multiplier"]),
            tail_df_multiplier=float(overlay["tail_df_multiplier"]),
        ),
        jump_state=_scale_jump_state(
            runtime.jump_state,
            systemic_jump_probability_multiplier=float(overlay["systemic_jump_probability_multiplier"]),
            systemic_jump_dispersion_multiplier=float(overlay["systemic_jump_dispersion_multiplier"]),
            idio_jump_probability_multiplier=float(overlay["idio_jump_probability_multiplier"]),
            idio_loss_multiplier=float(overlay["idio_loss_multiplier"]),
            idio_loss_std_multiplier=float(overlay["idio_loss_std_multiplier"]),
        ),
        regime_state=_scale_regime_state(
            runtime.regime_state,
            stay_multiplier=float(overlay["regime_stay_multiplier"]),
            off_diagonal_multiplier=float(overlay["regime_off_diagonal_multiplier"]),
            risk_off_multiplier=float(overlay["regime_risk_off_multiplier"]),
            stress_multiplier=float(overlay["regime_stress_multiplier"]),
            mean_shift_delta=float(overlay["regime_mean_shift_delta"]),
            volatility_multiplier=float(overlay["regime_volatility_multiplier"]),
            systemic_jump_probability_multiplier=float(overlay["regime_systemic_jump_probability_multiplier"]),
            systemic_jump_dispersion_multiplier=float(overlay["regime_systemic_jump_dispersion_multiplier"]),
            idio_jump_probability_multiplier=float(overlay["regime_idio_jump_probability_multiplier"]),
        ),
    )
