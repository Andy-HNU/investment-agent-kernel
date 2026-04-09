from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
import json
from typing import Any

import numpy as np


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


def _coerce_matrix(value: Any, *, context: str) -> list[list[float]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    matrix: list[list[float]] = []
    for row in value:
        if not isinstance(row, list):
            raise ValueError(f"{context} must contain row lists")
        matrix.append([float(item) for item in row])
    return matrix


def _normalize_row(row: list[float]) -> list[float]:
    total = float(sum(row))
    if total <= 0.0:
        raise ValueError("transition matrix row must sum to a positive value")
    return [float(value) / total for value in row]


def _select_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "regime_names",
        "current_regime",
        "transition_matrix",
        "regime_mean_adjustments",
        "regime_vol_adjustments",
        "regime_jump_adjustments",
    }
    return {key: value for key, value in payload.items() if key in allowed}


@dataclass
class RegimeStateSpec:
    regime_names: list[str]
    current_regime: str
    transition_matrix: list[list[float]]
    regime_mean_adjustments: dict[str, dict[str, float]]
    regime_vol_adjustments: dict[str, dict[str, float]]
    regime_jump_adjustments: dict[str, dict[str, float]]

    def __post_init__(self) -> None:
        self.regime_names = [str(item).strip() for item in list(self.regime_names or []) if str(item).strip()]
        if not self.regime_names:
            raise ValueError("regime_names must not be empty")
        if len(set(self.regime_names)) != len(self.regime_names):
            raise ValueError("regime_names must be unique")
        self.current_regime = str(self.current_regime).strip()
        if self.current_regime not in self.regime_names:
            raise ValueError("current_regime must be included in regime_names")
        self.transition_matrix = _coerce_matrix(self.transition_matrix, context="transition_matrix")
        if len(self.transition_matrix) != len(self.regime_names):
            raise ValueError("transition_matrix must have one row per regime")
        normalized_rows: list[list[float]] = []
        for row in self.transition_matrix:
            if len(row) != len(self.regime_names):
                raise ValueError("transition_matrix must be square")
            normalized_row = _normalize_row(row)
            if not np.isclose(sum(normalized_row), 1.0, atol=1e-8):
                raise ValueError("transition_matrix rows must sum to 1")
            normalized_rows.append(normalized_row)
        self.transition_matrix = normalized_rows
        self.regime_mean_adjustments = {
            str(regime): {str(key): float(value) for key, value in _coerce_mapping(adjustments, context=f"regime_mean_adjustments[{regime}]").items()}
            for regime, adjustments in dict(self.regime_mean_adjustments or {}).items()
        }
        self.regime_vol_adjustments = {
            str(regime): {str(key): float(value) for key, value in _coerce_mapping(adjustments, context=f"regime_vol_adjustments[{regime}]").items()}
            for regime, adjustments in dict(self.regime_vol_adjustments or {}).items()
        }
        self.regime_jump_adjustments = {
            str(regime): {str(key): float(value) for key, value in _coerce_mapping(adjustments, context=f"regime_jump_adjustments[{regime}]").items()}
            for regime, adjustments in dict(self.regime_jump_adjustments or {}).items()
        }

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    @classmethod
    def from_any(cls, value: "RegimeStateSpec | dict[str, Any] | None") -> "RegimeStateSpec | None":
        if value is None or isinstance(value, cls):
            return value
        return cls(**dict(value))


def load_regime_state_snapshot(snapshot_path: str | Path) -> RegimeStateSpec:
    payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("regime state snapshot must be a JSON object")
    return RegimeStateSpec.from_any(_select_fields(payload))  # type: ignore[return-value]


def regime_transition_row(regime_state: RegimeStateSpec, regime_name: str | None = None) -> dict[str, float]:
    selected = str(regime_name or regime_state.current_regime).strip()
    try:
        index = regime_state.regime_names.index(selected)
    except ValueError as exc:
        raise ValueError(f"unknown regime: {selected}") from exc
    return {
        name: float(probability)
        for name, probability in zip(regime_state.regime_names, regime_state.transition_matrix[index], strict=True)
    }


def sample_next_regime(
    regime_state: RegimeStateSpec,
    random_state: int | np.random.Generator | None = None,
    regime_name: str | None = None,
) -> str:
    row = regime_transition_row(regime_state, regime_name=regime_name)
    rng = random_state if isinstance(random_state, np.random.Generator) else np.random.default_rng(random_state)
    return str(rng.choice(regime_state.regime_names, p=[row[name] for name in regime_state.regime_names]))


def regime_adjustments(regime_state: RegimeStateSpec, regime_name: str | None = None) -> dict[str, dict[str, float]]:
    selected = str(regime_name or regime_state.current_regime).strip()
    return {
        "mean": dict(regime_state.regime_mean_adjustments.get(selected, {})),
        "vol": dict(regime_state.regime_vol_adjustments.get(selected, {})),
        "jump": dict(regime_state.regime_jump_adjustments.get(selected, {})),
    }
