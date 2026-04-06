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
                    "product_proxy_adjusted_success_probability": 0.65,
                    "product_probability_method": "product_proxy_adjustment_estimate",
                    "implied_required_annual_return": 0.08,
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
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "implied_required_annual_return": 0.08,
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
                        "product_proxy_adjusted_success_probability": 0.70,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "implied_required_annual_return": 0.08,
                        "expected_terminal_value": 1_080_000.0,
                        "risk_summary": {"max_drawdown_90pct": 0.29, "shortfall_probability": 0.26},
                        "weights": {"equity_cn": 0.70, "bond_cn": 0.15, "gold": 0.05, "satellite": 0.10},
                        "is_feasible": True,
                    },
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "当前推荐方案，同时权衡达成率、回撤和执行复杂度。",
                    },
                    "highest_probability": {
                        "allocation_name": "goal_chasing__aggressive__01",
                        "display_name": "冲目标方案",
                        "product_proxy_adjusted_success_probability": 0.70,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "expected_terminal_value": 1_080_000.0,
                        "expected_annual_return": 0.079,
                        "max_drawdown_90pct": 0.29,
                        "why_selected": "当前候选里，这个方案的产品修正后达成率最高。",
                    },
                    "target_return_priority": {
                        "allocation_name": "",
                        "display_name": "",
                        "why_selected": "当前候选里没有方案满足目标收益约束。",
                    },
                    "drawdown_priority": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "如果优先守住回撤约束，这个方案更稳。",
                    },
                    "scenario_status": {
                        "target_return_priority": {
                            "available": False,
                            "reason": "no_candidate_meets_required_annual_return",
                        }
                    },
                },
                "disclaimer": "以下为模型模拟结果，不是历史回测收益承诺。",
            },
            execution_plan_summary={
                "product_universe_audit_summary": {
                    "requested": True,
                    "source_status": "observed",
                    "source_name": "tinyshare_runtime_catalog",
                    "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
                    "as_of": "2026-04-05",
                    "item_count": 7420,
                },
                "valuation_audit_summary": {
                    "requested": True,
                    "source_status": "observed",
                    "source_name": "tinyshare_runtime_valuation",
                    "source_ref": "tinyshare://daily_basic?trade_date=20260403",
                    "as_of": "2026-04-05",
                },
                "policy_news_audit_summary": {
                    "source_status": "observed",
                    "matched_signal_count": 2,
                    "data_status": "computed_from_observed",
                    "confidence_data_status": "inferred",
                },
                "formal_path_visibility": {
                    "status": "formal",
                    "execution_eligible": True,
                    "execution_eligibility_reason": "all_required_fields_present",
                    "degraded_scope": [],
                    "fallback_used": False,
                    "fallback_scope": [],
                    "reasons": [],
                    "missing_audit_fields": [],
                },
                "items": [
                    {
                        "asset_bucket": "equity_cn",
                        "primary_product_id": "cn_equity_csi300_etf",
                        "target_weight": 0.55,
                        "risk_labels": ["权益波动"],
                        "valuation_audit": {
                            "status": "observed",
                            "valuation_mode": "index_proxy",
                            "pe_ratio": 18.0,
                            "percentile": 0.22,
                            "passed_filters": True,
                        },
                        "policy_news_audit": {
                            "status": "not_applicable",
                            "score": 0.0,
                            "realtime_eligible": False,
                        },
                    },
                    {
                        "asset_bucket": "satellite",
                        "primary_product_id": "cn_satellite_energy_etf",
                        "target_weight": 0.10,
                        "risk_labels": ["权益波动", "主题波动"],
                        "valuation_audit": {
                            "status": "observed",
                            "valuation_mode": "holdings_proxy",
                            "pe_ratio": 22.0,
                            "percentile": 0.18,
                            "passed_filters": True,
                        },
                        "policy_news_audit": {
                            "status": "observed",
                            "score": 0.48,
                            "realtime_eligible": True,
                            "matched_signal_ids": ["sig_energy_001"],
                            "influence_scope": "satellite_dynamic",
                        },
                    },
                ],
                "product_evidence_panel": {
                    "items": [
                        {
                            "asset_bucket": "equity_cn",
                            "primary_product_name": "沪深300ETF",
                            "primary_product_id": "cn_equity_csi300_etf",
                            "recommended_products": [
                                {"product_id": "cn_equity_csi300_etf", "product_name": "沪深300ETF"}
                            ],
                        }
                    ]
                },
            },
        )
    )

    assert card["key_metrics"]["bucket_success_probability"] == "68.00%"
    assert card["key_metrics"]["product_proxy_adjusted_success_probability"] == "65.00%"
    assert card["key_metrics"]["product_probability_method"] == "product_proxy_adjustment_estimate"
    assert card["key_metrics"]["implied_required_annual_return"] == "8.00%"
    assert card["key_metrics"]["expected_annual_return"] == "6.10%"
    assert card["candidate_options"][0]["expected_annual_return"] == "6.10%"
    assert card["goal_alternatives"][0]["expected_annual_return"] == "7.90%"
    assert card["probability_explanation"]["highest_probability_allocation_label"] == "冲目标方案"
    assert card["probability_explanation"]["recommended_allocation_label"] == "平衡推进方案"
    assert card["probability_explanation"]["recommended_expected_annual_return"] == "6.10%"
    assert card["probability_explanation"]["highest_probability_expected_annual_return"] == "7.90%"
    assert card["probability_explanation"]["implied_required_annual_return"] == "8.00%"
    assert "recommended_allocation_name" not in card["probability_explanation"]
    assert "highest_probability_allocation_name" not in card["probability_explanation"]
    assert "不是最高达成率方案" in card["probability_explanation"]["why_not_highest_probability"]
    assert card["probability_explanation"]["why_not_target_return_priority"] == "no_candidate_meets_required_annual_return"
    assert card["probability_explanation"]["product_probability_method"] == "product_proxy_adjustment_estimate"
    assert "代理修正" in card["probability_explanation"]["product_probability_disclosure"]
    assert card["probability_explanation"]["constraint_contributions"][0]["name"] == "required_annual_return"
    assert card["probability_explanation"]["evidence_layer"]["formal_path_status"] in {"formal", "ok", "degraded", "not_requested"}
    assert card["probability_explanation"]["evidence_layer"]["observed_inputs"] >= 2
    assert card["probability_explanation"]["counterfactuals"]["fallback_scenarios"][0]["scenario"] == "keep_target_relax_drawdown"
    assert {item["product_id"] for item in card["probability_explanation"]["product_contributions"]} == {
        "cn_equity_csi300_etf",
        "cn_satellite_energy_etf",
    }
    assert card["product_evidence_panel"]["items"][0]["primary_product_name"] == "沪深300ETF"


@pytest.mark.contract
def test_goal_baseline_card_surfaces_product_independent_probability_disclosure():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="decision_card_product_independent_probability",
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.68,
                    "bucket_success_probability": 0.61,
                    "product_proxy_adjusted_success_probability": 0.64,
                    "product_independent_success_probability": 0.68,
                    "product_probability_method": "product_independent_path",
                    "implied_required_annual_return": 0.08,
                    "expected_terminal_value": 1_030_000.0,
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "success_probability": 0.68,
                        "bucket_success_probability": 0.61,
                        "product_proxy_adjusted_success_probability": 0.64,
                        "product_independent_success_probability": 0.68,
                        "product_probability_method": "product_independent_path",
                        "expected_annual_return": 0.061,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "bucket_success_probability": 0.61,
                        "product_proxy_adjusted_success_probability": 0.64,
                        "product_independent_success_probability": 0.68,
                        "product_probability_method": "product_independent_path",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "逐产品独立路径下当前推荐仍最均衡。",
                    },
                },
                "frontier_diagnostics": {
                    "binding_constraints": [{"constraint_name": "required_annual_return"}],
                    "structural_limitations": ["required_return_above_frontier_ceiling"],
                },
            },
        )
    )

    assert card["key_metrics"]["product_independent_success_probability"] == "68.00%"
    assert card["key_metrics"]["product_proxy_adjusted_success_probability"] == "64.00%"
    assert card["probability_explanation"]["product_probability_method"] == "product_independent_path"
    assert "逐产品独立路径" in card["probability_explanation"]["product_probability_disclosure"]
    assert card["probability_explanation"]["difficulty_source"] == "constraint_binding"


@pytest.mark.contract
def test_goal_baseline_card_surfaces_probability_explanation_v2_layers(monkeypatch):
    monkeypatch.setattr(
        "decision_card.builder._build_probability_counterfactuals",
        lambda *_args, **_kwargs: {
            "keep_target_return": {"estimated_required_drawdown_90pct": "20.00%"},
            "keep_drawdown": {"expected_annual_return": "6.10%"},
            "increase_monthly_contribution_20pct": {"success_probability": "71.00%"},
            "extend_horizon_12m": {"success_probability": "74.00%"},
        },
    )
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="decision_card_probability_explanation_v2",
            goal_solver_input={
                "snapshot_id": "snapshot_probability_v2",
                "account_profile_id": "probability_v2_user",
                "goal": {
                    "goal_amount": 1_000_000.0,
                    "horizon_months": 36,
                    "goal_description": "probability explanation v2",
                    "success_prob_threshold": 0.7,
                    "priority": "important",
                    "risk_preference": "moderate",
                    "target_annual_return": 0.08,
                },
                "cashflow_plan": {
                    "monthly_contribution": 2500.0,
                    "annual_step_up_rate": 0.0,
                    "cashflow_events": [],
                },
                "current_portfolio_value": 18000.0,
                "candidate_allocations": [
                    {
                        "name": "balanced_progression__moderate__02",
                        "weights": {
                            "equity_cn": 0.55,
                            "bond_cn": 0.25,
                            "gold": 0.10,
                            "satellite": 0.10,
                        },
                        "complexity_score": 0.12,
                        "description": "balanced candidate",
                    }
                ],
                "constraints": {
                    "max_drawdown_tolerance": 0.20,
                    "ips_bucket_boundaries": {
                        "equity_cn": [0.20, 0.70],
                        "bond_cn": [0.10, 0.50],
                        "gold": [0.00, 0.25],
                        "satellite": [0.00, 0.15],
                    },
                    "satellite_cap": 0.15,
                    "theme_caps": {"technology": 0.10},
                    "qdii_cap": 0.20,
                    "liquidity_reserve_min": 0.05,
                },
                "solver_params": {
                    "version": "contract",
                    "n_paths": 32,
                    "n_paths_lightweight": 16,
                    "seed": 7,
                    "market_assumptions": {
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
                            "satellite": 0.24,
                        },
                        "correlation_matrix": {
                            "equity_cn": {"equity_cn": 1.0, "bond_cn": 0.15, "gold": 0.20, "satellite": 0.75},
                            "bond_cn": {"equity_cn": 0.15, "bond_cn": 1.0, "gold": 0.10, "satellite": 0.15},
                            "gold": {"equity_cn": 0.20, "bond_cn": 0.10, "gold": 1.0, "satellite": 0.15},
                            "satellite": {"equity_cn": 0.75, "bond_cn": 0.15, "gold": 0.15, "satellite": 1.0},
                        },
                    },
                },
                "candidate_product_contexts": {
                    "balanced_progression__moderate__02": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "product_probability_method": "product_independent_path",
                        "bucket_expected_return_adjustments": {"equity_cn": 0.01, "satellite": 0.02},
                        "bucket_volatility_multipliers": {"equity_cn": 1.05, "satellite": 1.12},
                        "selected_product_ids": ["cn_equity_csi300_etf", "cn_satellite_energy_etf"],
                        "selected_proxy_refs": ["tinyshare://510300.SH", "tinyshare://159930.SZ"],
                        "product_history_profiles": [
                            {
                                "product_id": "cn_equity_csi300_etf",
                                "source_ref": "tinyshare://510300.SH",
                                "observed_history_days": 250,
                                "inferred_history_days": 0,
                                "inference_weight": 1.0,
                                "data_status": "observed",
                            },
                            {
                                "product_id": "cn_satellite_energy_etf",
                                "source_ref": "tinyshare://159930.SZ",
                                "observed_history_days": 250,
                                "inferred_history_days": 0,
                                "inference_weight": 1.0,
                                "data_status": "observed",
                            },
                        ],
                        "product_simulation_input": {
                            "frequency": "daily",
                            "simulation_method": "product_independent_path",
                            "audit_window": {
                                "start_date": "2025-01-02",
                                "end_date": "2026-04-03",
                                "trading_days": 250,
                                "observed_days": 250,
                                "inferred_days": 0,
                            },
                            "coverage_summary": {
                                "selected_product_count": 2,
                                "observed_product_count": 2,
                                "missing_product_count": 0,
                            },
                            "products": [],
                        },
                    }
                },
            },
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.68,
                    "bucket_success_probability": 0.61,
                    "product_proxy_adjusted_success_probability": 0.64,
                    "product_independent_success_probability": 0.68,
                    "product_probability_method": "product_independent_path",
                    "implied_required_annual_return": 0.08,
                    "expected_annual_return": 0.061,
                    "expected_terminal_value": 1_030_000.0,
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "success_probability": 0.68,
                        "bucket_success_probability": 0.61,
                        "product_proxy_adjusted_success_probability": 0.64,
                        "product_independent_success_probability": 0.68,
                        "product_probability_method": "product_independent_path",
                        "expected_annual_return": 0.061,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "bucket_success_probability": 0.61,
                        "product_proxy_adjusted_success_probability": 0.64,
                        "product_independent_success_probability": 0.68,
                        "product_probability_method": "product_independent_path",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "逐产品独立路径下当前推荐仍最均衡。",
                    },
                },
                "frontier_diagnostics": {
                    "raw_candidate_count": 4,
                    "feasible_candidate_count": 2,
                    "frontier_max_expected_annual_return": 0.062,
                    "binding_constraints": [{"constraint_name": "required_annual_return", "reason": "no_candidate_meets_required_annual_return"}],
                    "structural_limitations": ["required_return_above_frontier_ceiling", "expected_return_shrinkage_applied"],
                },
            },
            input_provenance={
                "user_provided": [{"field": "goal.goal_amount", "label": "目标期末总资产", "value": 1_000_000}],
                "default_assumed": [{"field": "behavior_raw", "label": "行为输入", "value": "product_default_behavior_snapshot"}],
                "externally_fetched": [{"field": "market_raw", "label": "市场输入", "value": "tinyshare_runtime_catalog"}],
            },
            execution_plan_summary={
                "items": [
                    {
                        "asset_bucket": "equity_cn",
                        "primary_product_id": "cn_equity_csi300_etf",
                        "valuation_audit": {
                            "status": "observed",
                            "passed_filters": True,
                            "reason": "valuation:passed",
                        },
                        "policy_news_audit": {
                            "status": "not_applicable",
                            "score": 0.0,
                        },
                    },
                    {
                        "asset_bucket": "satellite",
                        "primary_product_id": "cn_satellite_energy_etf",
                        "valuation_audit": {
                            "status": "observed",
                            "passed_filters": True,
                            "reason": "valuation:passed",
                        },
                        "policy_news_audit": {
                            "status": "observed",
                            "score": 0.42,
                            "dominant_direction": "positive",
                        },
                    },
                ]
            },
        )
    )

    explanation = card["probability_explanation"]
    assert explanation["constraint_contributions"][0]["name"] == "required_annual_return"
    assert explanation["evidence_layer"]["product_probability_method"] == "product_independent_path"
    assert explanation["evidence_layer"]["observed_product_count"] == 2
    assert explanation["evidence_layer"]["formal_path_status"] in {"formal", "ok", "degraded", "not_requested"}
    assert explanation["formal_path_evidence"]["formal_path_status"] in {"formal", "ok", "degraded", "not_requested"}
    assert explanation["counterfactuals"]["keep_target_return"]["estimated_required_drawdown_90pct"] == "20.00%"
    assert {item["product_id"] for item in explanation["product_contributions"]} == {
        "cn_equity_csi300_etf",
        "cn_satellite_energy_etf",
    }


@pytest.mark.contract
def test_goal_baseline_card_surfaces_unavailable_frontier_reasons():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="decision_card_frontier_unavailable",
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.68,
                    "bucket_success_probability": 0.68,
                    "product_proxy_adjusted_success_probability": 0.65,
                    "product_probability_method": "product_proxy_adjustment_estimate",
                    "implied_required_annual_return": 0.08,
                    "expected_terminal_value": 1_030_000.0,
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "success_probability": 0.68,
                        "bucket_success_probability": 0.68,
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "implied_required_annual_return": 0.08,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.28},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.25, "gold": 0.10, "satellite": 0.10},
                        "is_feasible": True,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "当前推荐就是最高达成率方案。",
                    },
                    "highest_probability": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_proxy_adjusted_success_probability": 0.65,
                        "product_probability_method": "product_proxy_adjustment_estimate",
                        "expected_terminal_value": 1_030_000.0,
                        "expected_annual_return": 0.061,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "当前推荐就是最高达成率方案。",
                    },
                    "target_return_priority": {
                        "allocation_name": "",
                        "display_name": "",
                        "why_selected": "当前候选里没有方案满足目标收益约束。",
                    },
                    "drawdown_priority": {
                        "allocation_name": "",
                        "display_name": "",
                        "why_selected": "当前候选里没有方案满足最大回撤约束。",
                    },
                    "scenario_status": {
                        "target_return_priority": {
                            "available": False,
                            "reason": "no_candidate_meets_required_annual_return",
                        },
                        "drawdown_priority": {
                            "available": False,
                            "reason": "no_candidate_meets_max_drawdown_tolerance",
                        },
                    },
                },
            },
        )
    )

    assert card["probability_explanation"]["why_not_highest_probability"] == "当前推荐方案同时也是当前候选中的最高达成率方案。"
    assert card["probability_explanation"]["why_not_target_return_priority"] == "no_candidate_meets_required_annual_return"
    assert card["probability_explanation"]["why_not_drawdown_priority"] == "no_candidate_meets_max_drawdown_tolerance"
