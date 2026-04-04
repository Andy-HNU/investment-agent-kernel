from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CompletenessLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"


@dataclass
class QualityFlag:
    code: str
    severity: str
    domain: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyNewsSignal:
    signal_id: str
    as_of: str
    source_type: str
    source_refs: list[str]
    source_name: str | None = None
    published_at: str | None = None
    policy_regime: str | None = None
    macro_uncertainty: str | None = None
    sentiment_stress: str | None = None
    liquidity_stress: str | None = None
    direction: str | None = None
    strength: float = 0.0
    manual_review_required: bool = False
    confidence: float = 0.0
    decay_half_life_days: float | None = None
    recency_days: float | None = None
    decay_weight: float | None = None
    target_buckets: list[str] = field(default_factory=list)
    target_tags: list[str] = field(default_factory=list)
    target_products: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotBundle:
    bundle_id: str
    account_profile_id: str
    created_at: Any
    market: dict[str, Any]
    account: dict[str, Any]
    goal: dict[str, Any]
    constraint: dict[str, Any]
    behavior: dict[str, Any] | None
    bundle_quality: CompletenessLevel
    missing_domains: list[str] = field(default_factory=list)
    quality_summary: list[QualityFlag] = field(default_factory=list)
    policy_news_signals: list[PolicyNewsSignal] = field(default_factory=list)
    historical_dataset_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v1.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bundle_quality"] = self.bundle_quality.value
        data["quality_summary"] = [flag.to_dict() for flag in self.quality_summary]
        data["policy_news_signals"] = [signal.to_dict() for signal in self.policy_news_signals]
        return data
