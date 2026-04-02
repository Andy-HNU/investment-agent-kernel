from __future__ import annotations

from pathlib import Path
import sys
import types

import pandas as pd
import pytest

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries


def _cache(tmp_path: Path) -> DatasetCache:
    return DatasetCache(base_dir=tmp_path / "dataset-cache")


@pytest.mark.contract
def test_fetch_timeseries_akshare_index_contract(monkeypatch, tmp_path):
    def _fake_index_hist(*, symbol: str):
        assert symbol == "sh000300"
        return pd.DataFrame(
            [
                {"日期": "2025-03-03", "开盘": 3900.0, "最高": 3920.0, "最低": 3890.0, "收盘": 3910.0, "成交量": 123456},
                {"日期": "2025-03-04", "开盘": 3910.0, "最高": 3930.0, "最低": 3905.0, "收盘": 3925.0, "成交量": 120000},
            ]
        )

    fake_module = types.SimpleNamespace(stock_zh_index_daily_tx=_fake_index_hist)
    monkeypatch.setitem(sys.modules, "akshare", fake_module)

    rows = fetch_timeseries(
        DatasetSpec(kind="cn_index_daily", dataset_id="cn_index", provider="akshare", symbol="000300"),
        pin=VersionPin(
            version_id="akshare:000300:20250307",
            source_ref="akshare://stock_zh_index_daily_tx?start_date=20250303&end_date=20250307&series_type=cn_index_daily_tx",
        ),
        cache=_cache(tmp_path),
    )

    assert len(rows) == 2
    assert rows[0]["date"] == "2025-03-03"
    assert rows[0]["close"] == 3910.0


@pytest.mark.contract
def test_fetch_timeseries_akshare_tx_path_filters_dates(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        [
            {"date": "2024-12-31", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1, "amount": 100.0},
            {"date": "2025-01-02", "open": 11.0, "high": 11.2, "low": 10.8, "close": 11.1, "amount": 110.0},
            {"date": "2025-03-31", "open": 12.0, "high": 12.2, "low": 11.8, "close": 12.1, "amount": 120.0},
            {"date": "2025-04-01", "open": 13.0, "high": 13.2, "low": 12.8, "close": 13.1, "amount": 130.0},
        ]
    )
    fake_module = types.SimpleNamespace(
        stock_zh_index_daily_tx=lambda symbol: frame,
        index_zh_a_hist=lambda **kwargs: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_module)

    rows = fetch_timeseries(
        DatasetSpec(kind="cn_index_daily", dataset_id="cn_index", provider="akshare", symbol="000300"),
        pin=VersionPin(
            version_id="akshare:000300:20250331",
            source_ref="akshare://stock_zh_index_daily_tx?start_date=20250101&end_date=20250331&series_type=cn_index_daily_tx",
        ),
        cache=_cache(tmp_path),
    )

    assert [row["date"] for row in rows] == ["2025-01-02", "2025-03-31"]


@pytest.mark.contract
def test_fetch_timeseries_akshare_etf_contract(monkeypatch, tmp_path):
    def _fake_etf_hist(*, symbol: str):
        assert symbol == "sh510300"
        return pd.DataFrame(
            [
                {"日期": "2025-03-03", "开盘": 4.10, "最高": 4.12, "最低": 4.08, "收盘": 4.11, "成交量": 9876543},
            ]
        )

    fake_module = types.SimpleNamespace(fund_etf_hist_sina=_fake_etf_hist)
    monkeypatch.setitem(sys.modules, "akshare", fake_module)

    rows = fetch_timeseries(
        DatasetSpec(kind="cn_etf_daily", dataset_id="cn_etf", provider="akshare", symbol="510300"),
        pin=VersionPin(
            version_id="akshare:510300:20250307",
            source_ref="akshare://fund_etf_hist_sina?start_date=20250303&end_date=20250307&series_type=cn_etf_daily",
        ),
        cache=_cache(tmp_path),
    )

    assert len(rows) == 1
    assert rows[0]["close"] == 4.11


@pytest.mark.contract
def test_fetch_timeseries_baostock_index_contract(monkeypatch, tmp_path):
    class _Login:
        error_code = "0"
        error_msg = "success"

    class _Result:
        error_code = "0"

        def __init__(self):
            self._rows = iter(
                [
                    ["2025-01-02", "11.0", "11.2", "10.8", "11.1", "110"],
                    ["2025-01-03", "12.0", "12.2", "11.8", "12.1", "120"],
                ]
            )
            self._current = None

        def next(self):
            try:
                self._current = next(self._rows)
                return True
            except StopIteration:
                return False

        def get_row_data(self):
            return self._current

    fake_module = types.SimpleNamespace(
        login=lambda: _Login(),
        logout=lambda: None,
        query_history_k_data_plus=lambda *args, **kwargs: _Result(),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_module)

    rows = fetch_timeseries(
        DatasetSpec(kind="cn_index_daily", dataset_id="cn_index", provider="baostock", symbol="sh.000300"),
        pin=VersionPin(
            version_id="baostock:sh.000300:20250131",
            source_ref="baostock://query_history_k_data_plus?start_date=20250101&end_date=20250131",
        ),
        cache=_cache(tmp_path),
    )

    assert len(rows) == 2
    assert rows[0]["date"] == "2025-01-02"
    assert rows[0]["close"] == 11.1


@pytest.mark.contract
def test_fetch_timeseries_efinance_contract(monkeypatch, tmp_path):
    class _FakeStock:
        @staticmethod
        def get_quote_history(stock_codes, beg, end, klt, fqt, suppress_error):
            assert stock_codes == "510300"
            assert beg == "20250303"
            assert end == "20250307"
            assert klt == 101
            assert fqt == 1
            assert suppress_error is True
            return pd.DataFrame(
                [
                    {"日期": "2025-03-03", "开盘": 4.10, "最高": 4.12, "最低": 4.08, "收盘": 4.11, "成交量": 1200000},
                ]
            )

    fake_module = types.SimpleNamespace(stock=_FakeStock())
    monkeypatch.setitem(sys.modules, "efinance", fake_module)

    rows = fetch_timeseries(
        DatasetSpec(kind="cn_etf_daily", dataset_id="cn_etf", provider="efinance", symbol="510300"),
        pin=VersionPin(
            version_id="efinance:510300:20250307",
            source_ref="efinance://quote_history?start_date=20250303&end_date=20250307",
        ),
        cache=_cache(tmp_path),
    )

    assert len(rows) == 1
    assert rows[0]["volume"] == 1200000.0


@pytest.mark.contract
def test_fetch_timeseries_yfinance_respects_query_window(monkeypatch, tmp_path):
    class _FakeYF:
        @staticmethod
        def download(ticker, start, end, progress, auto_adjust):
            assert ticker == "SPY"
            assert start == "20250303"
            assert end == "20250307"
            assert progress is False
            assert auto_adjust is False
            return pd.DataFrame(
                {
                    ("Open", "SPY"): [500.0],
                    ("High", "SPY"): [505.0],
                    ("Low", "SPY"): [498.0],
                    ("Close", "SPY"): [503.0],
                    ("Volume", "SPY"): [12345.0],
                },
                index=pd.to_datetime(["2025-03-03"]),
            )

    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)

    rows = fetch_timeseries(
        DatasetSpec(kind="us_etf_daily", dataset_id="us_etf", provider="yfinance", symbol="SPY"),
        pin=VersionPin(
            version_id="yfinance:SPY:20250307",
            source_ref="yfinance://download?start_date=20250303&end_date=20250307",
        ),
        cache=_cache(tmp_path),
    )

    assert len(rows) == 1
    assert rows[0]["close"] == 503.0


@pytest.mark.contract
def test_fetch_timeseries_provider_failure_uses_cached_pin_when_allowed(monkeypatch, tmp_path):
    spec = DatasetSpec(kind="cn_index_daily", dataset_id="cn_index", provider="akshare", symbol="000300")
    cache = _cache(tmp_path)
    cached_pin = VersionPin(
        version_id="akshare:000300:20250307",
        source_ref="akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
    )
    cache.write(
        spec,
        cached_pin,
        [
            {"date": "2025-03-03", "open": 3910.0, "high": 3920.0, "low": 3890.0, "close": 3915.0, "volume": 123456.0},
        ],
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_zh_index_daily_tx=lambda symbol: (_ for _ in ()).throw(ConnectionError("boom"))),
    )

    rows, used_pin = fetch_timeseries(
        spec,
        pin=VersionPin(
            version_id="akshare:000300:20250331",
            source_ref="akshare://stock_zh_index_daily_tx?series_type=cn_index_daily_tx",
        ),
        cache=cache,
        allow_fallback=True,
        return_used_pin=True,
    )

    assert used_pin.version_id == cached_pin.version_id
    assert rows[0]["close"] == 3915.0


@pytest.mark.smoke
def test_fetch_timeseries_akshare_live_smoke(tmp_path):
    try:
        rows = fetch_timeseries(
            DatasetSpec(kind="cn_index_daily", dataset_id="cn_index_live", provider="akshare", symbol="000300"),
            pin=VersionPin(
                version_id="akshare-live:000300:20250307",
                source_ref="akshare://stock_zh_index_daily_tx?start_date=20250303&end_date=20250307&series_type=cn_index_daily_tx",
            ),
            cache=_cache(tmp_path),
        )
    except Exception as exc:  # pragma: no cover - live source dependent
        pytest.skip(f"akshare live unavailable: {exc}")

    assert rows
    assert rows[0]["date"]
    assert rows[0]["close"] > 0.0
