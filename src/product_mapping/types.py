from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Literal


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    return value


@dataclass(frozen=True)
class ProductCandidate:
    product_id: str
    product_name: str
    asset_bucket: str
    product_family: str
    wrapper_type: Literal["etf", "fund", "bond", "cash_mgmt", "stock", "other"]
    provider_source: str
    provider_symbol: str | None = None
    region: str = "CN"
    currency: str = "CNY"
    liquidity_tier: Literal["high", "medium", "low"] = "high"
    fee_tier: Literal["low", "medium", "high"] = "low"
    enabled: bool = True
    deprecated: bool = False
    deprecation_reason: str | None = None
    tags: list[str] = field(default_factory=list)
    risk_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductValuationAudit:
    status: Literal["observed", "missing_source", "missing_metrics", "not_applicable"]
    source_name: str | None = None
    source_ref: str | None = None
    as_of: str | None = None
    pe_ratio: float | None = None
    percentile: float | None = None
    passed_filters: bool | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class RuntimeProductCandidate:
    candidate: ProductCandidate
    registry_index: int
    filter_stage: str = "runtime_pool"
    filter_reason: str | None = None
    valuation_audit: ProductValuationAudit | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CandidateFilterStage:
    stage_name: str
    input_count: int
    output_count: int
    dropped_reasons: dict[str, int] = field(default_factory=dict)
    audit_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CandidateFilterBreakdown:
    registry_candidate_count: int
    runtime_candidate_count: int
    stages: list[CandidateFilterStage] = field(default_factory=list)
    dropped_reasons: dict[str, int] = field(default_factory=dict)
    valuation_audit_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass
class ExecutionPlanItem:
    asset_bucket: str
    target_weight: float
    primary_product_id: str
    alternate_product_ids: list[str]
    rationale: list[str]
    risk_labels: list[str]
    primary_product: ProductCandidate
    alternate_products: list[ProductCandidate] = field(default_factory=list)
    valuation_audit: ProductValuationAudit | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass
class ExecutionPlan:
    plan_id: str
    source_run_id: str
    source_allocation_id: str
    status: Literal["draft", "user_review", "approved", "superseded", "cancelled"] = "draft"
    items: list[ExecutionPlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confirmation_required: bool = True
    plan_version: int = 1
    approved_at: str | None = None
    superseded_by_plan_id: str | None = None
    registry_candidate_count: int = 0
    runtime_candidate_count: int = 0
    runtime_candidates: list[RuntimeProductCandidate] = field(default_factory=list)
    candidate_filter_breakdown: CandidateFilterBreakdown | None = None
    valuation_audit_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    def is_active(self) -> bool:
        return self.status in {"draft", "user_review", "approved"}

    def summary(self) -> dict[str, Any]:
        breakdown = self.candidate_filter_breakdown or CandidateFilterBreakdown(
            registry_candidate_count=self.registry_candidate_count,
            runtime_candidate_count=self.runtime_candidate_count,
        )
        return {
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "source_run_id": self.source_run_id,
            "source_allocation_id": self.source_allocation_id,
            "status": self.status,
            "item_count": len(self.items),
            "confirmation_required": self.confirmation_required,
            "warning_count": len(self.warnings),
            "approved_at": self.approved_at,
            "superseded_by_plan_id": self.superseded_by_plan_id,
            "registry_candidate_count": self.registry_candidate_count,
            "runtime_candidate_count": self.runtime_candidate_count,
            "candidate_filter_dropped_reasons": dict(breakdown.dropped_reasons),
            "candidate_filter_stages": [stage.to_dict() for stage in breakdown.stages],
            "valuation_audit_summary": dict(self.valuation_audit_summary or breakdown.valuation_audit_summary or {}),
        }
