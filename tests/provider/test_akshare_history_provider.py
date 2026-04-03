from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries


class _FakeFrame:
    def __init__(self, rows):
        self._rows = list(rows)

    def to_dict(self, orient: str):
        assert orient == "records"
        return list(self._rows)


@pytest.mark.contract
def test_akshare_provider_normalizes_rows_and_writes_cache(tmp_path, monkeypatch):
    def _stock_zh_a_hist(**kwargs):
        assert kwargs["symbol"] == "600000"
        assert kwargs["period"] == "daily"
        assert kwargs["start_date"] == "20240101"
        assert kwargs["end_date"] == "20240103"
        assert kwargs["adjust"] == "qfq"
        return _FakeFrame(
            [
                {"日期": "2024-01-02", "开盘": "10.1", "最高": "10.5", "最低": "10.0", "收盘": "10.4", "成交量": "100000"},
                {"日期": "2024-01-03", "开盘": "10.4", "最高": "10.6", "最低": "10.2", "收盘": "10.5", "成交量": "120000"},
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=_stock_zh_a_hist))

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="akshare", symbol="600000")
    pin = VersionPin(
        version_id="cn-a-share-v1",
        source_ref="akshare://stock_zh_a_hist?start_date=20240101&end_date=20240103&adjust=qfq",
    )

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert rows == [
        {"date": "2024-01-02", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4, "volume": 100000.0},
        {"date": "2024-01-03", "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 120000.0},
    ]
    manifest = cache.read_manifest(spec)
    assert manifest is not None
    assert manifest["version_id"] == "cn-a-share-v1"
    assert manifest["provider"] == "akshare"


@pytest.mark.contract
def test_akshare_provider_missing_optional_library_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="akshare", symbol="600000")
    pin = VersionPin(version_id="cn-a-share-v1", source_ref="akshare://stock_zh_a_hist")

    with pytest.raises(RuntimeError, match="akshare provider unavailable"):
        fetch_timeseries(spec, pin=pin, cache=cache)


@pytest.mark.contract
def test_akshare_provider_filters_kwargs_for_alternative_endpoint(tmp_path, monkeypatch):
    def _stock_zh_a_hist_tx(symbol, start_date, end_date, adjust):
        assert symbol == "sh600000"
        assert start_date == "20240101"
        assert end_date == "20240103"
        assert adjust == "qfq"
        return _FakeFrame(
            [
                {"date": "2024-01-02", "open": "10.1", "high": "10.5", "low": "10.0", "close": "10.4", "amount": "100000"},
                {"date": "2024-01-03", "open": "10.4", "high": "10.6", "low": "10.2", "close": "10.5", "amount": "120000"},
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist_tx=_stock_zh_a_hist_tx))

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="akshare", symbol="sh600000")
    pin = VersionPin(
        version_id="cn-a-share-tx-v1",
        source_ref="akshare://stock_zh_a_hist_tx?start_date=20240101&end_date=20240103&adjust=qfq",
    )

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert rows[0]["date"] == "2024-01-02"
    assert rows[-1]["close"] == 10.5
    assert rows[-1]["volume"] == 0.0


@pytest.mark.contract
def test_akshare_provider_uses_latest_cached_rows_when_live_fetch_raises_and_allow_fallback(tmp_path, monkeypatch):
    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="akshare", symbol="600000")
    good_pin = VersionPin(
        version_id="cn-a-share-v1",
        source_ref="akshare://stock_zh_a_hist?start_date=20240101&end_date=20240103&adjust=qfq",
    )

    def _good_fetcher(**kwargs):
        return _FakeFrame(
            [
                {"日期": "2024-01-02", "开盘": "10.1", "最高": "10.5", "最低": "10.0", "收盘": "10.4", "成交量": "100000"},
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=_good_fetcher))
    rows = fetch_timeseries(spec, pin=good_pin, cache=cache)
    assert rows[0]["close"] == 10.4

    def _broken_fetcher(**kwargs):
        raise RuntimeError("network boom")

    broken_pin = VersionPin(
        version_id="cn-a-share-v2",
        source_ref="akshare://stock_zh_a_hist?start_date=20240104&end_date=20240105&adjust=qfq",
    )
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=_broken_fetcher))

    fallback_rows, used_pin = fetch_timeseries(
        spec,
        pin=broken_pin,
        cache=cache,
        allow_fallback=True,
        return_used_pin=True,
    )

    assert fallback_rows == rows
    assert used_pin.version_id == good_pin.version_id
