from __future__ import annotations

import pytest

from product_mapping import (
    BucketConstructionExplanation,
    ProductExplanation,
    ProductGroupExplanation,
    ProductScenarioMetrics,
    build_portfolio_explanation_surfaces,
    load_builtin_catalog,
    build_execution_plan,
)


def test_product_explanation_requires_full_scenario_ladder() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=(0.01, 0.02),
                terminal_value_range=(1.0, 2.0),
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=0.1,
        terminal_mean_delta_if_removed=1000.0,
        drawdown_delta_if_removed=0.01,
        median_return_delta_if_removed=0.005,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=["high_expected_return"],
        suggested_action="keep",
    )

    assert {
        item.scenario_kind for item in explanation.scenario_metrics
    } == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }


def test_product_explanation_preserves_optional_none_fields() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=None,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=None,
        median_return_delta_if_removed=None,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=[],
        suggested_action=None,
    )

    assert explanation.scenario_metrics[0].annualized_range is None
    assert explanation.scenario_metrics[0].terminal_value_range is None
    assert explanation.success_delta_if_removed is None
    assert explanation.terminal_mean_delta_if_removed is None
    assert explanation.drawdown_delta_if_removed is None
    assert explanation.median_return_delta_if_removed is None
    assert explanation.suggested_action is None


def test_product_explanation_defaults_suggested_action_to_none() -> None:
    explanation = ProductExplanation(
        product_id="cn_equity_dividend_etf",
        role_in_portfolio="main_growth",
        scenario_metrics=[
            ProductScenarioMetrics(
                scenario_kind="historical_replay",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=None,
                pressure_level=None,
            ),
            ProductScenarioMetrics(
                scenario_kind="current_market",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=8.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_mild",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=21.0,
                pressure_level="L0_宽松",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_moderate",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=37.0,
                pressure_level="L1_中性偏紧",
            ),
            ProductScenarioMetrics(
                scenario_kind="deteriorated_severe",
                annualized_range=None,
                terminal_value_range=None,
                pressure_score=60.0,
                pressure_level="L2_风险偏高",
            ),
        ],
        success_delta_if_removed=None,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=None,
        median_return_delta_if_removed=None,
        highest_overlap_product_ids=[],
        highest_diversification_product_ids=[],
        quality_labels=[],
    )

    assert explanation.suggested_action is None


def test_product_explanation_rejects_incomplete_scenario_ladder() -> None:
    with pytest.raises(ValueError, match="full five-scenario ladder"):
        ProductExplanation(
            product_id="cn_equity_dividend_etf",
            role_in_portfolio="main_growth",
            scenario_metrics=[
                ProductScenarioMetrics(
                    scenario_kind="historical_replay",
                    annualized_range=(0.01, 0.02),
                    terminal_value_range=(1.0, 2.0),
                    pressure_score=None,
                    pressure_level=None,
                ),
                ProductScenarioMetrics(
                    scenario_kind="current_market",
                    annualized_range=(0.01, 0.02),
                    terminal_value_range=(1.0, 2.0),
                    pressure_score=8.0,
                    pressure_level="L0_宽松",
                ),
            ],
            success_delta_if_removed=0.1,
            terminal_mean_delta_if_removed=1000.0,
            drawdown_delta_if_removed=0.01,
            median_return_delta_if_removed=0.005,
            highest_overlap_product_ids=[],
            highest_diversification_product_ids=[],
            quality_labels=["high_expected_return"],
            suggested_action="keep",
        )


def test_product_group_explanation_matches_spec_shape() -> None:
    explanation = ProductGroupExplanation(
        group_type="duplicate_exposure_group",
        product_ids=["cn_equity_dividend_etf", "cn_equity_low_vol_etf"],
        rationale="shared equity beta with overlapping core exposure",
        success_delta_if_removed=0.05,
        terminal_mean_delta_if_removed=None,
        drawdown_delta_if_removed=0.02,
        median_return_delta_if_removed=0.01,
    )

    assert explanation.group_type == "duplicate_exposure_group"
    assert explanation.product_ids == ["cn_equity_dividend_etf", "cn_equity_low_vol_etf"]
    assert explanation.rationale == "shared equity beta with overlapping core exposure"
    assert explanation.terminal_mean_delta_if_removed is None


def test_bucket_construction_explanation_matches_spec_shape() -> None:
    explanation = BucketConstructionExplanation(
        bucket="satellite",
        requested_count=5,
        actual_count=4,
        count_source="explicit_user",
        count_satisfied=False,
        unmet_reason="minimum_weight_breach",
        why_split=["strong user request", "diversification gain"],
        no_split_counterfactual=["single_product", "lower_cost"],
        member_roles={"satellite_alpha": "theme_offset", "satellite_beta": "diversifier"},
    )

    assert explanation.actual_count == 4
    assert explanation.count_source == "explicit_user"
    assert explanation.count_satisfied is False
    assert explanation.unmet_reason == "minimum_weight_breach"
    assert explanation.why_split == ["strong user request", "diversification gain"]
    assert explanation.no_split_counterfactual == ["single_product", "lower_cost"]
    assert explanation.member_roles == {
        "satellite_alpha": "theme_offset",
        "satellite_beta": "diversifier",
    }


def test_portfolio_explanation_surfaces_include_top_level_sets() -> None:
    catalog = load_builtin_catalog()
    equity = next(item for item in catalog if item.product_id == "cn_equity_dividend_etf")
    equity_peer = next(item for item in catalog if item.product_id == "cn_equity_csi300_etf")
    gold = next(item for item in catalog if item.product_id == "cn_gold_etf")
    cash = next(item for item in catalog if item.product_id == "cn_cash_money_fund")
    plan = build_execution_plan(
        source_run_id="explanation_surface_test",
        source_allocation_id="explanation_surface_alloc",
        bucket_targets={"equity_cn": 0.50, "gold": 0.10, "cash_liquidity": 0.40},
        catalog=[equity, equity_peer, gold, cash],
        runtime_candidates=[equity, equity_peer, gold, cash],
        formal_path_required=False,
        execution_policy="exploratory",
    )
    surfaces = build_portfolio_explanation_surfaces(
        execution_plan=plan,
        probability_engine_result={
            "run_outcome_status": "success",
            "resolved_result_category": "formal_independent_result",
            "output": {
                "primary_result": {
                    "success_probability": 0.62,
                    "path_stats": {
                        "terminal_value_mean": 121000.0,
                        "terminal_value_p50": 119000.0,
                        "cagr_p50": 0.05,
                        "max_drawdown_p95": 0.16,
                    },
                },
                "current_market_pressure": {
                    "scenario_kind": "current_market",
                    "market_pressure_score": 43.0,
                    "market_pressure_level": "L1_中性偏紧",
                },
                "scenario_comparison": [
                    {"scenario_kind": "historical_replay", "label": "历史回测", "pressure": None},
                    {
                        "scenario_kind": "current_market",
                        "label": "当前市场延续",
                        "pressure": {"market_pressure_score": 43.0, "market_pressure_level": "L1_中性偏紧"},
                    },
                    {
                        "scenario_kind": "deteriorated_mild",
                        "label": "若市场轻度恶化",
                        "pressure": {"market_pressure_score": 57.0, "market_pressure_level": "L2_风险偏高"},
                    },
                    {
                        "scenario_kind": "deteriorated_moderate",
                        "label": "若市场中度恶化",
                        "pressure": {"market_pressure_score": 68.0, "market_pressure_level": "L2_风险偏高"},
                    },
                    {
                        "scenario_kind": "deteriorated_severe",
                        "label": "若市场重度恶化",
                        "pressure": {"market_pressure_score": 87.0, "market_pressure_level": "L3_高压"},
                    },
                ],
            },
        },
    )

    assert set(surfaces) == {
        "bucket_construction_explanations",
        "product_explanations",
        "product_group_explanations",
    }
    assert set(surfaces["bucket_construction_explanations"]) == {"equity_cn", "gold", "cash_liquidity"}
    assert {item.scenario_kind for item in surfaces["product_explanations"]["cn_equity_dividend_etf"].scenario_metrics} == {
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    }
    assert surfaces["product_explanations"]["cn_equity_dividend_etf"].success_delta_if_removed is not None
    assert any(
        group.group_type == "duplicate_exposure_group"
        for group in surfaces["product_group_explanations"].values()
    )
