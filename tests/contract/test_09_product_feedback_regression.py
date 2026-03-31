from __future__ import annotations

from copy import deepcopy
import json

import pytest

from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType
from orchestrator.engine import run_orchestrator


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.9,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.6,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
    }


def _account_raw(goal_solver_input_base: dict, live_portfolio_base: dict) -> dict:
    return {
        "weights": live_portfolio_base["weights"],
        "total_value": live_portfolio_base["total_value"],
        "available_cash": live_portfolio_base["available_cash"],
        "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
    }


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = dict(goal_solver_input_base["constraints"])
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


def _goal_output_with_user_readable_candidates(*, no_feasible: bool) -> dict:
    base_candidate = {
        "name": "liquidity_buffered__moderate__04",
        "display_name": "稳健起步方案",
        "description": "前期保留流动性缓冲，逐步提高权益仓位。",
        "user_summary": "适合起步资金较小、希望先控制波动的新用户。",
        "complexity_score": 0.20,
        "complexity_label": "low",
        "weights": {"equity_cn": 0.50, "bond_cn": 0.30, "gold": 0.15, "satellite": 0.05},
    }
    all_results = [
        {
            "allocation_name": "liquidity_buffered__moderate__04",
            "display_name": "稳健起步方案",
            "summary": "优先保留流动性，适合新账户冷启动。",
            "success_probability": 0.6684,
            "expected_terminal_value": 1_020_000.0,
            "risk_summary": {
                "max_drawdown_90pct": 0.1440,
                "shortfall_probability": 0.3316,
                "terminal_value_tail_mean_95": 710_000.0,
                "terminal_shortfall_p5_vs_initial": 0.12,
            },
            "complexity_label": "low",
            "is_feasible": not no_feasible,
            "infeasibility_reasons": [] if not no_feasible else ["drawdown_tolerance_exceeded"],
        },
        {
            "allocation_name": "balanced_progression__moderate__02",
            "display_name": "平衡推进方案",
            "summary": "提高权益暴露以换取更高目标达成率。",
            "success_probability": 0.7010,
            "expected_terminal_value": 1_060_000.0,
            "risk_summary": {
                "max_drawdown_90pct": 0.1820,
                "shortfall_probability": 0.2990,
                "terminal_value_tail_mean_95": 690_000.0,
                "terminal_shortfall_p5_vs_initial": 0.15,
            },
            "complexity_label": "medium",
            "is_feasible": False,
            "infeasibility_reasons": ["drawdown_tolerance_exceeded"],
        },
        {
            "allocation_name": "growth_tilt__moderate__07",
            "display_name": "进取增长方案",
            "summary": "进一步提高增长性资产占比，换取更高上行空间。",
            "success_probability": 0.7420,
            "expected_terminal_value": 1_120_000.0,
            "risk_summary": {
                "max_drawdown_90pct": 0.2380,
                "shortfall_probability": 0.2580,
                "terminal_value_tail_mean_95": 640_000.0,
                "terminal_shortfall_p5_vs_initial": 0.22,
            },
            "complexity_label": "medium",
            "is_feasible": False,
            "infeasibility_reasons": ["drawdown_tolerance_exceeded"],
        },
    ]
    output = {
        "goal_description": "5年内达到100万",
        "recommended_allocation": base_candidate,
        "recommended_result": all_results[0],
        "all_results": all_results,
        "ranking_mode_used": "sufficiency_first",
        "structure_budget": {
            "core_weight": 0.50,
            "defense_weight": 0.45,
            "satellite_weight": 0.05,
            "theme_remaining_budget": {"technology": 0.03},
            "satellite_remaining_cap": 0.10,
        },
        "risk_budget": {"drawdown_budget_used_pct": 1.44 if no_feasible else 0.96},
        "solver_notes": [],
        "candidate_menu": all_results,
        "disclaimer": "以下为模型模拟结果，不是历史回测收益承诺。",
    }
    if no_feasible:
        output["solver_notes"] = [
            "warning=no_feasible_allocation",
            "fallback=closest_feasible_candidate allocation=liquidity_buffered__moderate__04",
            "action_required=reassess_goal_amount_or_horizon_or_drawdown_or_candidate_allocations",
        ]
        output["fallback_suggestions"] = [
            {
                "label": "把期限从5年延长到6年",
                "success_probability": 0.7420,
                "risk_summary": {"max_drawdown_90pct": 0.1450, "shortfall_probability": 0.2580},
            },
            {
                "label": "把目标期末总资产从100万下调到90万",
                "success_probability": 0.7860,
                "risk_summary": {"max_drawdown_90pct": 0.1440, "shortfall_probability": 0.2140},
            },
            {
                "label": "把每月投入从12000提高到15000",
                "success_probability": 0.8120,
                "risk_summary": {"max_drawdown_90pct": 0.1470, "shortfall_probability": 0.1880},
            },
        ]
    return output


@pytest.mark.contract
def test_goal_baseline_card_hides_internal_candidate_ids_and_uses_user_readable_copy():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="product_feedback_readable_goal_baseline",
            goal_solver_output=_goal_output_with_user_readable_candidates(no_feasible=False),
        )
    )

    visible_copy = _json_text(
        {
            "summary": card["summary"],
            "primary_recommendation": card["primary_recommendation"],
            "recommended_action": card["recommended_action"],
            "recommendation_reason": card["recommendation_reason"],
        }
    )

    assert "liquidity_buffered__moderate__04" not in visible_copy
    assert any(
        token in visible_copy
        for token in (
            "稳健起步方案",
            "保留流动性缓冲",
            "控制波动",
            "readable",
        )
    )


@pytest.mark.contract
def test_goal_baseline_card_surfaces_top_n_candidates_with_metrics_and_disclaimer():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="product_feedback_top_n",
            goal_solver_output=_goal_output_with_user_readable_candidates(no_feasible=False),
        )
    )

    serialized_alternatives = _json_text(card["alternatives"])
    serialized_card = _json_text(card)

    assert len(card["alternatives"]) >= 2
    assert "balanced_progression__moderate__02" not in serialized_alternatives
    assert "growth_tilt__moderate__07" not in serialized_alternatives
    assert "success_probability" in serialized_alternatives
    assert "shortfall_probability" in serialized_alternatives
    assert "max_drawdown_90pct" in serialized_alternatives
    assert any(
        token in serialized_card
        for token in (
            "模型模拟结果",
            "不是历史回测收益承诺",
            "not historical backtest",
        )
    )


@pytest.mark.contract
def test_goal_baseline_card_translates_infeasible_goal_into_user_fallback_options():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="product_feedback_infeasible_goal",
            goal_solver_output=_goal_output_with_user_readable_candidates(no_feasible=True),
            degraded_notes=["goal_path_requires_review"],
        )
    )

    user_visible_payload = _json_text(
        {
            "summary": card["summary"],
            "recommendation_reason": card["recommendation_reason"],
            "evidence_highlights": card["evidence_highlights"],
            "review_conditions": card["review_conditions"],
            "next_steps": card["next_steps"],
            "alternatives": card["alternatives"],
        }
    )

    assert "warning=no_feasible_allocation" not in user_visible_payload
    assert "fallback=closest_feasible_candidate" not in user_visible_payload
    assert "当前不存在满足你回撤约束的配置" in user_visible_payload
    assert "最接近可行的临时参考" in user_visible_payload
    assert "不是正式推荐" in user_visible_payload
    assert any(
        token in user_visible_payload
        for token in (
            "延长到6年",
            "下调到90万",
            "提高到15000",
            "extend horizon",
            "reduce goal amount",
            "increase monthly contribution",
            "放宽回撤",
        )
    )


@pytest.mark.contract
def test_run_orchestrator_onboarding_serialization_includes_input_source_labels(
    goal_solver_input_base,
    live_portfolio_base,
):
    goal_solver_input = deepcopy(goal_solver_input_base)
    goal_solver_input["goal"]["goal_amount"] = 1_000_000.0
    goal_solver_input["goal"]["goal_description"] = "5年内达到100万"
    goal_solver_input["goal"]["horizon_months"] = 60
    goal_solver_input["goal"]["success_prob_threshold"] = 0.70
    goal_solver_input["cashflow_plan"]["monthly_contribution"] = 12_000.0
    goal_solver_input["current_portfolio_value"] = 50_000.0

    live_portfolio = deepcopy(live_portfolio_base)
    live_portfolio["weights"] = {
        "equity_cn": 0.0,
        "bond_cn": 0.0,
        "gold": 0.0,
        "satellite": 0.0,
        "cash": 1.0,
    }
    live_portfolio["total_value"] = 50_000.0
    live_portfolio["available_cash"] = 50_000.0

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "product_feedback_input_provenance"},
        raw_inputs={
            "account_profile_id": goal_solver_input["account_profile_id"],
            "as_of": "2026-03-30T00:00:00Z",
            "market_raw": _market_raw(goal_solver_input),
            "account_raw": _account_raw(goal_solver_input, live_portfolio),
            "goal_raw": dict(goal_solver_input["goal"]),
            "constraint_raw": _constraint_raw(goal_solver_input),
            "behavior_raw": {
                "recent_chase_risk": "low",
                "recent_panic_risk": "none",
                "trade_frequency_30d": 0.0,
                "override_count_90d": 0,
                "cooldown_active": False,
                "cooldown_until": None,
                "behavior_penalty_coeff": 0.0,
            },
            "remaining_horizon_months": goal_solver_input["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input),
            "goal_solver_input": goal_solver_input,
        },
    )

    payload_text = _json_text(result.to_dict())

    for label in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        assert label in payload_text
