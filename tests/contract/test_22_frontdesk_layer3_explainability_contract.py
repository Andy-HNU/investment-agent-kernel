from __future__ import annotations

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "layer3_explain_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=[],
    )


@pytest.mark.contract
def test_frontdesk_layer3_explain_and_daily_monitor_surfaces_snapshot_context(tmp_path):
    from frontdesk.service import (
        explain_frontdesk_plan_change,
        explain_frontdesk_probability,
        run_frontdesk_daily_monitor,
        run_frontdesk_onboarding,
    )

    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile()
    onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    pending_plan = onboarding["user_state"]["pending_execution_plan"]

    probability = explain_frontdesk_probability(
        account_profile_id=profile.account_profile_id,
        db_path=db_path,
    )
    assert probability["workflow"] == "explain_probability"
    assert probability["status"] == "explained"
    assert isinstance(probability["probability_explanation"], dict)
    assert isinstance(probability["frontier_analysis"], dict)
    assert probability["key_metrics"]["product_probability_method"] is not None

    plan_change = explain_frontdesk_plan_change(
        account_profile_id=profile.account_profile_id,
        db_path=db_path,
    )
    assert plan_change["workflow"] == "explain_plan_change"
    assert plan_change["status"] == "explained"
    assert plan_change["pending_execution_plan"]["plan_id"] == pending_plan["plan_id"]
    assert "execution_plan_guidance" in plan_change

    monitor = run_frontdesk_daily_monitor(
        account_profile_id=profile.account_profile_id,
        db_path=db_path,
    )
    assert monitor["workflow"] == "daily_monitor"
    assert monitor["status"] in {"monitoring_ready", "no_monitorable_actions"}
    assert "maintenance_policy_summary" in monitor
    assert isinstance(monitor["monitoring_actions"], list)

