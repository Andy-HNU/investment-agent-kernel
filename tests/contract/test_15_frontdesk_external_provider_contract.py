from __future__ import annotations

import json

import pytest

from frontdesk.external_data import ExternalSnapshotAdapterError
from frontdesk.service import load_user_state, run_frontdesk_followup, run_frontdesk_onboarding
from shared.datasets.types import VersionPin
from shared.onboarding import UserOnboardingProfile
from tests.support.http_snapshot_server import serve_json_routes


def _profile(*, account_profile_id: str = "frontdesk_provider_user") -> UserOnboardingProfile:
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
    weights = {"equity_cn": 0.48, "bond_cn": 0.32, "gold": 0.12, "satellite": 0.08}
    return {
        "market_raw": {
            "raw_volatility": {"equity_cn": 0.19, "bond_cn": 0.05, "gold": 0.10, "satellite": 0.22},
            "liquidity_scores": {"equity_cn": 0.90, "bond_cn": 0.96, "gold": 0.83, "satellite": 0.60},
            "valuation_z_scores": {"equity_cn": -0.1, "bond_cn": 0.05, "gold": -0.15, "satellite": 0.9},
            "expected_returns": {"equity_cn": 0.09, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.10},
        },
        "account_raw": {
            "weights": weights,
            "total_value": total_value,
            "available_cash": 2_000.0,
            "remaining_horizon_months": 60,
        },
        "behavior_raw": {
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 1.0,
            "override_count_90d": 0,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.1,
        },
        "provider_name": "broker_http_json",
        "fetched_at": "2026-03-30T08:00:00Z",
        "as_of": "2026-03-30T07:30:00Z",
        "domains": {
            "market_raw": {
                "status": "fresh",
                "fetched_at": "2026-03-30T08:00:00Z",
                "as_of": "2026-03-30T07:30:00Z",
            },
            "account_raw": {
                "status": "fresh",
                "fetched_at": "2026-03-30T08:00:00Z",
                "as_of": "2026-03-30T07:30:00Z",
            },
            "behavior_raw": {
                "status": "fresh",
                "fetched_at": "2026-03-30T08:00:00Z",
                "as_of": "2026-03-30T07:30:00Z",
            },
        },
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

    assert summary["status"] == "completed"
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

    assert summary["status"] == "completed"
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
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] == "completed"

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
    assert summary["status"] == "completed"
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
            "as_of": "2026-03-30T07:30:00Z",
            "fetched_at": "2026-03-30T08:00:00Z",
            "payload": _snapshot(total_value=62_500.0),
        },
    )

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "fixture_inline_provider"
    assert summary["user_state"]["profile"]["current_total_assets"] == 62_500.0


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_market_history_provider_config_and_surfaces_degraded_status(tmp_path, monkeypatch):
    from snapshot_ingestion.adapters import market_history_adapter

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        rows = [
            {"date": "2025-01-31", "open": 3900.0, "high": 3910.0, "low": 3890.0, "close": 3905.0, "volume": 1.0},
            {"date": "2025-02-28", "open": 3920.0, "high": 3940.0, "low": 3910.0, "close": 3936.0, "volume": 1.0},
            {"date": "2025-03-31", "open": 3940.0, "high": 3960.0, "low": 3930.0, "close": 3955.0, "volume": 1.0},
        ]
        used_pin = VersionPin(version_id=pin.version_id, source_ref=pin.source_ref)
        return (rows, used_pin) if return_used_pin else rows

    monkeypatch.setattr(market_history_adapter, "fetch_timeseries", _fake_fetch_timeseries)

    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="frontdesk_provider_market_history"),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "market_history",
            "provider_name": "akshare_market_history",
            "dataset_id": "cn_market_history",
            "dataset_cache_dir": str(tmp_path / "dataset-cache"),
            "historical_cache_dir": str(tmp_path / "historical-cache"),
            "coverage_expectation": ["equity_cn", "bond_cn", "gold", "satellite"],
            "bucket_series": {
                "equity_cn": {
                    "provider": "akshare",
                    "kind": "cn_index_daily",
                    "dataset_id": "cn_core_index",
                    "symbol": "000300",
                    "version_id": "akshare-cn-core:v1",
                    "source_ref": "akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
                    "proxy_label": "沪深300指数",
                }
            },
        },
    )

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "akshare_market_history"
    assert summary["refresh_summary"]["freshness_state"] == "degraded"
    market_domain = next(item for item in summary["refresh_summary"]["domain_details"] if item["domain"] == "market_raw")
    assert market_domain["freshness_state"] == "degraded"
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 1
    fetched_market = summary["decision_card"]["input_provenance"]["externally_fetched"][0]
    assert "coverage_status=degraded" in str(fetched_market.get("note") or "")
    assert "dataset_version=" in str(fetched_market.get("note") or "")
