from __future__ import annotations

from copy import deepcopy
from typing import Any


def _market_assumptions() -> dict[str, Any]:
    return {
        "expected_returns": {
            "equity_cn": 0.08,
            "bond_cn": 0.03,
            "gold": 0.04,
            "satellite": 0.10,
        },
        "volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "correlation_matrix": {
            "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.1, "gold": 0.2, "satellite": 0.7},
            "bond_cn": {"equity_cn": 0.1, "bond_cn": 1.0, "gold": 0.05, "satellite": 0.0},
            "gold": {"equity_cn": 0.2, "bond_cn": 0.05, "gold": 1.0, "satellite": 0.15},
            "satellite": {"equity_cn": 0.7, "bond_cn": 0.0, "gold": 0.15, "satellite": 1.0},
        },
    }


def build_demo_goal_solver_input() -> dict[str, Any]:
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
            "annual_step_up_rate": 0.0,
            "cashflow_events": [],
        },
        "current_portfolio_value": 380_000.0,
        "candidate_allocations": [
            {
                "name": "base_allocation",
                "weights": {
                    "equity_cn": 0.55,
                    "bond_cn": 0.30,
                    "gold": 0.05,
                    "satellite": 0.10,
                },
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
            "market_assumptions": _market_assumptions(),
        },
        "ranking_mode_override": None,
    }


def build_demo_live_portfolio() -> dict[str, Any]:
    return {
        "weights": {"equity_cn": 0.52, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.13},
        "total_value": 380_000.0,
        "available_cash": 12_000.0,
        "goal_gap": 2_120_000.0,
        "remaining_horizon_months": 144,
        "as_of_date": "2026-03-29",
        "current_drawdown": 0.05,
    }


def build_demo_market_raw(goal_solver_input: dict[str, Any] | None = None) -> dict[str, Any]:
    assumptions = (goal_solver_input or build_demo_goal_solver_input())["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.90,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.60,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
    }


def build_demo_account_raw(
    goal_solver_input: dict[str, Any] | None = None,
    live_portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal_solver_input = goal_solver_input or build_demo_goal_solver_input()
    live_portfolio = live_portfolio or build_demo_live_portfolio()
    return {
        "weights": deepcopy(live_portfolio["weights"]),
        "total_value": live_portfolio["total_value"],
        "available_cash": live_portfolio["available_cash"],
        "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
    }


def build_demo_goal_raw(goal_solver_input: dict[str, Any] | None = None) -> dict[str, Any]:
    goal_solver_input = goal_solver_input or build_demo_goal_solver_input()
    return deepcopy(goal_solver_input["goal"])


def build_demo_constraint_raw(goal_solver_input: dict[str, Any] | None = None) -> dict[str, Any]:
    goal_solver_input = goal_solver_input or build_demo_goal_solver_input()
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


def build_demo_behavior_raw(
    *,
    cooldown_active: bool = False,
    cooldown_until: str | None = None,
    override_count_90d: int = 0,
) -> dict[str, Any]:
    return {
        "recent_chase_risk": "low",
        "recent_panic_risk": "none",
        "trade_frequency_30d": 1.0,
        "override_count_90d": override_count_90d,
        "cooldown_active": cooldown_active,
        "cooldown_until": cooldown_until,
        "behavior_penalty_coeff": 0.2,
    }


def build_demo_allocation_input(goal_solver_input: dict[str, Any] | None = None) -> dict[str, Any]:
    goal_solver_input = goal_solver_input or build_demo_goal_solver_input()
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input["account_profile_id"],
            "risk_preference": goal_solver_input["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
        },
        "goal": deepcopy(goal_solver_input["goal"]),
        "cashflow_plan": deepcopy(goal_solver_input["cashflow_plan"]),
        "constraints": deepcopy(goal_solver_input["constraints"]),
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


def build_demo_onboarding_payload(as_of: str = "2026-03-29T12:00:00Z") -> dict[str, Any]:
    goal_solver_input = build_demo_goal_solver_input()
    live_portfolio = build_demo_live_portfolio()
    return {
        "account_profile_id": goal_solver_input["account_profile_id"],
        "as_of": as_of,
        "market_raw": build_demo_market_raw(goal_solver_input),
        "account_raw": build_demo_account_raw(goal_solver_input, live_portfolio),
        "goal_raw": build_demo_goal_raw(goal_solver_input),
        "constraint_raw": build_demo_constraint_raw(goal_solver_input),
        "behavior_raw": build_demo_behavior_raw(),
        "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
        "allocation_engine_input": build_demo_allocation_input(goal_solver_input),
        "goal_solver_input": goal_solver_input,
    }


def build_demo_quarterly_payload(as_of: str = "2026-03-29T13:00:00Z") -> dict[str, Any]:
    payload = build_demo_onboarding_payload(as_of=as_of)
    payload["live_portfolio"] = build_demo_live_portfolio()
    return payload


def build_demo_monthly_raw_payload(
    as_of: str = "2026-03-29T14:00:00Z",
    *,
    replay_mode: bool = False,
    cooldown_active: bool = False,
    cooldown_until: str | None = None,
    disable_provenance_checks: bool = False,
) -> dict[str, Any]:
    goal_solver_input = build_demo_goal_solver_input()
    live_portfolio = build_demo_live_portfolio()
    payload = {
        "account_profile_id": goal_solver_input["account_profile_id"],
        "as_of": as_of,
        "market_raw": build_demo_market_raw(goal_solver_input),
        "account_raw": build_demo_account_raw(goal_solver_input, live_portfolio),
        "goal_raw": build_demo_goal_raw(goal_solver_input),
        "constraint_raw": build_demo_constraint_raw(goal_solver_input),
        "behavior_raw": build_demo_behavior_raw(
            cooldown_active=cooldown_active,
            cooldown_until=cooldown_until,
            override_count_90d=1 if replay_mode else 0,
        ),
        "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
        "live_portfolio": live_portfolio,
    }
    if replay_mode:
        payload["replay_mode"] = True
    if disable_provenance_checks:
        payload["control_flags"] = {"disable_provenance_checks": True}
    return payload


def build_demo_aligned_prior_solver_input(prior_solver_output: Any) -> dict[str, Any]:
    solver_input = build_demo_goal_solver_input()
    output_data = prior_solver_output.to_dict() if hasattr(prior_solver_output, "to_dict") else dict(prior_solver_output)
    solver_input["snapshot_id"] = output_data.get("input_snapshot_id", solver_input["snapshot_id"])
    solver_input["solver_params"]["version"] = output_data.get(
        "params_version",
        solver_input["solver_params"]["version"],
    )
    return solver_input
