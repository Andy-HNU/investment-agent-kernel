from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from product_mapping.types import ProductPolicyNewsAudit, RuntimeProductCandidate
from shared.audit import DataStatus
from snapshot_ingestion.types import PolicyNewsSignal


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_recency_days(as_of: str | None, published_at: str | None) -> float | None:
    as_of_dt = _parse_iso_datetime(as_of)
    published_dt = _parse_iso_datetime(published_at)
    if as_of_dt is None or published_dt is None:
        return None
    return max((as_of_dt - published_dt).total_seconds() / 86400.0, 0.0)


def _compute_decay_weight(recency_days: float | None, decay_half_life_days: float | None) -> float | None:
    if recency_days is None or decay_half_life_days is None or decay_half_life_days <= 0:
        return None
    return 0.5 ** (recency_days / decay_half_life_days)


def _to_signal(payload: PolicyNewsSignal | dict[str, Any]) -> PolicyNewsSignal:
    if isinstance(payload, PolicyNewsSignal):
        return payload
    data = dict(payload or {})
    recency_days = float(data.get("recency_days")) if data.get("recency_days") is not None else None
    if recency_days is None:
        recency_days = _compute_recency_days(data.get("as_of"), data.get("published_at"))
    decay_half_life_days = float(data.get("decay_half_life_days", 7.0) or 7.0)
    decay_weight = float(data.get("decay_weight")) if data.get("decay_weight") is not None else None
    if decay_weight is None:
        decay_weight = _compute_decay_weight(recency_days, decay_half_life_days)
    return PolicyNewsSignal(
        signal_id=str(data.get("signal_id") or data.get("id") or "policy_signal"),
        as_of=str(data.get("as_of") or ""),
        source_type=str(data.get("source_type") or "analysis"),
        source_refs=[str(item) for item in list(data.get("source_refs") or []) if str(item).strip()],
        source_name=data.get("source_name"),
        published_at=data.get("published_at"),
        policy_regime=data.get("policy_regime"),
        macro_uncertainty=data.get("macro_uncertainty"),
        sentiment_stress=data.get("sentiment_stress"),
        liquidity_stress=data.get("liquidity_stress"),
        direction=data.get("direction"),
        strength=float(data.get("strength", 0.0) or 0.0),
        manual_review_required=bool(data.get("manual_review_required", False)),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        decay_half_life_days=decay_half_life_days,
        recency_days=recency_days,
        decay_weight=decay_weight,
        target_buckets=[str(item) for item in list(data.get("target_buckets") or []) if str(item).strip()],
        target_tags=[str(item) for item in list(data.get("target_tags") or []) if str(item).strip()],
        target_products=[str(item) for item in list(data.get("target_products") or []) if str(item).strip()],
        notes=[str(item) for item in list(data.get("notes") or []) if str(item).strip()],
    )


def _is_realtime_eligible(signal: PolicyNewsSignal) -> bool:
    return bool(signal.source_refs and signal.published_at and signal.confidence > 0.0)


def _direction_sign(direction: str | None) -> float:
    rendered = str(direction or "").strip().lower()
    if rendered in {"bullish", "positive", "positive_bias"}:
        return 1.0
    if rendered in {"bearish", "negative", "negative_bias"}:
        return -1.0
    return 0.0


def _relevance(signal: PolicyNewsSignal, candidate: RuntimeProductCandidate) -> tuple[float, list[str]]:
    bucket = candidate.candidate.asset_bucket
    tags = {str(tag).strip().lower() for tag in candidate.candidate.tags}
    signal_tags = {str(tag).strip().lower() for tag in signal.target_tags}
    signal_buckets = {str(item).strip() for item in signal.target_buckets}
    matched_tags = sorted(tags & signal_tags)
    if signal.target_products and candidate.candidate.product_id in signal.target_products:
        return 1.0, matched_tags
    if signal_tags:
        if matched_tags:
            return (0.9 if signal_buckets and bucket in signal_buckets else 0.8), matched_tags
        return 0.0, []
    if signal_buckets and bucket in signal_buckets:
        return 0.7, matched_tags
    if matched_tags:
        return 0.8, matched_tags
    return 0.0, []


def apply_policy_news_scores(
    runtime_candidates: list[RuntimeProductCandidate],
    policy_news_signals: list[PolicyNewsSignal | dict[str, Any]] | None,
) -> tuple[list[RuntimeProductCandidate], dict[str, Any]]:
    signals = [_to_signal(item) for item in list(policy_news_signals or [])]
    observed_signals = [signal for signal in signals if _is_realtime_eligible(signal)]

    if not signals:
        return runtime_candidates, {
            "source_status": "unavailable",
            "realtime_eligible": False,
            "matched_signal_count": 0,
            "core_influence_capped": False,
        }

    if not observed_signals:
        audited_candidates = [
            replace(
                candidate,
                policy_news_audit=ProductPolicyNewsAudit(
                    status="missing_materials",
                    realtime_eligible=False,
                    data_status=DataStatus.MANUAL_ANNOTATION.value,
                    confidence_data_status=DataStatus.MANUAL_ANNOTATION.value,
                    notes=["policy/news signals exist but no real source materials were available"],
                ),
            )
            for candidate in runtime_candidates
        ]
        return audited_candidates, {
            "source_status": "missing_materials",
            "realtime_eligible": False,
            "matched_signal_count": 0,
            "core_influence_capped": False,
        }

    scored_candidates: list[RuntimeProductCandidate] = []
    latest_published_at = max((signal.published_at or "" for signal in observed_signals), default=None)
    latest_as_of = max((signal.as_of or "" for signal in observed_signals), default=None)
    latest_recency_days = max(
        (float(signal.recency_days) for signal in observed_signals if signal.recency_days is not None),
        default=None,
    )
    latest_decay_weight = min(
        (float(signal.decay_weight) for signal in observed_signals if signal.decay_weight is not None),
        default=None,
    )
    source_refs = sorted({ref for signal in observed_signals for ref in signal.source_refs})
    source_names = sorted({str(signal.source_name or "").strip() for signal in observed_signals if str(signal.source_name or "").strip()})
    core_influence_capped = False
    matched_signal_count = 0

    for runtime_candidate in runtime_candidates:
        total_score = 0.0
        matched_signal_ids: list[str] = []
        matched_tags: list[str] = []
        directions: list[str] = []
        matched_recencies: list[float] = []
        matched_decays: list[float] = []
        for signal in observed_signals:
            relevance, signal_tags = _relevance(signal, runtime_candidate)
            if relevance <= 0:
                continue
            matched_signal_ids.append(signal.signal_id)
            matched_tags.extend(signal_tags)
            if signal.direction:
                directions.append(str(signal.direction))
            if signal.recency_days is not None:
                matched_recencies.append(float(signal.recency_days))
            if signal.decay_weight is not None:
                matched_decays.append(float(signal.decay_weight))
            decay = signal.decay_weight if signal.decay_weight is not None else 1.0
            raw_score = _direction_sign(signal.direction) * float(signal.strength or 0.0) * float(signal.confidence or 0.0) * float(decay) * relevance
            if runtime_candidate.candidate.asset_bucket == "satellite":
                total_score += raw_score
            else:
                total_score += raw_score * 0.2
                if raw_score:
                    core_influence_capped = True
        if matched_signal_ids:
            matched_signal_count += len(matched_signal_ids)
            influence_scope = "satellite_dynamic" if runtime_candidate.candidate.asset_bucket == "satellite" else "core_mild"
            status = "observed"
            notes = [f"matched {len(matched_signal_ids)} observed policy/news signals"]
        else:
            influence_scope = "none"
            status = "not_applicable"
            notes = ["no policy/news signals matched this product"]
        dominant_direction = directions[0] if directions else None
        scored_candidates.append(
            replace(
                runtime_candidate,
                policy_news_audit=ProductPolicyNewsAudit(
                    status=status,
                    realtime_eligible=True,
                    influence_scope=influence_scope,
                    data_status=DataStatus.COMPUTED_FROM_OBSERVED.value if matched_signal_ids else DataStatus.OBSERVED.value,
                    confidence_data_status=DataStatus.INFERRED.value if matched_signal_ids else DataStatus.OBSERVED.value,
                    source_name=",".join(source_names) or None,
                    source_refs=source_refs,
                    latest_as_of=latest_as_of,
                    latest_published_at=latest_published_at,
                    recency_days=max(matched_recencies) if matched_recencies else None,
                    decay_weight=min(matched_decays) if matched_decays else None,
                    matched_signal_ids=matched_signal_ids,
                    matched_tags=sorted(set(matched_tags)),
                    score=round(total_score, 6),
                    dominant_direction=dominant_direction,
                    notes=notes,
                ),
            )
        )

    return scored_candidates, {
        "source_status": "observed",
        "realtime_eligible": True,
        "matched_signal_count": matched_signal_count,
        "latest_published_at": latest_published_at,
        "latest_as_of": latest_as_of,
        "data_status": DataStatus.COMPUTED_FROM_OBSERVED.value,
        "confidence_data_status": DataStatus.INFERRED.value,
        "source_refs": source_refs,
        "source_names": source_names,
        "core_influence_capped": core_influence_capped,
    }
