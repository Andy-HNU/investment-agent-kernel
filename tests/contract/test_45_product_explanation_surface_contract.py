from __future__ import annotations

import pytest

from product_mapping import (
    BucketConstructionExplanation,
    ProductExplanation,
    ProductGroupExplanation,
    ProductScenarioMetrics,
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
