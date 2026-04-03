from __future__ import annotations

import inspect
from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers._history_common import cache_rows, import_optional_module, normalize_history_rows, parse_source_ref


_ALIASES = {
    "date": ("date", "日期", "Date"),
    "open": ("open", "开盘", "Open"),
    "high": ("high", "最高", "High"),
    "low": ("low", "最低", "Low"),
    "close": ("close", "收盘", "Close"),
    "volume": ("volume", "成交量", "Volume"),
}


def fetch_akshare_history(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    allow_fallback: bool = False,
    return_used_pin: bool = False,
) -> Any:
    ak = import_optional_module("akshare", missing_message="akshare provider unavailable - install akshare")
    endpoint, params = parse_source_ref(pin.source_ref)
    function_name = endpoint or "stock_zh_a_hist"
    fetcher = getattr(ak, function_name, None)
    if fetcher is None:
        raise RuntimeError(f"akshare provider unavailable - missing function {function_name}")
    symbol = spec.symbol or ""
    if not symbol:
        raise ValueError("akshare provider requires spec.symbol")

    candidate_kwargs = {
        "symbol": symbol,
        "period": params.get("period", "daily"),
        "start_date": params.get("start_date"),
        "end_date": params.get("end_date"),
        "adjust": params.get("adjust", ""),
    }
    signature = inspect.signature(fetcher)
    accepts_var_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_var_kwargs:
        filtered_kwargs = {name: value for name, value in candidate_kwargs.items() if value not in (None, "")}
    else:
        filtered_kwargs = {
            name: value
            for name, value in candidate_kwargs.items()
            if name in signature.parameters and value not in (None, "")
        }
    raw_frame = fetcher(**filtered_kwargs)
    if hasattr(raw_frame, "to_dict"):
        raw_rows = raw_frame.to_dict("records")
    else:
        raw_rows = list(raw_frame or [])
    rows = normalize_history_rows(raw_rows, aliases=_ALIASES)
    return cache_rows(spec, pin=pin, cache=cache, rows=rows, allow_fallback=allow_fallback, return_used_pin=return_used_pin)


__all__ = ["fetch_akshare_history"]
