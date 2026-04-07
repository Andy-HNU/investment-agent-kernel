from __future__ import annotations

from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType


def _build_input(*, disclosure_level: str, confidence_level: str, resolved_result_category: str) -> DecisionCardBuildInput:
    return DecisionCardBuildInput(
        card_type=DecisionCardType.GOAL_BASELINE,
        workflow_type="onboarding",
        run_id=f"probability_disclosure_{disclosure_level}",
        run_outcome_status="completed",
        resolved_result_category=resolved_result_category,
        disclosure_decision={
            "result_category": resolved_result_category,
            "disclosure_level": disclosure_level,
            "confidence_level": confidence_level,
            "data_completeness": "complete",
            "calibration_quality": "acceptable",
            "point_value_allowed": disclosure_level == "point_and_range",
            "range_required": disclosure_level in {"point_and_range", "range_only"},
            "diagnostic_only": disclosure_level == "diagnostic_only",
            "precision_cap": disclosure_level,
            "reasons": [],
        },
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
            "recommended_allocation": {
                "name": "balanced_progression__moderate__02",
                "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.10, "satellite": 0.05},
            },
            "recommended_result": {
                "allocation_name": "balanced_progression__moderate__02",
                "success_probability": 0.474,
                "bucket_success_probability": 0.5032,
                "product_proxy_adjusted_success_probability": 0.5032,
                "product_independent_success_probability": 0.474,
                "product_probability_method": "product_independent_path",
                "implied_required_annual_return": 0.08,
                "expected_annual_return": 0.0798,
                "expected_terminal_value": 123_000.0,
                "risk_summary": {
                    "max_drawdown_90pct": 0.20,
                    "shortfall_probability": 0.526,
                },
            },
            "candidate_menu": [],
            "frontier_analysis": {
                "recommended": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "display_name": "平衡推进方案",
                    "product_independent_success_probability": 0.474,
                    "product_proxy_adjusted_success_probability": 0.5032,
                    "product_probability_method": "product_independent_path",
                    "expected_terminal_value": 123_000.0,
                    "expected_annual_return": 0.0798,
                    "max_drawdown_90pct": 0.20,
                    "why_selected": "当前推荐在收益和回撤之间更平衡。",
                },
                "highest_probability": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "display_name": "平衡推进方案",
                    "product_independent_success_probability": 0.474,
                    "product_proxy_adjusted_success_probability": 0.5032,
                    "product_probability_method": "product_independent_path",
                    "expected_terminal_value": 123_000.0,
                    "expected_annual_return": 0.0798,
                    "max_drawdown_90pct": 0.20,
                    "why_selected": "当前推荐也是最高达成率方案。",
                },
                "target_return_priority": {"allocation_name": "", "display_name": "", "why_selected": ""},
                "drawdown_priority": {
                    "allocation_name": "balanced_progression__moderate__02",
                    "display_name": "平衡推进方案",
                    "product_independent_success_probability": 0.474,
                    "product_probability_method": "product_independent_path",
                    "expected_terminal_value": 123_000.0,
                    "expected_annual_return": 0.0798,
                    "max_drawdown_90pct": 0.20,
                    "why_selected": "当前方案也最接近回撤约束优先。",
                },
            },
            "frontier_diagnostics": {
                "frontier_max_expected_annual_return": 0.0798,
                "binding_constraints": [
                    {
                        "constraint_name": "required_annual_return",
                        "reason": "no_candidate_meets_required_annual_return",
                    }
                ],
                "structural_limitations": ["required_return_above_frontier_ceiling"],
            },
            "calibration_summary": {
                "sample_count": 180,
                "calibration_quality": "acceptable",
                "reliability_buckets": [],
                "regime_breakdown": [],
                "source_ref": "calibration://contract",
            },
        },
    )


def test_goal_baseline_card_shows_point_and_range_when_formal_independent_high_confidence():
    card = build_decision_card(_build_input(
        disclosure_level="point_and_range",
        confidence_level="high",
        resolved_result_category="formal_independent_result",
    ))

    assert card["key_metrics"]["success_probability"] == "47.40%"
    assert card["key_metrics"]["expected_annual_return"] == "7.98%"
    assert card["key_metrics"]["success_probability_range"] != ""
    assert card["key_metrics"]["expected_annual_return_range"] != ""
    assert card["probability_explanation"]["success_probability_point"] == "47.40%"
    assert card["probability_explanation"]["success_probability_range"] != ""
    assert card["probability_explanation"]["expected_annual_return_point"] == "7.98%"
    assert card["probability_explanation"]["expected_annual_return_range"] != ""
    assert card["probability_explanation"]["confidence_level"] == "high"
    assert card["probability_explanation"]["calibration_quality"] == "acceptable"


def test_goal_baseline_card_hides_point_estimates_when_range_only():
    card = build_decision_card(_build_input(
        disclosure_level="range_only",
        confidence_level="medium",
        resolved_result_category="formal_estimated_result",
    ))

    assert card["key_metrics"]["success_probability"] == ""
    assert card["key_metrics"]["expected_annual_return"] == ""
    assert card["key_metrics"]["success_probability_range"] != ""
    assert card["key_metrics"]["expected_annual_return_range"] != ""
    assert card["probability_explanation"]["success_probability_point"] == ""
    assert card["probability_explanation"]["expected_annual_return_point"] == ""
    assert card["probability_explanation"]["success_probability_range"] != ""
    assert card["probability_explanation"]["expected_annual_return_range"] != ""
    assert card["probability_explanation"]["confidence_level"] == "medium"


def test_goal_baseline_card_downgrades_to_diagnostic_only_without_ranges():
    card = build_decision_card(_build_input(
        disclosure_level="diagnostic_only",
        confidence_level="low",
        resolved_result_category="degraded_formal_result",
    ))

    assert card["key_metrics"]["success_probability"] == ""
    assert card["key_metrics"]["expected_annual_return"] == ""
    assert card["key_metrics"]["success_probability_range"] == ""
    assert card["key_metrics"]["expected_annual_return_range"] == ""
    assert card["probability_explanation"]["success_probability_point"] == ""
    assert card["probability_explanation"]["success_probability_range"] == ""
    assert card["probability_explanation"]["expected_annual_return_point"] == ""
    assert card["probability_explanation"]["expected_annual_return_range"] == ""
    assert card["probability_explanation"]["confidence_level"] == "low"
