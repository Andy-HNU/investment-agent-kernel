from .catalog import load_builtin_catalog
from .types import ExecutionPlan, ExecutionPlanItem, ProductCandidate, ProductProxySpec, ProxyUniverseSummary


def build_execution_plan(*args, **kwargs):
    from .engine import build_execution_plan as _build_execution_plan

    return _build_execution_plan(*args, **kwargs)


def build_candidate_product_context(*args, **kwargs):
    from .engine import build_candidate_product_context as _build_candidate_product_context

    return _build_candidate_product_context(*args, **kwargs)

__all__ = [
    "ExecutionPlan",
    "ExecutionPlanItem",
    "ProductCandidate",
    "ProductProxySpec",
    "ProxyUniverseSummary",
    "build_candidate_product_context",
    "build_execution_plan",
    "load_builtin_catalog",
]
