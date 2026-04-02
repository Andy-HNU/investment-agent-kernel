from __future__ import annotations

import csv
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

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


def _pin_query_params(pin: VersionPin) -> dict[str, str]:
    source = str(pin.source_ref or "")
    if "://" not in source or "?" not in source:
        return {}
    parsed = urlsplit(source)
    query = parse_qs(parsed.query, keep_blank_values=False)
    return {key: values[-1] for key, values in query.items() if values}


def _pin_route_name(pin: VersionPin) -> str:
    source = str(pin.source_ref or "")
    if "://" not in source:
        return ""
    parsed = urlsplit(source)
    route = parsed.netloc or parsed.path.lstrip("/")
    return str(route or "").strip().lower()


def _retry_fetch(fetcher, *, attempts: int = 3, backoff_seconds: float = 0.5):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetcher()
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(backoff_seconds * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("provider fetch failed without error")


def _normalize_history_frame_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    aliases = {
        "date": ("date", "Date", "日期"),
        "open": ("open", "Open", "开盘"),
        "high": ("high", "High", "最高"),
        "low": ("low", "Low", "最低"),
        "close": ("close", "Close", "收盘"),
        "volume": ("volume", "Volume", "amount", "Amount", "成交量", "成交额"),
    }
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        normalized: dict[str, Any] = {}
        for field, candidates in aliases.items():
            for candidate in candidates:
                if candidate in row:
                    normalized[field] = row[candidate]
                    break
        if "date" not in normalized or "close" not in normalized:
            continue
        normalized.setdefault("open", normalized["close"])
        normalized.setdefault("high", normalized["close"])
        normalized.setdefault("low", normalized["close"])
        normalized.setdefault("volume", 0.0)
        date_text = str(normalized["date"])[:10]
        if len(date_text) == 8 and date_text.isdigit():
            date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
        rows.append(
            {
                "date": date_text,
                "open": float(normalized["open"]),
                "high": float(normalized["high"]),
                "low": float(normalized["low"]),
                "close": float(normalized["close"]),
                "volume": float(normalized["volume"]),
            }
        )
    return HistoryBar.coerce_many(rows)


def _filter_frame_by_date(frame: Any, *, start_date: str | None, end_date: str | None) -> Any:
    if frame is None or getattr(frame, "empty", True):
        return frame
    if "date" in frame.columns:
        date_column = "date"
    elif "Date" in frame.columns:
        date_column = "Date"
    elif "日期" in frame.columns:
        date_column = "日期"
    else:
        return frame
    normalized = frame.copy()
    normalized[date_column] = normalized[date_column].astype(str).str.replace("-", "", regex=False)
    if start_date:
        normalized = normalized[normalized[date_column] >= start_date]
    if end_date:
        normalized = normalized[normalized[date_column] <= end_date]
    return normalized


def _normalize_yfinance_frame(frame: Any) -> Any:
    if frame is None or not hasattr(frame, "columns"):
        return frame
    if getattr(frame.columns, "nlevels", 1) <= 1:
        return frame
    normalized = frame.copy()
    flattened: list[str] = []
    for column in normalized.columns.to_flat_index():
        if not isinstance(column, tuple):
            flattened.append(str(column))
            continue
        names = [str(item) for item in column if str(item)]
        field = next(
            (
                item
                for item in names
                if item.lower() in {"open", "high", "low", "close", "adj close", "volume", "date"}
            ),
            names[0],
        )
        flattened.append(field)
    normalized.columns = flattened
    return normalized


def _normalize_akshare_cn_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().lower()
    if raw.startswith(("sh", "sz")):
        return raw
    if raw.startswith(("000", "001", "510", "511", "512", "513", "515", "518", "588", "600", "601", "603", "605")):
        return f"sh{raw}"
    return f"sz{raw}"


def _slice_rows_by_window(rows: list[dict[str, Any]], *, start_date: str, end_date: str) -> list[dict[str, Any]]:
    if not start_date and not end_date:
        return rows
    return [
        row
        for row in rows
        if (not start_date or row["date"].replace("-", "") >= start_date)
        and (not end_date or row["date"].replace("-", "") <= end_date)
    ]


def _fetch_akshare(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("akshare provider unavailable - install akshare") from exc
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("akshare provider requires spec.symbol")
    params = _pin_query_params(pin)
    start_date = params.get("start_date", "19900101")
    end_date = params.get("end_date", "20500101")
    period = params.get("period", "daily")
    adjust = params.get("adjust", "")
    series_type = params.get("series_type", spec.kind)
    route_name = _pin_route_name(pin)
    normalized_symbol = _normalize_akshare_cn_symbol(symbol)

    if route_name == "fund_etf_hist_em":
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(
                lambda: ak.fund_etf_hist_em(
                    symbol=symbol,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust or "qfq",
                )
            )
        return _normalize_history_frame_rows(frame)

    if route_name == "index_zh_a_hist":
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(
                lambda: ak.index_zh_a_hist(
                    symbol=symbol,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return _normalize_history_frame_rows(frame)

    if route_name == "bond_zh_hs_daily" or series_type in {"cn_bond_daily", "bond_daily"}:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(lambda: ak.bond_zh_hs_daily(symbol=normalized_symbol))
        return _slice_rows_by_window(_normalize_history_frame_rows(frame), start_date=start_date, end_date=end_date)

    if route_name == "spot_hist_sge" or series_type in {"cn_gold_spot", "gold_spot"}:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(lambda: ak.spot_hist_sge(symbol=symbol))
        return _slice_rows_by_window(_normalize_history_frame_rows(frame), start_date=start_date, end_date=end_date)

    if series_type in {"cn_etf_daily", "etf_daily", "fund_etf_daily"}:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(lambda: ak.fund_etf_hist_sina(symbol=normalized_symbol))
        frame = _filter_frame_by_date(frame, start_date=start_date, end_date=end_date)
        return _normalize_history_frame_rows(frame)

    if route_name in {"stock_zh_index_daily_tx", ""} and series_type in {
        "cn_index_daily_tx",
        "cn_index_daily",
        "index_daily",
        "broad_style_industry_index",
    }:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(lambda: ak.stock_zh_index_daily_tx(symbol=normalized_symbol))
        frame = _filter_frame_by_date(frame, start_date=start_date, end_date=end_date)
        return _normalize_history_frame_rows(frame)

    if series_type in {"cn_index_daily_em", "index_daily_em"}:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            frame = _retry_fetch(
                lambda: ak.stock_zh_index_daily_em(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return _normalize_history_frame_rows(frame)

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        frame = _retry_fetch(
            lambda: ak.index_zh_a_hist(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return _normalize_history_frame_rows(frame)


def _fetch_efinance(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import efinance as ef  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("efinance provider unavailable - install efinance") from exc
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("efinance provider requires spec.symbol")
    params = _pin_query_params(pin)
    start_date = params.get("start_date", "19900101")
    end_date = params.get("end_date", "20500101")
    frame = _retry_fetch(
        lambda: ef.stock.get_quote_history(
            symbol,
            beg=start_date,
            end=end_date,
            klt=int(params.get("klt", "101")),
            fqt=int(params.get("fqt", "1")),
            suppress_error=True,
        )
    )
    return _normalize_history_frame_rows(frame)


def _fetch_baostock(spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]]:
    try:
        import baostock as bs  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("baostock provider unavailable - install baostock") from exc
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("baostock provider requires spec.symbol")
    params = _pin_query_params(pin)
    start_date = params.get("start_date", "1990-01-01").replace("/", "-")
    end_date = params.get("end_date", "2050-01-01").replace("/", "-")
    if len(start_date) == 8 and start_date.isdigit():
        start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    if len(end_date) == 8 and end_date.isdigit():
        end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        login_result = bs.login()
    if str(getattr(login_result, "error_code", "")) != "0":
        raise RuntimeError(f"baostock login failed: {getattr(login_result, 'error_msg', 'unknown error')}")
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = _retry_fetch(
                lambda: bs.query_history_k_data_plus(
                    symbol,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",
                )
            )
        if str(getattr(result, "error_code", "")) != "0":
            raise RuntimeError(f"baostock query failed: {getattr(result, 'error_msg', 'unknown error')}")
        rows: list[dict[str, Any]] = []
        while result.next():
            date_text, open_px, high_px, low_px, close_px, volume = result.get_row_data()
            rows.append(
                {
                    "date": str(date_text),
                    "open": float(open_px),
                    "high": float(high_px),
                    "low": float(low_px),
                    "close": float(close_px),
                    "volume": float(volume),
                }
            )
        return HistoryBar.coerce_many(rows)
    finally:
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                bs.logout()
        except Exception:  # pragma: no cover
            pass


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
        last_error: Exception | None = None
        try:
            rows = _fetch_csv(spec, pin)
        except Exception as exc:
            rows = None
            last_error = exc
        if rows is None and allow_fallback:
            latest = cache.latest_cached_pin(spec)
            if latest is not None:
                cached = cache.read(spec, latest)
                if cached is not None:
                    return (cached, latest) if return_used_pin else cached
        if rows is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("csv provider returned no rows")
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    if spec.provider == "akshare":
        rows = None
        last_error: Exception | None = None
        try:
            rows = _fetch_akshare(spec, pin)
        except Exception as exc:
            rows = None
            last_error = exc
        if rows is None and allow_fallback:
            latest = cache.latest_cached_pin(spec)
            if latest is not None:
                cached = cache.read(spec, latest)
                if cached is not None:
                    return (cached, latest) if return_used_pin else cached
        if rows is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("akshare provider returned no rows")
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    if spec.provider == "efinance":
        rows = None
        last_error: Exception | None = None
        try:
            rows = _fetch_efinance(spec, pin)
        except Exception as exc:
            rows = None
            last_error = exc
        if rows is None and allow_fallback:
            latest = cache.latest_cached_pin(spec)
            if latest is not None:
                cached = cache.read(spec, latest)
                if cached is not None:
                    return (cached, latest) if return_used_pin else cached
        if rows is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("efinance provider returned no rows")
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    if spec.provider == "baostock":
        rows = None
        last_error: Exception | None = None
        try:
            rows = _fetch_baostock(spec, pin)
        except Exception as exc:
            rows = None
            last_error = exc
        if rows is None and allow_fallback:
            latest = cache.latest_cached_pin(spec)
            if latest is not None:
                cached = cache.read(spec, latest)
                if cached is not None:
                    return (cached, latest) if return_used_pin else cached
        if rows is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("baostock provider returned no rows")
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
        params = _pin_query_params(pin)
        df = _retry_fetch(
            lambda: yf.download(
                ticker,
                start=params.get("start_date"),
                end=params.get("end_date"),
                progress=False,
                auto_adjust=False,
            )
        )
        df = _normalize_yfinance_frame(df)
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
