from __future__ import annotations

import pytest

from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType


@pytest.mark.contract
def test_build_decision_card_validates_quarterly_inputs():
    with pytest.raises(ValueError, match="goal_solver_output"):
        build_decision_card(
            DecisionCardBuildInput(
                card_type=DecisionCardType.QUARTERLY_REVIEW,
                workflow_type="quarterly",
                runtime_result={"ev_report": {}},
            )
        )


@pytest.mark.contract
def test_build_decision_card_requires_formal_input_object():
    with pytest.raises(TypeError, match="DecisionCardBuildInput"):
        build_decision_card(  # type: ignore[arg-type]
            {
                "card_type": "runtime_action",
                "workflow_type": "monthly",
                "runtime_result": {"ev_report": {}},
            }
        )


@pytest.mark.contract
def test_runtime_action_card_surfaces_low_confidence_and_review_conditions():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.RUNTIME_ACTION,
            workflow_type="monthly",
            run_id="decision_card_runtime_low_confidence",
            runtime_result={
                "candidate_poverty": True,
                "candidates_after_filter": 1,
                "ev_report": {
                    "ranked_actions": [
                        {
                            "action": {"type": "observe"},
                            "score": {"total": 0.004},
                            "rank": 1,
                            "is_recommended": True,
                            "recommendation_reason": "candidate_poverty forced safe action",
                        },
                        {
                            "action": {"type": "freeze"},
                            "score": {"total": 0.003},
                            "rank": 2,
                            "is_recommended": False,
                            "recommendation_reason": "freeze is runner up",
                        },
                    ],
                    "eliminated_actions": [
                        (
                            {"type": "rebalance_full"},
                            {"is_feasible": False, "fail_reasons": ["cooldown_active"]},
                        )
                    ],
                    "recommended_action": {"type": "observe"},
                    "recommended_score": {"total": 0.004},
                    "confidence_flag": "low",
                    "confidence_reason": "candidate set too small",
                    "goal_solver_baseline": 0.68,
                    "goal_solver_after_recommended": 0.681,
                },
            },
            audit_record={"control_flags": {"cooldown_until": "2026-04-02T00:00:00Z"}},
        )
    )

    assert card["card_type"] == "runtime_action"
    assert card["recommended_action"] == "observe"
    assert card["runner_up_action"] == "freeze"
    assert card["low_confidence"] is True
    assert "low_confidence=true" in card["guardrails"]
    assert "treat_as_weak_signal" in card["execution_notes"]
    assert "after_cooldown_until=2026-04-02T00:00:00Z" in card["review_conditions"]
    assert "after_next_review_cycle" in card["review_conditions"]
    assert "after_clearer_signal" in card["review_conditions"]
    assert "hold_and_recheck" in card["next_steps"]
    assert "treat_as_weak_signal" in card["next_steps"]
    assert card["key_metrics"]["delta_prob"] == "0.001000"
    assert "runner_up_action=freeze" in card["evidence_highlights"]


@pytest.mark.contract
def test_runtime_action_card_requires_recommended_action_or_ranked_actions():
    with pytest.raises(ValueError, match="recommended_action or ranked_actions"):
        build_decision_card(
            DecisionCardBuildInput(
                card_type=DecisionCardType.RUNTIME_ACTION,
                workflow_type="monthly",
                runtime_result={"ev_report": {"confidence_flag": "low"}},
            )
        )


@pytest.mark.contract
def test_blocked_card_has_no_action_leakage_and_has_next_steps():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.BLOCKED,
            workflow_type="monthly",
            run_id="decision_card_blocked",
            blocking_reasons=["bundle_quality=degraded"],
            control_directives=["manual_review_required"],
        )
    )

    assert card["card_type"] == "blocked"
    assert card["recommended_action"] == "blocked"
    assert card["alternatives"] == []
    assert card["low_confidence"] is True
    assert "resolve_blockers" in card["next_steps"]
    assert "manual_review" in card["next_steps"]
    assert "after_input_repair" in card["review_conditions"]


@pytest.mark.contract
def test_non_blocked_card_rejects_blocking_reasons():
    with pytest.raises(ValueError, match="blocking_reasons"):
        build_decision_card(
            DecisionCardBuildInput(
                card_type=DecisionCardType.RUNTIME_ACTION,
                workflow_type="monthly",
                blocking_reasons=["bundle_quality=degraded"],
                runtime_result={
                    "ev_report": {
                        "ranked_actions": [
                            {
                                "action": {"type": "observe"},
                                "score": {"total": 0.0},
                                "rank": 1,
                                "is_recommended": True,
                                "recommendation_reason": "observe",
                            }
                        ],
                        "recommended_action": {"type": "observe"},
                        "confidence_flag": "low",
                    }
                },
            )
        )


@pytest.mark.contract
def test_quarterly_review_card_keeps_review_action_and_consumes_dual_evidence():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.QUARTERLY_REVIEW,
            workflow_type="quarterly",
            run_id="decision_card_quarterly_review",
            goal_solver_output={
                "recommended_result": {
                    "success_probability": 0.71,
                    "risk_summary": {"max_drawdown_90pct": 0.18},
                },
                "solver_notes": ["baseline refreshed"],
            },
            runtime_result={
                "candidate_poverty": False,
                "ev_report": {
                    "ranked_actions": [
                        {
                            "action": {"type": "observe"},
                            "score": {"total": 0.01},
                            "rank": 1,
                            "is_recommended": True,
                            "recommendation_reason": "observe while validating new baseline",
                        }
                    ],
                    "recommended_action": {"type": "observe"},
                    "confidence_flag": "medium",
                    "confidence_reason": "quarterly review context",
                    "goal_solver_baseline": 0.69,
                    "goal_solver_after_recommended": 0.70,
                },
            },
        )
    )

    assert card["card_type"] == "quarterly_review"
    assert card["recommended_action"] == "review"
    assert card["primary_recommendation"] == "review"
    assert card["key_metrics"]["quarterly_runtime_action"] == "observe"
    assert "success_probability=0.71" in card["evidence_highlights"]
    assert card["runner_up_action"] is None


@pytest.mark.contract
def test_goal_baseline_card_includes_model_disclaimer_and_input_source_summary():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="decision_card_goal_shell",
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.72,
                    "expected_terminal_value": 1_030_000.0,
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "summary": "在提高达成率的同时，尽量守住波动体验。",
                        "success_probability": 0.72,
                        "expected_terminal_value": 1_030_000.0,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                        "complexity_label": "medium",
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    }
                ],
                "disclaimer": "以下为模型模拟结果，不是历史回测收益承诺。",
            },
            input_provenance={
                "user_provided": [{"field": "goal.goal_amount", "label": "目标期末总资产", "value": 1_000_000}],
                "system_inferred": [{"field": "goal.goal_gap", "label": "目标缺口", "value": 950_000}],
                "default_assumed": [{"field": "market_raw", "label": "市场输入", "value": "system_default_market_snapshot"}],
                "externally_fetched": [],
            },
        )
    )

    assert card["model_disclaimer"] == "以下为模型模拟结果，不是历史回测收益承诺。"
    assert "用户提供 1 项" in card["input_source_summary"]
    assert "系统推断 1 项" in card["input_source_summary"]
    assert card["input_source_sections"][0]["source_label"] == "用户提供"


@pytest.mark.contract
def test_goal_baseline_card_surfaces_probability_explanation_and_product_evidence_panel():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="decision_card_probability_explanation",
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.68,
                    "bucket_success_probability": 0.68,
                    "product_adjusted_success_probability": 0.65,
                    "implied_required_annual_return": 0.08,
                    "simulation_mode_used": "static_gaussian",
                    "expected_terminal_value": 1_030_000.0,
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "summary": "在提高达成率的同时，尽量守住波动体验。",
                        "success_probability": 0.68,
                        "bucket_success_probability": 0.68,
                        "product_adjusted_success_probability": 0.65,
                        "implied_required_annual_return": 0.08,
                        "simulation_mode_used": "static_gaussian",
                        "expected_terminal_value": 1_030_000.0,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    },
                    {
                        "allocation_name": "goal_chasing__aggressive__01",
                        "display_name": "冲目标方案",
                        "summary": "达成率更高，但回撤和复杂度也更高。",
                        "success_probability": 0.74,
                        "bucket_success_probability": 0.74,
                        "product_adjusted_success_probability": 0.70,
                        "implied_required_annual_return": 0.08,
                        "simulation_mode_used": "static_gaussian",
                        "expected_terminal_value": 1_080_000.0,
                        "risk_summary": {"max_drawdown_90pct": 0.29, "shortfall_probability": 0.26},
                        "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
                        "is_feasible": True,
                    },
                ],
                "disclaimer": "以下为模型模拟结果，不是历史回测收益承诺。",
            },
            execution_plan_summary={
                "plan_id": "plan_probability_explanation",
                "product_evidence_panel": {
                    "items": [
                        {
                            "asset_bucket": "equity_cn",
                            "primary_product_name": "沪深300ETF",
                            "primary_product_id": "cn_equity_csi300_etf",
                            "provider_symbol": "510300",
                            "target_weight": 0.55,
                            "recommended_products": [
                                {
                                    "product_id": "cn_equity_csi300_etf",
                                    "product_name": "沪深300ETF",
                                    "wrapper_type": "etf",
                                    "core_or_satellite": "core",
                                    "target_weight_within_bucket": 0.60,
                                    "target_portfolio_weight": 0.33,
                                },
                                {
                                    "product_id": "cn_equity_dividend_etf",
                                    "product_name": "红利ETF",
                                    "wrapper_type": "etf",
                                    "core_or_satellite": "core",
                                    "target_weight_within_bucket": 0.25,
                                    "target_portfolio_weight": 0.1375,
                                },
                            ],
                            "selection_evidence": {
                                "core_or_satellite": "core",
                                "selection_reason": ["候选按流动性、费率、估值与约束排序。"],
                            },
                        }
                    ]
                },
            },
        )
    )

    assert card["key_metrics"]["bucket_success_probability"] == "68.00%"
    assert card["key_metrics"]["product_adjusted_success_probability"] == "65.00%"
    assert card["key_metrics"]["implied_required_annual_return"] == "8.00%"
    assert card["probability_explanation"]["highest_probability_allocation_label"] == "冲目标方案"
    assert card["probability_explanation"]["recommended_allocation_label"] == "平衡推进方案"
    assert "不是最高达成率方案" in card["probability_explanation"]["why_not_highest_probability"]
    assert card["product_evidence_panel"]["items"][0]["primary_product_name"] == "沪深300ETF"
    assert card["product_evidence_panel"]["items"][0]["recommended_products"][0]["product_id"] == "cn_equity_csi300_etf"
    assert card["product_evidence_panel"]["items"][0]["selection_evidence"]["selection_reason"]
