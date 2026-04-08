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


def _profile(*, account_profile_id: str = "frontdesk_provider_cli") -> UserOnboardingProfile:
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


def _snapshot(*, total_value: float) -> dict[str, object]:
    weights = {"equity_cn": 0.46, "bond_cn": 0.34, "gold": 0.12, "satellite": 0.08}
    profile = _profile(account_profile_id="frontdesk_provider_cli_fixture")
    payload = build_formal_snapshot_payload(
        profile,
        account_raw_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 1_500.0,
            "remaining_horizon_months": 36,
        },
        live_portfolio_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 1_500.0,
            "remaining_horizon_months": 36,
        },
        provider_name="broker_http_json",
        source_ref="provider://snapshot/broker_http_json",
    )
    meta = payload["external_snapshot_meta"]
    return {
        "market_raw": payload["market_raw"],
        "account_raw": payload["account_raw"],
        "behavior_raw": payload["behavior_raw"],
        "live_portfolio": payload["live_portfolio"],
        "provider_name": meta["provider_name"],
        "as_of": meta["as_of"],
        "fetched_at": meta["fetched_at"],
        "domains": meta["domains"],
    }


@pytest.mark.smoke
def test_frontdesk_cli_onboard_accepts_external_provider_config_inline_json(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    with serve_json_routes({"/snapshot": (200, _snapshot(total_value=63_000.0))}) as base_url:
        exit_code = main(
            [
                "onboard",
                "--db",
                str(tmp_path / "frontdesk.sqlite"),
                "--profile-json",
                str(profile_path),
                "--external-data-config",
                json.dumps({"adapter": "http_json", "snapshot_url": f"{base_url}/snapshot"}, ensure_ascii=False),
                "--non-interactive",
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert payload["user_state"]["profile"]["current_total_assets"] == 63_000.0


@pytest.mark.smoke
def test_frontdesk_cli_monthly_accepts_external_provider_config_file(tmp_path, capsys):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="frontdesk_provider_cli_monthly")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    db_path = tmp_path / "frontdesk.sqlite"
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

    config_path = tmp_path / "provider_config.json"
    with serve_json_routes({"/snapshot": (200, _snapshot(total_value=66_000.0))}) as base_url:
        config_path.write_text(
            json.dumps(
                {"adapter": "http_json", "snapshot_url": f"{base_url}/snapshot", "fail_open": True},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        monthly_exit_code = main(
            [
                "monthly",
                "--db",
                str(db_path),
                "--account-profile-id",
                profile.account_profile_id,
                "--external-data-config",
                str(config_path),
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)
    user_state = load_user_state(profile.account_profile_id, db_path=db_path)

    assert monthly_exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert user_state is not None
    assert user_state["profile"]["current_total_assets"] == 66_000.0
