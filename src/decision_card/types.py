from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any


class DecisionCardType(str, Enum):
    GOAL_BASELINE = "goal_baseline"
    RUNTIME_ACTION = "runtime_action"
    QUARTERLY_REVIEW = "quarterly_review"
    BLOCKED = "blocked"


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    if hasattr(value, "to_dict"):
        return _serialize(value.to_dict())
    return value


@dataclass
class DecisionCardBuildInput:
    card_type: DecisionCardType
    workflow_type: str
    run_id: str = ""
    bundle_id: str | None = None
    calibration_id: str | None = None
    solver_snapshot_id: str | None = None
    goal_solver_output: Any | None = None
    goal_solver_input: Any | None = None
    runtime_result: Any | None = None
    workflow_decision: Any | None = None
    runtime_restriction: Any | None = None
    audit_record: Any | None = None
    input_provenance: dict[str, Any] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)
    degraded_notes: list[str] = field(default_factory=list)
    escalation_reasons: list[str] = field(default_factory=list)
    control_directives: list[str] = field(default_factory=list)

    @classmethod
    def from_any(cls, value: "DecisionCardBuildInput | dict[str, Any]") -> "DecisionCardBuildInput":
        if isinstance(value, cls):
            return value
        data = dict(value)
        card_type = data.get("card_type", DecisionCardType.GOAL_BASELINE)
        if not isinstance(card_type, DecisionCardType):
            card_type = DecisionCardType(str(getattr(card_type, "value", card_type)))
        return cls(
            card_type=card_type,
            workflow_type=str(data.get("workflow_type", "")),
            run_id=str(data.get("run_id", "")),
            bundle_id=data.get("bundle_id"),
            calibration_id=data.get("calibration_id"),
            solver_snapshot_id=data.get("solver_snapshot_id"),
            goal_solver_output=data.get("goal_solver_output"),
            goal_solver_input=data.get("goal_solver_input"),
            runtime_result=data.get("runtime_result"),
            workflow_decision=data.get("workflow_decision"),
            runtime_restriction=data.get("runtime_restriction"),
            audit_record=data.get("audit_record"),
            input_provenance=dict(data.get("input_provenance", {})),
            blocking_reasons=list(data.get("blocking_reasons", [])),
            degraded_notes=list(data.get("degraded_notes", [])),
            escalation_reasons=list(data.get("escalation_reasons", [])),
            control_directives=list(data.get("control_directives", [])),
        )

    def validate(self) -> None:
        if not self.workflow_type:
            raise ValueError("workflow_type is required")
        if self.card_type != DecisionCardType.BLOCKED and self.blocking_reasons:
            raise ValueError("blocking_reasons are only valid for blocked card")
        if self.card_type == DecisionCardType.GOAL_BASELINE and self.goal_solver_output is None:
            raise ValueError("goal_baseline card requires goal_solver_output")
        if self.card_type == DecisionCardType.RUNTIME_ACTION and self.runtime_result is None:
            raise ValueError("runtime_action card requires runtime_result")
        if self.card_type == DecisionCardType.QUARTERLY_REVIEW:
            missing: list[str] = []
            if self.goal_solver_output is None:
                missing.append("goal_solver_output")
            if self.runtime_result is None:
                missing.append("runtime_result")
            if missing:
                raise ValueError(
                    "quarterly_review card requires " + ", ".join(missing)
                )
        if self.card_type == DecisionCardType.BLOCKED and not (
            self.blocking_reasons or self.degraded_notes or self.escalation_reasons
        ):
            raise ValueError("blocked card requires blocking or degraded reasons")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass
class DecisionCard:
    card_id: str
    card_type: DecisionCardType
    workflow_type: str
    title: str
    status_badge: str
    summary: str
    primary_recommendation: str
    recommendation_reason: list[str]
    not_recommended_reason: list[str]
    key_metrics: dict[str, str]
    alternatives: list[Any]
    guardrails: list[str]
    execution_notes: list[str]
    trace_refs: dict[str, str]
    recommended_action: str
    reasons: list[str]
    evidence_highlights: list[str] = field(default_factory=list)
    review_conditions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    runner_up_action: str | None = None
    low_confidence: bool = False
    model_disclaimer: str = ""
    input_provenance: dict[str, Any] = field(default_factory=dict)
    input_source_summary: list[str] = field(default_factory=list)
    input_source_sections: list[dict[str, Any]] = field(default_factory=list)
    candidate_options: list[dict[str, Any]] = field(default_factory=list)
    goal_alternatives: list[dict[str, Any]] = field(default_factory=list)
    goal_semantics: dict[str, Any] = field(default_factory=dict)
    profile_dimensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))
