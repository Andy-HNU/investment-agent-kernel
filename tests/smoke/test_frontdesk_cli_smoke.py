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
    assert payload["status"] in {"completed", "degraded"}
    assert payload["user_state"]["profile"]["display_name"] == "Andy"
    assert payload["user_state"]["decision_card"]["card_type"] == "goal_baseline"
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1


@pytest.mark.smoke
def test_frontdesk_cli_accepts_inline_profile_json(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["user_state"]["profile"]["account_profile_id"] == profile.account_profile_id
    assert payload["user_state"]["active_execution_plan"] is None
    assert payload["user_state"]["pending_execution_plan"]["plan_version"] == 1
    assert (
        payload["user_state"]["decision_card"]["execution_plan_summary"]["plan_id"]
        == payload["user_state"]["pending_execution_plan"]["plan_id"]
    )


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
    assert "pending_execution_plan:" in output
    assert "execution_feedback:" in output


@pytest.mark.smoke
def test_frontdesk_cli_approve_plan_promotes_pending_execution_plan(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert onboard_exit == 0
    assert approve_exit == 0
    assert payload["workflow"] == "approve_plan"
    assert payload["status"] == "approved"
    assert payload["approved_execution_plan"]["plan_id"] == pending_plan["plan_id"]
    assert payload["user_state"]["active_execution_plan"]["status"] == "approved"
    assert payload["user_state"]["pending_execution_plan"] is None


@pytest.mark.smoke
def test_frontdesk_cli_show_user_surfaces_execution_plan_comparison(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(profile.to_dict(), ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    onboard_payload = json.loads(capsys.readouterr().out)
    pending_plan = onboard_payload["user_state"]["pending_execution_plan"]

    approve_exit = main(
        [
            "approve-plan",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--plan-id",
            str(pending_plan["plan_id"]),
            "--plan-version",
            str(pending_plan["plan_version"]),
            "--approved-at",
            "2026-03-31T00:00:00Z",
            "--json",
        ]
    )
    capsys.readouterr()

    updated_profile = profile.to_dict()
    updated_profile["restrictions"] = ["不碰股票"]
    second_onboard_exit = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            json.dumps(updated_profile, ensure_ascii=False),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()

    show_user_exit = main(
        [
            "show-user",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
        ]
    )
    output = capsys.readouterr().out

    assert onboard_exit == 0
    assert approve_exit == 0
    assert second_onboard_exit == 0
    assert show_user_exit == 0
    assert "execution_plan_comparison:" in output
    assert "recommendation=replace_active" in output
    assert "bucket=equity_cn" in output
