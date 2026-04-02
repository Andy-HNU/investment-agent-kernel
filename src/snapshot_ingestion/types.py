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
    policy_regime: str | None = None
    macro_uncertainty: str | None = None
    sentiment_stress: str | None = None
    liquidity_stress: str | None = None
    manual_review_required: bool = False
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalReturnPanelRaw:
    dataset_id: str
    version_id: str
    as_of: str
    source_name: str
    lookback_months: int
    return_series: dict[str, list[float]]
    source_ref: str | None = None
    coverage_status: str = "raw"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimeFeatureSnapshotRaw:
    snapshot_id: str
    as_of: str
    feature_values: dict[str, float]
    inferred_regime: str | None = None
    source_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JumpEventHistoryRaw:
    history_id: str
    as_of: str
    events: list[dict[str, Any]]
    source_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BucketProxyMappingRaw:
    mapping_id: str
    as_of: str
    bucket_to_proxy: dict[str, str]
    proxy_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    historical_return_panel: HistoricalReturnPanelRaw | dict[str, Any] | None = None
    regime_feature_snapshot: RegimeFeatureSnapshotRaw | dict[str, Any] | None = None
    jump_event_history: JumpEventHistoryRaw | dict[str, Any] | None = None
    bucket_proxy_mapping: BucketProxyMappingRaw | dict[str, Any] | None = None
    schema_version: str = "v1.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bundle_quality"] = self.bundle_quality.value
        data["quality_summary"] = [flag.to_dict() for flag in self.quality_summary]
        data["policy_news_signals"] = [signal.to_dict() for signal in self.policy_news_signals]
        return data
