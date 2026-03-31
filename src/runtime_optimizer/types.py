from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


@dataclass
class LivePortfolioSnapshot:
    weights: dict[str, float]
    total_value: float
    available_cash: float
    goal_gap: float
    remaining_horizon_months: int
    as_of_date: str
    current_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeOptimizerMode(str, Enum):
    MONTHLY = "monthly"
    EVENT = "event"
    QUARTERLY = "quarterly"


@dataclass
class RuntimeOptimizerResult:
    mode: RuntimeOptimizerMode
    ev_report: Any
    state_snapshot: Any
    candidates_generated: int
    candidates_after_filter: int
    candidate_poverty: bool
    run_timestamp: str
    optimizer_params_version: str
    goal_solver_params_version: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        return data
