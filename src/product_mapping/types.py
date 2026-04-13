from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Literal

from shared.audit import AuditWindow


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
    valuation_mode: str | None = None
    source_name: str | None = None
    source_ref: str | None = None
    as_of: str | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    percentile: float | None = None
    data_status: str | None = None
    audit_window: AuditWindow | None = None
    passed_filters: bool | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductUniverseItem:
    product_id: str
    ts_code: str | None
    wrapper: str
    asset_bucket: str
    market: str
    region: str | None
    theme_tags: list[str] = field(default_factory=list)
    risk_labels: list[str] = field(default_factory=list)
    source_ref: str = ""
    data_status: str = "manual_annotation"
    as_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductUniverseSnapshot:
    snapshot_id: str
    as_of: str
    source_name: str
    source_ref: str
    data_status: str
    item_count: int
    items: list[ProductUniverseItem] = field(default_factory=list)
    audit_window: AuditWindow | None = None
    source_names: list[str] = field(default_factory=list)
    wrapper_counts: dict[str, int] = field(default_factory=dict)
    asset_bucket_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductProxySpec:
    product_id: str
    proxy_kind: str
    proxy_ref: str
    confidence: float
    confidence_data_status: str
    confidence_disclosure: str
    source_ref: str
    data_status: str
    as_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProxyUniverseSummary:
    solving_mode: str
    proxy_scope: str = "selected_plan_items"
    covered_asset_buckets: list[str] = field(default_factory=list)
    uncovered_asset_buckets: list[str] = field(default_factory=list)
    covered_regions: list[str] = field(default_factory=list)
    product_proxy_count: int = 0
    runtime_candidate_proxy_count: int = 0
    data_status: str = "manual_annotation"
    claims_real_product_history: bool = False
    disclosure: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class UserPortfolioResolutionItem:
    product_id: str
    requested_weight: float | None
    product_state: Literal["recognized", "unrecognized_product"]
    resolution_state: Literal[
        "recognized",
        "unrecognized_requires_user_action",
        "user_selected_proxy",
        "user_excluded_product",
        "estimated_non_formal_allowed",
        "resolved_formal_ready",
    ]
    entered_product_name: str | None = None
    selected_proxy_product_id: str | None = None
    selected_proxy_product_name: str | None = None
    suggested_proxy_product_ids: list[str] = field(default_factory=list)
    allowed_next_actions: list[str] = field(default_factory=list)
    strict_formal_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class PortfolioEvaluationSummary:
    evaluation_mode: Literal["system_recommended_portfolio", "user_specified_portfolio"]
    requested_structure_visibility: dict[str, Any] = field(default_factory=dict)
    requested_structure: dict[str, Any] = field(default_factory=dict)
    unknown_product_resolution_state: Literal[
        "recognized",
        "unrecognized_requires_user_action",
        "user_selected_proxy",
        "user_excluded_product",
        "estimated_non_formal_allowed",
        "resolved_formal_ready",
    ] = "recognized"
    unknown_product_resolution_items: list[UserPortfolioResolutionItem] = field(default_factory=list)
    strict_formal_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(asdict(self))
        payload["unknown_product_resolution"] = {
            "state": payload.pop("unknown_product_resolution_state"),
            "items": payload.pop("unknown_product_resolution_items"),
            "strict_formal_blocked": payload.pop("strict_formal_blocked"),
        }
        return payload


@dataclass(frozen=True)
class ExecutionRealismSummary:
    executable: bool
    account_total_value: float | None = None
    available_cash: float | None = None
    cash_reserve_target_amount: float | None = None
    initial_buy_amount: float | None = None
    initial_sell_amount: float | None = None
    fundable_initial_cash: float | None = None
    minimum_trade_amount: float | None = None
    total_target_amount: float | None = None
    cash_target_amount: float | None = None
    amount_closure_delta: float | None = None
    estimated_total_fee: float | None = None
    estimated_total_slippage: float | None = None
    execution_cost_data_status: str | None = None
    execution_cost_disclosure: str | None = None
    tax_estimate_status: str | None = None
    tiny_trade_buckets: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class RuntimeProductCandidate:
    candidate: ProductCandidate
    registry_index: int
    filter_stage: str = "runtime_pool"
    filter_reason: str | None = None
    proxy_spec: ProductProxySpec | None = None
    valuation_audit: ProductValuationAudit | None = None
    policy_news_audit: "ProductPolicyNewsAudit | None" = None

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
    product_universe_audit_summary: dict[str, Any] = field(default_factory=dict)
    valuation_audit_summary: dict[str, Any] = field(default_factory=dict)
    policy_news_audit_summary: dict[str, Any] = field(default_factory=dict)
    formal_path_preflight: dict[str, Any] = field(default_factory=dict)
    failure_artifact: dict[str, Any] | None = None

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
    policy_news_audit: "ProductPolicyNewsAudit | None" = None
    current_weight: float | None = None
    current_amount: float | None = None
    target_amount: float | None = None
    trade_direction: Literal["buy", "sell", "hold"] | None = None
    trade_amount: float | None = None
    initial_trade_amount: float | None = None
    deferred_trade_amount: float | None = None
    estimated_fee: float | None = None
    estimated_slippage: float | None = None
    violates_minimum_trade: bool = False
    trigger_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductPolicyNewsAudit:
    status: Literal["observed", "missing_materials", "unavailable", "not_applicable"]
    realtime_eligible: bool
    influence_scope: Literal["satellite_dynamic", "core_mild", "none"] = "none"
    data_status: str | None = None
    confidence_data_status: str | None = None
    source_name: str | None = None
    source_refs: list[str] = field(default_factory=list)
    latest_as_of: str | None = None
    latest_published_at: str | None = None
    recency_days: float | None = None
    decay_weight: float | None = None
    matched_signal_ids: list[str] = field(default_factory=list)
    matched_tags: list[str] = field(default_factory=list)
    score: float = 0.0
    dominant_direction: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass
class ExecutionPlan:
    plan_id: str
    source_run_id: str
    source_allocation_id: str
    status: Literal["draft", "user_review", "approved", "superseded", "cancelled"] = "draft"
    items: list[ExecutionPlanItem] = field(default_factory=list)
    bucket_construction_explanations: dict[str, "BucketConstructionExplanation"] = field(default_factory=dict)
    bucket_construction_suggestions: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    confirmation_required: bool = True
    plan_version: int = 1
    approved_at: str | None = None
    superseded_by_plan_id: str | None = None
    registry_candidate_count: int = 0
    runtime_candidate_count: int = 0
    runtime_candidates: list[RuntimeProductCandidate] = field(default_factory=list)
    product_proxy_specs: list[ProductProxySpec] = field(default_factory=list)
    proxy_universe_summary: ProxyUniverseSummary | None = None
    execution_realism_summary: ExecutionRealismSummary | None = None
    maintenance_policy_summary: dict[str, Any] = field(default_factory=dict)
    candidate_filter_breakdown: CandidateFilterBreakdown | None = None
    valuation_audit_summary: dict[str, Any] = field(default_factory=dict)
    policy_news_audit_summary: dict[str, Any] = field(default_factory=dict)
    formal_path_preflight: dict[str, Any] = field(default_factory=dict)
    failure_artifact: dict[str, Any] | None = None

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
            "bucket_construction_explanations": {
                bucket: explanation.to_dict()
                for bucket, explanation in sorted((self.bucket_construction_explanations or {}).items())
            },
            "bucket_construction_suggestions": dict(self.bucket_construction_suggestions or {}),
            "confirmation_required": self.confirmation_required,
            "warning_count": len(self.warnings),
            "approved_at": self.approved_at,
            "superseded_by_plan_id": self.superseded_by_plan_id,
            "registry_candidate_count": self.registry_candidate_count,
            "runtime_candidate_count": self.runtime_candidate_count,
            "product_proxy_specs": [spec.to_dict() for spec in self.product_proxy_specs],
            "proxy_universe_summary": (
                self.proxy_universe_summary.to_dict() if self.proxy_universe_summary is not None else {}
            ),
            "execution_realism_summary": (
                self.execution_realism_summary.to_dict() if self.execution_realism_summary is not None else {}
            ),
            "maintenance_policy_summary": dict(self.maintenance_policy_summary or {}),
            "candidate_filter_dropped_reasons": dict(breakdown.dropped_reasons),
            "candidate_filter_stages": [stage.to_dict() for stage in breakdown.stages],
            "product_universe_audit_summary": dict(breakdown.product_universe_audit_summary or {}),
            "valuation_audit_summary": dict(self.valuation_audit_summary or breakdown.valuation_audit_summary or {}),
            "policy_news_audit_summary": dict(
                self.policy_news_audit_summary or breakdown.policy_news_audit_summary or {}
            ),
            "formal_path_preflight": dict(self.formal_path_preflight or breakdown.formal_path_preflight or {}),
            "failure_artifact": dict(self.failure_artifact or breakdown.failure_artifact or {}),
        }


@dataclass(frozen=True)
class SearchExpansionRecommendation:
    search_expansion_level: str
    why_this_level_was_run: str
    why_search_stopped: str | None
    new_product_ids_added: list[str] = field(default_factory=list)
    products_removed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


from .cardinality import BucketCardinalityPreference, BucketCountResolution
from .explanations import (
    BucketConstructionExplanation,
    ProductExplanation,
    ProductGroupExplanation,
    ProductScenarioMetrics,
)
