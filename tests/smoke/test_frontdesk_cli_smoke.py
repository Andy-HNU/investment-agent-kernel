from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_andy",
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
def test_frontdesk_cli_non_interactive_onboarding_smoke(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
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
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["workflow"] == "onboard"
    assert payload["status"] == "completed"
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    assert payload["user_state"]["decision_card"]["card_type"] == "goal_baseline"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1


@pytest.mark.smoke
def test_frontdesk_cli_status_reads_existing_state(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    first_exit_code = main(
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
    capsys.readouterr()
    assert first_exit_code == 0

    status_exit_code = main(
        [
            "status",
            "--db",
            str(db_path),
            "--user-id",
            profile.account_profile_id,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert status_exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    serialized = json.dumps(payload["user_state"], ensure_ascii=False, sort_keys=True)
    for label in ("用户提供", "系统推断", "默认假设", "外部抓取"):
        assert label in serialized


@pytest.mark.smoke
def test_frontdesk_cli_text_summary_surfaces_readable_candidates_and_disclaimer(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "onboarding",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--non-interactive",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "candidate_1=" in output
    assert "input_sources=" in output
    assert "model_disclaimer=" in output
    assert "goal_semantics:" in output
    assert "profile_model:" in output
    assert "refresh:" in output
    assert "execution_feedback:" in output
