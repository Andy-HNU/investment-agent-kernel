"""Shared utility namespace for audit helpers and lazy demo utilities."""

from .audit import (
    AuditRecord,
    AuditWindow,
    CoverageSummary,
    DataStatus,
    DisclosureDecision,
    EvidenceBundle,
    FormalPathStatus,
    FormalPathVisibility,
    RunOutcomeStatus,
    coerce_data_status,
    coerce_formal_path_status,
    coerce_run_outcome_status,
)


_DEMO_FLOW_EXPORTS = {
    "build_demo_allocation_input",
    "build_demo_behavior_raw",
    "build_demo_constraint_raw",
    "build_demo_goal_raw",
    "build_demo_goal_solver_input",
    "build_demo_live_portfolio",
    "build_demo_market_raw",
    "run_demo_journey",
    "run_demo_monthly_replay_override",
    "run_demo_onboarding",
    "run_demo_provenance_bypass",
    "run_demo_quarterly_review",
    "serialize_demo_journey",
}

_DEMO_SCENARIO_EXPORTS = {
    "CANONICAL_DEMO_SCENARIOS",
    "DEMO_SCENARIO_ALIASES",
    "DEMO_SCENARIOS",
    "build_demo_report",
    "normalize_demo_scenario_name",
    "render_demo_report",
    "run_demo_lifecycle",
    "run_demo_monthly_followup",
    "run_demo_provenance_blocked",
    "run_demo_provenance_relaxed",
    "summarize_demo_lifecycle",
}

__all__ = [
    "AuditRecord",
    "AuditWindow",
    "CoverageSummary",
    "DataStatus",
    "DisclosureDecision",
    "EvidenceBundle",
    "FormalPathStatus",
    "FormalPathVisibility",
    "RunOutcomeStatus",
    "coerce_data_status",
    "coerce_formal_path_status",
    "coerce_run_outcome_status",
]
__all__.extend(sorted(_DEMO_FLOW_EXPORTS))
__all__.extend(sorted(_DEMO_SCENARIO_EXPORTS))


def __getattr__(name: str):
    if name in _DEMO_FLOW_EXPORTS:
        from . import demo_flow as _demo_flow

        return getattr(_demo_flow, name)
    if name in _DEMO_SCENARIO_EXPORTS:
        from . import demo_scenarios as _demo_scenarios

        return getattr(_demo_scenarios, name)
    raise AttributeError(name)
