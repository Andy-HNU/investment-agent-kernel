from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "layer3_cli_user") -> UserOnboardingProfile:
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


@pytest.mark.smoke
def test_frontdesk_cli_layer3_commands(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    assert main(["onboard", "--db", str(db_path), "--profile-json", str(profile_path), "--non-interactive", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["workflow"] == "onboard"

    assert main(["daily-monitor", "--db", str(db_path), "--account-profile-id", profile.account_profile_id, "--json"]) == 0
    monitor = json.loads(capsys.readouterr().out)
    assert monitor["workflow"] == "daily_monitor"

    assert main(["explain-probability", "--db", str(db_path), "--account-profile-id", profile.account_profile_id, "--json"]) == 0
    probability = json.loads(capsys.readouterr().out)
    assert probability["workflow"] == "explain_probability"
    assert "probability_explanation" in probability

    assert main(["explain-plan-change", "--db", str(db_path), "--account-profile-id", profile.account_profile_id, "--json"]) == 0
    plan_change = json.loads(capsys.readouterr().out)
    assert plan_change["workflow"] == "explain_plan_change"
    assert "pending_execution_plan" in plan_change

