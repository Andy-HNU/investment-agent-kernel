from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile
from tests.support.http_snapshot_server import serve_json_routes


def _profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_external_user",
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
def test_frontdesk_cli_onboarding_with_remote_external_snapshot_fetches_data(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    db_path = tmp_path / "frontdesk.sqlite"

    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "market_raw": {"source": "remote-market"},
                    "account_raw": {"weights": {"equity_cn": 0.4, "bond_cn": 0.4, "gold": 0.1, "satellite": 0.1}},
                },
            )
        }
    ) as base_url:
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
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 1


@pytest.mark.smoke
def test_frontdesk_cli_onboarding_with_missing_remote_external_snapshot_falls_back(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    db_path = tmp_path / "frontdesk.sqlite"

    exit_code = main(
        [
            "onboard",
            "--db",
            str(db_path),
            "--profile-json",
            str(profile_path),
            "--external-snapshot-source",
            "http://127.0.0.1:9/missing_snapshot.json",
            "--non-interactive",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fallback"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert any(
        item["field"] == "market_raw"
        for item in payload["user_state"]["decision_card"]["input_provenance"]["externally_fetched"]
    )


@pytest.mark.smoke
def test_frontdesk_cli_monthly_with_remote_external_snapshot_fetches_data(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    db_path = tmp_path / "frontdesk.sqlite"

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
    capsys.readouterr()
    assert onboarding_exit_code == 0

    with serve_json_routes(
        {
            "/monthly": (
                200,
                {
                    "market_raw": {"source": "remote-market"},
                    "account_raw": {
                        "weights": {"equity_cn": 0.35, "bond_cn": 0.45, "gold": 0.10, "satellite": 0.10},
                        "total_value": 52_000.0,
                        "available_cash": 52_000.0,
                        "remaining_horizon_months": 60,
                    },
                },
            )
        }
    ) as base_url:
        monthly_exit_code = main(
            [
                "monthly",
                "--db",
                str(db_path),
                "--account-profile-id",
                profile.account_profile_id,
                "--external-snapshot-source",
                f"{base_url}/monthly",
                "--json",
            ]
        )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert monthly_exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["input_provenance"]["counts"]["externally_fetched"] >= 1
