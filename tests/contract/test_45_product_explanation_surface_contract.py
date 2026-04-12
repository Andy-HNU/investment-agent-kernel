from __future__ import annotations

from product_mapping import ProductExplanation, ProductScenarioMetrics


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

