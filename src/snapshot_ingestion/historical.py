from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha1
from math import sqrt
from pathlib import Path
from typing import Any

from snapshot_ingestion.types import (
    BucketProxyMappingRaw,
    HistoricalReturnPanelRaw,
    JumpEventHistoryRaw,
    RegimeFeatureSnapshotRaw,
)


@dataclass(frozen=True)
class HistoricalDatasetSnapshot:
    dataset_id: str
    version_id: str
    as_of: str
    source_name: str
    source_ref: str
    lookback_months: int
    return_series: dict[str, list[float]]
    coverage_status: str = "in_progress"
    cached_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "HistoricalDatasetSnapshot":
        return cls(
            dataset_id=str(payload.get("dataset_id") or payload.get("source_name") or "historical_dataset"),
            version_id=str(payload.get("version_id") or payload.get("dataset_version") or ""),
            as_of=str(payload.get("as_of") or ""),
            source_name=str(payload.get("source_name") or "unknown_source"),
            source_ref=str(payload.get("source_ref") or payload.get("source_name") or "unknown_source"),
            lookback_months=int(payload.get("lookback_months") or 0),
            return_series={
                str(bucket): [float(value) for value in list(series or [])]
                for bucket, series in dict(payload.get("return_series") or {}).items()
            },
            coverage_status=str(payload.get("coverage_status") or "in_progress"),
            cached_at=payload.get("cached_at"),
            notes=[str(item) for item in list(payload.get("notes") or []) if str(item).strip()],
        )


def build_historical_return_panel(
    payload: HistoricalReturnPanelRaw | dict[str, Any] | None,
) -> HistoricalReturnPanelRaw | None:
    if payload is None:
        return None
    if isinstance(payload, HistoricalReturnPanelRaw):
        return payload
    data = dict(payload)
    if "return_series" not in data:
        return None
    source_name = str(data.get("source_name") or "unknown_source")
    as_of = str(data.get("as_of") or "")
    return HistoricalReturnPanelRaw(
        dataset_id=str(data.get("dataset_id") or f"{source_name}:{as_of}" or "historical_return_panel"),
        version_id=str(data.get("version_id") or data.get("dataset_version") or ""),
        as_of=as_of,
        source_name=source_name,
        lookback_months=int(data.get("lookback_months") or 0),
        return_series={
            str(bucket): [float(value) for value in list(series or [])]
            for bucket, series in dict(data.get("return_series") or {}).items()
        },
        source_ref=data.get("source_ref"),
        coverage_status=str(data.get("coverage_status") or "raw"),
        notes=[str(item) for item in list(data.get("notes") or []) if str(item).strip()],
    )


def build_regime_feature_snapshot(
    payload: RegimeFeatureSnapshotRaw | dict[str, Any] | None,
) -> RegimeFeatureSnapshotRaw | None:
    if payload is None:
        return None
    if isinstance(payload, RegimeFeatureSnapshotRaw):
        return payload
    data = dict(payload)
    feature_values = dict(data.get("feature_values") or {})
    if not feature_values:
        return None
    return RegimeFeatureSnapshotRaw(
        snapshot_id=str(data.get("snapshot_id") or "regime_feature_snapshot"),
        as_of=str(data.get("as_of") or ""),
        feature_values={str(key): float(value) for key, value in feature_values.items()},
        inferred_regime=_optional_text(data.get("inferred_regime")),
        source_refs=[str(item) for item in list(data.get("source_refs") or []) if str(item).strip()],
        notes=[str(item) for item in list(data.get("notes") or []) if str(item).strip()],
    )


def build_jump_event_history(
    payload: JumpEventHistoryRaw | dict[str, Any] | None,
) -> JumpEventHistoryRaw | None:
    if payload is None:
        return None
    if isinstance(payload, JumpEventHistoryRaw):
        return payload
    data = dict(payload)
    return JumpEventHistoryRaw(
        history_id=str(data.get("history_id") or "jump_event_history"),
        as_of=str(data.get("as_of") or ""),
        events=[dict(event or {}) for event in list(data.get("events") or [])],
        source_refs=[str(item) for item in list(data.get("source_refs") or []) if str(item).strip()],
        notes=[str(item) for item in list(data.get("notes") or []) if str(item).strip()],
    )


def build_bucket_proxy_mapping(
    payload: BucketProxyMappingRaw | dict[str, Any] | None,
) -> BucketProxyMappingRaw | None:
    if payload is None:
        return None
    if isinstance(payload, BucketProxyMappingRaw):
        return payload
    data = dict(payload)
    mapping = dict(data.get("bucket_to_proxy") or {})
    if not mapping:
        return None
    return BucketProxyMappingRaw(
        mapping_id=str(data.get("mapping_id") or "bucket_proxy_mapping"),
        as_of=str(data.get("as_of") or ""),
        bucket_to_proxy={str(bucket): str(proxy) for bucket, proxy in mapping.items()},
        proxy_metadata={
            str(bucket): dict(metadata or {})
            for bucket, metadata in dict(data.get("proxy_metadata") or {}).items()
        },
        notes=[str(item) for item in list(data.get("notes") or []) if str(item).strip()],
    )


def _optional_text(value: Any) -> str | None:
    rendered = str(value or "").strip()
    return rendered or None


def _dataset_identity(payload: dict[str, Any]) -> tuple[str, str]:
    source_name = str(payload.get("source_name") or "unknown_source")
    as_of = str(payload.get("as_of") or "")
    version_id = str(payload.get("version_id") or payload.get("dataset_version") or "")
    if not version_id:
        digest = sha1(
            json.dumps(payload.get("return_series") or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        version_id = f"{source_name}:{as_of}:{digest}"
    dataset_id = str(payload.get("dataset_id") or f"{source_name}:{as_of}")
    return dataset_id, version_id


def build_historical_dataset_snapshot(
    payload: HistoricalReturnPanelRaw | dict[str, Any] | None,
) -> HistoricalDatasetSnapshot | None:
    if not payload:
        return None
    panel = build_historical_return_panel(payload)
    if panel is not None:
        data = panel.to_dict()
    else:
        data = dict(payload)
    dataset_id, version_id = _dataset_identity(data)
    if not str(data.get("dataset_id") or "").strip():
        data["dataset_id"] = dataset_id
    if not str(data.get("version_id") or data.get("dataset_version") or "").strip():
        data["version_id"] = version_id
    if "return_series" not in data:
        return None
    return HistoricalDatasetSnapshot.from_mapping(data)


def summarize_historical_dataset(
    dataset: HistoricalDatasetSnapshot,
    *,
    buckets: list[str] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, dict[str, float]]]:
    selected_buckets = buckets or sorted(dataset.return_series)
    if not selected_buckets:
        return {}, {}, {}
    series_map: dict[str, list[float]] = {}
    for bucket in selected_buckets:
        raw_series = [float(value) for value in list(dataset.return_series.get(bucket) or [])]
        if not raw_series:
            continue
        series_map[bucket] = raw_series
    if not series_map:
        return {}, {}, {}

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values)

    def _variance(values: list[float], mean_value: float) -> float:
        if len(values) <= 1:
            return 0.0
        return sum((value - mean_value) ** 2 for value in values) / len(values)

    expected_returns: dict[str, float] = {}
    volatility: dict[str, float] = {}
    mean_map: dict[str, float] = {}
    for bucket, series in series_map.items():
        mean_value = _mean(series)
        mean_map[bucket] = mean_value
        expected_returns[bucket] = float(mean_value * 12.0)
        volatility[bucket] = float(max(sqrt(_variance(series, mean_value)) * sqrt(12.0), 0.03))

    ordered = sorted(series_map)
    min_len = min(len(series_map[bucket]) for bucket in ordered)
    correlation_matrix: dict[str, dict[str, float]] = {}
    for row_idx, bucket in enumerate(ordered):
        row: dict[str, float] = {}
        series_a = series_map[bucket][-min_len:]
        mean_a = mean_map[bucket]
        variance_a = _variance(series_a, mean_a)
        std_a = sqrt(max(variance_a, 0.0))
        for col_idx, peer in enumerate(ordered):
            if row_idx == col_idx:
                row[peer] = 1.0
            else:
                series_b = series_map[peer][-min_len:]
                mean_b = mean_map[peer]
                variance_b = _variance(series_b, mean_b)
                std_b = sqrt(max(variance_b, 0.0))
                if min_len < 2 or std_a <= 0.0 or std_b <= 0.0:
                    corr = 0.0
                else:
                    covariance = sum(
                        (value_a - mean_a) * (value_b - mean_b)
                        for value_a, value_b in zip(series_a, series_b, strict=True)
                    ) / min_len
                    corr = covariance / (std_a * std_b)
                row[peer] = float(max(min(corr, 0.95), -0.95))
        correlation_matrix[bucket] = row
    return expected_returns, volatility, correlation_matrix


class HistoricalDatasetCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _dataset_path(self, version_id: str) -> Path:
        safe_name = version_id.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_name}.json"

    def save(self, dataset: HistoricalDatasetSnapshot) -> Path:
        path = self._dataset_path(dataset.version_id)
        path.write_text(json.dumps(dataset.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return path

    def load(self, version_id: str) -> HistoricalDatasetSnapshot | None:
        path = self._dataset_path(version_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return HistoricalDatasetSnapshot.from_mapping(payload)


__all__ = [
    "HistoricalDatasetCache",
    "HistoricalDatasetSnapshot",
    "build_bucket_proxy_mapping",
    "build_historical_dataset_snapshot",
    "build_historical_return_panel",
    "build_jump_event_history",
    "build_regime_feature_snapshot",
    "summarize_historical_dataset",
]
