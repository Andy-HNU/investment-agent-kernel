from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries


class _FakeQueryResult:
    def __init__(self, rows):
        self.error_code = "0"
        self.error_msg = ""
        self.fields = ["date", "open", "high", "low", "close", "volume"]
        self._rows = list(rows)
        self._idx = -1

    def next(self):
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self):
        return list(self._rows[self._idx])


@pytest.mark.contract
def test_baostock_provider_normalizes_rows_and_logs_out(tmp_path, monkeypatch):
    state = {"logged_out": False}

    def _login():
        return SimpleNamespace(error_code="0", error_msg="")

    def _logout():
        state["logged_out"] = True

    def _query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag):
        assert code == "sh.600000"
        assert "volume" in fields
        assert start_date == "2024-01-02"
        assert end_date == "2024-01-03"
        assert frequency == "d"
        assert adjustflag == "2"
        return _FakeQueryResult(
            [
                ["2024-01-02", "10.1", "10.5", "10.0", "10.4", "100000"],
                ["2024-01-03", "10.4", "10.6", "10.2", "10.5", "120000"],
            ]
        )

    fake_module = SimpleNamespace(
        login=_login,
        logout=_logout,
        query_history_k_data_plus=_query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_module)

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="baostock", symbol="sh.600000")
    pin = VersionPin(
        version_id="cn-a-share-v1",
        source_ref="baostock://query_history_k_data_plus?start_date=2024-01-02&end_date=2024-01-03&adjustflag=2",
    )

    rows = fetch_timeseries(spec, pin=pin, cache=cache)

    assert rows == [
        {"date": "2024-01-02", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4, "volume": 100000.0},
        {"date": "2024-01-03", "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 120000.0},
    ]
    assert state["logged_out"] is True


@pytest.mark.contract
def test_baostock_provider_missing_optional_library_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "baostock", SimpleNamespace())

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="a_share_daily", provider="baostock", symbol="sh.600000")
    pin = VersionPin(version_id="cn-a-share-v1", source_ref="baostock://query_history_k_data_plus")

    with pytest.raises(RuntimeError, match="baostock provider unavailable"):
        fetch_timeseries(spec, pin=pin, cache=cache)
