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

    def reset_index(self):
        return self

    def to_dict(self, orient: str):
        assert orient == "records"
        return list(self._rows)


@pytest.mark.contract
def test_yfinance_provider_normalizes_rows_and_writes_cache(tmp_path, monkeypatch):
    def _download(symbol, period, interval, auto_adjust, progress, start=None, end=None):
        assert symbol == "SPY"
        assert period == "10y"
        assert interval == "1d"
        assert auto_adjust is True
        assert progress is False
        assert start is None
        assert end is None
        return _FakeFrame(
            [
                {"Date": "2024-01-02", "Open": "470.0", "High": "472.0", "Low": "468.5", "Close": "471.2", "Volume": "1000000"},
                {"Date": "2024-01-03", "Open": "471.2", "High": "473.5", "Low": "470.8", "Close": "472.6", "Volume": "1200000"},
            ]
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=_download))

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="us_equity_daily", provider="yfinance", symbol="SPY")
    pin = VersionPin(version_id="us-equity-v1", source_ref="yfinance://download?period=10y&interval=1d&auto_adjust=true")

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert rows == [
        {"date": "2024-01-02", "open": 470.0, "high": 472.0, "low": 468.5, "close": 471.2, "volume": 1000000.0},
        {"date": "2024-01-03", "open": 471.2, "high": 473.5, "low": 470.8, "close": 472.6, "volume": 1200000.0},
    ]
    manifest = cache.read_manifest(spec)
    assert manifest is not None
    assert manifest["provider"] == "yfinance"


@pytest.mark.contract
def test_yfinance_provider_missing_optional_library_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace())

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="us_equity_daily", provider="yfinance", symbol="SPY")
    pin = VersionPin(version_id="us-equity-v1", source_ref="yfinance://download")

    with pytest.raises(RuntimeError, match="yfinance provider unavailable"):
        fetch_timeseries(spec, pin=pin, cache=cache)


@pytest.mark.contract
def test_yfinance_provider_falls_back_to_ticker_history_when_download_returns_empty(tmp_path, monkeypatch):
    class _MalformedFrame:
        def reset_index(self):
            return self

        def to_dict(self, orient: str):
            assert orient == "records"
            return [{"Ticker": "SPY"}]

    class _TickerFrame:
        def reset_index(self):
            return self

        def to_dict(self, orient: str):
            assert orient == "records"
            return [
                {"Date": "2024-01-02", "Open": "470.0", "High": "472.0", "Low": "468.5", "Close": "471.2", "Volume": "1000000"},
                {"Date": "2024-01-03", "Open": "471.2", "High": "473.5", "Low": "470.8", "Close": "472.6", "Volume": "1200000"},
            ]

    class _Ticker:
        def history(self, period, interval, auto_adjust, start=None, end=None):
            assert period == "1mo"
            assert interval == "1d"
            assert auto_adjust is True
            assert start is None
            assert end is None
            return _TickerFrame()

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: _MalformedFrame(), Ticker=lambda symbol: _Ticker()),
    )

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="us_equity_daily", provider="yfinance", symbol="SPY")
    pin = VersionPin(version_id="us-equity-v2", source_ref="yfinance://download?period=1mo&interval=1d&auto_adjust=true")

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-02"


@pytest.mark.contract
def test_yfinance_provider_supports_fixed_start_end_window(tmp_path, monkeypatch):
    def _download(symbol, period, interval, auto_adjust, progress, start=None, end=None):
        assert symbol == "SPY"
        assert period == "max"
        assert interval == "1d"
        assert auto_adjust is True
        assert start == "2024-01-02"
        assert end == "2024-01-31"
        return _FakeFrame(
            [
                {"Date": "2024-01-02", "Open": "470.0", "High": "472.0", "Low": "468.5", "Close": "471.2", "Volume": "1000000"},
                {"Date": "2024-01-03", "Open": "471.2", "High": "473.5", "Low": "470.8", "Close": "472.6", "Volume": "1200000"},
            ]
        )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=_download))

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="us_equity_daily", provider="yfinance", symbol="SPY")
    pin = VersionPin(
        version_id="us-equity-fixed-window-v1",
        source_ref="yfinance://download?start=2024-01-02&end=2024-01-31&interval=1d&auto_adjust=true",
    )

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-02"
