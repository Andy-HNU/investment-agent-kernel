from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    if not rows:
        raise ValueError("need at least one row")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


@pytest.mark.contract
def test_csv_provider_with_version_pinning_and_cache(tmp_path):
    # Prepare fixture data
    csv_path = _write_csv(
        tmp_path / "AAPL_sample.csv",
        [
            {"date": "2024-03-28", "open": 172.0, "high": 175.0, "low": 171.2, "close": 174.1, "volume": 120000000},
            {"date": "2024-03-29", "open": 174.2, "high": 176.8, "low": 173.6, "close": 176.2, "volume": 98000000},
        ],
    )

    # Write tests against wished-for API
    from shared.datasets.types import DatasetSpec, VersionPin
    from shared.datasets.cache import DatasetCache
    from shared.providers.timeseries import fetch_timeseries

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="equity_ohlcv", provider="csv", symbol="AAPL")
    pin = VersionPin(version_id="v1-fixture", source_ref=str(csv_path))

    # First fetch populates cache manifest and returns rows
    rows_v1 = fetch_timeseries(spec, pin=pin, cache=cache)
    assert rows_v1 and isinstance(rows_v1[0], dict)
    manifest = cache.read_manifest(spec)
    assert manifest is not None
    assert manifest["version_id"] == pin.version_id
    assert manifest["provider"] == "csv"

    # Second fetch with same pin returns identical data (replay)
    rows_v1b = fetch_timeseries(spec, pin=pin, cache=cache)
    assert rows_v1b == rows_v1

    # Update underlying file, request a new pin, data changes
    _write_csv(
        csv_path,
        [
            {"date": "2024-03-28", "open": 172.0, "high": 175.0, "low": 171.2, "close": 174.1, "volume": 120000000},
            {"date": "2024-03-29", "open": 174.2, "high": 176.8, "low": 173.6, "close": 176.2, "volume": 98000000},
            {"date": "2024-04-01", "open": 175.1, "high": 177.0, "low": 174.4, "close": 176.5, "volume": 101000000},
        ],
    )
    new_pin = VersionPin(version_id="v2-fixture", source_ref=str(csv_path))
    rows_v2 = fetch_timeseries(spec, pin=new_pin, cache=cache)
    assert len(rows_v2) == 3
    assert rows_v2[-1]["date"] == "2024-04-01"

    # Stale/fallback: ask for a new pin, but make fetch fail; expect fallback to latest cached version
    broken_pin = VersionPin(version_id="v3-broken", source_ref=str(csv_path.with_suffix(".missing.csv")))
    rows_fallback, used_pin = fetch_timeseries(spec, pin=broken_pin, cache=cache, allow_fallback=True, return_used_pin=True)
    assert rows_fallback == rows_v2
    assert used_pin.version_id == new_pin.version_id


@pytest.mark.contract
def test_manifest_schema_and_row_shape(tmp_path):
    csv_path = _write_csv(
        tmp_path / "AAPL_sample.csv",
        [
            {"date": "2024-03-28", "open": 172.0, "high": 175.0, "low": 171.2, "close": 174.1, "volume": 120000000},
        ],
    )
    from shared.datasets.types import DatasetSpec, VersionPin, HistoryBar
    from shared.datasets.cache import DatasetCache
    from shared.providers.timeseries import fetch_timeseries

    cache = DatasetCache(base_dir=tmp_path / "cache")
    spec = DatasetSpec(kind="timeseries", dataset_id="equity_ohlcv", provider="csv", symbol="AAPL")
    pin = VersionPin(version_id="v1-fixture", source_ref=str(csv_path))

    rows = fetch_timeseries(spec, pin=pin, cache=cache)
    assert rows
    first = HistoryBar.from_mapping(rows[0])
    assert asdict(first) == {
        "date": "2024-03-28",
        "open": 172.0,
        "high": 175.0,
        "low": 171.2,
        "close": 174.1,
        "volume": 120000000.0,
    }

