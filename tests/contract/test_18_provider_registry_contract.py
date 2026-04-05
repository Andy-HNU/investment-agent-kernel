from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk.service import run_frontdesk_onboarding
from shared.datasets.types import VersionPin
from shared.onboarding import UserOnboardingProfile
from snapshot_ingestion.historical import (
    HistoricalDatasetCache,
    build_historical_dataset_snapshot,
    summarize_historical_dataset,
)
from snapshot_ingestion.provider_matrix import find_provider_coverage, provider_capability_matrix_dicts
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config, provider_debug_metadata


def _profile(*, account_profile_id: str = "provider_registry_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=900_000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={"equity_cn": 0.50, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.10},
    )


@pytest.mark.contract
def test_provider_capability_matrix_covers_account_and_live_portfolio():
    matrix = provider_capability_matrix_dicts()
    coverage = {row["asset_class"] for row in matrix}

    assert "account_raw" in coverage
    assert "live_portfolio" in coverage
    assert find_provider_coverage("etf") is not None
    assert provider_debug_metadata()["live_portfolio_coverage"]["asset_class"] == "live_portfolio"


@pytest.mark.contract
def test_fetch_snapshot_from_provider_config_supports_local_json_fixture(tmp_path):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "provider_snapshot_local.json"
    fetched = fetch_snapshot_from_provider_config(
        {
            "adapter": "local_json",
            "snapshot_path": str(fixture_path),
            "provider_name": "fixture_local_json",
            "as_of": "2026-03-30T07:30:00Z",
            "fetched_at": "2026-03-30T08:00:00Z",
        },
        workflow_type="monthly",
        account_profile_id="provider_registry_user",
        as_of="2026-03-30T07:30:00Z",
    )

    assert fetched is not None
    assert fetched.provider_name == "fixture_local_json"
    assert fetched.raw_overrides["account_raw"]["total_value"] == 63_500.0
    assert fetched.freshness["domains"]["account_raw"]["status"] == "fresh"


@pytest.mark.contract
def test_historical_dataset_cache_roundtrip_preserves_version_pin(tmp_path):
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "fixture_history",
            "source_ref": "fixture://history",
            "as_of": "2026-03-29",
            "lookback_months": 24,
            "version_id": "fixture_history:2026-03-29:v1",
            "audit_window": {
                "start_date": "2024-03-29",
                "end_date": "2026-03-29",
                "trading_days": 480,
                "observed_days": 480,
                "inferred_days": 0,
            },
            "return_series": {
                "equity_cn": [0.01, 0.02, -0.01, 0.03],
                "bond_cn": [0.002, 0.004, 0.001, 0.003],
            },
        }
    )

    assert dataset is not None
    cache = HistoricalDatasetCache(tmp_path / "history-cache")
    cache.save(dataset)
    reloaded = cache.load("fixture_history:2026-03-29:v1")

    assert reloaded is not None
    assert reloaded.version_id == dataset.version_id
    assert reloaded.return_series == dataset.return_series
    assert reloaded.audit_window is not None
    assert reloaded.audit_window.trading_days == 480

    expected_returns, volatility, correlation_matrix = summarize_historical_dataset(reloaded)
    assert set(expected_returns) == {"equity_cn", "bond_cn"}
    assert set(volatility) == {"equity_cn", "bond_cn"}
    assert correlation_matrix["equity_cn"]["equity_cn"] == 1.0


@pytest.mark.contract
def test_historical_dataset_summary_annualizes_daily_frequency_correctly():
    dataset = build_historical_dataset_snapshot(
        {
            "source_name": "market_history",
            "source_ref": "yfinance://market_history?symbols=equity_cn:510300.SS",
            "as_of": "2026-04-04",
            "lookback_months": 24,
            "frequency": "daily",
            "return_series": {
                "equity_cn": [0.001, 0.002, -0.001, 0.0],
            },
        }
    )

    assert dataset is not None
    expected_returns, volatility, _ = summarize_historical_dataset(dataset)

    expected_mean = sum([0.001, 0.002, -0.001, 0.0]) / 4
    assert expected_returns["equity_cn"] == pytest.approx(expected_mean * 252.0)
    assert volatility["equity_cn"] >= 0.03


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_local_json_provider_fixture(tmp_path):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "provider_snapshot_local.json"
    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="local_json_provider_user"),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "local_json",
            "snapshot_path": str(fixture_path),
            "provider_name": "fixture_local_json",
        },
    )

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "fixture_local_json"
    assert summary["user_state"]["profile"]["current_total_assets"] == 63_500.0


@pytest.mark.contract
def test_fetch_snapshot_from_provider_config_supports_market_history_with_provider_fallback(tmp_path, monkeypatch):
    from shared.audit import DataStatus

    calls: list[tuple[str, str]] = []

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        calls.append((spec.provider, spec.symbol or ""))
        if spec.provider == "akshare":
            raise RuntimeError("historical_provider_unavailable:eastmoney_history_endpoint_closed")
        rows = [
            {"date": "2024-03-28", "open": 3.20, "high": 3.25, "low": 3.18, "close": 3.24, "volume": 1000},
            {"date": "2024-03-29", "open": 3.24, "high": 3.28, "low": 3.20, "close": 3.27, "volume": 2000},
            {"date": "2024-04-01", "open": 3.27, "high": 3.30, "low": 3.25, "close": 3.29, "volume": 1500},
        ]
        return (rows, pin) if return_used_pin else rows

    monkeypatch.setattr("snapshot_ingestion.providers.fetch_timeseries", _fake_fetch_timeseries)

    fetched = fetch_snapshot_from_provider_config(
        {
            "adapter": "market_history",
            "provider": "akshare",
            "coverage_asset_class": "etf",
            "cache_dir": str(tmp_path / "cache"),
            "lookback_months": 12,
        },
        workflow_type="onboarding",
        account_profile_id="provider_registry_user",
        as_of="2026-04-04T00:00:00Z",
    )

    assert fetched is not None
    assert calls[0][0] == "akshare"
    assert any(provider == "yfinance" for provider, _ in calls)
    assert fetched.provider_name == "market_history"
    assert fetched.provenance_items[0]["data_status"] == DataStatus.COMPUTED_FROM_OBSERVED.value

    historical = fetched.raw_overrides["market_raw"]["historical_dataset"]
    assert historical["source_name"] == "yfinance"
    assert historical["coverage_status"] == "degraded"
    assert any("eastmoney_history_endpoint_closed" in note for note in historical["notes"])
    assert historical["audit_window"]["trading_days"] == 3


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_market_history_provider_config(tmp_path, monkeypatch):
    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        rows = [
            {"date": "2024-03-28", "open": 3.20, "high": 3.25, "low": 3.18, "close": 3.24, "volume": 1000},
            {"date": "2024-03-29", "open": 3.24, "high": 3.28, "low": 3.20, "close": 3.27, "volume": 2000},
            {"date": "2024-04-01", "open": 3.27, "high": 3.30, "low": 3.25, "close": 3.29, "volume": 1500},
        ]
        return (rows, pin) if return_used_pin else rows

    monkeypatch.setattr("snapshot_ingestion.providers.fetch_timeseries", _fake_fetch_timeseries)

    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="market_history_provider_user"),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "market_history",
            "provider": "yfinance",
            "coverage_asset_class": "etf",
            "cache_dir": str(tmp_path / "cache"),
            "lookback_months": 12,
        },
    )

    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "market_history"
    assert summary["refresh_summary"]["external_status"] == "fetched"
    assert summary["decision_card"]["input_provenance"]["counts"]["externally_fetched"] > 0


@pytest.mark.contract
def test_frontdesk_refresh_summary_surfaces_historical_dataset_metadata(tmp_path, monkeypatch):
    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        rows = [
            {"date": "2024-03-28", "open": 3.20, "high": 3.25, "low": 3.18, "close": 3.24, "volume": 1000},
            {"date": "2024-03-29", "open": 3.24, "high": 3.28, "low": 3.20, "close": 3.27, "volume": 2000},
            {"date": "2024-04-01", "open": 3.27, "high": 3.30, "low": 3.25, "close": 3.29, "volume": 1500},
        ]
        return (rows, pin) if return_used_pin else rows

    monkeypatch.setattr("snapshot_ingestion.providers.fetch_timeseries", _fake_fetch_timeseries)

    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="market_history_refresh_summary_user"),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "market_history",
            "provider": "yfinance",
            "coverage_asset_class": "etf",
            "cache_dir": str(tmp_path / "cache"),
            "lookback_months": 12,
        },
    )

    market_detail = next(
        item for item in summary["refresh_summary"]["domain_details"] if item.get("domain") == "market_raw"
    )
    historical = market_detail["historical_dataset"]
    assert historical["source_name"] == "yfinance"
    assert historical["coverage_status"] == "verified"
    assert historical["audit_window"]["trading_days"] == 3
    assert historical["source_ref"].startswith("yfinance://market_history?")


@pytest.mark.contract
def test_market_history_adapter_marks_cache_fallback_as_degraded(tmp_path, monkeypatch):
    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        rows = [
            {"date": "2024-03-28", "open": 3.20, "high": 3.25, "low": 3.18, "close": 3.24, "volume": 1000},
            {"date": "2024-03-29", "open": 3.24, "high": 3.28, "low": 3.20, "close": 3.27, "volume": 2000},
            {"date": "2024-04-01", "open": 3.27, "high": 3.30, "low": 3.25, "close": 3.29, "volume": 1500},
        ]
        used_pin = VersionPin(version_id=f"cached::{spec.symbol}", source_ref=f"{spec.provider}://cached::{spec.symbol}")
        return (rows, used_pin) if return_used_pin else rows

    monkeypatch.setattr("snapshot_ingestion.providers.fetch_timeseries", _fake_fetch_timeseries)

    fetched = fetch_snapshot_from_provider_config(
        {
            "adapter": "market_history",
            "provider": "yfinance",
            "coverage_asset_class": "etf",
            "cache_dir": str(tmp_path / "cache"),
            "lookback_months": 12,
        },
        workflow_type="monthly",
        account_profile_id="provider_registry_user",
        as_of="2026-04-04T00:00:00Z",
    )

    historical = fetched.raw_overrides["market_raw"]["historical_dataset"]
    assert historical["coverage_status"] == "degraded"
    assert any("cache fallback activated" in note for note in historical["notes"])
