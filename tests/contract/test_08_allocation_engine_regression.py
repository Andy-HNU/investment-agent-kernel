from __future__ import annotations

import pytest

from allocation_engine.engine import run_allocation_engine
from allocation_engine.projection import project_to_constraints
from allocation_engine.types import AllocationEngineParams, AllocationProfile, AllocationUniverse
from goal_solver.engine import run_goal_solver
from goal_solver.types import (
    AccountConstraints,
    CashFlowEvent,
    CashFlowPlan,
    GoalCard,
    GoalSolverInput,
    GoalSolverParams,
    MarketAssumptions,
)


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal_solver_input_base["goal"],
        "cashflow_plan": goal_solver_input_base["cashflow_plan"],
        "constraints": goal_solver_input_base["constraints"],
        "universe": {
            "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": {
                "equity_cn": None,
                "bond_cn": None,
                "gold": None,
                "satellite": "technology",
            },
            "qdii_buckets": [],
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def _typed_projection_inputs(goal_solver_input_base: dict):
    allocation_input = _allocation_input(goal_solver_input_base)
    profile = AllocationProfile(**allocation_input["account_profile"])
    universe = AllocationUniverse(**allocation_input["universe"])
    constraints = AccountConstraints(
        max_drawdown_tolerance=allocation_input["constraints"]["max_drawdown_tolerance"],
        ips_bucket_boundaries=allocation_input["constraints"]["ips_bucket_boundaries"],
        satellite_cap=allocation_input["constraints"]["satellite_cap"],
        theme_caps=allocation_input["constraints"]["theme_caps"],
        qdii_cap=allocation_input["constraints"]["qdii_cap"],
        liquidity_reserve_min=allocation_input["constraints"]["liquidity_reserve_min"],
        bucket_category=universe.bucket_category,
        bucket_to_theme=universe.bucket_to_theme,
    )
    params = AllocationEngineParams(**allocation_input.get("params", {}))
    return profile, universe, constraints, params


def _add_second_theme_bucket(allocation_input: dict) -> None:
    allocation_input["account_profile"]["preferred_themes"] = ["technology", "healthcare"]
    allocation_input["universe"]["buckets"].append("satellite_healthcare")
    allocation_input["universe"]["bucket_category"]["satellite_healthcare"] = "satellite"
    allocation_input["universe"]["bucket_to_theme"]["satellite_healthcare"] = "healthcare"
    allocation_input["universe"]["bucket_order"].append("satellite_healthcare")
    allocation_input["constraints"]["ips_bucket_boundaries"]["satellite_healthcare"] = (0.0, 0.15)
    allocation_input["constraints"]["theme_caps"]["healthcare"] = 0.08


@pytest.mark.contract
def test_run_allocation_engine_is_deterministic(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    first = run_allocation_engine(allocation_input)
    second = run_allocation_engine(allocation_input)

    assert [item.name for item in first.candidate_allocations] == [
        item.name for item in second.candidate_allocations
    ]
    assert [item.weights for item in first.candidate_allocations] == [
        item.weights for item in second.candidate_allocations
    ]
    assert [item.to_dict() for item in first.diagnostics] == [
        item.to_dict() for item in second.diagnostics
    ]


@pytest.mark.contract
def test_allocation_engine_output_can_feed_goal_solver(goal_solver_input_base):
    allocation_result = run_allocation_engine(_allocation_input(goal_solver_input_base))
    base = goal_solver_input_base
    solver_input = GoalSolverInput(
        snapshot_id=base["snapshot_id"],
        account_profile_id=base["account_profile_id"],
        goal=GoalCard(**base["goal"]),
        cashflow_plan=CashFlowPlan(
            monthly_contribution=base["cashflow_plan"]["monthly_contribution"],
            annual_step_up_rate=base["cashflow_plan"]["annual_step_up_rate"],
            cashflow_events=[
                CashFlowEvent(**event) for event in base["cashflow_plan"]["cashflow_events"]
            ],
        ),
        current_portfolio_value=base["current_portfolio_value"],
        candidate_allocations=allocation_result.candidate_allocations,
        constraints=AccountConstraints(
            max_drawdown_tolerance=base["constraints"]["max_drawdown_tolerance"],
            ips_bucket_boundaries=base["constraints"]["ips_bucket_boundaries"],
            satellite_cap=base["constraints"]["satellite_cap"],
            theme_caps=base["constraints"]["theme_caps"],
            qdii_cap=base["constraints"]["qdii_cap"],
            liquidity_reserve_min=base["constraints"]["liquidity_reserve_min"],
        ),
        solver_params=GoalSolverParams(
            version=base["solver_params"]["version"],
            n_paths=base["solver_params"]["n_paths"],
            n_paths_lightweight=base["solver_params"]["n_paths_lightweight"],
            seed=base["solver_params"]["seed"],
            market_assumptions=MarketAssumptions(**base["solver_params"]["market_assumptions"]),
        ),
        ranking_mode_override=None,
    )
    solver_output = run_goal_solver(solver_input)

    assert solver_output.recommended_allocation is not None
    assert solver_output.all_results
    assert solver_output.recommended_allocation.name in {
        item.name for item in allocation_result.candidate_allocations
    }


@pytest.mark.contract
def test_allocation_engine_projects_profile_and_liquidity_constraints(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    allocation_input["account_profile"]["qdii_allowed"] = False
    allocation_input["account_profile"]["forbidden_buckets"] = ["gold"]
    allocation_input["universe"]["qdii_buckets"] = ["satellite"]
    allocation_input["constraints"]["liquidity_reserve_min"] = 0.10

    result = run_allocation_engine(allocation_input)

    assert result.candidate_allocations
    for allocation in result.candidate_allocations:
        assert allocation.weights.get("gold", 0.0) == 0.0
        assert allocation.weights.get("satellite", 0.0) == 0.0
        assert allocation.weights.get("bond_cn", 0.0) >= 0.10 - 1e-6


@pytest.mark.contract
def test_allocation_engine_requires_full_ips_boundary_coverage(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    del allocation_input["constraints"]["ips_bucket_boundaries"]["gold"]

    with pytest.raises(ValueError, match="ips_bucket_boundaries must fully cover universe.buckets"):
        run_allocation_engine(allocation_input)


@pytest.mark.contract
def test_project_to_constraints_repairs_satellite_qdii_theme_and_liquidity_limits(
    goal_solver_input_base,
):
    profile, universe, constraints, params = _typed_projection_inputs(goal_solver_input_base)
    universe.qdii_buckets = ["satellite"]
    universe.liquidity_buckets = ["bond_cn"]
    constraints.satellite_cap = 0.10
    constraints.qdii_cap = 0.08
    constraints.theme_caps = {"technology": 0.06}
    constraints.liquidity_reserve_min = 0.20

    projected = project_to_constraints(
        draft_weights={
            "equity_cn": 0.15,
            "bond_cn": 0.05,
            "gold": 0.10,
            "satellite": 0.70,
        },
        constraints=constraints,
        universe=universe,
        profile=profile,
        params=params,
    )

    assert abs(sum(projected.values()) - 1.0) <= 1e-6
    assert all(value >= -1e-9 for value in projected.values())
    assert projected["satellite"] <= 0.06 + 1e-6
    assert projected["bond_cn"] >= 0.20 - 1e-6
    for bucket, (lower, upper) in constraints.ips_bucket_boundaries.items():
        assert lower - 1e-6 <= projected.get(bucket, 0.0) <= upper + 1e-6


@pytest.mark.contract
def test_project_to_constraints_is_idempotent_for_valid_weights(goal_solver_input_base):
    profile, universe, constraints, params = _typed_projection_inputs(goal_solver_input_base)
    draft = {
        "equity_cn": 0.55,
        "bond_cn": 0.30,
        "gold": 0.10,
        "satellite": 0.05,
    }

    projected = project_to_constraints(
        draft_weights=draft,
        constraints=constraints,
        universe=universe,
        profile=profile,
        params=params,
    )

    assert projected == draft


@pytest.mark.contract
def test_allocation_engine_trim_keeps_diagnostics_aligned(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    allocation_input["params"] = {"min_candidates": 2, "max_candidates": 2}

    result = run_allocation_engine(allocation_input)

    assert len(result.candidate_allocations) == 2
    assert len(result.diagnostics) == 2
    assert [diag.allocation_name for diag in result.diagnostics] == [
        allocation.name for allocation in result.candidate_allocations
    ]
    assert [allocation.name.split("__")[0] for allocation in result.candidate_allocations] == [
        "defense_heavy",
        "balanced_core",
    ]


@pytest.mark.contract
def test_allocation_engine_warns_when_candidate_count_below_min(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    allocation_input["account_profile"]["preferred_themes"] = []
    allocation_input["constraints"]["liquidity_reserve_min"] = 0.0
    allocation_input["params"] = {"min_candidates": 6, "max_candidates": 6}

    result = run_allocation_engine(allocation_input)

    assert len(result.candidate_allocations) < 6
    assert any("candidate count below min_candidates" in item for item in result.warnings)


@pytest.mark.contract
def test_allocation_engine_forces_liquidity_template_for_essential_goal(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    allocation_input["goal"]["priority"] = "essential"
    allocation_input["constraints"]["liquidity_reserve_min"] = 0.0
    allocation_input["cashflow_plan"]["cashflow_events"] = []

    result = run_allocation_engine(allocation_input)

    assert "liquidity_buffered" in result.generation_notes
    assert any(
        allocation.name.startswith("liquidity_buffered__")
        for allocation in result.candidate_allocations
    )


@pytest.mark.contract
def test_allocation_engine_low_complexity_limits_theme_templates(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    _add_second_theme_bucket(allocation_input)
    allocation_input["account_profile"]["complexity_tolerance"] = "low"

    result = run_allocation_engine(allocation_input)

    theme_templates = [
        template_name
        for template_name in result.generation_notes
        if template_name.startswith("theme_tilt_")
    ]
    assert theme_templates == ["theme_tilt_technology"]
    assert "satellite_light" not in result.generation_notes


@pytest.mark.contract
def test_allocation_engine_trim_preserves_family_diversity(goal_solver_input_base):
    allocation_input = _allocation_input(goal_solver_input_base)
    _add_second_theme_bucket(allocation_input)
    allocation_input["params"] = {"min_candidates": 4, "max_candidates": 5}

    result = run_allocation_engine(allocation_input)
    families = [allocation.name.split("__")[0] for allocation in result.candidate_allocations]

    assert len(result.candidate_allocations) == 5
    assert families.count("theme_tilt") == 1
    assert "liquidity_buffered" in families
