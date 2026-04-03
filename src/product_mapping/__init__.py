from .catalog import load_builtin_catalog
from .maintenance import build_quarterly_execution_policy, derive_budget_structure
from .selection import normalize_user_restrictions
from .types import (
    BudgetStructure,
    ExecutionPlan,
    ExecutionPlanItem,
    ProductCandidate,
    ProductConstraintProfile,
    QuarterlyExecutionPolicy,
    RecommendedProduct,
    TriggerRule,
)


def build_execution_plan(*args, **kwargs):
    from .engine import build_execution_plan as _build_execution_plan

    return _build_execution_plan(*args, **kwargs)

__all__ = [
    "ExecutionPlan",
    "ExecutionPlanItem",
    "BudgetStructure",
    "ProductCandidate",
    "ProductConstraintProfile",
    "QuarterlyExecutionPolicy",
    "RecommendedProduct",
    "TriggerRule",
    "build_execution_plan",
    "build_quarterly_execution_policy",
    "derive_budget_structure",
    "load_builtin_catalog",
    "normalize_user_restrictions",
]
