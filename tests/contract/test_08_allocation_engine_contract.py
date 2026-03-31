from __future__ import annotations

import pytest

from allocation_engine.engine import generate_candidate_allocations, run_allocation_engine
from allocation_engine.types import AllocationEngineResult
from goal_solver.types import StrategicAllocation


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


@pytest.mark.contract
def test_run_allocation_engine_returns_typed_result(goal_solver_input_base):
    result = run_allocation_engine(_allocation_input(goal_solver_input_base))

    assert isinstance(result, AllocationEngineResult)
    assert result.account_profile_id == goal_solver_input_base["account_profile_id"]
    assert result.candidate_allocations
    assert all(isinstance(item, StrategicAllocation) for item in result.candidate_allocations)
    for allocation in result.candidate_allocations:
        assert 0 < sum(allocation.weights.values()) <= 1.01
        assert set(allocation.weights).issubset({"equity_cn", "bond_cn", "gold", "satellite"})


@pytest.mark.contract
def test_generate_candidate_allocations_is_allocation_list(goal_solver_input_base):
    allocations = generate_candidate_allocations(_allocation_input(goal_solver_input_base))
    assert allocations
    assert all(isinstance(item, StrategicAllocation) for item in allocations)

