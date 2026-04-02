from __future__ import annotations

import pytest

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config


@pytest.mark.smoke
def test_live_akshare_cn_index_timeseries_smoke(tmp_path):
    spec = DatasetSpec(
        kind="cn_index_daily",
        dataset_id="cn_core_index_live",
        provider="akshare",
        symbol="000300",
    )
    pin = VersionPin(
        version_id="akshare-live-cn-core-smoke",
        source_ref="akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
    )

    try:
        rows, used_pin = fetch_timeseries(
            spec,
            pin=pin,
            cache=DatasetCache(base_dir=tmp_path / "dataset-cache"),
            return_used_pin=True,
        )
    except Exception as exc:  # pragma: no cover - depends on external provider reachability
        pytest.skip(f"akshare live provider unavailable: {exc}")

    assert used_pin.version_id == "akshare-live-cn-core-smoke"
    assert rows
    assert rows[-1]["date"]
    assert rows[-1]["close"] > 0


@pytest.mark.smoke
def test_live_yfinance_us_equity_timeseries_smoke(tmp_path):
    try:
        rows, used_pin = fetch_timeseries(
            DatasetSpec(kind="us_equity_daily", dataset_id="us_equity_live", provider="yfinance", symbol="SPY"),
            pin=VersionPin(
                version_id="yfinance-live-spy-smoke",
                source_ref="yfinance://download?start_date=20250303&end_date=20250307",
            ),
            cache=DatasetCache(base_dir=tmp_path / "dataset-cache"),
            return_used_pin=True,
        )
    except Exception as exc:  # pragma: no cover - depends on external provider reachability
        pytest.skip(f"yfinance live provider unavailable: {exc}")
    if not rows:  # pragma: no cover - external provider may return empty data instead of raising
        pytest.skip("yfinance live provider returned empty rows")

    assert used_pin.version_id == "yfinance-live-spy-smoke"
    assert rows
    assert rows[-1]["date"]
    assert rows[-1]["close"] > 0


@pytest.mark.smoke
def test_live_baostock_cn_index_timeseries_smoke(tmp_path):
    try:
        rows, used_pin = fetch_timeseries(
            DatasetSpec(kind="cn_index_daily", dataset_id="cn_index_live", provider="baostock", symbol="sh.000300"),
            pin=VersionPin(
                version_id="baostock-live-cn-core-smoke",
                source_ref="baostock://query_history_k_data_plus?start_date=20250303&end_date=20250307",
            ),
            cache=DatasetCache(base_dir=tmp_path / "dataset-cache"),
            return_used_pin=True,
        )
    except Exception as exc:  # pragma: no cover - depends on external provider reachability
        pytest.skip(f"baostock live provider unavailable: {exc}")

    assert used_pin.version_id == "baostock-live-cn-core-smoke"
    assert rows
    assert rows[-1]["date"]
    assert rows[-1]["close"] > 0


@pytest.mark.smoke
def test_live_market_history_adapter_smoke(tmp_path):
    try:
        payload = fetch_snapshot_from_provider_config(
            {
                "adapter": "market_history",
                "provider_name": "market_history_akshare_tx",
                "dataset_id": "cn_core_history_live",
                "dataset_cache_dir": str(tmp_path / "dataset-cache"),
                "historical_cache_dir": str(tmp_path / "historical-cache"),
                "bucket_series": {
                    "equity_cn": {
                        "provider": "akshare",
                        "kind": "cn_index_daily",
                        "dataset_id": "cn_index_000300",
                        "symbol": "000300",
                        "version_id": "tx-csi300:live",
                        "source_ref": "akshare://stock_zh_index_daily_tx?start_date=20250101&end_date=20250331&series_type=cn_index_daily_tx",
                    },
                    "bond_cn": {
                        "provider": "akshare",
                        "kind": "cn_bond_daily",
                        "dataset_id": "cn_bond_511010",
                        "symbol": "511010",
                        "version_id": "bond-511010:live",
                        "source_ref": "akshare://bond_zh_hs_daily?start_date=20250101&end_date=20250331&series_type=cn_bond_daily",
                    },
                    "gold": {
                        "provider": "akshare",
                        "kind": "cn_gold_spot",
                        "dataset_id": "cn_gold_au9999",
                        "symbol": "Au99.99",
                        "version_id": "gold-au9999:live",
                        "source_ref": "akshare://spot_hist_sge?start_date=20250101&end_date=20250331&series_type=cn_gold_spot",
                    },
                    "satellite": {
                        "provider": "akshare",
                        "kind": "cn_index_daily",
                        "dataset_id": "cn_index_399006",
                        "symbol": "399006",
                        "version_id": "tx-cyb:live",
                        "source_ref": "akshare://stock_zh_index_daily_tx?start_date=20250101&end_date=20250331&series_type=cn_index_daily_tx",
                    },
                },
                "coverage_expectation": ["equity_cn", "bond_cn", "gold", "satellite"],
            },
            workflow_type="monthly",
            account_profile_id="market_history_smoke",
            as_of="2026-04-03T09:30:00Z",
        )
    except Exception as exc:  # pragma: no cover - depends on external provider reachability
        pytest.skip(f"market_history live provider unavailable: {exc}")

    assert payload is not None
    dataset = payload.raw_overrides["market_raw"]["historical_dataset"]
    assert dataset["return_series"]["equity_cn"]
    assert payload.freshness["domains"]["market_raw"]["status"] in {"fresh", "degraded"}
