from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
import json
from typing import Any

import numpy as np

from probability_engine.regime import RegimeStateSpec, regime_adjustments


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _coerce_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return dict(value)


def _select_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "systemic_jump_probability_1d",
        "systemic_jump_impact_by_factor",
        "systemic_jump_dispersion",
        "idio_jump_profile_by_product",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _regime_adjustment_value(
    regime_state: RegimeStateSpec | dict[str, Any] | None,
    regime_name: str | None,
    key: str,
    default: float,
) -> float:
    if regime_state is None:
        return float(default)
    regime = RegimeStateSpec.from_any(regime_state)
    if regime is None:
        raise ValueError("regime_state is required")
    selected = str(regime_name or regime.current_regime).strip()
    adjustments = regime_adjustments(regime, regime_name=selected)["jump"]
    return float(adjustments.get(key, default))


@dataclass
class JumpStateSpec:
    systemic_jump_probability_1d: float
    systemic_jump_impact_by_factor: dict[str, float]
    systemic_jump_dispersion: float
    idio_jump_profile_by_product: dict[str, dict[str, float]]

    def __post_init__(self) -> None:
        self.systemic_jump_probability_1d = float(self.systemic_jump_probability_1d)
        if not 0.0 <= self.systemic_jump_probability_1d <= 1.0:
            raise ValueError("systemic_jump_probability_1d must be between 0 and 1")
        self.systemic_jump_impact_by_factor = {
            str(key): float(value) for key, value in dict(self.systemic_jump_impact_by_factor or {}).items()
        }
        self.systemic_jump_dispersion = float(self.systemic_jump_dispersion)
        if self.systemic_jump_dispersion <= 0.0:
            raise ValueError("systemic_jump_dispersion must be positive")
        self.idio_jump_profile_by_product = {
            str(product_id): {str(key): float(value) for key, value in _coerce_mapping(profile, context=f"idio_jump_profile_by_product[{product_id}]").items()}
            for product_id, profile in dict(self.idio_jump_profile_by_product or {}).items()
        }

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    @classmethod
    def from_any(cls, value: "JumpStateSpec | dict[str, Any] | None") -> "JumpStateSpec | None":
        if value is None or isinstance(value, cls):
            return value
        return cls(**dict(value))


def load_jump_state_snapshot(snapshot_path: str | Path) -> JumpStateSpec:
    payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("jump state snapshot must be a JSON object")
    return JumpStateSpec.from_any(_select_fields(payload))  # type: ignore[return-value]


def systemic_jump_probability(
    jump_state: JumpStateSpec | dict[str, Any],
    regime_state: RegimeStateSpec | dict[str, Any] | None = None,
    regime_name: str | None = None,
) -> float:
    state = JumpStateSpec.from_any(jump_state)
    if state is None:
        raise ValueError("jump_state is required")
    probability = float(state.systemic_jump_probability_1d)
    if regime_state is not None:
        probability *= _regime_adjustment_value(regime_state, regime_name, "systemic_jump_probability_multiplier", 1.0)
    return max(0.0, min(1.0, probability))


def regime_adjusted_systemic_jump_dispersion(
    jump_state: JumpStateSpec | dict[str, Any],
    regime_state: RegimeStateSpec | dict[str, Any] | None = None,
    regime_name: str | None = None,
) -> float:
    state = JumpStateSpec.from_any(jump_state)
    if state is None:
        raise ValueError("jump_state is required")
    dispersion = float(state.systemic_jump_dispersion)
    if regime_state is not None:
        dispersion *= _regime_adjustment_value(
            regime_state,
            regime_name,
            "systemic_jump_dispersion_multiplier",
            1.0,
        )
    return max(0.0, dispersion)


def systemic_jump_impact_by_factor(
    jump_state: JumpStateSpec | dict[str, Any],
    factor_name: str,
) -> float:
    state = JumpStateSpec.from_any(jump_state)
    if state is None:
        raise ValueError("jump_state is required")
    return float(state.systemic_jump_impact_by_factor.get(str(factor_name).strip(), 0.0))


def idiosyncratic_jump_profile(
    jump_state: JumpStateSpec | dict[str, Any],
    product_id: str,
    regime_state: RegimeStateSpec | dict[str, Any] | None = None,
    regime_name: str | None = None,
) -> dict[str, float]:
    state = JumpStateSpec.from_any(jump_state)
    if state is None:
        raise ValueError("jump_state is required")
    profile = dict(state.idio_jump_profile_by_product.get(str(product_id).strip(), {}))
    if regime_state is not None:
        regime = RegimeStateSpec.from_any(regime_state)
        if regime is None:
            raise ValueError("regime_state is required")
        selected = str(regime_name or regime.current_regime).strip()
        adjustments = regime_adjustments(regime, regime_name=selected)["jump"]
        probability_multiplier = float(adjustments.get("idio_jump_probability_multiplier", 1.0))
        if "probability_1d" in profile:
            profile["probability_1d"] = float(profile["probability_1d"]) * probability_multiplier
        if "loss_mean" in profile:
            profile["loss_mean"] = float(profile["loss_mean"]) * float(adjustments.get("idio_loss_multiplier", 1.0))
        if "loss_std" in profile:
            profile["loss_std"] = float(profile["loss_std"]) * float(adjustments.get("idio_loss_std_multiplier", 1.0))
    return profile


def draw_systemic_jump(
    jump_state: JumpStateSpec | dict[str, Any],
    regime_state: RegimeStateSpec | dict[str, Any] | None = None,
    regime_name: str | None = None,
    random_state: int | np.random.Generator | None = None,
) -> bool:
    rng = random_state if isinstance(random_state, np.random.Generator) else np.random.default_rng(random_state)
    return bool(rng.random() < systemic_jump_probability(jump_state, regime_state=regime_state, regime_name=regime_name))
