from .catalog import load_builtin_catalog
from .cardinality import resolve_bucket_count
from .explanations import validate_product_scenario_metrics
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
    "build_candidate_product_context",
    "build_execution_plan",
    "load_builtin_catalog",
    "resolve_bucket_count",
    "validate_product_scenario_metrics",
]
