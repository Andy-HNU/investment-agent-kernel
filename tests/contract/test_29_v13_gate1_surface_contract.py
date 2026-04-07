from __future__ import annotations

from frontdesk.cli import render_frontdesk_summary
from frontdesk.service import run_frontdesk_onboarding
from frontdesk.storage import FrontdeskStore
from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


def _profile(*, account_profile_id: str) -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=124_203.16,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金12000，黄金6000",
        restrictions=["不买个股", "不碰科技", "不碰高风险产品"],
        current_weights=None,
    )


def test_orchestrator_onboarding_surfaces_gate1_contract_fields_end_to_end():
    profile = _profile(account_profile_id="gate1_surface_orchestrator")
    bundle = build_user_onboarding_inputs(profile, as_of="2026-04-07T00:00:00Z")
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "gate1_surface_run"},
        raw_inputs=bundle.raw_inputs,
    ).to_dict()

    assert result["run_outcome_status"] in {"completed", "degraded", "unavailable", "blocked"}
    assert result["resolved_result_category"] in {
        None,
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert result["disclosure_decision"]["disclosure_level"] in {
        "point_and_range",
        "range_only",
        "diagnostic_only",
        "unavailable",
    }
    assert result["evidence_bundle"]["run_outcome_status"] == result["run_outcome_status"]
    assert result["decision_card"]["run_outcome_status"] == result["run_outcome_status"]
    assert result["decision_card"]["resolved_result_category"] == result["resolved_result_category"]
    assert (
        result["decision_card"]["probability_explanation"]["run_outcome_status"]
        == result["run_outcome_status"]
    )
    assert (
        result["decision_card"]["probability_explanation"]["resolved_result_category"]
        == result["resolved_result_category"]
    )


def test_frontdesk_summary_storage_and_cli_surface_gate1_contract_fields(tmp_path):
    profile = _profile(account_profile_id="gate1_surface_frontdesk")
    db_path = tmp_path / "gate1_surface.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    store = FrontdeskStore(db_path)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)

    assert summary["run_outcome_status"] in {"completed", "degraded", "unavailable", "blocked"}
    assert summary["resolved_result_category"] in {
        None,
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert summary["decision_card"]["run_outcome_status"] == summary["run_outcome_status"]
    assert summary["decision_card"]["resolved_result_category"] == summary["resolved_result_category"]
    assert summary["disclosure_decision"]["disclosure_level"] in {
        "point_and_range",
        "range_only",
        "diagnostic_only",
        "unavailable",
    }
    assert summary["evidence_bundle"]["run_outcome_status"] == summary["run_outcome_status"]

    assert snapshot is not None
    latest_run = snapshot["latest_run"]
    assert latest_run["result_payload"]["run_outcome_status"] == summary["run_outcome_status"]
    assert latest_run["result_payload"]["resolved_result_category"] == summary["resolved_result_category"]

    output = render_frontdesk_summary(summary)
    assert f"run_outcome_status={summary['run_outcome_status']}" in output
    assert f"resolved_result_category={summary['resolved_result_category']}" in output
    assert "disclosure_level=" in output
