from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from frontdesk.storage import FrontdeskStore
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


def _patched_external_payload(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(
        "frontdesk.service._external_snapshot_payload",
        lambda source: deepcopy(payload),
    )


@pytest.mark.contract
def test_frontdesk_onboarding_with_http_json_provider_config_path_persists_externally_fetched_provenance(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_onboarding

    profile = _profile(account_profile_id="provider_config_onboarding_path")
    config_path = _write_config(
        tmp_path / "provider_config.json",
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "onboarding-path",
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
    assert fetched.raw_overrides["market_raw"]["raw_volatility"]["equity_cn"] == 0.20
    assert fetched.raw_overrides["behavior_raw"]["recent_chase_risk"] == "low"
    assert all("workflow_type=onboarding" in item["value"] for item in fetched.provenance_items)
    assert all("channel=onboarding-path" in item["value"] for item in fetched.provenance_items)

    provider_payload = payload_from_snapshot(fetched)
    _patched_external_payload(monkeypatch, provider_payload)

    summary = run_frontdesk_onboarding(
        profile,
        db_path=tmp_path / "frontdesk.sqlite",
        external_snapshot_source=str(config_path),
    )

    store = FrontdeskStore(tmp_path / "frontdesk.sqlite")
    user_state = store.load_user_state(profile.account_profile_id)

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fetched"
    assert Path(summary["external_snapshot_source"]) == config_path
    assert user_state is not None
    assert user_state["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 2
    assert {
        item["field"]
        for item in user_state["decision_card"]["input_provenance"]["externally_fetched"]
    } == {"market_raw", "behavior_raw"}


@pytest.mark.contract
def test_frontdesk_monthly_followup_with_inline_http_json_provider_config_updates_state_and_provenance(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_followup, run_frontdesk_onboarding

    profile = _profile(account_profile_id="provider_config_followup_inline")
    db_path = tmp_path / "frontdesk.sqlite"
    run_frontdesk_onboarding(profile, db_path=db_path)

    inline_config = json.dumps(
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "followup-inline",
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
    assert fetched.raw_overrides["account_raw"]["total_value"] == 88_000.0
    assert all("workflow_type=monthly" in item["value"] for item in fetched.provenance_items)
    assert all("channel=followup-inline" in item["value"] for item in fetched.provenance_items)

    provider_payload = payload_from_snapshot(fetched)
    _patched_external_payload(monkeypatch, provider_payload)

    summary = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        external_snapshot_source=inline_config,
    )

    store = FrontdeskStore(db_path)
    user_state = store.load_user_state(profile.account_profile_id)

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert json.loads(summary["external_snapshot_source"])["query_params"]["channel"] == "followup-inline"
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 2
    assert user_state is not None
    assert user_state["profile"]["current_total_assets"] == 88_000.0
    assert user_state["profile"]["current_holdings"] == "externally_fetched_snapshot"
    assert user_state["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 2


@pytest.mark.contract
def test_frontdesk_onboarding_http_json_provider_config_fail_open_falls_back_without_external_provenance(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_onboarding

    profile = _profile(account_profile_id="provider_config_fail_open")
    config_path = _write_config(
        tmp_path / "provider_config.json",
        {
            "adapter": "http_json",
            "snapshot_url": "http://snapshot.test/snapshot",
            "query_params": {
                "channel": "fail-open",
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

    _patched_external_payload(monkeypatch, payload_from_snapshot(fetched))

    summary = run_frontdesk_onboarding(
        profile,
        db_path=tmp_path / "frontdesk.sqlite",
        external_snapshot_source=str(config_path),
    )

    store = FrontdeskStore(tmp_path / "frontdesk.sqlite")
    user_state = store.load_user_state(profile.account_profile_id)

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fallback"
    assert summary.get("external_snapshot_error") is None
    assert user_state is not None
    assert user_state["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 0
