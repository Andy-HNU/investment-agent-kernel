from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontdesk.cli import main
from shared.onboarding import UserOnboardingProfile


def _profile(*, display_name: str = "Andy") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="cli_frontdesk_user",
        display_name=display_name,
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
    )


@pytest.mark.smoke
def test_frontdesk_cli_non_interactive_missing_input_fails_fast(tmp_path, monkeypatch):
    db_path = tmp_path / "frontdesk.sqlite"

    def _fail_on_prompt(*args, **kwargs):
        raise AssertionError("non-interactive CLI should not prompt for missing inputs")

    monkeypatch.setattr("builtins.input", _fail_on_prompt)

    with pytest.raises((SystemExit, ValueError)):
        main([
            "onboard",
            "--db",
            str(db_path),
            "--non-interactive",
            "--json",
        ])


@pytest.mark.smoke
def test_frontdesk_cli_followup_profile_json_update_changes_state_and_output(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    initial_profile = _profile(display_name="Andy")
    updated_profile = _profile(display_name="Andy Prime")
    initial_profile_path = tmp_path / "initial_profile.json"
    initial_profile_path.write_text(
        json.dumps(initial_profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    updated_profile_path = tmp_path / "updated_profile.json"
    updated_profile_path.write_text(
        json.dumps(updated_profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    onboarding_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(initial_profile_path),
            "--non-interactive",
            "--json",
        ]
    )

    assert onboarding_exit_code == 0

    followup_exit_code = main(
        [
            "monthly",
            "--db",
            str(db_path),
            "--account-profile-id",
            initial_profile.account_profile_id,
            "--profile-json",
            str(updated_profile_path),
            "--non-interactive",
            "--json",
        ]
    )

    assert followup_exit_code == 0


@pytest.mark.smoke
def test_frontdesk_cli_feedback_updates_execution_status(tmp_path, capsys):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(display_name="Andy")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    onboarding_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
            "--json",
        ]
    )
    onboarding_payload = json.loads(capsys.readouterr().out)

    assert onboarding_exit_code == 0

    feedback_exit_code = main(
        [
            "feedback",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--run-id",
            onboarding_payload["run_id"],
            "--executed",
            "--actual-action",
            "adopt_recommended_plan",
            "--executed-at",
            "2026-03-30T10:00:00Z",
            "--json",
        ]
    )
    feedback_payload = json.loads(capsys.readouterr().out)

    assert feedback_exit_code == 0
    assert feedback_payload["status"] == "recorded"
    assert feedback_payload["execution_feedback"]["feedback_status"] == "executed"
    assert feedback_payload["execution_feedback_summary"]["counts"]["executed"] >= 1
