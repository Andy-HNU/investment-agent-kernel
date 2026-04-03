from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin, HistoryBar
from shared.providers._history_common import read_cached_rows
from shared.providers.akshare_history import fetch_akshare_history
from shared.providers.baostock_history import fetch_baostock_history
from shared.providers.yfinance_history import fetch_yfinance_history


def _fetch_csv(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    source = pin.source_ref
    if not source:
        raise ValueError("csv provider requires VersionPin.source_ref to point to a CSV file")
    path = Path(source)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "date": str(r.get("date")),
                "open": float(r.get("open")),
                "high": float(r.get("high")),
                "low": float(r.get("low")),
                "close": float(r.get("close")),
                "volume": float(r.get("volume")),
            })
    return HistoryBar.coerce_many(rows)


def fetch_timeseries(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool = False,
    return_used_pin: bool = False,
):
    if spec.provider == "csv":
        try:
            rows = _fetch_csv(spec, pin)
        except Exception:
            if allow_fallback:
                cached = read_cached_rows(spec, cache=cache, return_used_pin=return_used_pin)
                if cached is not None:
                    return cached
            raise
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    if spec.provider == "akshare":
        try:
            return fetch_akshare_history(
                spec,
                pin=pin,
                cache=cache,
                allow_fallback=allow_fallback,
                return_used_pin=return_used_pin,
            )
        except Exception:
            if allow_fallback:
                cached = read_cached_rows(spec, cache=cache, return_used_pin=return_used_pin)
                if cached is not None:
                    return cached
            raise
    if spec.provider == "baostock":
        try:
            return fetch_baostock_history(
                spec,
                pin=pin,
                cache=cache,
                allow_fallback=allow_fallback,
                return_used_pin=return_used_pin,
            )
        except Exception:
            if allow_fallback:
                cached = read_cached_rows(spec, cache=cache, return_used_pin=return_used_pin)
                if cached is not None:
                    return cached
            raise
    if spec.provider == "yfinance":
        try:
            return fetch_yfinance_history(
                spec,
                pin=pin,
                cache=cache,
                allow_fallback=allow_fallback,
                return_used_pin=return_used_pin,
            )
        except Exception:
            if allow_fallback:
                cached = read_cached_rows(spec, cache=cache, return_used_pin=return_used_pin)
                if cached is not None:
                    return cached
            raise

    raise ValueError(f"unsupported timeseries provider: {spec.provider}")


__all__ = ["fetch_timeseries"]
