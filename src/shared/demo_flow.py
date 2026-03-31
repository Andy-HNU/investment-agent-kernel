from __future__ import annotations

from copy import deepcopy
from typing import Any

from allocation_engine.engine import run_allocation_engine
from orchestrator.types import OrchestratorResult

def build_demo_goal_solver_input() -> dict[str, Any]:
    market_assumptions = {
        "expected_returns": {
            "equity_cn": 0.08,
            "bond_cn": 0.03,
            "gold": 0.05,
            "satellite": 0.11,
        },
        "volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "correlation_matrix": {
            "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.1, "gold": 0.0, "satellite": 0.55},
            "bond_cn": {"equity_cn": 0.1, "bond_cn": 1.0, "gold": 0.05, "satellite": 0.15},
            "gold": {"equity_cn": 0.0, "bond_cn": 0.05, "gold": 1.0, "satellite": 0.10},
            "satellite": {"equity_cn": 0.55, "bond_cn": 0.15, "gold": 0.10, "satellite": 1.0},
        },
    }
    return {
        "snapshot_id": "acc001_20260329T120000Z",
        "account_profile_id": "acc001",
        "goal": {
            "goal_amount": 2_500_000.0,
            "horizon_months": 144,
            "goal_description": "12年后达到250万",
            "success_prob_threshold": 0.70,
            "priority": "important",
            "risk_preference": "moderate",
        },
        "cashflow_plan": {
            "monthly_contribution": 12_000.0,
            "annual_step_up_rate": 0.00,
            "cashflow_events": [],
        },
        "current_portfolio_value": 380_000.0,
        "candidate_allocations": [
            {
                "name": "base_allocation",
                "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
                "complexity_score": 0.2,
                "description": "baseline demo allocation",
            }
        ],
        "constraints": {
            "max_drawdown_tolerance": 0.22,
            "ips_bucket_boundaries": {
                "equity_cn": (0.30, 0.70),
                "bond_cn": (0.10, 0.50),
                "gold": (0.0, 0.15),
                "satellite": (0.0, 0.15),
            },
            "satellite_cap": 0.15,
            "theme_caps": {"technology": 0.08},
            "qdii_cap": 0.20,
            "liquidity_reserve_min": 0.05,
        },
        "solver_params": {
            "version": "v4.0.0",
            "n_paths": 5000,
            "n_paths_lightweight": 1000,
            "seed": 42,
            "market_assumptions": market_assumptions,
        },
        "ranking_mode_override": None,
    }


def build_demo_live_portfolio(as_of_date: str = "2026-03-29") -> dict[str, Any]:
    return {
        "weights": {"equity_cn": 0.52, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.13},
        "total_value": 380_000.0,
        "available_cash": 12_000.0,
        "goal_gap": 2_120_000.0,
        "remaining_horizon_months": 144,
        "as_of_date": as_of_date,
        "current_drawdown": 0.05,
    }


def build_demo_allocation_input(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input["account_profile_id"],
            "risk_preference": goal_solver_input["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": goal_solver_input["goal"],
        "cashflow_plan": goal_solver_input["cashflow_plan"],
        "constraints": goal_solver_input["constraints"],
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
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def build_demo_market_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    assumptions = goal_solver_input["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": assumptions["volatility"]["equity_cn"],
            "bond_cn": assumptions["volatility"]["bond_cn"],
            "gold": assumptions["volatility"]["gold"],
            "satellite": assumptions["volatility"]["satellite"],
        },
        "liquidity_scores": {
            "equity_cn": 0.90,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.60,
        },
        "valuation_z_scores": {
            "equity_cn": 0.20,
            "bond_cn": 0.10,
            "gold": -0.30,
            "satellite": 1.80,
        },
        "expected_returns": assumptions["expected_returns"],
    }


def build_demo_account_raw(goal_solver_input: dict[str, Any], live_portfolio: dict[str, Any]) -> dict[str, Any]:
    return {
        "weights": dict(live_portfolio["weights"]),
        "total_value": live_portfolio["total_value"],
        "available_cash": live_portfolio["available_cash"],
        "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
    }


def build_demo_goal_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(goal_solver_input["goal"])


def build_demo_constraint_raw(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    constraints = deepcopy(goal_solver_input["constraints"])
    constraints.update(
        {
            "rebalancing_band": 0.10,
            "forbidden_actions": [],
            "cooling_period_days": 3,
            "soft_preferences": {},
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
            "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
        }
    )
    return constraints


def build_demo_behavior_raw(*, override_count_90d: int = 0, cooldown_active: bool = False) -> dict[str, Any]:
    return {
        "recent_chase_risk": "low",
        "recent_panic_risk": "none",
        "trade_frequency_30d": 1.0,
        "override_count_90d": override_count_90d,
        "cooldown_active": cooldown_active,
        "cooldown_until": "2026-04-05T00:00:00Z" if cooldown_active else None,
        "behavior_penalty_coeff": 0.0,
    }


def build_demo_prior_solver_input(
    goal_solver_input: dict[str, Any],
    calibration_result: Any,
) -> dict[str, Any]:
    calibration = calibration_result.to_dict() if hasattr(calibration_result, "to_dict") else deepcopy(calibration_result)
    allocation_result = run_allocation_engine(build_demo_allocation_input(goal_solver_input))
    solver_input = deepcopy(goal_solver_input)
    solver_input["candidate_allocations"] = [
        item.to_dict() if hasattr(item, "to_dict") else deepcopy(item)
        for item in allocation_result.candidate_allocations
    ]
    solver_input["snapshot_id"] = calibration["source_bundle_id"]
    constraints = deepcopy(solver_input.get("constraints", {}))
    constraint_state = calibration.get("constraint_state", {})
    for field_name in (
        "max_drawdown_tolerance",
        "ips_bucket_boundaries",
        "satellite_cap",
        "theme_caps",
        "qdii_cap",
        "liquidity_reserve_min",
        "bucket_category",
        "bucket_to_theme",
    ):
        if field_name in constraint_state:
            constraints[field_name] = deepcopy(constraint_state[field_name])
    solver_input["constraints"] = constraints
    if calibration.get("goal_solver_params") is not None:
        solver_input["solver_params"] = deepcopy(calibration["goal_solver_params"])
    return solver_input


def _demo_summary(result: OrchestratorResult) -> dict[str, Any]:
    card = result.decision_card or {}
    return {
        "run_id": result.run_id,
        "workflow_type": result.workflow_type.value,
        "status": result.status.value,
        "bundle_id": result.bundle_id,
        "calibration_id": result.calibration_id,
        "card_type": card.get("card_type"),
        "recommended_action": card.get("recommended_action"),
        "summary": card.get("summary"),
    }


def run_demo_onboarding() -> OrchestratorResult:
    from shared.demo_scenarios import run_demo_onboarding as run_canonical_demo_onboarding

    return run_canonical_demo_onboarding()


def run_demo_monthly_replay_override(
    onboarding_result: OrchestratorResult | None = None,
) -> OrchestratorResult:
    from shared.demo_scenarios import (
        run_demo_monthly_replay_override as run_canonical_demo_monthly_replay_override,
    )

    return run_canonical_demo_monthly_replay_override(onboarding_result)


def run_demo_quarterly_review(
    prior_calibration: Any | None = None,
) -> OrchestratorResult:
    from shared.demo_scenarios import run_demo_quarterly_review as run_canonical_demo_quarterly_review

    return run_canonical_demo_quarterly_review(prior_calibration=prior_calibration)


def run_demo_provenance_bypass(
    onboarding_result: OrchestratorResult | None = None,
) -> OrchestratorResult:
    from shared.demo_scenarios import run_demo_provenance_relaxed as run_canonical_demo_provenance_relaxed

    return run_canonical_demo_provenance_relaxed(onboarding_result)


def run_demo_journey() -> dict[str, OrchestratorResult]:
    onboarding = run_demo_onboarding()
    monthly_replay_override = run_demo_monthly_replay_override(onboarding)
    quarterly_review = run_demo_quarterly_review(monthly_replay_override.calibration_result)
    provenance_bypass = run_demo_provenance_bypass(onboarding)
    return {
        "onboarding": onboarding,
        "monthly_replay_override": monthly_replay_override,
        "quarterly_review": quarterly_review,
        "provenance_bypass": provenance_bypass,
    }


def serialize_demo_journey(journey: dict[str, OrchestratorResult]) -> dict[str, Any]:
    return {
        "scenarios": {name: result.to_dict() for name, result in journey.items()},
        "summary": {name: _demo_summary(result) for name, result in journey.items()},
    }
