from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


# 这组 factory 是“测试输入工厂”，用于在实现未完全完成前统一测试口径。
# 一旦正式模块完成，可逐步替换为真实类型 import。


class _ActionType(str, Enum):
    FREEZE = "freeze"
    OBSERVE = "observe"
    ADD_CASH_TO_CORE = "add_cash_core"


@dataclass
class _Action:
    type: _ActionType
    target_bucket: str | None = None
    amount: float | None = None
    amount_pct: float | None = 0.0
    from_bucket: str | None = None
    to_bucket: str | None = None
    cash_source: str = "new_cash"
    requires_sell: bool = False
    expected_turnover: float = 0.0
    policy_tag: str = "observe"
    cooldown_applicable: bool = False
    rationale: str = "test action"
    explanation_facts: list[str] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_market_assumptions() -> dict[str, Any]:
    return {
        "expected_returns": {"equity_cn": 0.08, "bond_cn": 0.03},
        "volatility": {"equity_cn": 0.18, "bond_cn": 0.04},
        "correlation_matrix": {
            "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.1},
            "bond_cn": {"equity_cn": 0.1, "bond_cn": 1.0},
        },
        "source_name": None,
        "dataset_version": None,
        "lookback_months": None,
        "historical_backtest_used": False,
    }


def make_goal_solver_input() -> dict[str, Any]:
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
                "description": "baseline test allocation",
            }
        ],
        "constraints": {
            "max_drawdown_tolerance": 0.22,
            "ips_bucket_boundaries": {"equity_cn": (0.30, 0.70), "bond_cn": (0.10, 0.50), "gold": (0.0, 0.15), "satellite": (0.0, 0.15)},
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
            "shrinkage_factor": 0.85,
            "simulation_mode_requested": "static_gaussian",
            "simulation_frequency": "monthly",
            "regime_sensitive": False,
            "jump_overlay_enabled": False,
            "distribution_model_state": None,
            "simulation_mode_auto_selected": False,
            "market_assumptions": make_market_assumptions(),
        },
        "ranking_mode_override": None,
    }


def make_goal_solver_output(goal_solver_input: dict[str, Any] | None = None) -> dict[str, Any]:
    goal_solver_input = goal_solver_input or make_goal_solver_input()
    return {
        "input_snapshot_id": goal_solver_input["snapshot_id"],
        "generated_at": now_iso(),
        "recommended_allocation": goal_solver_input["candidate_allocations"][0],
        "recommended_result": {
            "allocation_name": "base_allocation",
            "weights": goal_solver_input["candidate_allocations"][0]["weights"],
            "success_probability": 0.68,
            "bucket_success_probability": 0.68,
            "product_adjusted_success_probability": 0.675,
            "expected_terminal_value": 2_620_000.0,
            "implied_required_annual_return": 0.058,
            "risk_summary": {
                "max_drawdown_90pct": 0.19,
                "terminal_value_tail_mean_95": 1_950_000.0,
                "shortfall_probability": 0.32,
                "terminal_shortfall_p5_vs_initial": 0.08,
            },
            "is_feasible": True,
            "simulation_mode_requested": "static_gaussian",
            "simulation_mode_used": "static_gaussian",
            "infeasibility_reasons": [],
        },
        "all_results": [],
        "ranking_mode_used": "sufficiency_first",
        "structure_budget": {
            "core_weight": 0.55,
            "defense_weight": 0.30,
            "satellite_weight": 0.10,
            "theme_remaining_budget": {"technology": 0.03},
            "satellite_remaining_cap": 0.05,
        },
        "risk_budget": {"drawdown_budget_used_pct": 0.86},
        "solver_notes": [],
        "params_version": "v4.0.0",
        "simulation_mode_requested": "static_gaussian",
        "simulation_mode_used": "static_gaussian",
        "simulation_mode_auto_selected": False,
    }


def make_market_state() -> dict[str, Any]:
    return {
        "as_of": now_iso(),
        "source_bundle_id": "bundle_acc001_20260329T120000Z",
        "version": "market_state_20260329T120000Z",
        "risk_environment": "moderate",
        "volatility_regime": "normal",
        "liquidity_status": {"equity_cn": "normal", "bond_cn": "normal", "gold": "normal", "satellite": "normal"},
        "valuation_positions": {"equity_cn": "fair", "bond_cn": "fair", "gold": "fair", "satellite": "rich"},
        "correlation_spike_alert": False,
        "quality_flags": [],
        "is_degraded": False,
        # EV 侧常用消费字段，可以在实现中通过 adapter 提供
        "valuation_percentile": {"equity_cn": 0.50, "bond_cn": 0.50},
        "liquidity_flag": {"equity_cn": False, "bond_cn": False},
    }


def make_constraint_state() -> dict[str, Any]:
    return {
        "as_of": now_iso(),
        "source_bundle_id": "bundle_acc001_20260329T120000Z",
        "version": "constraint_state_20260329T120000Z",
        "ips_bucket_boundaries": {"equity_cn": (0.30, 0.70), "bond_cn": (0.10, 0.50), "gold": (0.0, 0.15), "satellite": (0.0, 0.15)},
        "satellite_cap": 0.15,
        "theme_caps": {"technology": 0.08},
        "qdii_cap": 0.20,
        "liquidity_reserve_min": 0.05,
        "max_drawdown_tolerance": 0.22,
        "rebalancing_band": 0.10,
        "forbidden_actions": [],
        "cooling_period_days": 3,
        "soft_preferences": {},
        "effective_drawdown_threshold": 0.20,
        "cooldown_currently_active": False,
        # EV 侧消费字段
        "bucket_category": {"equity_cn": "core", "bond_cn": "defense", "gold": "defense", "satellite": "satellite"},
        "bucket_to_theme": {"equity_cn": None, "bond_cn": None, "gold": None, "satellite": "technology"},
        "qdii_available": 50_000.0,
        "premium_discount": {},
        "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
    }


def make_behavior_state() -> dict[str, Any]:
    return {
        "as_of": now_iso(),
        "source_bundle_id": "bundle_acc001_20260329T120000Z",
        "version": "behavior_state_20260329T120000Z",
        "recent_chase_risk": "low",
        "recent_panic_risk": "none",
        "trade_frequency_30d": 1.0,
        "override_count_90d": 0,
        "cooldown_active": False,
        "cooldown_until": None,
        "behavior_penalty_coeff": 0.2,
        "recent_chasing_flag": False,
        # EV 侧消费字段
        "high_emotion_flag": False,
        "panic_flag": False,
        "action_frequency_30d": 1,
        "emotion_score": 0.1,
    }


def make_runtime_optimizer_params() -> dict[str, Any]:
    return {
        "version": "v1.0.0",
        "deviation_soft_threshold": 0.03,
        "deviation_hard_threshold": 0.10,
        "satellite_overweight_threshold": 0.02,
        "drawdown_event_threshold": 0.10,
        "min_candidates": 2,
        "max_candidates": 8,
        "min_cash_for_action": 1000.0,
        "new_cash_split_buckets": 2,
        "new_cash_use_pct": 0.80,
        "defense_add_pct": 0.05,
        "rebalance_full_allowed_monthly": False,
        "cooldown_trade_frequency_limit": 4.0,
        "amount_pct_min": 0.02,
        "amount_pct_max": 0.30,
        "max_portfolio_snapshot_age_days": 3,
    }


def make_ev_params() -> dict[str, Any]:
    return {
        "version": "v1.0.0",
        "goal_impact_weight": 0.40,
        "risk_penalty_weight": 0.25,
        "soft_constraint_weight": 0.15,
        "behavior_penalty_weight": 0.10,
        "execution_penalty_weight": 0.10,
        "goal_solver_seed": 42,
        "goal_solver_min_delta": 0.003,
        "high_confidence_min_diff": 0.020,
        "medium_confidence_min_diff": 0.005,
    }


def make_live_portfolio_snapshot() -> dict[str, Any]:
    return {
        "weights": {"equity_cn": 0.52, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.13},
        "total_value": 380_000.0,
        "available_cash": 12_000.0,
        "goal_gap": 2_120_000.0,
        "remaining_horizon_months": 144,
        "as_of_date": "2026-03-29",
        "current_drawdown": 0.05,
    }


def make_calibration_result() -> dict[str, Any]:
    return {
        "calibration_id": "acc001_20260329T120000Z",
        "source_bundle_id": "bundle_acc001_20260329T120000Z",
        "created_at": now_iso(),
        "account_profile_id": "acc001",
        "market_state": make_market_state(),
        "constraint_state": make_constraint_state(),
        "behavior_state": make_behavior_state(),
        "market_assumptions": make_market_assumptions(),
        "goal_solver_params": {
            "version": "v4.0.0",
            "n_paths": 5000,
            "n_paths_lightweight": 1000,
            "seed": 42,
            "shrinkage_factor": 0.85,
            "simulation_mode_requested": "static_gaussian",
            "market_assumptions": make_market_assumptions(),
        },
        "runtime_optimizer_params": make_runtime_optimizer_params(),
        "ev_params": make_ev_params(),
        "calibration_quality": "full",
        "degraded_domains": [],
        "notes": [],
        "param_version_meta": {
            "version_id": "calibration_20260329T120000Z",
            "source_bundle_id": "bundle_acc001_20260329T120000Z",
            "created_at": now_iso(),
            "updated_reason": "test",
            "quality": "full",
            "is_temporary": False,
            "can_be_replayed": True,
            "previous_version_id": None,
            "market_assumptions_version": "market_assumptions_20260329T120000Z",
            "goal_solver_params_version": "v4.0.0",
            "runtime_optimizer_params_version": "v1.0.0",
            "ev_params_version": "v1.0.0",
        },
    }


def make_action(action_type: str) -> _Action:
    mapping = {
        "freeze": _ActionType.FREEZE,
        "observe": _ActionType.OBSERVE,
        "add_cash_core": _ActionType.ADD_CASH_TO_CORE,
    }
    enum_value = mapping[action_type]
    return _Action(type=enum_value, amount=0.0, amount_pct=0.0)
