from .catalog import load_builtin_catalog
from .cardinality import resolve_bucket_count
from .explanations import build_portfolio_explanation_surfaces, validate_product_scenario_metrics
from .search_expansion import candidate_pool_limit, normalize_search_expansion_level, resolve_search_stop_reason
from .types import (
    BucketCardinalityPreference,
    BucketConstructionExplanation,
    BucketCountResolution,
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    ProductExplanation,
    ProductGroupExplanation,
    ProductProxySpec,
    ProductScenarioMetrics,
    ProxyUniverseSummary,
    SearchExpansionRecommendation,
)


def build_execution_plan(*args, **kwargs):
    from .engine import build_execution_plan as _build_execution_plan

    return _build_execution_plan(*args, **kwargs)


def build_candidate_product_context(*args, **kwargs):
    from .engine import build_candidate_product_context as _build_candidate_product_context

    return _build_candidate_product_context(*args, **kwargs)


__all__ = [
    "BucketCardinalityPreference",
    "BucketConstructionExplanation",
    "BucketCountResolution",
    "ExecutionPlan",
    "ExecutionPlanItem",
    "ProductCandidate",
    "ProductExplanation",
    "ProductGroupExplanation",
    "ProductProxySpec",
    "ProductScenarioMetrics",
    "ProxyUniverseSummary",
    "SearchExpansionRecommendation",
    "build_candidate_product_context",
    "build_execution_plan",
    "build_portfolio_explanation_surfaces",
    "candidate_pool_limit",
    "load_builtin_catalog",
    "normalize_search_expansion_level",
    "resolve_bucket_count",
    "resolve_search_stop_reason",
    "validate_product_scenario_metrics",
]
