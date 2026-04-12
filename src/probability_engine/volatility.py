from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


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


@dataclass
class FactorDynamicsSpec:
    factor_names: list[str]
    factor_series_ref: str
    innovation_family: str
    tail_df: float | None
    garch_params_by_factor: dict[str, dict[str, float]]
    dcc_params: dict[str, float]
    long_run_covariance: dict[str, dict[str, float]]
    covariance_shrinkage: float
    calibration_window_days: int
    expected_return_by_factor: dict[str, float] = field(default_factory=dict)
    expected_return_basis: str = ""

    def __post_init__(self) -> None:
        self.factor_names = [str(item).strip() for item in list(self.factor_names or []) if str(item).strip()]
        if not self.factor_names:
            raise ValueError("factor_names must not be empty")
        if len(set(self.factor_names)) != len(self.factor_names):
            raise ValueError("factor_names must be unique")
        self.factor_series_ref = str(self.factor_series_ref).strip()
        if not self.factor_series_ref:
            raise ValueError("factor_series_ref is required")
        self.innovation_family = str(self.innovation_family).strip().lower()
        if not self.innovation_family:
            raise ValueError("innovation_family is required")
        self.tail_df = None if self.tail_df is None else float(self.tail_df)
        if self.tail_df is not None and self.tail_df <= 0:
            raise ValueError("tail_df must be positive when provided")
        self.garch_params_by_factor = {
            str(factor): {str(key): float(value) for key, value in _coerce_mapping(params, context=f"garch_params_by_factor[{factor}]").items()}
            for factor, params in dict(self.garch_params_by_factor or {}).items()
        }
        self.dcc_params = {str(key): float(value) for key, value in dict(self.dcc_params or {}).items()}
        self.long_run_covariance = {
            str(factor): {str(peer): float(value) for peer, value in _coerce_mapping(row, context=f"long_run_covariance[{factor}]").items()}
            for factor, row in dict(self.long_run_covariance or {}).items()
        }
        self.covariance_shrinkage = float(self.covariance_shrinkage)
        if not 0.0 <= self.covariance_shrinkage <= 1.0:
            raise ValueError("covariance_shrinkage must be between 0 and 1")
        self.calibration_window_days = int(self.calibration_window_days)
        if self.calibration_window_days < 0:
            raise ValueError("calibration_window_days must be >= 0")
        self.expected_return_by_factor = {
            str(factor): float(value)
            for factor, value in dict(self.expected_return_by_factor or {}).items()
        }
        invalid_expected_return_factors = sorted(set(self.expected_return_by_factor) - set(self.factor_names))
        if invalid_expected_return_factors:
            raise ValueError("expected_return_by_factor keys must be a subset of factor_names")
        if self.expected_return_basis is None:
            raise ValueError("expected_return_basis must not be null")
        self.expected_return_basis = str(self.expected_return_basis).strip()
        if self.expected_return_by_factor and not self.expected_return_basis:
            raise ValueError("expected_return_basis is required when expected_return_by_factor is provided")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    @classmethod
    def from_any(cls, value: "FactorDynamicsSpec | dict[str, Any] | None") -> "FactorDynamicsSpec | None":
        if value is None or isinstance(value, cls):
            return value
        return cls(**dict(value))


def update_garch_state(
    previous_variance: float,
    pre_jump_residual: float,
    omega: float,
    alpha: float,
    beta: float,
) -> float:
    previous_variance = float(previous_variance)
    pre_jump_residual = float(pre_jump_residual)
    omega = float(omega)
    alpha = float(alpha)
    beta = float(beta)
    return omega + alpha * (pre_jump_residual ** 2) + beta * previous_variance
