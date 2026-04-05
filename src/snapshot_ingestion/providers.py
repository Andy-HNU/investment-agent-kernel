from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shared.audit import AuditWindow, DataStatus
from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.adapters import (
    ExternalSnapshotAdapterError,
    FetchedSnapshotPayload,
    HttpJsonSnapshotAdapterConfig,
    fetch_http_json_snapshot,
)
from snapshot_ingestion.provider_matrix import find_provider_coverage, provider_capability_matrix_dicts

_ALLOWED_INLINE_KEYS = {
    "market_raw",
    "account_raw",
    "behavior_raw",
    "live_portfolio",
}

_SUPPORTED_MARKET_HISTORY_PROVIDERS = {"csv", "yfinance", "akshare", "baostock", "tinyshare"}
_DEFAULT_MARKET_HISTORY_SYMBOL_MAP: dict[str, dict[str, str]] = {
    "equity_cn": {
        "akshare": "510300",
        "yfinance": "510300.SS",
        "tinyshare": "510300.SH",
    },
    "bond_cn": {
        "akshare": "511010",
        "yfinance": "511010.SS",
        "tinyshare": "511010.SH",
    },
    "gold": {
        "akshare": "518880",
        "yfinance": "518880.SS",
        "tinyshare": "518880.SH",
    },
    "satellite": {
        "akshare": "159915",
        "yfinance": "159915.SZ",
        "tinyshare": "159915.SZ",
    },
}


def _source_ref(config: dict[str, Any], default: str) -> str:
    return str(config.get("source_ref") or default)


def _payload_warning_list(payload: dict[str, Any]) -> list[str]:
    return [str(item) for item in list(payload.get("warnings") or []) if str(item).strip()]


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_of_date(text: str) -> str:
    return str(text).split("T", 1)[0]


def _parse_market_history_window(config: dict[str, Any], *, as_of: str) -> tuple[str, str, int]:
    lookback_months = int(config.get("lookback_months") or 24)
    end_date = str(config.get("end_date") or _as_of_date(as_of))
    start_date = str(config.get("start_date") or (datetime.fromisoformat(end_date) - timedelta(days=lookback_months * 31)).date())
    return start_date, end_date, lookback_months


def _market_history_provider_sequence(config: dict[str, Any]) -> list[str]:
    requested_primary = str(config.get("provider") or "").strip().lower()
    coverage_asset_class = str(config.get("coverage_asset_class") or "etf").strip().lower()
    coverage = find_provider_coverage(coverage_asset_class)
    primary = requested_primary or str((coverage.primary_source if coverage is not None else "yfinance") or "yfinance").lower()
    sequence: list[str] = []
    for value in (
        primary,
        str(config.get("fallback_provider") or "").strip().lower(),
        str((coverage.fallback_source if coverage is not None else "") or "").strip().lower(),
    ):
        if value and value not in sequence and value in _SUPPORTED_MARKET_HISTORY_PROVIDERS:
            sequence.append(value)
    if not sequence:
        sequence.append("yfinance")
    return sequence


def _market_history_symbol_map(config: dict[str, Any], provider: str) -> dict[str, str]:
    configured = dict(config.get("symbol_map") or {})
    if not configured:
        configured = _DEFAULT_MARKET_HISTORY_SYMBOL_MAP
    resolved: dict[str, str] = {}
    for bucket, value in configured.items():
        if isinstance(value, dict):
            symbol = value.get(provider) or value.get("default") or value.get("symbol")
        else:
            symbol = value
        if symbol is None:
            continue
        resolved[str(bucket)] = str(symbol)
    return resolved


def _make_version_pin(provider: str, symbol: str, *, start_date: str, end_date: str, lookback_months: int) -> VersionPin:
    source_ref = f"{provider}://{symbol}?start={start_date}&end={end_date}&lookback_months={lookback_months}"
    version_id = f"{provider}:{symbol}:{start_date}:{end_date}:{lookback_months}m"
    return VersionPin(version_id=version_id, source_ref=source_ref)


def _return_series_from_rows(rows: list[dict[str, Any]]) -> list[float]:
    closes = [float(item["close"]) for item in rows if item.get("close") is not None]
    if len(closes) < 2:
        return []
    return [(closes[idx] / closes[idx - 1]) - 1.0 for idx in range(1, len(closes))]


def _audit_window_from_rows(rows: list[dict[str, Any]]) -> AuditWindow | None:
    if not rows:
        return None
    return AuditWindow(
        start_date=str(rows[0].get("date") or ""),
        end_date=str(rows[-1].get("date") or ""),
        trading_days=len(rows),
        observed_days=len(rows),
        inferred_days=0,
    )


def _merge_audit_windows(windows: list[AuditWindow]) -> AuditWindow | None:
    if not windows:
        return None
    start_dates = [item.start_date for item in windows if item.start_date]
    end_dates = [item.end_date for item in windows if item.end_date]
    trading_days = [item.trading_days for item in windows if item.trading_days is not None]
    observed_days = [item.observed_days for item in windows if item.observed_days is not None]
    inferred_days = [item.inferred_days or 0 for item in windows]
    return AuditWindow(
        start_date=min(start_dates) if start_dates else None,
        end_date=max(end_dates) if end_dates else None,
        trading_days=min(trading_days) if trading_days else None,
        observed_days=min(observed_days) if observed_days else None,
        inferred_days=max(inferred_days) if inferred_days else 0,
    )


def _market_history_failure_payload(
    *,
    provider_name: str,
    source_ref: str,
    requested_as_of: str,
    warnings: list[str],
) -> FetchedSnapshotPayload:
    return FetchedSnapshotPayload(
        raw_overrides={},
        provenance_items=[],
        warnings=warnings,
        source_ref=source_ref,
        provider_name=provider_name,
        fetched_at=_iso_now(),
        requested_as_of=requested_as_of,
        freshness={
            "as_of": requested_as_of,
            "fetched_at": _iso_now(),
            "domains": {},
        },
    )


def _coerce_market_history_snapshot(config: dict[str, Any], *, as_of: str) -> FetchedSnapshotPayload:
    start_date, end_date, lookback_months = _parse_market_history_window(config, as_of=as_of)
    provider_sequence = _market_history_provider_sequence(config)
    cache_dir = Path(str(config.get("cache_dir") or (Path.home() / ".cache" / "investment_system" / "timeseries")))
    cache = DatasetCache(base_dir=cache_dir)
    warnings: list[str] = []
    failure_reasons: list[str] = []
    used_provider: str | None = None
    used_source_ref: str | None = None
    used_window: AuditWindow | None = None
    used_cached_pin = False
    return_series: dict[str, list[float]] = {}

    for provider in provider_sequence:
        symbol_map = _market_history_symbol_map(config, provider)
        if not symbol_map:
            warnings.append(f"market_history provider={provider} has no symbol_map")
            continue
        provider_rows: dict[str, list[dict[str, Any]]] = {}
        provider_window_parts: list[AuditWindow] = []
        provider_error: str | None = None
        for bucket, symbol in symbol_map.items():
            spec = DatasetSpec(kind="timeseries", dataset_id=str(config.get("dataset_id") or "market_history"), provider=provider, symbol=symbol)
            pin = _make_version_pin(provider, symbol, start_date=start_date, end_date=end_date, lookback_months=lookback_months)
            try:
                rows, used_pin = fetch_timeseries(spec, pin=pin, cache=cache, allow_fallback=True, return_used_pin=True)
            except Exception as exc:
                provider_error = str(exc)
                break
            provider_rows[bucket] = rows
            window = _audit_window_from_rows(rows)
            if window is not None:
                provider_window_parts.append(window)
            if used_pin.version_id != pin.version_id:
                used_cached_pin = True
        if provider_error:
            failure_reasons.append(f"{provider}:{provider_error}")
            warnings.append(f"market_history provider={provider} failed: {provider_error}")
            continue
        computed = {bucket: _return_series_from_rows(rows) for bucket, rows in provider_rows.items()}
        if not all(series for series in computed.values()):
            failure_reasons.append(f"{provider}:insufficient_history")
            warnings.append(f"market_history provider={provider} returned insufficient_history")
            continue
        used_provider = provider
        ordered_symbols = ",".join(f"{bucket}:{symbol}" for bucket, symbol in sorted(symbol_map.items()))
        used_source_ref = f"{provider}://market_history?symbols={ordered_symbols}&start={start_date}&end={end_date}"
        used_window = _merge_audit_windows(provider_window_parts)
        return_series = computed
        break

    provider_name = str(config.get("provider_name") or "market_history")
    if used_provider is None:
        if bool(config.get("fail_open", True)):
            return _market_history_failure_payload(
                provider_name=provider_name,
                source_ref=_source_ref(config, f"market_history://{provider_sequence[0]}"),
                requested_as_of=as_of,
                warnings=warnings or ["market_history provider unavailable"],
            )
        raise ExternalSnapshotAdapterError("; ".join(warnings) or "market_history provider unavailable")

    coverage_status = "verified" if used_provider == provider_sequence[0] else "degraded"
    if used_provider != provider_sequence[0]:
        warnings.append(f"market_history fallback activated: {provider_sequence[0]} -> {used_provider}")
    if used_cached_pin:
        coverage_status = "degraded"
        warnings.append(f"market_history cache fallback activated for provider={used_provider}")
    historical_dataset = {
        "dataset_id": str(config.get("dataset_id") or "market_history"),
        "version_id": f"{used_provider}:{start_date}:{end_date}:{lookback_months}m",
        "frequency": "daily",
        "as_of": end_date,
        "source_name": used_provider,
        "source_ref": used_source_ref or f"{used_provider}://market_history",
        "lookback_months": lookback_months,
        "return_series": return_series,
        "coverage_status": coverage_status,
        "cached_at": _iso_now(),
        "notes": warnings + failure_reasons,
        "audit_window": None if used_window is None else used_window.to_dict(),
    }
    raw_overrides = {"market_raw": {"historical_dataset": historical_dataset}}
    freshness = {
        "as_of": end_date,
        "fetched_at": _iso_now(),
        "domains": {
            "market_raw": {
                "status": "fresh" if coverage_status == "verified" else "fallback",
                "as_of": end_date,
                "fetched_at": _iso_now(),
                "source_ref": used_source_ref,
                "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
                "audit_window": None if used_window is None else used_window.to_dict(),
                "detail": f"market_history provider={used_provider}",
            }
        },
    }
    provenance_items = [
        {
            "field": "market_raw",
            "label": "市场输入",
            "value": used_source_ref,
            "source_ref": used_source_ref,
            "as_of": end_date,
            "fetched_at": freshness["fetched_at"],
            "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
            "audit_window": None if used_window is None else used_window.to_dict(),
            "note": f"market_history provider={used_provider}; fallback={'yes' if coverage_status == 'degraded' else 'no'}",
            "freshness": dict(freshness["domains"]["market_raw"]),
        }
    ]
    return FetchedSnapshotPayload(
        raw_overrides=raw_overrides,
        provenance_items=provenance_items,
        warnings=warnings,
        source_ref=used_source_ref or _source_ref(config, f"market_history://{used_provider}"),
        provider_name=provider_name,
        fetched_at=freshness["fetched_at"],
        requested_as_of=as_of,
        freshness=freshness,
    )


def _coerce_inline_snapshot(config: dict[str, Any]) -> FetchedSnapshotPayload:
    payload = dict(config.get("payload") or {})
    raw_overrides = {
        key: dict(value)
        for key, value in payload.items()
        if key in _ALLOWED_INLINE_KEYS and isinstance(value, dict)
    }
    ignored = [key for key in payload if key not in raw_overrides and key not in {"warnings"}]
    warnings = _payload_warning_list(payload)
    if ignored:
        warnings.append("ignored inline snapshot keys: " + ", ".join(sorted(ignored)))
    provider_name = str(config.get("provider_name") or "inline_snapshot").strip()
    source_ref = _source_ref(config, f"inline://{provider_name}")
    freshness = {
        "as_of": config.get("as_of"),
        "fetched_at": config.get("fetched_at"),
        "domains": {
            key: {
                "status": "fresh",
                "as_of": config.get("as_of"),
                "fetched_at": config.get("fetched_at"),
            }
            for key in raw_overrides
        },
    }
    provenance_items = [
        {
            "field": key,
            "label": key,
            "value": source_ref,
            "source_ref": source_ref,
            "as_of": config.get("as_of"),
            "fetched_at": config.get("fetched_at"),
            "data_status": DataStatus.SYNTHETIC_DEMO.value,
            "audit_window": {},
            "note": f"provider={provider_name}; inline_snapshot",
            "freshness": dict(freshness["domains"].get(key) or {}),
        }
        for key in sorted(raw_overrides)
    ]
    return FetchedSnapshotPayload(
        raw_overrides=raw_overrides,
        provenance_items=provenance_items,
        warnings=warnings,
        source_ref=source_ref,
        provider_name=provider_name,
        fetched_at=config.get("fetched_at"),
        requested_as_of=config.get("as_of"),
        freshness=freshness,
    )


def _coerce_local_json_snapshot(config: dict[str, Any]) -> FetchedSnapshotPayload:
    source = str(config.get("snapshot_path") or "").strip()
    if not source:
        raise ValueError("local_json snapshot_path is required")
    path = Path(source)
    payload = json.loads(path.read_text(encoding="utf-8"))
    inline_config = {
        "provider_name": config.get("provider_name") or "local_json_snapshot",
        "source_ref": _source_ref(config, f"file://{path}"),
        "as_of": config.get("as_of"),
        "fetched_at": config.get("fetched_at"),
        "payload": payload,
    }
    return _coerce_inline_snapshot(inline_config)


def fetch_snapshot_from_provider_config(
    config: dict[str, Any] | None,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload | None:
    if not config:
        return None
    adapter_name = str(config.get("adapter") or "http_json").strip().lower()
    if adapter_name == "http_json":
        adapter_config = HttpJsonSnapshotAdapterConfig.from_mapping(config)
        return fetch_http_json_snapshot(
            adapter_config,
            workflow_type=workflow_type,
            account_profile_id=account_profile_id,
            as_of=as_of,
        )
    if adapter_name == "inline_snapshot":
        inline_config = dict(config)
        inline_config.setdefault("as_of", as_of)
        return _coerce_inline_snapshot(inline_config)
    if adapter_name == "local_json":
        local_config = dict(config)
        local_config.setdefault("as_of", as_of)
        return _coerce_local_json_snapshot(local_config)
    if adapter_name == "market_history":
        market_history_config = dict(config)
        market_history_config.setdefault("as_of", as_of)
        return _coerce_market_history_snapshot(market_history_config, as_of=as_of)
    raise ValueError(f"unsupported external data adapter: {adapter_name}")


def provider_debug_metadata() -> dict[str, Any]:
    return {
        "capability_matrix": provider_capability_matrix_dicts(),
        "live_portfolio_coverage": (
            find_provider_coverage("live_portfolio").to_dict()
            if find_provider_coverage("live_portfolio") is not None
            else None
        ),
    }


__all__ = [
    "ExternalSnapshotAdapterError",
    "fetch_snapshot_from_provider_config",
    "provider_debug_metadata",
]
