from __future__ import annotations

import json

import pytest

from orchestrator.types import WorkflowStatus, WorkflowType
from shared.demo_flow import run_demo_journey, serialize_demo_journey


@pytest.mark.smoke
def test_demo_lifecycle_smoke():
    journey = run_demo_journey()

    assert journey["onboarding"].workflow_type == WorkflowType.ONBOARDING
    assert journey["onboarding"].status == WorkflowStatus.COMPLETED
    assert journey["onboarding"].decision_card["card_type"] == "goal_baseline"

    assert journey["monthly_replay_override"].workflow_type == WorkflowType.EVENT
    assert journey["monthly_replay_override"].status == WorkflowStatus.ESCALATED
    assert journey["monthly_replay_override"].decision_card["card_type"] == "runtime_action"
    assert journey["monthly_replay_override"].decision_card["recommended_action"] == "freeze"

    assert journey["quarterly_review"].workflow_type == WorkflowType.QUARTERLY
    assert journey["quarterly_review"].status in {WorkflowStatus.COMPLETED, WorkflowStatus.DEGRADED}
    assert journey["quarterly_review"].decision_card["card_type"] == "quarterly_review"
    assert journey["quarterly_review"].decision_card["recommended_action"] == "review"

    assert journey["provenance_bypass"].workflow_type == WorkflowType.MONTHLY
    assert journey["provenance_bypass"].status in {WorkflowStatus.COMPLETED, WorkflowStatus.DEGRADED}
    assert journey["provenance_bypass"].decision_card["card_type"] == "runtime_action"


@pytest.mark.smoke
def test_demo_lifecycle_summary_is_json_serializable():
    payload = json.loads(json.dumps(serialize_demo_journey(run_demo_journey()), ensure_ascii=False))

    assert set(payload["summary"].keys()) == {
        "onboarding",
        "monthly_replay_override",
        "quarterly_review",
        "provenance_bypass",
    }
    assert payload["summary"]["monthly_replay_override"]["status"] == "escalated"
    assert payload["summary"]["quarterly_review"]["card_type"] == "quarterly_review"
