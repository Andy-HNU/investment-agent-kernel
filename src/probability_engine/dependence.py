from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol

import numpy as np


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _coerce_matrix(value: Any, *, context: str) -> list[list[float]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    matrix: list[list[float]] = []
    for row in value:
        if not isinstance(row, list):
            raise ValueError(f"{context} must contain row lists")
        matrix.append([float(item) for item in row])
    return matrix


def _correlation_from_q_matrix(q_matrix: list[list[float]]) -> list[list[float]]:
    q = np.asarray(q_matrix, dtype=float)
    if q.ndim != 2 or q.shape[0] != q.shape[1]:
        raise ValueError("DCC state matrix must be square")
    diagonal = np.sqrt(np.maximum(np.diag(q), 1e-12))
    scale = np.outer(diagonal, diagonal)
    correlation = q / scale
    np.fill_diagonal(correlation, 1.0)
    return correlation.tolist()


@dataclass
class FactorLevelDccState:
    factor_names: list[str]
    q_matrix: list[list[float]]
    q_bar_matrix: list[list[float]]
    alpha: float
    beta: float

    def __post_init__(self) -> None:
        self.factor_names = [str(item).strip() for item in list(self.factor_names or []) if str(item).strip()]
        if not self.factor_names:
            raise ValueError("factor_names must not be empty")
        if len(set(self.factor_names)) != len(self.factor_names):
            raise ValueError("factor_names must be unique")
        self.q_matrix = _coerce_matrix(self.q_matrix, context="q_matrix")
        self.q_bar_matrix = _coerce_matrix(self.q_bar_matrix, context="q_bar_matrix")
        if len(self.q_matrix) != len(self.factor_names) or len(self.q_bar_matrix) != len(self.factor_names):
            raise ValueError("dcc matrices must match factor_names")
        self.alpha = float(self.alpha)
        self.beta = float(self.beta)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    @classmethod
    def from_any(cls, value: "FactorLevelDccState | dict[str, Any] | None") -> "FactorLevelDccState | None":
        if value is None or isinstance(value, cls):
            return value
        return cls(**dict(value))


class DependenceProvider(Protocol):
    def initialize(self, factor_names: list[str], state: dict[str, Any]) -> Any: ...

    def update(self, standardized_factor_residual: list[float], prev_state: Any) -> Any: ...

    def current_correlation(self, state: Any) -> list[list[float]]: ...

    def dependency_scope(self) -> str: ...


class FactorLevelDccProvider:
    def __init__(self, alpha: float, beta: float) -> None:
        self.alpha = float(alpha)
        self.beta = float(beta)
        if self.alpha < 0.0 or self.beta < 0.0:
            raise ValueError("alpha and beta must be non-negative")
        if self.alpha + self.beta >= 1.0:
            raise ValueError("alpha + beta must be < 1.0")

    def initialize(self, factor_names: list[str], state: dict[str, Any]) -> FactorLevelDccState:
        factor_names = [str(item).strip() for item in list(factor_names or []) if str(item).strip()]
        if not factor_names:
            raise ValueError("factor_names must not be empty")
        payload = dict(state or {})
        long_run = payload.get("long_run_correlation")
        if long_run is None:
            long_run = payload.get("correlation_matrix")
        if long_run is None:
            long_run = np.identity(len(factor_names)).tolist()
        q_bar = _coerce_matrix(long_run, context="long_run_correlation")
        q = _coerce_matrix(payload.get("initial_q", q_bar), context="initial_q")
        return FactorLevelDccState(
            factor_names=factor_names,
            q_matrix=q,
            q_bar_matrix=q_bar,
            alpha=self.alpha,
            beta=self.beta,
        )

    def update(
        self,
        standardized_factor_residual: list[float],
        prev_state: FactorLevelDccState | dict[str, Any],
    ) -> FactorLevelDccState:
        state = FactorLevelDccState.from_any(prev_state)
        if state is None:
            raise ValueError("prev_state is required")
        residual = np.asarray(list(standardized_factor_residual), dtype=float)
        if residual.ndim != 1 or residual.shape[0] != len(state.factor_names):
            raise ValueError("standardized_factor_residual must match factor_names")
        q_prev = np.asarray(state.q_matrix, dtype=float)
        q_bar = np.asarray(state.q_bar_matrix, dtype=float)
        q_next = (1.0 - self.alpha - self.beta) * q_bar + self.alpha * np.outer(residual, residual) + self.beta * q_prev
        return FactorLevelDccState(
            factor_names=list(state.factor_names),
            q_matrix=q_next.tolist(),
            q_bar_matrix=q_bar.tolist(),
            alpha=self.alpha,
            beta=self.beta,
        )

    def current_correlation(self, state: FactorLevelDccState | dict[str, Any]) -> list[list[float]]:
        dcc_state = FactorLevelDccState.from_any(state)
        if dcc_state is None:
            raise ValueError("state is required")
        return _correlation_from_q_matrix(dcc_state.q_matrix)

    def dependency_scope(self) -> str:
        return "factor_level_dcc"
