from .catalog import load_builtin_catalog
from .selection import normalize_user_restrictions
from .types import ExecutionPlan, ExecutionPlanItem, ProductCandidate, ProductConstraintProfile, RecommendedProduct


def build_execution_plan(*args, **kwargs):
    from .engine import build_execution_plan as _build_execution_plan

    return _build_execution_plan(*args, **kwargs)

__all__ = [
    "ExecutionPlan",
    "ExecutionPlanItem",
    "ProductCandidate",
    "ProductConstraintProfile",
    "RecommendedProduct",
    "build_execution_plan",
    "load_builtin_catalog",
    "normalize_user_restrictions",
]
