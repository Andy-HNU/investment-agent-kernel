from __future__ import annotations

import json

import pytest

from frontdesk.external_data import ExternalSnapshotAdapterError
from frontdesk.storage import FrontdeskStore
from frontdesk.service import load_user_state, run_frontdesk_followup, run_frontdesk_onboarding
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
def test_formal_frontdesk_onboarding_defaults_to_real_source_market_history(tmp_path):
    profile = _profile(account_profile_id="frontdesk_real_source_default")
    db_path = tmp_path / "frontdesk.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)

    assert summary["status"] in {"completed", "degraded"}
    assert summary["refresh_summary"]["provider_name"] == "real_source_market_history"
    assert summary["refresh_summary"]["source_kind"] == "snapshot_source"
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert any(
        str(item.get("field")) == "market_raw"
        for item in summary["input_provenance"].get("externally_fetched", [])
    )
    snapshot = FrontdeskStore(db_path).get_frontdesk_snapshot(profile.account_profile_id)
    assert snapshot is not None
    market_assumptions = snapshot["latest_baseline"]["goal_solver_input"]["solver_params"]["market_assumptions"]
    assert market_assumptions["source_name"] == "real_source_market_history"
    assert market_assumptions["historical_backtest_used"] is True
    assert market_assumptions["frequency"] == "daily"
    assert market_assumptions["lookback_days"] >= 252
    assert market_assumptions["dataset_version"].startswith("real_source_market_history:")
    assert market_assumptions["coverage_status"] in {"verified", "cycle_insufficient"}


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

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fallback"
    assert summary["external_snapshot_error"] is not None
    assert summary["input_provenance"]["counts"]["externally_fetched"] >= 1
    assert summary["refresh_summary"]["provider_name"] == "real_source_market_history"
    assert not any(
        item.get("field") in {"market_raw", "behavior_raw"}
        for item in summary["input_provenance"].get("default_assumed", [])
    )


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
def test_formal_frontdesk_onboarding_rejects_inline_snapshot_provider_config(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_inline")
    with pytest.raises(ValueError, match="formal frontdesk flow forbids debug adapter: inline_snapshot"):
        run_frontdesk_onboarding(
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


@pytest.mark.contract
def test_formal_frontdesk_onboarding_rejects_file_json_provider_config(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_file_json")
    payload_path = tmp_path / "snapshot.json"
    payload_path.write_text(json.dumps(_snapshot(total_value=62_500.0), ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="formal frontdesk flow forbids debug adapter: file_json"):
        run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "frontdesk.sqlite",
            external_data_config={
                "adapter": "file_json",
                "file_path": str(payload_path),
            },
        )


@pytest.mark.contract
def test_formal_frontdesk_followup_rejects_file_json_provider_config(tmp_path):
    profile = _profile(account_profile_id="frontdesk_provider_file_json_followup")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] in {"completed", "degraded"}

    payload_path = tmp_path / "snapshot.json"
    payload_path.write_text(json.dumps(_snapshot(total_value=65_500.0), ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="formal frontdesk flow forbids debug adapter: file_json"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
            external_data_config={
                "adapter": "file_json",
                "file_path": str(payload_path),
            },
        )


@pytest.mark.contract
def test_formal_frontdesk_overrides_external_fake_historical_dataset_with_real_source_market_history(tmp_path):
    profile = _profile(account_profile_id="frontdesk_fake_history_override")
    db_path = tmp_path / "frontdesk.sqlite"
    fake_snapshot = _snapshot(total_value=61_000.0)
    fake_snapshot["market_raw"]["historical_dataset"] = {
        "source_name": "fixture_fake_history",
        "version_id": "fixture_fake_history:2026-03-30:v1",
        "as_of": "2026-03-30T07:30:00Z",
        "frequency": "daily",
        "lookback_days": 252,
        "lookback_months": 12,
        "series_dates": ["2026-03-28", "2026-03-29"],
        "return_series": {"equity_cn": [0.01, -0.02]},
        "coverage_status": "verified",
    }

    with serve_json_routes({"/snapshot": (200, fake_snapshot)}) as base_url:
        summary = run_frontdesk_onboarding(
            profile,
            db_path=db_path,
            external_data_config={
                "adapter": "http_json",
                "snapshot_url": f"{base_url}/snapshot",
            },
        )

    assert summary["status"] in {"completed", "degraded"}
    snapshot = FrontdeskStore(db_path).get_frontdesk_snapshot(profile.account_profile_id)
    assert snapshot is not None
    market_assumptions = snapshot["latest_baseline"]["goal_solver_input"]["solver_params"]["market_assumptions"]
    assert market_assumptions["source_name"] == "real_source_market_history"
    assert market_assumptions["dataset_version"].startswith("real_source_market_history:")
