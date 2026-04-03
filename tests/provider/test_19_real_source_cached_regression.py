from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, HistoryBar, VersionPin


_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "real_source"


@pytest.mark.contract
@pytest.mark.parametrize(
    ("fixture_name", "provider", "dataset_id", "symbol"),
    [
        ("akshare_sh510300_fund_etf_hist_sina_full.json", "akshare", "cn_equity_core_daily", "sh510300"),
        ("akshare_sh511010_fund_etf_hist_sina_full.json", "akshare", "cn_bond_core_daily", "sh511010"),
        ("akshare_sh518880_fund_etf_hist_sina_full.json", "akshare", "cn_gold_daily", "sh518880"),
        ("akshare_sz159915_fund_etf_hist_sina_full.json", "akshare", "cn_satellite_daily", "sz159915"),
        ("baostock_sh600000_daily_20240102_20240110.json", "baostock", "cn_equity_daily", "sh.600000"),
        ("akshare_sh600000_tx_20240102_20240110.json", "akshare", "cn_equity_daily", "sh600000"),
        ("yfinance_SPY_20240102_20240329.json", "yfinance", "us_equity_daily", "SPY"),
    ],
)
def test_real_source_cached_history_fixture_roundtrip(tmp_path, fixture_name, provider, dataset_id, symbol):
    payload = json.loads((_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
    rows = list(payload["rows"])
    assert rows, "real-source fixture must contain at least one row"

    first = HistoryBar.from_mapping(rows[0])
    assert first.date
    assert first.close > 0.0

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id=dataset_id, provider=provider, symbol=symbol)
    pin = VersionPin(version_id=payload["version_id"], source_ref=payload["source_ref"])

    cache.write(spec, pin, rows)
    reloaded = cache.read(spec, pin)
    manifest = cache.read_manifest(spec)

    assert reloaded == rows
    assert manifest is not None
    assert manifest["provider"] == provider
    assert manifest["version_id"] == payload["version_id"]


@pytest.mark.contract
def test_build_real_source_market_snapshot_uses_cached_real_source_bucket_history():
    from snapshot_ingestion.real_source_market import build_real_source_market_snapshot

    snapshot = build_real_source_market_snapshot(as_of="2026-04-04T00:00:00Z")

    assert snapshot.provider_name == "real_source_market_history"
    metadata = snapshot.historical_dataset_metadata
    assert metadata["source_name"] == "real_source_market_history"
    assert metadata["frequency"] == "daily"
    assert metadata["lookback_days"] >= 252
    assert metadata["coverage_status"] in {"verified", "cycle_insufficient"}
    assert set(snapshot.source_versions) == {"equity_cn", "bond_cn", "gold", "satellite"}
