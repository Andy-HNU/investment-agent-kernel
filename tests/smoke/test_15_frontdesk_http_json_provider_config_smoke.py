from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from frontdesk.service import load_user_state
from shared.onboarding import UserOnboardingProfile
from tests.support.frontdesk_http_json_provider_config import (
    fetch_provider_snapshot,
    payload_from_snapshot,
)
from tests.support.http_snapshot_server import serve_json_routes


AS_OF = "2026-03-30T00:00:00Z"


def _profile(*, account_profile_id: str = "frontdesk_provider_config_user") -> UserOnboardingProfile:
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


def _write_config(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.mark.smoke
def test_frontdesk_cli_onboard_with_http_json_provider_config_path_fetches_external_provenance(
    tmp_path,
    capsys,
    monkeypatch,
):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="provider_config_smoke_onboarding")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = _write_config(
        tmp_path / "provider_config.json",
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "smoke-onboarding",
            },
            "fail_open": False,
        },
    )

    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "market_raw": {
                        "raw_volatility": {
                            "equity_cn": 0.20,
                            "bond_cn": 0.05,
                            "gold": 0.11,
                            "satellite": 0.24,
                        },
                        "liquidity_scores": {
                            "equity_cn": 0.91,
                            "bond_cn": 0.96,
                            "gold": 0.82,
                            "satellite": 0.58,
                        },
                        "valuation_z_scores": {
                            "equity_cn": -0.2,
                            "bond_cn": 0.1,
                            "gold": -0.1,
                            "satellite": 1.1,
                        },
                        "expected_returns": {
                            "equity_cn": 0.09,
                            "bond_cn": 0.03,
                            "gold": 0.04,
                            "satellite": 0.11,
                        },
                    },
                    "behavior_raw": {
                        "recent_chase_risk": "low",
                        "recent_panic_risk": "none",
                        "trade_frequency_30d": 0.0,
                        "override_count_90d": 0,
                        "cooldown_active": False,
                        "cooldown_until": None,
                        "behavior_penalty_coeff": 0.2,
                    },
                },
            )
        }
    ):
        fetched = fetch_provider_snapshot(
            config_path,
            workflow_type="onboarding",
            account_profile_id=profile.account_profile_id,
            as_of=AS_OF,
        )

    assert fetched is not None
    provider_payload = payload_from_snapshot(fetched)
    monkeypatch.setattr(
        "frontdesk.service._external_snapshot_payload",
        lambda source: deepcopy(provider_payload),
    )

    exit_code = main(
        [
            "onboard",
            "--db",
            str(tmp_path / "frontdesk.sqlite"),
            "--profile-json",
            str(profile_path),
            "--external-snapshot-source",
            str(config_path),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 2
    assert Path(payload["external_snapshot_source"]) == config_path


@pytest.mark.smoke
def test_frontdesk_cli_monthly_with_inline_http_json_provider_config_updates_state(
    tmp_path,
    capsys,
    monkeypatch,
):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="provider_config_smoke_followup")
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

    inline_config = json.dumps(
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "smoke-followup-inline",
            },
            "fail_open": False,
        },
        ensure_ascii=False,
    )

    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "account_raw": {
                        "weights": {
                            "equity_cn": 0.20,
                            "bond_cn": 0.50,
                            "gold": 0.20,
                            "satellite": 0.10,
                        },
                        "total_value": 88_000.0,
                        "available_cash": 4_000.0,
                        "remaining_horizon_months": 60,
                    },
                    "live_portfolio": {
                        "weights": {
                            "equity_cn": 0.20,
                            "bond_cn": 0.50,
                            "gold": 0.20,
                            "satellite": 0.10,
                        },
                        "total_value": 88_000.0,
                        "available_cash": 4_000.0,
                        "remaining_horizon_months": 60,
                        "current_drawdown": 0.06,
                    },
                },
            )
        }
    ):
        fetched = fetch_provider_snapshot(
            inline_config,
            workflow_type="monthly",
            account_profile_id=profile.account_profile_id,
            as_of=AS_OF,
        )

    assert fetched is not None
    provider_payload = payload_from_snapshot(fetched)
    monkeypatch.setattr(
        "frontdesk.service._external_snapshot_payload",
        lambda source: deepcopy(provider_payload),
    )

    exit_code = main(
        [
            "monthly",
            "--db",
            str(db_path),
            "--account-profile-id",
            profile.account_profile_id,
            "--external-snapshot-source",
            inline_config,
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    user_state = load_user_state(profile.account_profile_id, db_path=db_path)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fetched"
    assert payload["input_provenance"]["counts"]["externally_fetched"] >= 2
    assert json.loads(payload["external_snapshot_source"])["query_params"]["channel"] == "smoke-followup-inline"
    assert user_state is not None
    assert user_state["profile"]["current_total_assets"] == 88_000.0


@pytest.mark.smoke
def test_frontdesk_cli_onboard_http_json_provider_config_fail_open_falls_back(
    tmp_path,
    capsys,
    monkeypatch,
):
    from frontdesk.cli import main

    profile = _profile(account_profile_id="provider_config_smoke_fail_open")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = _write_config(
        tmp_path / "provider_config.json",
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "smoke-fail-open",
            },
            "fail_open": True,
        },
    )

    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}):
        fetched = fetch_provider_snapshot(
            config_path,
            workflow_type="onboarding",
            account_profile_id=profile.account_profile_id,
            as_of=AS_OF,
        )

    assert fetched is not None
    assert fetched.raw_overrides == {}
    assert fetched.provenance_items == []
    assert fetched.warnings

    monkeypatch.setattr(
        "frontdesk.service._external_snapshot_payload",
        lambda source: {},
    )

    exit_code = main(
        [
            "onboard",
            "--db",
            str(tmp_path / "frontdesk.sqlite"),
            "--profile-json",
            str(profile_path),
            "--external-snapshot-source",
            str(config_path),
            "--non-interactive",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["external_snapshot_status"] == "fallback"
    assert payload["user_state"]["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert any(
        item["field"] == "market_raw"
        for item in payload["user_state"]["decision_card"]["input_provenance"]["externally_fetched"]
    )
