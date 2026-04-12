from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from probability_engine.contracts import MarketPressureSnapshot
from probability_engine.path_generator import DailyEngineRuntimeInput
from probability_engine.regime import RegimeStateSpec


_SCENARIO_LEVEL_THRESHOLDS = (
    (25.0, "L0_宽松"),
    (50.0, "L1_中性偏紧"),
    (75.0, "L2_风险偏高"),
)

_DETERIORATION_OVERLAYS: dict[str, dict[str, float]] = {
    "mild": {
        "drift_multiplier": -0.08,
        "volatility_uplift": 0.08,
        "systemic_jump_probability_multiplier": 1.20,
        "idio_jump_probability_multiplier": 1.10,
        "systemic_jump_dispersion_multiplier": 1.05,
        "persistence_uplift": 0.04,
    },
    "moderate": {
        "drift_multiplier": -0.16,
        "volatility_uplift": 0.18,
        "systemic_jump_probability_multiplier": 1.45,
        "idio_jump_probability_multiplier": 1.20,
        "systemic_jump_dispersion_multiplier": 1.10,
        "persistence_uplift": 0.08,
    },
    "severe": {
        "drift_multiplier": -0.28,
        "volatility_uplift": 0.32,
        "systemic_jump_probability_multiplier": 1.90,
        "idio_jump_probability_multiplier": 1.35,
        "systemic_jump_dispersion_multiplier": 1.18,
        "persistence_uplift": 0.14,
    },
}


def _clamp(value: float, *, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, float(value)))


def _clamp01(value: float) -> float:
    return _clamp(value, lower=0.0, upper=1.0)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / float(len(values)))


def _current_regime(runtime_input: DailyEngineRuntimeInput) -> str:
    return str(runtime_input.regime_state.current_regime).strip()


def _current_regime_row(runtime_input: DailyEngineRuntimeInput) -> tuple[int, list[float]]:
    regime_name = _current_regime(runtime_input)
    index = runtime_input.regime_state.regime_names.index(regime_name)
    return index, [float(value) for value in runtime_input.regime_state.transition_matrix[index]]


def _current_regime_adjustments(runtime_input: DailyEngineRuntimeInput) -> tuple[dict[str, float], dict[str, float]]:
    regime_name = _current_regime(runtime_input)
    mean_adjustments = dict(runtime_input.regime_state.regime_mean_adjustments.get(regime_name, {}))
    jump_adjustments = dict(runtime_input.regime_state.regime_jump_adjustments.get(regime_name, {}))
    vol_adjustments = dict(runtime_input.regime_state.regime_vol_adjustments.get(regime_name, {}))
    return (
        {
            "mean_shift": float(mean_adjustments.get("mean_shift", 0.0)),
        },
        {
            "volatility_multiplier": float(vol_adjustments.get("volatility_multiplier", 1.0)),
            "systemic_jump_probability_multiplier": float(jump_adjustments.get("systemic_jump_probability_multiplier", 1.0)),
            "idio_jump_probability_multiplier": float(jump_adjustments.get("idio_jump_probability_multiplier", 1.0)),
            "systemic_jump_dispersion_multiplier": float(jump_adjustments.get("systemic_jump_dispersion_multiplier", 1.0)),
        },
    )


def _base_daily_drift(runtime_input: DailyEngineRuntimeInput) -> float:
    expected_returns = [float(value) for value in runtime_input.factor_dynamics.expected_return_by_factor.values()]
    if not expected_returns:
        return 0.0
    return float(_mean(expected_returns) / 252.0)


def _regime_pressure_component(runtime_input: DailyEngineRuntimeInput) -> float:
    regime_name = _current_regime(runtime_input)
    regime_base = {"normal": 10.0, "risk_off": 45.0, "stress": 75.0}.get(regime_name, 10.0)
    _, row = _current_regime_row(runtime_input)
    p_self = float(row[runtime_input.regime_state.regime_names.index(regime_name)])
    persistence_bonus = 25.0 * _clamp01((p_self - 0.60) / 0.30)
    return _clamp(regime_base + persistence_bonus)


def _drift_haircut_component(runtime_input: DailyEngineRuntimeInput) -> float:
    base_daily_drift = _base_daily_drift(runtime_input)
    current_mean_shift = _current_regime_mean_shift(runtime_input)
    effective_daily_drift = max(base_daily_drift + current_mean_shift, -0.005)
    drift_haircut_ratio = _clamp01((base_daily_drift - effective_daily_drift) / max(base_daily_drift, 1e-9))
    return 100.0 * drift_haircut_ratio


def _volatility_component(runtime_input: DailyEngineRuntimeInput) -> float:
    current_vol_multiplier = _current_regime_adjustments(runtime_input)[1]["volatility_multiplier"]
    return 100.0 * _clamp01((current_vol_multiplier - 1.0) / 0.40)


def _jump_probability_component(runtime_input: DailyEngineRuntimeInput) -> float:
    adjustments = _current_regime_adjustments(runtime_input)[1]
    sys_mult = adjustments["systemic_jump_probability_multiplier"]
    idio_mult = adjustments["idio_jump_probability_multiplier"]
    return 50.0 * _clamp01((sys_mult - 1.0) / 1.0) + 50.0 * _clamp01((idio_mult - 1.0) / 0.50)


def _tail_severity_component(runtime_input: DailyEngineRuntimeInput) -> float:
    disp_mult = _current_regime_adjustments(runtime_input)[1]["systemic_jump_dispersion_multiplier"]
    return 100.0 * _clamp01((disp_mult - 1.0) / 0.20)


def _drift_haircut_component(runtime_input: DailyEngineRuntimeInput) -> float:
    base_daily_drift = _base_daily_drift(runtime_input)
    current_mean_shift = _current_regime_mean_shift(runtime_input)
    effective_daily_drift = max(base_daily_drift + current_mean_shift, -0.005)
    drift_haircut_ratio = _clamp01((base_daily_drift - effective_daily_drift) / max(base_daily_drift, 1e-9))
    return 100.0 * drift_haircut_ratio


def _volatility_component(runtime_input: DailyEngineRuntimeInput) -> float:
    current_vol_multiplier = _current_regime_volatility_multiplier(runtime_input)
    return 100.0 * _clamp01((current_vol_multiplier - 1.0) / 0.40)


def _jump_probability_component(runtime_input: DailyEngineRuntimeInput) -> float:
    systemic_jump_probability_multiplier, idio_jump_probability_multiplier, _ = _current_regime_jump_multipliers(runtime_input)
    return 50.0 * _clamp01((systemic_jump_probability_multiplier - 1.0) / 1.0) + 50.0 * _clamp01(
        (idio_jump_probability_multiplier - 1.0) / 0.50
    )


def _tail_severity_component(runtime_input: DailyEngineRuntimeInput) -> float:
    _, _, systemic_jump_dispersion_multiplier = _current_regime_jump_multipliers(runtime_input)
    return 100.0 * _clamp01((systemic_jump_dispersion_multiplier - 1.0) / 0.20)


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

    current_regime = _current_regime(runtime)
    regime_component = _regime_pressure_component(runtime)
    base_daily_drift = _base_daily_drift(runtime)
    current_mean_shift, current_multipliers = _current_regime_adjustments(runtime)
    effective_daily_drift = max(base_daily_drift + current_mean_shift["mean_shift"], -0.005)
    drift_haircut_component = _drift_haircut_component(runtime)
    volatility_component = _volatility_component(runtime)
    jump_probability_component = _jump_probability_component(runtime)
    tail_severity_component = _tail_severity_component(runtime)

    score = (
        0.30 * regime_component
        + 0.10 * drift_haircut_component
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
        volatility_multiplier=current_multipliers["volatility_multiplier"],
        systemic_jump_probability_multiplier=current_multipliers["systemic_jump_probability_multiplier"],
        idio_jump_probability_multiplier=current_multipliers["idio_jump_probability_multiplier"],
        systemic_jump_dispersion_multiplier=current_multipliers["systemic_jump_dispersion_multiplier"],
    )


def _mutate_current_regime_row(
    regime_state: RegimeStateSpec,
    *,
    persistence_uplift: float,
) -> list[list[float]]:
    regime_name = str(regime_state.current_regime).strip()
    current_index = regime_state.regime_names.index(regime_name)
    current_row = [float(value) for value in regime_state.transition_matrix[current_index]]
    current_p_self = float(current_row[current_index])
    new_p_self = min(0.95, current_p_self + float(persistence_uplift))
    if len(current_row) == 1:
        return [[1.0]]
    remaining_mass = max(0.0, 1.0 - new_p_self)
    off_diagonal_total = max(0.0, 1.0 - current_p_self)
    if off_diagonal_total <= 1e-12:
        redistributed = [
            remaining_mass / float(len(current_row) - 1) if idx != current_index else new_p_self
            for idx in range(len(current_row))
        ]
    else:
        scale = remaining_mass / off_diagonal_total
        redistributed = [
            new_p_self if idx == current_index else float(value) * scale
            for idx, value in enumerate(current_row)
        ]
    adjusted_matrix = [list(row) for row in regime_state.transition_matrix]
    adjusted_matrix[current_index] = redistributed
    return adjusted_matrix


def _current_regime_mean_shift(runtime_input: DailyEngineRuntimeInput) -> float:
    return _current_regime_adjustments(runtime_input)[0]["mean_shift"]


def _current_regime_volatility_multiplier(runtime_input: DailyEngineRuntimeInput) -> float:
    return _current_regime_adjustments(runtime_input)[1]["volatility_multiplier"]


def _current_regime_jump_multipliers(runtime_input: DailyEngineRuntimeInput) -> tuple[float, float, float]:
    adjustments = _current_regime_adjustments(runtime_input)[1]
    return (
        adjustments["systemic_jump_probability_multiplier"],
        adjustments["idio_jump_probability_multiplier"],
        adjustments["systemic_jump_dispersion_multiplier"],
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
    base_daily_drift = _base_daily_drift(runtime)
    regime_state = runtime.regime_state
    current_regime = str(regime_state.current_regime).strip()
    current_mean_adjustments = deepcopy(regime_state.regime_mean_adjustments.get(current_regime, {}))
    current_vol_adjustments = deepcopy(regime_state.regime_vol_adjustments.get(current_regime, {}))
    current_jump_adjustments = deepcopy(regime_state.regime_jump_adjustments.get(current_regime, {}))
    current_mean_adjustments["mean_shift"] = float(current_mean_adjustments.get("mean_shift", 0.0)) + float(
        overlay["drift_multiplier"] * base_daily_drift
    )
    current_vol_adjustments["volatility_multiplier"] = float(current_vol_adjustments.get("volatility_multiplier", 1.0)) + float(
        overlay["volatility_uplift"]
    )
    current_jump_adjustments["systemic_jump_probability_multiplier"] = float(
        current_jump_adjustments.get("systemic_jump_probability_multiplier", 1.0)
    ) * float(overlay["systemic_jump_probability_multiplier"])
    current_jump_adjustments["idio_jump_probability_multiplier"] = float(
        current_jump_adjustments.get("idio_jump_probability_multiplier", 1.0)
    ) * float(overlay["idio_jump_probability_multiplier"])
    current_jump_adjustments["systemic_jump_dispersion_multiplier"] = float(
        current_jump_adjustments.get("systemic_jump_dispersion_multiplier", 1.0)
    ) * float(overlay["systemic_jump_dispersion_multiplier"])

    updated_mean_adjustments = deepcopy(regime_state.regime_mean_adjustments)
    updated_vol_adjustments = deepcopy(regime_state.regime_vol_adjustments)
    updated_jump_adjustments = deepcopy(regime_state.regime_jump_adjustments)
    updated_mean_adjustments[current_regime] = current_mean_adjustments
    updated_vol_adjustments[current_regime] = current_vol_adjustments
    updated_jump_adjustments[current_regime] = current_jump_adjustments

    return replace(
        runtime,
        regime_state=replace(
            regime_state,
            transition_matrix=_mutate_current_regime_row(
                regime_state,
                persistence_uplift=float(overlay["persistence_uplift"]),
            ),
            regime_mean_adjustments=updated_mean_adjustments,
            regime_vol_adjustments=updated_vol_adjustments,
            regime_jump_adjustments=updated_jump_adjustments,
        ),
    )
