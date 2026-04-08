from __future__ import annotations

import json

import pytest

from frontdesk.service import load_user_state
from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import (
    build_formal_snapshot_payload,
    write_formal_snapshot_source,
)
from tests.support.http_snapshot_server import serve_json_routes


def _profile(*, account_profile_id: str = "frontdesk_external_user") -> UserOnboardingProfile:
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


def _external_snapshot(*, total_value: float) -> dict[str, object]:
    profile = _profile(account_profile_id="frontdesk_external_snapshot_profile")
    weights = {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.15, "satellite": 0.05}
    return build_formal_snapshot_payload(
        profile,
        account_raw_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 1_000.0,
            "remaining_horizon_months": 36,
        },
        live_portfolio_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 1_000.0,
            "remaining_horizon_months": 36,
            "current_drawdown": 0.03,
        },
    )


@pytest.mark.smoke
def test_frontdesk_cli_onboarding_can_fetch_external_snapshot(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    with serve_json_routes({"/snapshot": (200, _external_snapshot(total_value=62_000.0))}) as base_url:
        exit_code = main(
            [
                "onboard",
                "--db",
                str(db_path),
                "--profile-json",
                str(profile_path),
                "--external-snapshot-source",
                f"{base_url}/snapshot",
                "--non-interactive",
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert payload["user_state"]["profile"]["current_total_assets"] == 62_000.0
    assert payload["user_state"]["profile"]["current_holdings"] == "externally_fetched_snapshot"


@pytest.mark.smoke
def test_frontdesk_cli_onboarding_fetch_failure_falls_back(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="frontdesk_external_fallback")
    db_path = tmp_path / "frontdesk.sqlite"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}) as base_url:
        exit_code = main(
            [
                "onboard",
                "--db",
                str(db_path),
                "--profile-json",
                str(profile_path),
                "--external-snapshot-source",
                f"{base_url}/snapshot",
                "--non-interactive",
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "blocked"
    assert payload["external_snapshot_status"] == "fallback"
    assert payload["external_snapshot_error"]
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 0


@pytest.mark.smoke
def test_frontdesk_cli_monthly_can_use_external_snapshot_updates(tmp_path, capsys):
    from frontdesk.cli import main

    account_profile_id = "frontdesk_external_monthly"
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id=account_profile_id)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    baseline_snapshot_path = write_formal_snapshot_source(tmp_path, profile)

    onboarding_exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--external-snapshot-source",
            str(baseline_snapshot_path),
            "--non-interactive",
            "--json",
        ]
    )
    capsys.readouterr()
    assert onboarding_exit_code == 0

    with serve_json_routes({"/snapshot": (200, _external_snapshot(total_value=64_000.0))}) as base_url:
        monthly_exit_code = main(
            [
                "monthly",
                "--db",
                str(db_path),
                "--account-profile-id",
                account_profile_id,
                "--external-snapshot-source",
                f"{base_url}/snapshot",
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)
    user_state = load_user_state(account_profile_id, db_path=db_path)

    assert monthly_exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert user_state is not None
    assert user_state["profile"]["current_total_assets"] == 64_000.0
    assert user_state["latest_result"]["workflow_type"] == "monthly"
