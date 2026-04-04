from .catalog import load_builtin_catalog
from .types import ExecutionPlan, ExecutionPlanItem, ProductCandidate, ProductProxySpec, ProxyUniverseSummary


def build_execution_plan(*args, **kwargs):
    from .engine import build_execution_plan as _build_execution_plan

    return _build_execution_plan(*args, **kwargs)

__all__ = [
    "ExecutionPlan",
    "ExecutionPlanItem",
    "ProductCandidate",
    "ProductProxySpec",
    "ProxyUniverseSummary",
    "build_execution_plan",
    "load_builtin_catalog",
]
