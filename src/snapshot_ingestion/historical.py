from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha1
from math import sqrt
from pathlib import Path
from typing import Any

from snapshot_ingestion.cycle_policy import evaluate_cycle_coverage


@dataclass(frozen=True)
class HistoricalDatasetSnapshot:
    dataset_id: str
    version_id: str
    as_of: str
    source_name: str
    source_ref: str
    lookback_months: int
    return_series: dict[str, list[float]]
    frequency: str = "daily"
    lookback_days: int = 0
    series_dates: list[str] = field(default_factory=list)
    coverage_status: str = "verified"
    cycle_reasons: list[str] = field(default_factory=list)
    observed_history_days: int = 0
    inferred_history_days: int = 0
    inference_method: str | None = None
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
            frequency=str(payload.get("frequency") or "daily"),
            lookback_months=int(payload.get("lookback_months") or 0),
            lookback_days=int(payload.get("lookback_days") or 0),
            return_series={
                str(bucket): [float(value) for value in list(series or [])]
                for bucket, series in dict(payload.get("return_series") or {}).items()
            },
            series_dates=[str(item) for item in list(payload.get("series_dates") or []) if str(item).strip()],
            coverage_status=str(payload.get("coverage_status") or "verified"),
            cycle_reasons=[str(item) for item in list(payload.get("cycle_reasons") or []) if str(item).strip()],
            observed_history_days=int(payload.get("observed_history_days") or 0),
            inferred_history_days=int(payload.get("inferred_history_days") or 0),
            inference_method=(
                str(payload.get("inference_method")).strip() if payload.get("inference_method") is not None else None
            ),
            cached_at=payload.get("cached_at"),
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
    series_map = {
        str(bucket): [float(value) for value in list(series or [])]
        for bucket, series in dict(data.get("return_series") or {}).items()
        if list(series or [])
    }
    series_dates = [str(item) for item in list(data.get("series_dates") or []) if str(item).strip()]
    observed_history_days = int(data.get("observed_history_days") or 0)
    if observed_history_days <= 0:
        observed_history_days = len(series_dates) if series_dates else max((len(series) for series in series_map.values()), default=0)
        data["observed_history_days"] = observed_history_days
    frequency = str(data.get("frequency") or "daily").strip().lower() or "daily"
    data["frequency"] = frequency
    inferred_history_days = int(data.get("inferred_history_days") or 0)
    data["inferred_history_days"] = inferred_history_days
    if int(data.get("lookback_days") or 0) <= 0:
        data["lookback_days"] = observed_history_days + inferred_history_days

    existing_cycle_reasons = [str(item) for item in list(data.get("cycle_reasons") or []) if str(item).strip()]
    if existing_cycle_reasons:
        data["cycle_reasons"] = existing_cycle_reasons
        data["coverage_status"] = "cycle_insufficient"
    else:
        ordered_buckets = sorted(series_map)
        if ordered_buckets:
            min_len = min(len(series_map[bucket]) for bucket in ordered_buckets)
            aggregate_returns = [
                sum(series_map[bucket][idx] for bucket in ordered_buckets) / len(ordered_buckets)
                for idx in range(min_len)
            ]
            effective_dates = series_dates[-min_len:] if len(series_dates) >= min_len else [str(idx) for idx in range(min_len)]
            cycle_summary = evaluate_cycle_coverage(dates=effective_dates, returns=aggregate_returns, frequency=frequency)
            data["cycle_reasons"] = cycle_summary.reasons
            data["coverage_status"] = "verified" if cycle_summary.coverage_ok else "cycle_insufficient"
        else:
            data["cycle_reasons"] = ["missing_observed_history"]
            data["coverage_status"] = "cycle_insufficient"
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

    annualization_map = {
        "daily": 252.0,
        "weekly": 52.0,
        "monthly": 12.0,
    }
    annualization_scale = annualization_map.get(str(dataset.frequency or "daily").strip().lower(), 252.0)

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
        expected_returns[bucket] = float(mean_value * annualization_scale)
        volatility[bucket] = float(max(sqrt(_variance(series, mean_value)) * sqrt(annualization_scale), 0.03))

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
