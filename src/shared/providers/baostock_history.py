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


def fetch_baostock_history(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool = False,
    return_used_pin: bool = False,
) -> Any:
    bs = import_optional_module("baostock", missing_message="baostock provider unavailable - install baostock")
    if not hasattr(bs, "login") or not hasattr(bs, "logout") or not hasattr(bs, "query_history_k_data_plus"):
        raise RuntimeError("baostock provider unavailable - install baostock")
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("baostock provider requires spec.symbol")
    _, params = parse_source_ref(pin.source_ref)
    fields = params.get("fields", "date,open,high,low,close,volume")
    login_result = bs.login()
    if getattr(login_result, "error_code", "") != "0":
        raise RuntimeError(f"baostock login failed: {getattr(login_result, 'error_msg', '')}")
    try:
        query = bs.query_history_k_data_plus(
            symbol,
            fields=fields,
            start_date=params.get("start_date", ""),
            end_date=params.get("end_date", ""),
            frequency=params.get("frequency", "d"),
            adjustflag=params.get("adjustflag", "2"),
        )
        if getattr(query, "error_code", "") != "0":
            raise RuntimeError(f"baostock query failed: {getattr(query, 'error_msg', '')}")
        raw_rows: list[dict[str, Any]] = []
        field_names = list(getattr(query, "fields", []) or [])
        while query.next():
            values = list(query.get_row_data())
            raw_rows.append(dict(zip(field_names, values, strict=True)))
    finally:
        bs.logout()
    rows = normalize_history_rows(raw_rows, aliases=_ALIASES)
    return cache_rows(spec, pin=pin, cache=cache, rows=rows, allow_fallback=allow_fallback, return_used_pin=return_used_pin)


__all__ = ["fetch_baostock_history"]
