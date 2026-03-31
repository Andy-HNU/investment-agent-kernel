from __future__ import annotations

import json

import pytest

from frontdesk.service import load_user_state
from shared.onboarding import UserOnboardingProfile
from tests.support.http_snapshot_server import serve_json_routes


def _profile(*, account_profile_id: str = "frontdesk_provider_cli") -> UserOnboardingProfile:
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


def _snapshot(*, total_value: float) -> dict[str, object]:
    weights = {"equity_cn": 0.46, "bond_cn": 0.34, "gold": 0.12, "satellite": 0.08}
    return {
        "market_raw": {
            "raw_volatility": {"equity_cn": 0.18, "bond_cn": 0.05, "gold": 0.10, "satellite": 0.21},
            "liquidity_scores": {"equity_cn": 0.89, "bond_cn": 0.96, "gold": 0.84, "satellite": 0.62},
            "valuation_z_scores": {"equity_cn": -0.1, "bond_cn": 0.05, "gold": -0.12, "satellite": 0.85},
            "expected_returns": {"equity_cn": 0.09, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.10},
        },
        "account_raw": {
            "weights": weights,
            "total_value": total_value,
            "available_cash": 1_500.0,
            "remaining_horizon_months": 60,
        },
        "behavior_raw": {
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 0.0,
            "override_count_90d": 0,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.15,
        },
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
