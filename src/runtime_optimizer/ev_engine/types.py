from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from calibration.types import BehaviorState, ConstraintState, EVParams, MarketState
from goal_solver.engine import _goal_solver_input_from_any
from goal_solver.types import GoalSolverInput
from runtime_optimizer.candidates import Action


@dataclass
class AccountState:
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    goal_gap: float
    success_prob_baseline: float
    horizon_months: int
    available_cash: float
    total_portfolio_value: float
    theme_remaining_budget: dict[str, float]

    @property
    def deviation(self) -> dict[str, float]:
        return {
            key: self.current_weights.get(key, 0.0) - self.target_weights.get(key, 0.0)
            for key in self.target_weights
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _market_state_from_any(value: MarketState | dict[str, Any]) -> MarketState:
    if isinstance(value, MarketState):
        return value
    return MarketState(**dict(_obj(value)))


def _constraint_state_from_any(value: ConstraintState | dict[str, Any]) -> ConstraintState:
    if isinstance(value, ConstraintState):
        return value
    data = dict(_obj(value))
    data["ips_bucket_boundaries"] = {
        key: tuple(bounds)
        for key, bounds in dict(data.get("ips_bucket_boundaries", {})).items()
    }
    return ConstraintState(**data)


def _behavior_state_from_any(value: BehaviorState | dict[str, Any]) -> BehaviorState:
    if isinstance(value, BehaviorState):
        return value
    return BehaviorState(**dict(_obj(value)))


def _ev_params_from_any(value: EVParams | dict[str, Any]) -> EVParams:
    if isinstance(value, EVParams):
        return value
    return EVParams(**dict(_obj(value)))


@dataclass
class EVState:
    account: AccountState
    market: MarketState
    constraints: ConstraintState
    behavior: BehaviorState
    ev_params: EVParams
    goal_solver_baseline_inp: GoalSolverInput

    @classmethod
    def from_any(cls, value: "EVState | dict[str, Any]") -> "EVState":
        if isinstance(value, cls):
            return value
        data = dict(_obj(value))
        account_data = dict(_obj(data.get("account", {})))
        return cls(
            account=AccountState(**account_data),
            market=_market_state_from_any(data.get("market", {})),
            constraints=_constraint_state_from_any(data.get("constraints", {})),
            behavior=_behavior_state_from_any(data.get("behavior", {})),
            ev_params=_ev_params_from_any(data.get("ev_params", {})),
            goal_solver_baseline_inp=_goal_solver_input_from_any(
                data.get("goal_solver_baseline_inp", {})
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeasibilityResult:
    is_feasible: bool
    fail_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EVComponentScore:
    goal_impact: float
    risk_penalty: float
    soft_constraint_penalty: float
    behavior_penalty: float
    execution_penalty: float
    total: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EVResult:
    action: Action
    score: EVComponentScore
    rank: int
    is_recommended: bool
    recommendation_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "score": self.score.to_dict(),
            "rank": self.rank,
            "is_recommended": self.is_recommended,
            "recommendation_reason": self.recommendation_reason,
        }


@dataclass
class EVReport:
    trigger_type: str
    generated_at: str
    state_snapshot_id: str
    ranked_actions: list[EVResult]
    eliminated_actions: list[tuple[Action, FeasibilityResult]]
    recommended_action: Action | None
    recommended_score: EVComponentScore | None
    confidence_flag: str
    confidence_reason: str
    goal_solver_baseline: float
    goal_solver_after_recommended: float
    params_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "generated_at": self.generated_at,
            "state_snapshot_id": self.state_snapshot_id,
            "ranked_actions": [item.to_dict() for item in self.ranked_actions],
            "eliminated_actions": [
                (action.to_dict(), feasibility.to_dict()) for action, feasibility in self.eliminated_actions
            ],
            "recommended_action": None if self.recommended_action is None else self.recommended_action.to_dict(),
            "recommended_score": None if self.recommended_score is None else self.recommended_score.to_dict(),
            "confidence_flag": self.confidence_flag,
            "confidence_reason": self.confidence_reason,
            "goal_solver_baseline": self.goal_solver_baseline,
            "goal_solver_after_recommended": self.goal_solver_after_recommended,
            "params_version": self.params_version,
        }
