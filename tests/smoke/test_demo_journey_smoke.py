from __future__ import annotations

import pytest

from orchestrator.types import WorkflowStatus, WorkflowType
from shared.demo_flow import run_demo_journey, serialize_demo_journey


@pytest.mark.smoke
def test_demo_journey_covers_onboarding_monthly_quarterly_and_provenance_bypass():
    journey = run_demo_journey()
    payload = serialize_demo_journey(journey)

    onboarding = journey["onboarding"]
    monthly = journey["monthly_replay_override"]
    quarterly = journey["quarterly_review"]
    provenance = journey["provenance_bypass"]

    assert onboarding.workflow_type == WorkflowType.ONBOARDING
    assert onboarding.status == WorkflowStatus.COMPLETED
    assert onboarding.decision_card["card_type"] == "goal_baseline"

    assert monthly.audit_record is not None
    assert monthly.audit_record.requested_workflow_type == "monthly"
    assert monthly.status == WorkflowStatus.ESCALATED
    assert monthly.decision_card["recommended_action"] == "freeze"
    assert monthly.persistence_plan.execution_record["user_override_requested"] is True
    assert monthly.calibration_result.param_version_meta["updated_reason"] == "manual_review"

    assert quarterly.workflow_type == WorkflowType.QUARTERLY
    assert quarterly.decision_card["card_type"] == "quarterly_review"
    assert quarterly.decision_card["recommended_action"] == "review"

    assert provenance.status != WorkflowStatus.BLOCKED
    assert provenance.audit_record.control_flags["enforce_provenance_checks"] is False
    assert provenance.decision_card["trace_refs"]["bundle_id"] == "bundle_demo_raw_override"

    assert payload["summary"]["onboarding"]["card_type"] == "goal_baseline"
    assert payload["summary"]["monthly_replay_override"]["recommended_action"] == "freeze"
    assert payload["summary"]["quarterly_review"]["card_type"] == "quarterly_review"
    assert payload["summary"]["provenance_bypass"]["status"] != "blocked"
