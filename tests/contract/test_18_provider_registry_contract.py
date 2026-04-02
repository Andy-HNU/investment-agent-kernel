from __future__ import annotations

from pathlib import Path

import pytest

from frontdesk.service import run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile
from shared.datasets.types import VersionPin
from snapshot_ingestion.adapters import market_history_adapter
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

    expected_returns, volatility, correlation_matrix = summarize_historical_dataset(reloaded)
    assert set(expected_returns) == {"equity_cn", "bond_cn"}
    assert set(volatility) == {"equity_cn", "bond_cn"}
    assert correlation_matrix["equity_cn"]["equity_cn"] == 1.0


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
def test_fetch_snapshot_from_provider_config_supports_market_history_provider(tmp_path, monkeypatch):
    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        rows = [
            {"date": "2025-01-31", "open": 3900.0, "high": 3910.0, "low": 3890.0, "close": 3905.0, "volume": 1.0},
            {"date": "2025-02-28", "open": 3920.0, "high": 3940.0, "low": 3910.0, "close": 3936.0, "volume": 1.0},
            {"date": "2025-03-31", "open": 3940.0, "high": 3960.0, "low": 3930.0, "close": 3955.0, "volume": 1.0},
        ]
        used_pin = VersionPin(version_id=pin.version_id, source_ref=pin.source_ref)
        return (rows, used_pin) if return_used_pin else rows

    monkeypatch.setattr(market_history_adapter, "fetch_timeseries", _fake_fetch_timeseries)

    fetched = fetch_snapshot_from_provider_config(
        {
            "adapter": "market_history",
            "provider_name": "akshare_market_history",
            "dataset_id": "cn_market_history",
            "dataset_cache_dir": str(tmp_path / "dataset-cache"),
            "historical_cache_dir": str(tmp_path / "historical-cache"),
            "coverage_expectation": ["equity_cn", "bond_cn"],
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
        workflow_type="onboarding",
        account_profile_id="provider_registry_user",
        as_of="2026-04-03T09:30:00Z",
    )

    assert fetched is not None
    assert fetched.provider_name == "akshare_market_history"
    market_raw = fetched.raw_overrides["market_raw"]
    assert market_raw["historical_dataset"]["dataset_id"] == "cn_market_history"
    assert market_raw["historical_dataset"]["coverage_status"] == "degraded"
    assert market_raw["historical_dataset"]["return_series"]["equity_cn"]
    assert market_raw["bucket_proxy_mapping"]["bucket_to_proxy"]["equity_cn"] == "沪深300指数"
    assert fetched.freshness["domains"]["market_raw"]["status"] == "degraded"
    assert any("partial bucket coverage" in warning for warning in fetched.warnings)
    cached_files = list((tmp_path / "historical-cache").glob("*.json"))
    assert cached_files


@pytest.mark.contract
def test_frontdesk_onboarding_accepts_market_history_provider_fixture(tmp_path, monkeypatch):
    rows_by_symbol = {
        "000300": [
            {"date": "2025-01-31", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0},
            {"date": "2025-02-28", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "volume": 1000.0},
            {"date": "2025-03-31", "open": 121.0, "high": 121.0, "low": 121.0, "close": 121.0, "volume": 1000.0},
        ],
        "511010": [
            {"date": "2025-01-31", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0},
            {"date": "2025-02-28", "open": 101.0, "high": 101.0, "low": 101.0, "close": 101.0, "volume": 1000.0},
            {"date": "2025-03-31", "open": 102.0, "high": 102.0, "low": 102.0, "close": 102.0, "volume": 1000.0},
        ],
        "Au99.99": [
            {"date": "2025-01-31", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0},
            {"date": "2025-02-28", "open": 98.0, "high": 98.0, "low": 98.0, "close": 98.0, "volume": 1000.0},
            {"date": "2025-03-31", "open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "volume": 1000.0},
        ],
        "399006": [
            {"date": "2025-01-31", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0},
            {"date": "2025-02-28", "open": 115.0, "high": 115.0, "low": 115.0, "close": 115.0, "volume": 1000.0},
            {"date": "2025-03-31", "open": 120.0, "high": 120.0, "low": 120.0, "close": 120.0, "volume": 1000.0},
        ],
    }

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback=False, return_used_pin=False):
        del cache, allow_fallback
        rows = rows_by_symbol[str(spec.symbol)]
        return (rows, pin) if return_used_pin else rows

    monkeypatch.setattr(market_history_adapter, "fetch_timeseries", _fake_fetch_timeseries)

    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="market_history_provider_user"),
        db_path=tmp_path / "frontdesk.sqlite",
        external_data_config={
            "adapter": "market_history",
            "provider_name": "market_history_akshare_tx",
            "dataset_id": "cn_core_history",
            "dataset_cache_dir": str(tmp_path / "dataset-cache"),
            "historical_cache_dir": str(tmp_path / "historical-cache"),
            "bucket_series": {
                "equity_cn": {
                    "provider": "akshare",
                    "kind": "cn_index_daily",
                    "dataset_id": "cn_index_000300",
                    "symbol": "000300",
                    "version_id": "tx-csi300:v1",
                    "source_ref": "akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
                },
                "bond_cn": {
                    "provider": "akshare",
                    "kind": "cn_bond_daily",
                    "dataset_id": "cn_bond_511010",
                    "symbol": "511010",
                    "version_id": "bond-511010:v1",
                    "source_ref": "akshare://bond_zh_hs_daily?series_type=cn_bond_daily",
                },
                "gold": {
                    "provider": "akshare",
                    "kind": "cn_gold_spot",
                    "dataset_id": "cn_gold_au9999",
                    "symbol": "Au99.99",
                    "version_id": "gold-au9999:v1",
                    "source_ref": "akshare://spot_hist_sge?series_type=cn_gold_spot",
                },
                "satellite": {
                    "provider": "akshare",
                    "kind": "cn_index_daily",
                    "dataset_id": "cn_index_399006",
                    "symbol": "399006",
                    "version_id": "tx-cyb:v1",
                    "source_ref": "akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
                },
            },
            "coverage_expectation": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    )

    assert summary["status"] == "completed"
    assert summary["external_snapshot_status"] == "fetched"
    assert summary["refresh_summary"]["provider_name"] == "market_history_akshare_tx"
    market_domain = next(item for item in summary["refresh_summary"]["domain_details"] if item["domain"] == "market_raw")
    assert market_domain["freshness_state"] == "fresh"
