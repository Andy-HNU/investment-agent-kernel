from __future__ import annotations

import pytest

from demo_scenarios import (
    build_demo_aligned_prior_solver_input,
    build_demo_goal_solver_input,
    build_demo_live_portfolio,
    build_demo_monthly_raw_payload,
    build_demo_onboarding_payload,
)
from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus, WorkflowType


def _bootstrap_onboarding_result():
    return run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "round5_bootstrap_onboarding"},
        raw_inputs=build_demo_onboarding_payload(),
    )


@pytest.mark.contract
def test_run_orchestrator_monthly_raw_replay_override_regression():
    bootstrap = _bootstrap_onboarding_result()
    aligned_prior_input = build_demo_aligned_prior_solver_input(bootstrap.goal_solver_output)

    result = run_orchestrator(
        trigger={
            "workflow_type": "monthly",
            "run_id": "round5_monthly_replay_override",
            "manual_override_requested": True,
        },
        raw_inputs=build_demo_monthly_raw_payload(replay_mode=True),
        prior_solver_output=bootstrap.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=bootstrap.calibration_result,
    )

    meta = result.calibration_result.param_version_meta

    assert result.requested_workflow_type == WorkflowType.MONTHLY
    assert result.workflow_type == WorkflowType.EVENT
    assert result.status == WorkflowStatus.ESCALATED
    assert result.snapshot_bundle is not None
    assert result.runtime_result is not None
    assert result.decision_card is not None
    assert result.audit_record is not None
    assert result.persistence_plan is not None
    assert result.audit_record.artifact_refs["snapshot_bundle_origin"] == "generated"
    assert result.audit_record.artifact_refs["calibration_origin"] == "generated"
    assert result.audit_record.control_flags["manual_override_requested"] is True
    assert result.decision_card["recommended_action"] == "freeze"
    assert meta["quality"] == "manual"
    assert meta["updated_reason"] == "manual_review"
    assert meta["previous_version_id"] is not None
    assert result.persistence_plan.execution_record["user_override_requested"] is True


@pytest.mark.contract
def test_run_orchestrator_disable_provenance_checks_allows_mismatch_regression():
    bootstrap = _bootstrap_onboarding_result()
    aligned_prior_input = build_demo_aligned_prior_solver_input(bootstrap.goal_solver_output)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "round5_provenance_relaxed"},
        raw_inputs={
            "bundle_id": "bundle_demo_provenance_mismatch",
            "snapshot_bundle": bootstrap.snapshot_bundle,
            "calibration_result": bootstrap.calibration_result,
            "live_portfolio": build_demo_live_portfolio(),
            "control_flags": {"disable_provenance_checks": True},
        },
        prior_solver_output=bootstrap.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=bootstrap.calibration_result,
    )

    assert result.status != WorkflowStatus.BLOCKED
    assert result.audit_record is not None
    assert result.persistence_plan is not None
    assert result.blocking_reasons == []
    assert result.audit_record.control_flags["enforce_provenance_checks"] is False
    assert result.audit_record.version_refs["bundle_id"] == "bundle_demo_provenance_mismatch"
    assert result.decision_card is not None
    assert result.decision_card["trace_refs"]["bundle_id"] == "bundle_demo_provenance_mismatch"
