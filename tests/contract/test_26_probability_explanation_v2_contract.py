from __future__ import annotations

from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType


def test_goal_baseline_card_surfaces_probability_explanation_v2_layers():
    card = build_decision_card(
        DecisionCardBuildInput(
            card_type=DecisionCardType.GOAL_BASELINE,
            workflow_type="onboarding",
            run_id="probability_explanation_v2",
            goal_solver_input={
                "goal": {
                    "goal_amount": 123_588.24,
                    "horizon_months": 36,
                    "target_annual_return": 0.08,
                    "goal_amount_scope": "total_assets",
                    "goal_amount_basis": "nominal",
                },
                "cashflow_plan": {
                    "monthly_contribution": 2_500.0,
                    "annual_step_up_rate": 0.0,
                    "cashflow_events": [],
                },
                "current_portfolio_value": 18_000.0,
            },
            goal_solver_output={
                "recommended_result": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "success_probability": 0.35,
                    "bucket_success_probability": 0.38,
                    "product_proxy_adjusted_success_probability": 0.35,
                    "product_independent_success_probability": 0.37,
                    "product_probability_method": "product_independent_path",
                    "implied_required_annual_return": 0.08,
                    "expected_annual_return": 0.0621,
                    "expected_terminal_value": 110_000.0,
                    "selected_product_ids": ["ts_equity_core_etf", "ts_bond_core_etf"],
                    "selected_proxy_refs": ["tinyshare://510300.SH", "tinyshare://511010.SH"],
                    "bucket_expected_return_adjustments": {"equity_cn": 0.004, "bond_cn": -0.001},
                    "bucket_volatility_multipliers": {"equity_cn": 1.03, "bond_cn": 0.98},
                    "simulation_coverage_summary": {
                        "selected_product_count": 2,
                        "observed_product_count": 2,
                        "missing_product_count": 0,
                    },
                    "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.65},
                },
                "candidate_menu": [
                    {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "success_probability": 0.35,
                        "bucket_success_probability": 0.38,
                        "product_proxy_adjusted_success_probability": 0.35,
                        "product_independent_success_probability": 0.37,
                        "product_probability_method": "product_independent_path",
                        "expected_annual_return": 0.0621,
                        "expected_terminal_value": 110_000.0,
                        "risk_summary": {"max_drawdown_90pct": 0.16, "shortfall_probability": 0.65},
                        "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
                        "is_feasible": True,
                    }
                ],
                "frontier_analysis": {
                    "recommended": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_independent_success_probability": 0.37,
                        "product_proxy_adjusted_success_probability": 0.35,
                        "product_probability_method": "product_independent_path",
                        "expected_terminal_value": 110_000.0,
                        "expected_annual_return": 0.0621,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "当前推荐在目标差距、波动和执行复杂度之间更平衡。",
                    },
                    "highest_probability": {
                        "allocation_name": "growth_tilt__aggressive__01",
                        "display_name": "增长倾向方案",
                        "product_independent_success_probability": 0.39,
                        "product_proxy_adjusted_success_probability": 0.37,
                        "product_probability_method": "product_independent_path",
                        "expected_terminal_value": 112_000.0,
                        "expected_annual_return": 0.0635,
                        "max_drawdown_90pct": 0.20,
                        "why_selected": "如果只看达成率，这个方案更高。",
                    },
                    "target_return_priority": {
                        "allocation_name": "",
                        "display_name": "",
                        "why_selected": "当前候选里没有方案满足目标收益约束。",
                    },
                    "drawdown_priority": {
                        "allocation_name": "balanced_progression__moderate__02",
                        "display_name": "平衡推进方案",
                        "product_independent_success_probability": 0.37,
                        "product_probability_method": "product_independent_path",
                        "expected_terminal_value": 110_000.0,
                        "expected_annual_return": 0.0621,
                        "max_drawdown_90pct": 0.16,
                        "why_selected": "当前方案也最接近回撤约束优先。",
                    },
                    "scenario_status": {
                        "target_return_priority": {
                            "available": False,
                            "reason": "no_candidate_meets_required_annual_return",
                        }
                    },
                },
                "frontier_diagnostics": {
                    "raw_candidate_count": 5,
                    "feasible_candidate_count": 3,
                    "frontier_max_expected_annual_return": 0.0621,
                    "candidate_families": ["balanced_progression", "growth_tilt", "liquidity_buffered"],
                    "binding_constraints": [
                        {
                            "constraint_name": "required_annual_return",
                            "reason": "no_candidate_meets_required_annual_return",
                            "required_value": 0.08,
                        }
                    ],
                    "structural_limitations": [
                        "required_return_above_frontier_ceiling",
                        "satellite_cap_limits_high_beta_allocations",
                        "expected_return_shrinkage_applied",
                    ],
                },
            },
            execution_plan_summary={
                "product_universe_audit_summary": {
                    "source_status": "observed",
                    "source_name": "tinyshare_runtime_catalog",
                    "item_count": 2000,
                },
                "valuation_audit_summary": {
                    "source_status": "observed",
                    "source_name": "tinyshare_runtime_valuation",
                    "passed_candidate_count": 2,
                },
                "policy_news_audit_summary": {
                    "source_status": "observed",
                    "matched_signal_count": 2,
                    "core_influence_capped": True,
                },
                "product_evidence_panel": {
                    "items": [
                        {
                            "asset_bucket": "equity_cn",
                            "primary_product_name": "沪深300ETF",
                            "primary_product_id": "ts_equity_core_etf",
                            "valuation_audit": {"status": "observed", "reason": "valuation:passed"},
                            "policy_news_audit": {"status": "observed", "score": 0.12},
                        },
                        {
                            "asset_bucket": "bond_cn",
                            "primary_product_name": "国债ETF",
                            "primary_product_id": "ts_bond_core_etf",
                            "valuation_audit": {"status": "not_applicable", "reason": "valuation:not_applicable"},
                            "policy_news_audit": {"status": "not_applicable", "score": 0.0},
                        },
                    ]
                },
            },
            input_provenance={
                "externally_fetched": [
                    {
                        "field": "market_raw.historical_dataset",
                        "value": "tinyshare://market_history",
                        "source_ref": "tinyshare://market_history?symbols=510300.SH,511010.SH",
                    }
                ]
            },
            audit_record={
                "formal_path_visibility": {
                    "status": "ok",
                    "domains": [
                        {"domain": "market_raw", "data_status": "observed"},
                        {"domain": "valuation", "data_status": "computed_from_observed"},
                    ],
                }
            },
        )
    )

    explanation = card["probability_explanation"]

    assert explanation["difficulty_source"] == "constraint_binding"
    assert explanation["constraint_contributions"][0]["name"] == "required_annual_return"
    assert explanation["constraint_contributions"][0]["is_binding"] is True
    assert explanation["evidence_summary"]["product_probability_method"] == "product_independent_path"
    assert explanation["formal_path_evidence"]["formal_path_status"] == "ok"
    assert explanation["evidence_summary"]["product_universe_source_status"] == "observed"
    assert explanation["evidence_summary"]["valuation_source_status"] == "observed"
    assert explanation["evidence_summary"]["policy_news_source_status"] == "observed"
    assert explanation["counterfactuals"]["required_return_gap"] == "1.79%"
    assert explanation["counterfactuals"]["monthly_contribution_delta_to_hit_goal_at_frontier_return"] != ""
    assert explanation["counterfactuals"]["extra_horizon_months_to_hit_goal_at_frontier_return"] != ""
    assert explanation["product_contributions"][0]["product_id"] == "ts_equity_core_etf"
    assert explanation["product_contributions"][0]["success_role"] == "supports_probability"
    assert explanation["product_contributions"][1]["success_role"] == "execution_stability"
