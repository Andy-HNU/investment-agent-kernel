from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from decision_card.types import DecisionCard, DecisionCardBuildInput


class WorkflowType(str, Enum):
    ONBOARDING = "onboarding"
    MONTHLY = "monthly"
    EVENT = "event"
    QUARTERLY = "quarterly"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    ESCALATED = "escalated"


@dataclass
class TriggerSignal:
    workflow_type: WorkflowType | None = None
    run_id: str = ""
    structural_event: bool = False
    behavior_event: bool = False
    drawdown_event: bool = False
    satellite_event: bool = False
    manual_review_requested: bool = False
    manual_override_requested: bool = False
    high_risk_request: bool = False
    force_full_review: bool = False


@dataclass
class WorkflowDecision:
    requested_workflow_type: WorkflowType | None
    selected_workflow_type: WorkflowType
    selection_reason: str = ""
    auto_selected: bool = False


@dataclass
class RuntimeRestriction:
    cooldown_active: bool = False
    manual_review_requested: bool = False
    high_risk_request: bool = False
    allowed_actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    restriction_reasons: list[str] = field(default_factory=list)
    requires_escalation: bool = False
    forced_safe_action: str | None = None


@dataclass
class OrchestratorAuditRecord:
    requested_workflow_type: str | None
    selected_workflow_type: str
    selection_reason: str
    trigger_flags: dict[str, bool] = field(default_factory=dict)
    control_flags: dict[str, Any] = field(default_factory=dict)
    version_refs: dict[str, Any] = field(default_factory=dict)
    artifact_refs: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorPersistencePlan:
    run_record: dict[str, Any] = field(default_factory=dict)
    artifact_records: dict[str, Any] = field(default_factory=dict)
    execution_record: dict[str, Any] = field(default_factory=dict)


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return sorted((_serialize(item) for item in value), key=repr)
    if hasattr(value, "to_dict"):
        return _serialize(value.to_dict())
    if hasattr(value, "_asdict"):
        return _serialize(value._asdict())
    if hasattr(value, "__fspath__"):
        return str(value)
    if hasattr(value, "__dict__"):
        return _serialize(vars(value))
    return value


@dataclass
class OrchestratorResult:
    run_id: str
    workflow_type: WorkflowType
    status: WorkflowStatus
    requested_workflow_type: WorkflowType | None = None
    bundle_id: str | None = None
    calibration_id: str | None = None
    solver_snapshot_id: str | None = None
    snapshot_bundle: dict[str, Any] | None = None
    calibration_result: Any | None = None
    goal_solver_output: Any | None = None
    runtime_result: Any | None = None
    execution_plan: Any | None = None
    card_build_input: DecisionCardBuildInput | None = None
    decision_card: DecisionCard | dict[str, Any] | None = None
    workflow_decision: WorkflowDecision | None = None
    runtime_restriction: RuntimeRestriction | None = None
    audit_record: OrchestratorAuditRecord | None = None
    persistence_plan: OrchestratorPersistencePlan | None = None
    blocking_reasons: list[str] = field(default_factory=list)
    degraded_notes: list[str] = field(default_factory=list)
    escalation_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_type": self.workflow_type.value,
            "status": self.status.value,
            "requested_workflow_type": None
            if self.requested_workflow_type is None
            else self.requested_workflow_type.value,
            "bundle_id": self.bundle_id,
            "calibration_id": self.calibration_id,
            "solver_snapshot_id": self.solver_snapshot_id,
            "snapshot_bundle": _serialize(self.snapshot_bundle),
            "calibration_result": _serialize(self.calibration_result),
            "goal_solver_output": _serialize(self.goal_solver_output),
            "runtime_result": _serialize(self.runtime_result),
            "execution_plan": _serialize(self.execution_plan),
            "card_build_input": _serialize(self.card_build_input),
            "decision_card": _serialize(self.decision_card),
            "workflow_decision": _serialize(self.workflow_decision),
            "runtime_restriction": _serialize(self.runtime_restriction),
            "audit_record": _serialize(self.audit_record),
            "persistence_plan": _serialize(self.persistence_plan),
            "blocking_reasons": list(self.blocking_reasons),
            "degraded_notes": list(self.degraded_notes),
            "escalation_reasons": list(self.escalation_reasons),
        }
