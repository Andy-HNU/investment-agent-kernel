from __future__ import annotations

from copy import deepcopy

import pytest

import orchestrator.engine as orchestrator_engine

pytest.importorskip("decision_card.builder")

from decision_card.builder import build_decision_card
from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus, WorkflowType
from runtime_optimizer.types import RuntimeOptimizerMode, RuntimeOptimizerResult


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal_solver_input_base["goal"],
        "cashflow_plan": goal_solver_input_base["cashflow_plan"],
        "constraints": goal_solver_input_base["constraints"],
        "universe": {
            "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": {
                "equity_cn": None,
                "bond_cn": None,
                "gold": None,
                "satellite": "technology",
            },
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def _poverty_runtime_result(mode: RuntimeOptimizerMode) -> RuntimeOptimizerResult:
    return RuntimeOptimizerResult(
        mode=mode,
        ev_report={"ranked_actions": []},
        state_snapshot={"mode": mode.value},
        candidates_generated=1,
        candidates_after_filter=1,
        candidate_poverty=True,
        run_timestamp="2026-03-29T12:00:00Z",
        optimizer_params_version="v1.0.0",
        goal_solver_params_version="v4.0.0",
    )


@pytest.mark.smoke
def test_orchestrator_onboarding_to_decision_card_smoke(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_onboarding"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.workflow_type == WorkflowType.ONBOARDING
    assert result.status == WorkflowStatus.COMPLETED
    assert card["card_type"] == "goal_baseline"
    assert card["trace_refs"]["run_id"] == "smoke_onboarding"
    assert card["trace_refs"]["bundle_id"] == "bundle_acc001_20260329T120000Z"
    assert card["trace_refs"]["calibration_id"] == calibration_result_base["calibration_id"]


@pytest.mark.smoke
def test_orchestrator_monthly_poverty_to_safe_card_smoke(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
    monkeypatch,
):
    def _fake_runtime_optimizer(**kwargs):
        assert kwargs["mode"] == RuntimeOptimizerMode.MONTHLY
        return _poverty_runtime_result(RuntimeOptimizerMode.MONTHLY)

    monkeypatch.setattr(orchestrator_engine, "run_runtime_optimizer", _fake_runtime_optimizer)

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "smoke_monthly_poverty"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.workflow_type == WorkflowType.MONTHLY
    assert result.status == WorkflowStatus.DEGRADED
    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert card["card_type"] == "runtime_action"
    assert card["recommended_action"] == "freeze"
    assert "candidate_poverty=true" in card["guardrails"]
    assert "forced_safe_action=freeze" in card["guardrails"]


@pytest.mark.smoke
def test_orchestrator_auto_quarterly_review_smoke(
    goal_solver_input_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"run_id": "smoke_quarterly_auto"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "live_portfolio": live_portfolio_base,
            "control_flags": {"quarterly_review": True},
        },
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.workflow_type == WorkflowType.QUARTERLY
    assert result.workflow_decision is not None
    assert result.workflow_decision.auto_selected is True
    assert result.workflow_decision.selection_reason == "quarterly_review_requested"
    assert card["card_type"] == "quarterly_review"
    assert card["recommended_action"] == "review"
    assert card["trace_refs"]["run_id"] == "smoke_quarterly_auto"


@pytest.mark.smoke
def test_orchestrator_blocked_path_to_blocked_card_smoke(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_blocked"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {
                "bundle_id": "bundle_acc001_20260329T120000Z",
                "bundle_quality": "degraded",
            },
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.status == WorkflowStatus.BLOCKED
    assert card["card_type"] == "blocked"
    assert card["recommended_action"] == "blocked"
    assert card["primary_recommendation"] == "resolve blockers"
    assert "bundle_quality=degraded" in card["guardrails"]
    assert card["trace_refs"]["run_id"] == "smoke_blocked"


@pytest.mark.smoke
def test_orchestrator_manual_review_and_high_risk_request_smoke(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    calibration_result = deepcopy(calibration_result_base)
    calibration_result["behavior_state"] = {
        **calibration_result["behavior_state"],
        "cooldown_active": True,
        "cooldown_until": "2026-04-02T00:00:00Z",
    }
    calibration_result["constraint_state"] = {
        **calibration_result["constraint_state"],
        "cooldown_currently_active": True,
    }

    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "smoke_manual_review"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result,
            "live_portfolio": live_portfolio_base,
            "control_flags": {"manual_review_requested": True},
            "user_request_context": {"requested_action": "rebalance_full"},
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.workflow_type == WorkflowType.EVENT
    assert result.status == WorkflowStatus.ESCALATED
    assert result.runtime_restriction is not None
    assert result.runtime_restriction.forced_safe_action == "freeze"
    assert card["card_type"] == "runtime_action"
    assert card["recommended_action"] == "freeze"
    assert card["status_badge"] == "degraded"
    assert "high_risk_request=true" in card["guardrails"]
    assert "cooldown_active" in card["guardrails"]
    assert "directive=manual_review_required" in card["execution_notes"]
    assert card["trace_refs"]["selected_workflow_type"] == "event"


@pytest.mark.smoke
def test_orchestrator_provenance_mismatch_to_blocked_card_smoke(
    goal_solver_input_base,
    goal_solver_output_base,
    calibration_result_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "smoke_provenance_blocked"},
        raw_inputs={
            "bundle_id": "bundle_raw",
            "snapshot_bundle": {"bundle_id": "bundle_snapshot"},
            "calibration_result": calibration_result_base,
            "live_portfolio": live_portfolio_base,
        },
        prior_solver_output=goal_solver_output_base,
        prior_solver_input=goal_solver_input_base,
    )
    card = build_decision_card(result.card_build_input)

    assert result.decision_card == card
    assert result.status == WorkflowStatus.BLOCKED
    assert card["card_type"] == "blocked"
    assert card["recommended_action"] == "blocked"
    assert "bundle_id mismatch between raw_inputs and snapshot_bundle" in card["guardrails"]
    assert "calibration.source_bundle_id mismatch with bundle_id" in card["guardrails"]
    assert card["trace_refs"]["run_id"] == "smoke_provenance_blocked"
