from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.adapters.http_json_adapter import FetchedSnapshotPayload
from snapshot_ingestion.historical import (
    HistoricalDatasetCache,
    build_historical_dataset_snapshot,
    summarize_historical_dataset,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _month_end_closes(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    latest_by_month: dict[str, tuple[str, float]] = {}
    for row in rows:
        date_text = str(row.get("date") or "")
        month_key = date_text[:7]
        close_value = float(row.get("close") or 0.0)
        current = latest_by_month.get(month_key)
        if current is None or date_text > current[0]:
            latest_by_month[month_key] = (date_text, close_value)
    return [latest_by_month[key] for key in sorted(latest_by_month)]


def _monthly_returns(rows: list[dict[str, Any]]) -> list[float]:
    closes = _month_end_closes(rows)
    if len(closes) < 2:
        return []
    returns: list[float] = []
    for (_, previous_close), (_, current_close) in zip(closes, closes[1:]):
        if previous_close <= 0.0:
            continue
        returns.append(float(current_close / previous_close - 1.0))
    return returns


def _coverage_status(
    *,
    covered: int,
    expected: int,
    fallback_buckets: list[str],
    default_status: str,
) -> str:
    if covered <= 0:
        return "degraded"
    if covered < expected:
        return "degraded"
    if fallback_buckets:
        return "degraded"
    return default_status


def _freshness_status(*, coverage_status: str, fallback_buckets: list[str]) -> str:
    if coverage_status == "degraded":
        return "degraded"
    if fallback_buckets:
        return "fallback"
    if coverage_status in {"verified", "in_progress"}:
        return "fresh"
    return "degraded"


def _is_verified_route(*, provider: str, kind: str, source_ref: str | None) -> bool:
    rendered_provider = str(provider or "").strip().lower()
    rendered_kind = str(kind or "").strip().lower()
    rendered_source_ref = str(source_ref or "").strip().lower()
    return (
        rendered_provider == "akshare"
        and rendered_kind in {"cn_index_daily", "cn_index_daily_tx", "index_daily"}
        and "stock_zh_index_daily_tx" in rendered_source_ref
    )


def _aggregate_version_id(
    *,
    provider_name: str,
    requested_as_of: str,
    used_pins: dict[str, VersionPin],
) -> str:
    digest = sha1(
        json.dumps(
            {
                bucket: {"version_id": pin.version_id, "source_ref": pin.source_ref}
                for bucket, pin in sorted(used_pins.items())
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"{provider_name}:{requested_as_of[:10]}:{digest}"


@dataclass(frozen=True)
class MarketHistorySnapshotAdapterConfig:
    provider_name: str
    dataset_id: str
    bucket_series: dict[str, dict[str, Any]]
    dataset_cache_dir: str
    historical_cache_dir: str
    lookback_months: int = 36
    allow_fallback: bool = True
    coverage_expectation: list[str] = field(default_factory=list)
    verified_status: str = "in_progress"
    version_id: str | None = None
    source_ref: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "MarketHistorySnapshotAdapterConfig":
        bucket_series = {
            str(bucket): dict(series or {})
            for bucket, series in dict(payload.get("bucket_series") or {}).items()
            if isinstance(series, dict)
        }
        if not bucket_series:
            raise ValueError("market_history bucket_series is required")
        provider_name = str(payload.get("provider_name") or "market_history").strip()
        dataset_id = str(payload.get("dataset_id") or f"{provider_name}_dataset").strip()
        dataset_cache_dir = str(payload.get("dataset_cache_dir") or "").strip()
        historical_cache_dir = str(payload.get("historical_cache_dir") or "").strip()
        if not dataset_cache_dir:
            raise ValueError("market_history dataset_cache_dir is required")
        if not historical_cache_dir:
            raise ValueError("market_history historical_cache_dir is required")
        return cls(
            provider_name=provider_name,
            dataset_id=dataset_id,
            bucket_series=bucket_series,
            dataset_cache_dir=dataset_cache_dir,
            historical_cache_dir=historical_cache_dir,
            lookback_months=int(payload.get("lookback_months") or 36),
            allow_fallback=bool(payload.get("allow_fallback", True)),
            coverage_expectation=[str(item) for item in list(payload.get("coverage_expectation") or []) if str(item).strip()],
            verified_status=str(payload.get("verified_status") or "in_progress").strip() or "in_progress",
            version_id=str(payload.get("version_id") or "").strip() or None,
            source_ref=str(payload.get("source_ref") or "").strip() or None,
        )


def fetch_market_history_snapshot(
    config: MarketHistorySnapshotAdapterConfig,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload:
    del workflow_type, account_profile_id
    dataset_cache = DatasetCache(base_dir=Path(config.dataset_cache_dir))
    historical_cache = HistoricalDatasetCache(Path(config.historical_cache_dir))
    requested_as_of = str(as_of or _now_iso())
    fetched_at = _now_iso()
    covered_buckets: dict[str, list[float]] = {}
    used_pins: dict[str, VersionPin] = {}
    warnings: list[str] = []
    fallback_buckets: list[str] = []
    missing_buckets: list[str] = []
    bucket_proxy_mapping: dict[str, str] = {}
    proxy_metadata: dict[str, dict[str, Any]] = {}

    for bucket, series in sorted(config.bucket_series.items()):
        provider = str(series.get("provider") or "").strip()
        kind = str(series.get("kind") or "").strip()
        dataset_id = str(series.get("dataset_id") or f"{config.dataset_id}:{bucket}").strip()
        symbol = str(series.get("symbol") or "").strip() or None
        version_id = str(series.get("version_id") or "").strip()
        source_ref = str(series.get("source_ref") or "").strip() or None
        proxy_label = str(series.get("proxy_label") or symbol or dataset_id).strip()
        if not provider or not kind or not version_id:
            missing_buckets.append(bucket)
            warnings.append(f"bucket {bucket} missing provider/kind/version_id configuration")
            continue
        spec = DatasetSpec(kind=kind, dataset_id=dataset_id, provider=provider, symbol=symbol)
        requested_pin = VersionPin(version_id=version_id, source_ref=source_ref)
        try:
            rows, used_pin = fetch_timeseries(
                spec,
                pin=requested_pin,
                cache=dataset_cache,
                allow_fallback=config.allow_fallback,
                return_used_pin=True,
            )
        except Exception as exc:
            missing_buckets.append(bucket)
            warnings.append(f"bucket {bucket} fetch failed: {exc}")
            continue
        monthly_returns = _monthly_returns(rows)
        if not monthly_returns:
            missing_buckets.append(bucket)
            warnings.append(f"bucket {bucket} produced insufficient monthly history")
            continue
        covered_buckets[bucket] = monthly_returns
        used_pins[bucket] = used_pin
        bucket_proxy_mapping[bucket] = proxy_label
        proxy_metadata[bucket] = {
            "provider": provider,
            "kind": kind,
            "symbol": symbol,
            "dataset_id": dataset_id,
            "requested_version_id": requested_pin.version_id,
            "used_version_id": used_pin.version_id,
            "source_ref": used_pin.source_ref or requested_pin.source_ref,
        }
        if used_pin.version_id != requested_pin.version_id:
            fallback_buckets.append(bucket)

    expected_buckets = config.coverage_expectation or list(config.bucket_series)
    uncovered_expected = [bucket for bucket in expected_buckets if bucket not in covered_buckets]
    coverage_status = _coverage_status(
        covered=len(covered_buckets),
        expected=len(expected_buckets),
        fallback_buckets=fallback_buckets,
        default_status=config.verified_status,
    )
    if missing_buckets or uncovered_expected:
        partial_buckets = sorted({*missing_buckets, *uncovered_expected})
        warnings.append("partial bucket coverage: " + ", ".join(partial_buckets))
    if fallback_buckets:
        warnings.append("cached fallback used for buckets: " + ", ".join(sorted(fallback_buckets)))

    aggregate_version_id = config.version_id or _aggregate_version_id(
        provider_name=config.provider_name,
        requested_as_of=requested_as_of,
        used_pins=used_pins,
    )
    aggregate_source_ref = config.source_ref or (
        f"market_history://{config.provider_name}/{config.dataset_id}?as_of={requested_as_of}&version_id={aggregate_version_id}"
    )
    notes = []
    if missing_buckets or uncovered_expected:
        notes.append("partial bucket coverage - market history is degraded")
    if fallback_buckets:
        notes.append("cached fallback used for at least one bucket")

    dataset_payload = {
        "dataset_id": config.dataset_id,
        "version_id": aggregate_version_id,
        "as_of": requested_as_of,
        "source_name": config.provider_name,
        "source_ref": aggregate_source_ref,
        "lookback_months": config.lookback_months,
        "return_series": covered_buckets,
        "coverage_status": coverage_status,
        "cached_at": fetched_at,
        "notes": notes,
    }
    dataset = build_historical_dataset_snapshot(dataset_payload)
    if dataset is None:
        raise ValueError("market_history adapter could not build historical dataset")
    historical_cache.save(dataset)
    expected_returns, raw_volatility, correlation_matrix = summarize_historical_dataset(dataset)

    market_raw = {
        "historical_dataset": dataset.to_dict(),
        "historical_return_panel": {
            "dataset_id": dataset.dataset_id,
            "version_id": dataset.version_id,
            "as_of": dataset.as_of,
            "source_name": dataset.source_name,
            "source_ref": dataset.source_ref,
            "lookback_months": dataset.lookback_months,
            "return_series": dataset.return_series,
            "coverage_status": coverage_status,
            "notes": list(dataset.notes),
        },
        "bucket_proxy_mapping": {
            "mapping_id": f"{config.dataset_id}:proxy_mapping",
            "as_of": requested_as_of,
            "bucket_to_proxy": bucket_proxy_mapping,
            "proxy_metadata": proxy_metadata,
            "notes": notes,
        },
        "expected_returns": expected_returns,
        "raw_volatility": raw_volatility,
        "correlation_matrix": correlation_matrix,
    }
    freshness_status = _freshness_status(coverage_status=coverage_status, fallback_buckets=fallback_buckets)
    freshness = {
        "as_of": requested_as_of,
        "fetched_at": fetched_at,
        "domains": {
            "market_raw": {
                "status": freshness_status,
                "as_of": requested_as_of,
                "fetched_at": fetched_at,
                "detail": (
                    f"coverage={len(covered_buckets)}/{len(expected_buckets)}; "
                    f"fallback_buckets={len(fallback_buckets)}; version_id={aggregate_version_id}"
                ),
            }
        },
    }
    provenance = [
        {
            "field": "market_raw",
            "label": "市场输入",
            "value": aggregate_source_ref,
            "note": (
                f"provider={config.provider_name}; coverage_status={coverage_status}; "
                f"dataset_version={aggregate_version_id}"
            ),
            "freshness": dict(freshness["domains"]["market_raw"]),
        }
    ]
    return FetchedSnapshotPayload(
        raw_overrides={"market_raw": market_raw},
        provenance_items=provenance,
        warnings=warnings,
        source_ref=aggregate_source_ref,
        provider_name=config.provider_name,
        fetched_at=fetched_at,
        requested_as_of=requested_as_of,
        freshness=freshness,
    )


__all__ = [
    "MarketHistorySnapshotAdapterConfig",
    "fetch_market_history_snapshot",
]
