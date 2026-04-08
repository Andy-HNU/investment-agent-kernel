from __future__ import annotations

import pytest

from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import write_formal_snapshot_source


def _profile(*, account_profile_id: str = "layer3_explain_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
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
    onboarding = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    pending_plan = onboarding["user_state"]["pending_execution_plan"]

    probability = explain_frontdesk_probability(
        account_profile_id=profile.account_profile_id,
        db_path=db_path,
    )
    assert probability["workflow"] == "explain_probability"
    assert probability["status"] == "explained"
    assert isinstance(probability["probability_explanation"], dict)
    assert isinstance(probability["frontier_analysis"], dict)
    probability_method = (
        (probability.get("key_metrics") or {}).get("product_probability_method")
        or (probability.get("probability_explanation") or {}).get("product_probability_method")
    )
    assert probability_method is not None

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
