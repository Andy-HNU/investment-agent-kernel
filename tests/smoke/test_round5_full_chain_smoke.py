from __future__ import annotations

import pytest

from demo_scenarios import build_demo_quarterly_payload
from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus, WorkflowType


@pytest.mark.smoke
def test_raw_snapshots_to_orchestrator_quarterly_full_chain_smoke():
    result = run_orchestrator(
        trigger={"workflow_type": "quarterly", "run_id": "round5_quarterly_full_chain"},
        raw_inputs=build_demo_quarterly_payload(),
    )

    assert result.workflow_type == WorkflowType.QUARTERLY
    assert result.status == WorkflowStatus.COMPLETED
    assert result.snapshot_bundle is not None
    assert result.calibration_result is not None
    assert result.goal_solver_output is not None
    assert result.runtime_result is not None
    assert result.decision_card is not None
    assert result.audit_record is not None
    assert result.persistence_plan is not None
    assert result.audit_record.artifact_refs["snapshot_bundle_origin"] == "generated"
    assert result.audit_record.artifact_refs["calibration_origin"] == "generated"
    assert result.decision_card["card_type"] == "quarterly_review"
    assert result.decision_card["recommended_action"] == "review"
    assert result.decision_card["trace_refs"]["bundle_id"] == result.bundle_id
    assert result.persistence_plan.artifact_records["decision_card"]["payload"]["recommended_action"] == "review"
