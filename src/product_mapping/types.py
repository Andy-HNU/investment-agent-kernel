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
    if isinstance(value, set):
        return sorted(_serialize(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    return value


@dataclass(frozen=True)
class ProductCandidate:
    product_id: str
    product_name: str
    asset_bucket: str
    product_family: str
    wrapper_type: Literal["etf", "fund", "bond", "cash_mgmt", "single_stock", "savings", "other"]
    provider_source: str
    provider_symbol: str | None = None
    region: str = "CN"
    currency: str = "CNY"
    market: str = "CN"
    liquidity_tier: Literal["high", "medium", "low"] = "high"
    fee_tier: Literal["low", "medium", "high"] = "low"
    tracking_quality: Literal["high", "medium", "low"] = "medium"
    valuation_percentile: float | None = None
    policy_news_score: float | None = None
    core_or_satellite: Literal["core", "satellite", "defense", "cash"] = "core"
    enabled: bool = True
    deprecated: bool = False
    deprecation_reason: str | None = None
    tags: list[str] = field(default_factory=list)
    style_tags: list[str] = field(default_factory=list)
    risk_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductConstraintProfile:
    forbidden_exposures: set[str] = field(default_factory=set)
    forbidden_wrappers: set[str] = field(default_factory=set)
    forbidden_styles: set[str] = field(default_factory=set)
    allowed_wrappers: set[str] = field(default_factory=set)
    allowed_markets: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class RecommendedProduct:
    product_id: str
    product_name: str
    wrapper_type: str
    market: str
    core_or_satellite: str
    target_weight_within_bucket: float
    target_portfolio_weight: float
    selection_reason: list[str] = field(default_factory=list)
    style_tags: list[str] = field(default_factory=list)
    product: ProductCandidate | None = None

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
    recommended_products: list[RecommendedProduct] = field(default_factory=list)
    selection_evidence: dict[str, Any] = field(default_factory=dict)

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

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    def is_active(self) -> bool:
        return self.status in {"draft", "user_review", "approved"}

    def summary(self) -> dict[str, Any]:
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
        }
