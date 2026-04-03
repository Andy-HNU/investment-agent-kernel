from __future__ import annotations

from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers._history_common import cache_rows, import_optional_module, normalize_history_rows, parse_source_ref


_ALIASES = {
    "date": ("date", "Date"),
    "open": ("open", "Open"),
    "high": ("high", "High"),
    "low": ("low", "Low"),
    "close": ("close", "Close"),
    "volume": ("volume", "Volume"),
}


def _has_required_ohlc(raw_rows: list[dict[str, Any]]) -> bool:
    if not raw_rows:
        return False
    sample = dict(raw_rows[0])
    required = ("date", "open", "high", "low", "close")
    for field in required:
        if not any(sample.get(alias) not in (None, "") for alias in _ALIASES[field]):
            return False
    return True


def fetch_yfinance_history(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool = False,
    return_used_pin: bool = False,
) -> Any:
    yf = import_optional_module("yfinance", missing_message="yfinance provider unavailable - install yfinance")
    download = getattr(yf, "download", None)
    if download is None:
        raise RuntimeError("yfinance provider unavailable - install yfinance")
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("yfinance provider requires spec.symbol")
    _, params = parse_source_ref(pin.source_ref)
    start = params.get("start")
    end = params.get("end")
    period = params.get("period", "10y")
    if start or end:
        period = params.get("period", "max")
    raw_frame = download(
        symbol,
        period=period,
        interval=params.get("interval", "1d"),
        auto_adjust=str(params.get("auto_adjust", "true")).lower() == "true",
        progress=False,
        start=start,
        end=end,
    )
    if hasattr(raw_frame, "reset_index"):
        raw_frame = raw_frame.reset_index()
    if hasattr(raw_frame, "to_dict"):
        raw_rows = raw_frame.to_dict("records")
    else:
        raw_rows = list(raw_frame or [])
    if not _has_required_ohlc(raw_rows):
        ticker_factory = getattr(yf, "Ticker", None)
        if ticker_factory is not None:
            ticker = ticker_factory(symbol)
            history = ticker.history(
                period=period,
                interval=params.get("interval", "1d"),
                auto_adjust=str(params.get("auto_adjust", "true")).lower() == "true",
                start=start,
                end=end,
            )
            if hasattr(history, "reset_index"):
                history = history.reset_index()
            if hasattr(history, "to_dict"):
                raw_rows = history.to_dict("records")
            else:
                raw_rows = list(history or [])
    rows = normalize_history_rows(raw_rows, aliases=_ALIASES)
    return cache_rows(spec, pin=pin, cache=cache, rows=rows, allow_fallback=allow_fallback, return_used_pin=return_used_pin)


__all__ = ["fetch_yfinance_history"]
