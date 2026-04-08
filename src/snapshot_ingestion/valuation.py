from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from shared.audit import AuditWindow, DataStatus, coerce_data_status


@dataclass(frozen=True)
class ValuationObservation:
    subject_id: str
    metric_name: str
    current_value: float
    source_ref: str
    as_of: str
    data_status: DataStatus
    audit_window: AuditWindow | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_status"] = self.data_status.value
        payload["audit_window"] = None if self.audit_window is None else self.audit_window.to_dict()
        return payload


@dataclass(frozen=True)
class ValuationPercentileResult:
    subject_id: str
    metric_name: str
    current_value: float | None
    percentile: float
    valuation_position: str
    source_ref: str
    as_of: str
    data_status: DataStatus
    audit_window: AuditWindow | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_status"] = self.data_status.value
        payload["audit_window"] = None if self.audit_window is None else self.audit_window.to_dict()
        return payload


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        rendered = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(rendered):
        return None
    return rendered


def coerce_valuation_observations(
    payload: dict[str, Any] | None,
) -> dict[str, ValuationObservation]:
    observations: dict[str, ValuationObservation] = {}
    for subject_id, raw_value in dict(payload or {}).items():
        entry = dict(raw_value or {})
        current_value = _coerce_float(entry.get("current_value"))
        if current_value is None:
            continue
        observations[str(subject_id)] = ValuationObservation(
            subject_id=str(subject_id),
            metric_name=str(entry.get("metric_name") or entry.get("metric") or "pe_ttm"),
            current_value=current_value,
            source_ref=str(entry.get("source_ref") or f"valuation:{subject_id}"),
            as_of=str(entry.get("as_of") or ""),
            data_status=coerce_data_status(entry.get("data_status") or DataStatus.OBSERVED),
            audit_window=AuditWindow.from_any(entry.get("audit_window")),
        )
    return observations


def _percentile(values: list[float], current_value: float) -> float:
    if not values:
        return 0.5
    count = sum(1 for value in values if value <= current_value)
    return max(0.0, min(1.0, count / len(values)))


def _valuation_position(percentile: float) -> str:
    if percentile >= 0.95:
        return "extreme"
    if percentile >= 0.70:
        return "rich"
    if percentile <= 0.30:
        return "cheap"
    return "fair"


def build_valuation_percentile_results(
    *,
    buckets: list[str],
    observed_inputs: dict[str, Any] | None,
    valuation_z_scores: dict[str, Any] | None,
    as_of: str,
) -> dict[str, ValuationPercentileResult]:
    observations = coerce_valuation_observations(observed_inputs)
    z_scores = dict(valuation_z_scores or {})
    results: dict[str, ValuationPercentileResult] = {}

    for bucket in buckets:
        observation = observations.get(bucket)
        if observation is not None:
            raw_history = list((observed_inputs or {}).get(bucket, {}).get("history_values") or [])
            history_values = [value for value in (_coerce_float(item) for item in raw_history) if value is not None]
            percentile = _percentile(history_values, observation.current_value)
            results[bucket] = ValuationPercentileResult(
                subject_id=bucket,
                metric_name=observation.metric_name,
                current_value=observation.current_value,
                percentile=percentile,
                valuation_position=_valuation_position(percentile),
                source_ref=observation.source_ref,
                as_of=observation.as_of or as_of,
                data_status=observation.data_status,
                audit_window=observation.audit_window,
            )
            continue

        z_score = _coerce_float(z_scores.get(bucket))
        if z_score is not None:
            percentile = max(0.0, min(1.0, 0.5 + (z_score / 3.0)))
            results[bucket] = ValuationPercentileResult(
                subject_id=bucket,
                metric_name="valuation_z_score",
                current_value=z_score,
                percentile=percentile,
                valuation_position=_valuation_position(percentile),
                source_ref="market_raw.valuation_z_scores",
                as_of=as_of,
                data_status=DataStatus.INFERRED,
                audit_window=None,
            )
            continue

        results[bucket] = ValuationPercentileResult(
            subject_id=bucket,
            metric_name="valuation_prior_default",
            current_value=None,
            percentile=0.5,
            valuation_position="fair",
            source_ref="calibration:valuation_prior_default",
            as_of=as_of,
            data_status=DataStatus.PRIOR_DEFAULT,
            audit_window=None,
        )
    return results


__all__ = [
    "ValuationObservation",
    "ValuationPercentileResult",
    "build_valuation_percentile_results",
    "coerce_valuation_observations",
]
