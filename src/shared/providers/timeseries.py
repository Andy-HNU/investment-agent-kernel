from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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


def _window_from_source_ref(pin: VersionPin) -> tuple[str | None, str | None]:
    source = str(pin.source_ref or "")
    if not source:
        return None, None
    parsed = urlparse(source)
    query = parse_qs(parsed.query)
    start = query.get("start", [None])[0]
    end = query.get("end", [None])[0]
    return (str(start) if start else None, str(end) if end else None)


def _load_cached_fallback(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool,
    return_used_pin: bool,
):
    if not allow_fallback:
        return None
    requested_start, requested_end = _window_from_source_ref(pin)
    for candidate in reversed(cache.cached_pins(spec)):
        candidate_start, candidate_end = _window_from_source_ref(candidate)
        if requested_start != candidate_start or requested_end != candidate_end:
            continue
        cached = cache.read(spec, candidate)
        if cached is None:
            continue
        return (cached, candidate) if return_used_pin else cached
    return None


def _inclusive_yfinance_end(end: str | None) -> str | None:
    if not end:
        return None
    return (date.fromisoformat(end) + timedelta(days=1)).isoformat()


def _normalize_provider_error(spec: DatasetSpec, exc: Exception) -> RuntimeError:
    text = f"{type(exc).__name__}: {exc}"
    lower = text.lower()
    if spec.provider == "akshare":
        if "remote end closed connection without response" in lower or "remotedisconnected" in lower:
            return RuntimeError("historical_provider_unavailable:eastmoney_history_endpoint_closed")
        return RuntimeError(f"historical_provider_unavailable:akshare:{exc}")
    if spec.provider == "yfinance":
        if "rate limited" in lower or "yfratelimiterror" in lower:
            return RuntimeError("historical_provider_unavailable:yfinance_rate_limited")
        if "empty_dataset" in lower:
            return RuntimeError("historical_provider_unavailable:yfinance_empty_dataset")
        return RuntimeError(f"historical_provider_unavailable:yfinance:{exc}")
    if spec.provider == "baostock":
        if "empty_dataset" in lower:
            return RuntimeError("historical_provider_unavailable:baostock_empty_or_unsupported_symbol")
        return RuntimeError(f"historical_provider_unavailable:baostock:{exc}")
    return RuntimeError(f"historical_provider_unavailable:{spec.provider}:{exc}")


def _coerce_yfinance_columns(df: Any, ticker: str) -> Any:
    columns = getattr(df, "columns", None)
    if columns is not None and getattr(columns, "nlevels", 1) > 1:
        try:
            return df.xs(ticker, axis=1, level=-1)
        except Exception:
            return df.droplevel(-1, axis=1)
    return df


def _fetch_yfinance(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # pragma: no cover (not installed in CI)
        raise RuntimeError("yfinance provider unavailable - install yfinance") from exc
    ticker = spec.symbol or ""
    if not ticker:
        raise ValueError("yfinance provider requires spec.symbol")
    start, end = _window_from_source_ref(pin)
    df = yf.download(
        ticker,
        start=start,
        end=_inclusive_yfinance_end(end),
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError("yfinance_empty_dataset")
    df = _coerce_yfinance_columns(df, ticker)
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
    return HistoryBar.coerce_many(rows)


def _normalize_akshare_symbol(symbol: str) -> str:
    value = symbol.strip()
    if value.lower().startswith(("sh.", "sz.")):
        return value.split(".", 1)[1]
    if value.upper().endswith((".SS", ".SZ")):
        return value.split(".", 1)[0]
    return value


def _fetch_akshare(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("akshare provider unavailable - install akshare") from exc
    symbol = _normalize_akshare_symbol(spec.symbol or "")
    if not symbol:
        raise ValueError("akshare provider requires spec.symbol")
    start, end = _window_from_source_ref(pin)
    start_date = (start or "").replace("-", "")
    end_date = (end or "").replace("-", "")
    if symbol.startswith(("5", "1")):
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
    else:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
    if df is None or df.empty:
        raise RuntimeError("akshare_empty_dataset")
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "date": str(row.get("日期")),
                "open": float(row.get("开盘")),
                "high": float(row.get("最高")),
                "low": float(row.get("最低")),
                "close": float(row.get("收盘")),
                "volume": float(row.get("成交量") or 0.0),
            }
        )
    return HistoryBar.coerce_many(rows)


def _normalize_baostock_symbol(symbol: str) -> str:
    value = symbol.strip()
    if value.lower().startswith(("sh.", "sz.")):
        return value.lower()
    if value.upper().endswith(".SS"):
        return f"sh.{value.split('.', 1)[0]}"
    if value.upper().endswith(".SZ"):
        return f"sz.{value.split('.', 1)[0]}"
    if value.startswith("6"):
        return f"sh.{value}"
    return f"sz.{value}"


def _fetch_baostock(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import baostock as bs  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("baostock provider unavailable - install baostock") from exc
    symbol = _normalize_baostock_symbol(spec.symbol or "")
    if not symbol:
        raise ValueError("baostock provider requires spec.symbol")
    start, end = _window_from_source_ref(pin)
    lg = bs.login()
    if getattr(lg, "error_code", "1") != "0":
        raise RuntimeError(f"baostock_login_failed:{getattr(lg, 'error_msg', 'unknown')}")
    try:
        rs = bs.query_history_k_data_plus(
            symbol,
            "date,open,high,low,close,volume",
            start_date=start or "",
            end_date=end or "",
            frequency="d",
            adjustflag="2",
        )
        rows: list[dict[str, Any]] = []
        while getattr(rs, "error_code", "1") == "0" and rs.next():
            date, open_, high, low, close, volume = rs.get_row_data()
            rows.append(
                {
                    "date": date,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume or 0.0),
                }
            )
        if not rows:
            raise RuntimeError("baostock_empty_dataset")
        return HistoryBar.coerce_many(rows)
    finally:
        try:
            bs.logout()
        except Exception:
            pass


def fetch_timeseries(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool = False,
    return_used_pin: bool = False,
):
    try:
        if spec.provider == "csv":
            rows = _fetch_csv(spec, pin)
        elif spec.provider == "yfinance":
            rows = _fetch_yfinance(spec, pin)
        elif spec.provider == "akshare":
            rows = _fetch_akshare(spec, pin)
        elif spec.provider == "baostock":
            rows = _fetch_baostock(spec, pin)
        else:
            raise ValueError(f"unsupported timeseries provider: {spec.provider}")
    except Exception as exc:
        fallback = _load_cached_fallback(
            spec,
            pin=pin,
            cache=cache,
            allow_fallback=allow_fallback,
            return_used_pin=return_used_pin,
        )
        if fallback is not None:
            return fallback
        if isinstance(exc, ValueError) and str(exc).startswith("unsupported timeseries provider:"):
            raise
        raise _normalize_provider_error(spec, exc) from exc

    cache.write(spec, pin, rows)
    return (rows, pin) if return_used_pin else rows


__all__ = ["fetch_timeseries"]
