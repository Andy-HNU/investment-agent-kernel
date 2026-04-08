from __future__ import annotations

import json

import pytest

from frontdesk.external_data import ExternalSnapshotAdapterError
from frontdesk.service import load_user_state, run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import (
    build_formal_snapshot_payload,
    write_formal_snapshot_source,
)
from tests.support.http_snapshot_server import serve_json_routes


def _profile(*, account_profile_id: str = "frontdesk_provider_user") -> UserOnboardingProfile:
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
    profile = _profile(account_profile_id="provider_snapshot_profile")
    weights = {"equity_cn": 0.48, "bond_cn": 0.32, "gold": 0.12, "satellite": 0.08}
    payload = build_formal_snapshot_payload(
        profile,
        account_raw_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 2_000.0,
            "remaining_horizon_months": 36,
        },
        live_portfolio_overrides={
            "weights": weights,
            "total_value": total_value,
            "available_cash": 2_000.0,
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


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_http_json_provider_config(tmp_path):
    profile = _profile()
    db_path = tmp_path / "frontdesk.sqlite"

    with serve_json_routes({"/snapshot": (200, _snapshot(total_value=61_000.0))}) as base_url:
        summary = run_frontdesk_onboarding(
            profile,
            db_path=db_path,
            external_data_config={
                "adapter": "http_json",
                "snapshot_url": f"{base_url}/snapshot",
                "query_params": {"client": "frontdesk"},
            },
        )

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["external_snapshot_source"].startswith(f"{base_url}/snapshot?")
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert summary["refresh_summary"]["provider_name"] == "broker_http_json"
    assert summary["refresh_summary"]["freshness_state"] == "fresh"
    assert summary["refresh_summary"]["domain_details"][0]["freshness_label"] == "新鲜"
    assert not any(
        item.get("field") in {"market_raw", "behavior_raw"}
        for item in summary["input_provenance"].get("default_assumed", [])
    )
    assert summary["user_state"]["profile"]["current_total_assets"] == 61_000.0


@pytest.mark.contract
def test_frontdesk_provider_config_fail_open_falls_back_without_blocking(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_fallback")

    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}) as base_url:
        summary = run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "frontdesk.sqlite",
            external_data_config={
                "adapter": "http_json",
                "snapshot_url": f"{base_url}/snapshot",
                "fail_open": True,
            },
        )

    assert summary["status"] == "blocked"
    assert summary["external_snapshot_status"] == "fallback"
    assert summary["external_snapshot_error"] is not None
    assert summary["input_provenance"]["counts"]["externally_fetched"] == 0
    assert summary["input_provenance"]["counts"]["default_assumed"] >= 1


@pytest.mark.contract
def test_frontdesk_provider_config_fail_closed_raises(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_strict")

    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}) as base_url:
        with pytest.raises(ExternalSnapshotAdapterError, match="external snapshot fetch failed"):
            run_frontdesk_onboarding(
                profile,
                db_path=tmp_path / "frontdesk.sqlite",
                external_data_config={
                    "adapter": "http_json",
                    "snapshot_url": f"{base_url}/snapshot",
                    "fail_open": False,
                },
            )


@pytest.mark.contract
def test_frontdesk_monthly_accepts_provider_config_from_json_file(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_monthly")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    assert onboarding_summary["status"] in {"completed", "degraded"}

    config_path = tmp_path / "provider_config.json"
    with serve_json_routes({"/snapshot": (200, _snapshot(total_value=64_000.0))}) as base_url:
        config_path.write_text(
            json.dumps(
                {
                    "adapter": "http_json",
                    "snapshot_url": f"{base_url}/snapshot",
                    "headers": {"X-Frontdesk-Test": "1"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        summary = run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
            external_data_config=str(config_path),
        )

    user_state = load_user_state(profile.account_profile_id, db_path=db_path)
    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert user_state is not None
    assert user_state["profile"]["current_total_assets"] == 64_000.0


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_inline_snapshot_provider_config(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_inline")

    summary = run_frontdesk_onboarding(
        profile,
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "inline_snapshot",
            "provider_name": "fixture_inline_provider",
            "payload": _snapshot(total_value=62_500.0),
        },
    )

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "fixture_inline_provider"
    assert summary["user_state"]["profile"]["current_total_assets"] == 62_500.0
