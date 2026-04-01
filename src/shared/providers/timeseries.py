from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin, HistoryBar


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
        rows = None
        try:
            rows = _fetch_csv(spec, pin)
        except Exception:
            rows = None
        if rows is None and allow_fallback:
            latest = cache.latest_cached_pin(spec)
            if latest is not None:
                cached = cache.read(spec, latest)
                if cached is not None:
                    return (cached, latest) if return_used_pin else cached
        if rows is None:
            raise
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    # Optional yfinance path (graceful): if unavailable, raise clear error
    if spec.provider == "yfinance":
        try:
            import yfinance as yf  # type: ignore
        except Exception as exc:  # pragma: no cover (not installed in CI)
            raise RuntimeError("yfinance provider unavailable - install yfinance") from exc
        ticker = spec.symbol or ""
        if not ticker:
            raise ValueError("yfinance provider requires spec.symbol")
        df = yf.download(ticker, progress=False)
        rows = [
            {
                "date": str(idx.date()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]
        rows = HistoryBar.coerce_many(rows)
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows

    raise ValueError(f"unsupported timeseries provider: {spec.provider}")


__all__ = ["fetch_timeseries"]

