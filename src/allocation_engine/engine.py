from __future__ import annotations

from typing import Any

from allocation_engine.complexity import build_strategic_allocation
from allocation_engine.dedup import (
    deduplicate_candidate_pairs,
    stable_sort_candidate_pairs,
    trim_candidate_pairs,
)
from allocation_engine.generator import instantiate_template
from allocation_engine.projection import project_to_constraints
from allocation_engine.templates import build_template_family
from allocation_engine.types import (
    AllocationEngineInput,
    AllocationEngineParams,
    AllocationEngineResult,
    AllocationProfile,
    AllocationTemplate,
    AllocationUniverse,
    CandidateDiagnostics,
)
from allocation_engine.validator import validate_allocation_input, validate_candidate
from goal_solver.types import (
    AccountConstraints,
    CashFlowEvent,
    CashFlowPlan,
    GoalCard,
    StrategicAllocation,
)


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _goal_from_any(value: GoalCard | dict[str, Any]) -> GoalCard:
    if isinstance(value, GoalCard):
        return value
    return GoalCard(**dict(_obj(value)))


def _cashflow_plan_from_any(value: CashFlowPlan | dict[str, Any]) -> CashFlowPlan:
    if isinstance(value, CashFlowPlan):
        return value
    data = dict(_obj(value))
    events = [CashFlowEvent(**dict(_obj(event))) for event in data.get("cashflow_events", [])]
    return CashFlowPlan(
        monthly_contribution=float(data["monthly_contribution"]),
        annual_step_up_rate=float(data["annual_step_up_rate"]),
        cashflow_events=events,
    )


def _constraints_from_any(value: AccountConstraints | dict[str, Any]) -> AccountConstraints:
    if isinstance(value, AccountConstraints):
        return value
    data = dict(_obj(value))
    return AccountConstraints(
        max_drawdown_tolerance=float(data["max_drawdown_tolerance"]),
        ips_bucket_boundaries={
            key: tuple(bounds)
            for key, bounds in dict(data["ips_bucket_boundaries"]).items()
        },
        satellite_cap=float(data["satellite_cap"]),
        theme_caps=dict(data.get("theme_caps", {})),
        qdii_cap=float(data.get("qdii_cap", 0.0)),
        liquidity_reserve_min=float(data.get("liquidity_reserve_min", 0.0)),
        bucket_category=dict(data.get("bucket_category", {})),
        bucket_to_theme=dict(data.get("bucket_to_theme", {})),
    )


def _profile_from_any(value: AllocationProfile | dict[str, Any]) -> AllocationProfile:
    if isinstance(value, AllocationProfile):
        return value
    return AllocationProfile(**dict(_obj(value)))


def _universe_from_any(value: AllocationUniverse | dict[str, Any]) -> AllocationUniverse:
    if isinstance(value, AllocationUniverse):
        return value
    return AllocationUniverse(**dict(_obj(value)))


def _params_from_any(value: AllocationEngineParams | dict[str, Any] | None) -> AllocationEngineParams:
    if value is None:
        return AllocationEngineParams()
    if isinstance(value, AllocationEngineParams):
        return value
    return AllocationEngineParams(**dict(_obj(value)))


def _input_from_any(value: AllocationEngineInput | dict[str, Any]) -> AllocationEngineInput:
    if isinstance(value, AllocationEngineInput):
        return value
    data = dict(_obj(value))
    return AllocationEngineInput(
        account_profile=_profile_from_any(data["account_profile"]),
        goal=_goal_from_any(data["goal"]),
        cashflow_plan=_cashflow_plan_from_any(data["cashflow_plan"]),
        constraints=_constraints_from_any(data["constraints"]),
        universe=_universe_from_any(data["universe"]),
        params=_params_from_any(data.get("params")),
    )
def _build_diagnostics(
    allocation: StrategicAllocation,
    template: AllocationTemplate,
    universe: AllocationUniverse,
    validation_notes: list[str],
) -> CandidateDiagnostics:
    theme_exposure: dict[str, float] = {}
    for bucket, value in allocation.weights.items():
        theme = universe.bucket_to_theme.get(bucket)
        if theme:
            theme_exposure[theme] = theme_exposure.get(theme, 0.0) + value
    satellite_weight = sum(
        value
        for bucket, value in allocation.weights.items()
        if universe.bucket_category.get(bucket) == "satellite"
    )
    qdii_weight = sum(allocation.weights.get(bucket, 0.0) for bucket in universe.qdii_buckets)
    liquidity_weight = sum(allocation.weights.get(bucket, 0.0) for bucket in universe.liquidity_buckets)
    return CandidateDiagnostics(
        allocation_name=allocation.name,
        template_name=template.template_name,
        theme_exposure={theme: round(value, 4) for theme, value in theme_exposure.items()},
        satellite_weight=round(satellite_weight, 4),
        qdii_weight=round(qdii_weight, 4),
        liquidity_weight=round(liquidity_weight, 4),
        notes=list(validation_notes),
    )


def deduplicate_candidates(
    allocations: list[StrategicAllocation],
    params: AllocationEngineParams,
) -> list[StrategicAllocation]:
    unique_pairs = deduplicate_candidate_pairs(
        [
            (
                allocation,
                CandidateDiagnostics(
                    allocation_name=allocation.name,
                    template_name=allocation.name.split("__")[0],
                    theme_exposure={},
                    satellite_weight=0.0,
                    qdii_weight=0.0,
                    liquidity_weight=0.0,
                ),
            )
            for allocation in allocations
        ],
        params.dedup_l1_threshold,
    )
    return [allocation for allocation, _diag in unique_pairs]


def trim_candidates(
    allocations: list[StrategicAllocation],
    min_candidates: int,
    max_candidates: int,
) -> list[StrategicAllocation]:
    del min_candidates
    return allocations[:max_candidates]


def run_allocation_engine(inp: AllocationEngineInput | dict[str, Any]) -> AllocationEngineResult:
    normalized = _input_from_any(inp)
    issues = validate_allocation_input(normalized)
    if issues:
        raise ValueError("; ".join(issues))

    templates = build_template_family(normalized)
    candidate_pairs: list[tuple[StrategicAllocation, CandidateDiagnostics]] = []
    warnings: list[str] = []
    for index, template in enumerate(templates, start=1):
        draft = instantiate_template(template, normalized.universe, normalized.account_profile)
        projected = project_to_constraints(
            draft_weights=draft,
            constraints=normalized.constraints,
            universe=normalized.universe,
            profile=normalized.account_profile,
            params=normalized.params,
        )
        validation_notes = validate_candidate(
            projected,
            normalized.constraints,
            normalized.universe,
            normalized.account_profile,
        )
        if validation_notes:
            warnings.extend([f"{template.template_name}: {note}" for note in validation_notes])
            continue
        candidate_name = (
            f"{template.template_family}__{normalized.goal.risk_preference}__{index:02d}"
        )
        description_bits = [template.template_family]
        if template.preferred_theme:
            description_bits.append(f"theme={template.preferred_theme}")
        if template.liquidity_buffer_bonus > 0:
            description_bits.append("liquidity_buffered")
        allocation = build_strategic_allocation(
            name=candidate_name,
            weights=projected,
            universe=normalized.universe,
            params=normalized.params,
            description=", ".join(description_bits),
        )
        candidate_pairs.append(
            (
                allocation,
                _build_diagnostics(
                    allocation,
                    template,
                    normalized.universe,
                    validation_notes,
                ),
            )
        )
    paired = stable_sort_candidate_pairs(candidate_pairs)
    paired = deduplicate_candidate_pairs(paired, normalized.params.dedup_l1_threshold)
    paired = trim_candidate_pairs(
        paired,
        normalized.params.min_candidates,
        normalized.params.max_candidates,
    )
    allocations = [allocation for allocation, _diag in paired]
    diagnostics = [diag for _allocation, diag in paired]
    if len(allocations) < normalized.params.min_candidates:
        warnings.append(
            "candidate count below min_candidates: "
            f"{len(allocations)} < {normalized.params.min_candidates}"
        )

    return AllocationEngineResult(
        candidate_set_id=(
            f"{normalized.account_profile.account_profile_id}_"
            f"{normalized.params.version}_"
            f"{normalized.goal.risk_preference}_"
            f"{normalized.goal.horizon_months}"
        ),
        account_profile_id=normalized.account_profile.account_profile_id,
        engine_version=normalized.params.version,
        candidate_allocations=allocations,
        diagnostics=diagnostics,
        generation_notes=[template.template_name for template in templates],
        warnings=sorted(set(warnings)),
    )


def generate_candidate_allocations(inp: AllocationEngineInput | dict[str, Any]) -> list[StrategicAllocation]:
    return run_allocation_engine(inp).candidate_allocations
