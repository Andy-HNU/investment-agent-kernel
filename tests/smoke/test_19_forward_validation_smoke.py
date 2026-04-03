from __future__ import annotations


def test_run_anchor_validation_returns_realized_terminal_value():
    from scripts.run_v12_forward_validation import run_anchor_validation

    result = run_anchor_validation(anchor_date="2021-01-01", horizon_months=60)

    assert "predicted_success_probability" in result
    assert "predicted_product_adjusted_success_probability" in result
    assert "realized_terminal_value" in result
    assert "goal_achieved" in result
    assert "future_observed_days" in result


def test_run_rolling_validation_returns_anchor_summary():
    from scripts.run_v12_forward_validation import run_rolling_validation

    result = run_rolling_validation(
        anchor_dates=["2021-01-01", "2022-01-03"],
        horizon_months=24,
    )

    assert result["anchor_count"] == 2
    assert "hit_rate" in result
    assert "avg_predicted_success_probability" in result
    assert len(result["results"]) == 2
