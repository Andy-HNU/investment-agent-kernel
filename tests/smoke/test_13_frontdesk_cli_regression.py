from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "frontdesk_regression_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
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
    from frontdesk.cli import main

    db_path = tmp_path / "frontdesk.sqlite"

    def _unexpected_input(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("prompt should not run in non-interactive mode")

    monkeypatch.setattr("builtins.input", _unexpected_input)

    with pytest.raises(SystemExit, match="non-interactive onboarding requires"):
        main(
            [
                "onboard",
                "--db",
                str(db_path),
                "--non-interactive",
                "--display-name",
                "Andy",
            ]
        )


@pytest.mark.smoke
def test_frontdesk_cli_followup_profile_json_updates_state_and_output(tmp_path, capsys):
    from frontdesk.cli import main
    from frontdesk.service import load_user_state

    account_profile_id = "frontdesk_followup_profile_update"
    db_path = tmp_path / "frontdesk.sqlite"

    baseline_profile = _profile(account_profile_id=account_profile_id)
    baseline_path = tmp_path / "baseline_profile.json"
    baseline_path.write_text(
        json.dumps(baseline_profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    onboarding_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(baseline_path),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()
    assert onboarding_exit_code == 0

    updated_profile = baseline_profile.to_dict()
    updated_profile["display_name"] = "Andy Updated"
    updated_profile["current_total_assets"] = 62_000.0
    updated_profile["current_holdings"] = "cash"
    updated_profile_path = tmp_path / "updated_profile.json"
    updated_profile_path.write_text(
        json.dumps(updated_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monthly_exit_code = main(
        [
            "monthly",
            "--db",
            str(db_path),
            "--account-profile-id",
            account_profile_id,
            "--profile-json",
            str(updated_profile_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert monthly_exit_code == 0
    assert payload["display_name"] == "Andy Updated"
    assert payload["workflow_type"] == "monthly"

    user_state = load_user_state(account_profile_id, db_path=db_path)
    assert user_state is not None
    assert user_state["profile"]["display_name"] == "Andy Updated"
    assert user_state["profile"]["current_total_assets"] == 62_000.0
    assert user_state["profile"]["current_holdings"] == "cash"
    assert user_state["latest_result"]["workflow_type"] == "monthly"
