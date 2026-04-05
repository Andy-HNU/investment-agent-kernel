from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha1
from math import sqrt
from pathlib import Path
from typing import Any

from shared.audit import AuditWindow


@dataclass(frozen=True)
class HistoricalDatasetSnapshot:
    dataset_id: str
    version_id: str
    as_of: str
    source_name: str
    source_ref: str
    lookback_months: int
    return_series: dict[str, list[float]]
    frequency: str = "monthly"
    coverage_status: str = "verified"
    cached_at: str | None = None
    audit_window: AuditWindow | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["audit_window"] = None if self.audit_window is None else self.audit_window.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "HistoricalDatasetSnapshot":
        return cls(
            dataset_id=str(payload.get("dataset_id") or payload.get("source_name") or "historical_dataset"),
            version_id=str(payload.get("version_id") or payload.get("dataset_version") or ""),
            as_of=str(payload.get("as_of") or ""),
            source_name=str(payload.get("source_name") or "unknown_source"),
            source_ref=str(payload.get("source_ref") or payload.get("source_name") or "unknown_source"),
            lookback_months=int(payload.get("lookback_months") or 0),
            frequency=str(payload.get("frequency") or "monthly"),
            return_series={
                str(bucket): [float(value) for value in list(series or [])]
                for bucket, series in dict(payload.get("return_series") or {}).items()
            },
            coverage_status=str(payload.get("coverage_status") or "verified"),
            cached_at=payload.get("cached_at"),
            audit_window=AuditWindow.from_any(payload.get("audit_window")),
            notes=[str(item) for item in list(payload.get("notes") or []) if str(item).strip()],
        )


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


def build_historical_dataset_snapshot(payload: dict[str, Any] | None) -> HistoricalDatasetSnapshot | None:
    if not payload:
        return None
    data = dict(payload)
    dataset_id, version_id = _dataset_identity(data)
    data.setdefault("dataset_id", dataset_id)
    data.setdefault("version_id", version_id)
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
    annualization = {
        "daily": 252.0,
        "weekly": 52.0,
        "monthly": 12.0,
        "quarterly": 4.0,
    }.get(str(dataset.frequency or "monthly").lower(), 12.0)
    volatility_scale = sqrt(annualization)
    for bucket, series in series_map.items():
        mean_value = _mean(series)
        mean_map[bucket] = mean_value
        expected_returns[bucket] = float(mean_value * annualization)
        volatility[bucket] = float(max(sqrt(_variance(series, mean_value)) * volatility_scale, 0.03))

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
    "build_historical_dataset_snapshot",
    "summarize_historical_dataset",
]
