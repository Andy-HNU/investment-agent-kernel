from __future__ import annotations

import pytest

from probability_engine.challengers import build_stress_recipe_result, run_challenger_bootstrap
from probability_engine.contracts import PathStatsSummary, ProbabilityEngineRunResult, RecipeSimulationResult, SuccessEventSpec
from probability_engine.disclosure_bridge import assemble_probability_run_result


def _make_success_event_spec() -> SuccessEventSpec:
    return SuccessEventSpec(
        horizon_days=20,
        horizon_months=1,
        target_type="goal_amount",
        target_value=1.05,
        drawdown_constraint=0.20,
        benchmark_ref=None,
        contribution_policy="fixed",
        withdrawal_policy="none",
        rebalancing_policy_ref="none",
        return_basis="nominal",
        fee_basis="net",
        success_logic="joint_target_and_drawdown",
    )


def _make_primary_result() -> RecipeSimulationResult:
    return RecipeSimulationResult(
        recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
        role="primary",
        success_probability=0.62,
        success_probability_range=(0.58, 0.66),
        cagr_range=(0.05, 0.11),
        drawdown_range=(0.08, 0.16),
        sample_count=4000,
        path_stats=PathStatsSummary(
            terminal_value_mean=1.08,
            terminal_value_p05=0.92,
            terminal_value_p50=1.05,
            terminal_value_p95=1.22,
            cagr_p05=0.04,
            cagr_p50=0.08,
            cagr_p95=0.12,
            max_drawdown_p05=0.06,
            max_drawdown_p50=0.11,
            max_drawdown_p95=0.18,
            success_count=2480,
            path_count=4000,
        ),
        calibration_link_ref="cal://primary",
    )


def _make_secondary_result(*, recipe_name: str, role: str, success_probability: float, success_range: tuple[float, float]) -> RecipeSimulationResult:
    return RecipeSimulationResult(
        recipe_name=recipe_name,
        role=role,
        success_probability=success_probability,
        success_probability_range=success_range,
        cagr_range=(0.01, 0.09),
        drawdown_range=(0.10, 0.24),
        sample_count=2000,
        path_stats=PathStatsSummary(
            terminal_value_mean=1.02,
            terminal_value_p05=0.84,
            terminal_value_p50=1.00,
            terminal_value_p95=1.15,
            cagr_p05=0.00,
            cagr_p50=0.05,
            cagr_p95=0.10,
            max_drawdown_p05=0.08,
            max_drawdown_p50=0.14,
            max_drawdown_p95=0.26,
            success_count=int(round(success_probability * 2000)),
            path_count=2000,
        ),
        calibration_link_ref=f"cal://{recipe_name}",
    )


def test_scheme_c_challenger_bootstrap_and_disclosure_bridge_widen_range() -> None:
    history_matrix = [
        [0.01, 0.02, -0.01, 0.03, 0.01, 0.00, -0.02, 0.01],
        [0.00, -0.01, 0.02, 0.01, -0.02, 0.00, 0.01, 0.02],
    ]
    regime_labels = [
        "normal",
        "normal",
        "risk_off",
        "risk_off",
        "normal",
        "stress",
        "risk_off",
        "normal",
    ]
    challenger = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=2,
        path_count=64,
        horizon_days=4,
        success_event_spec=_make_success_event_spec(),
    )
    stress = build_stress_recipe_result(_make_primary_result())
    run_result = assemble_probability_run_result(
        primary=_make_primary_result(),
        challengers=[challenger],
        stresses=[stress],
        success_event_spec=_make_success_event_spec(),
    )

    assert isinstance(run_result, ProbabilityEngineRunResult)
    assert run_result.output is not None
    assert run_result.output.primary_result.role == "primary"
    assert run_result.output.challenger_results[0].role == "challenger"
    assert run_result.output.stress_results[0].role == "stress"
    assert run_result.output.probability_disclosure_payload.published_point == 0.62
    assert run_result.output.probability_disclosure_payload.published_range is not None
    assert run_result.output.probability_disclosure_payload.published_range[0] <= 0.58
    assert run_result.output.probability_disclosure_payload.published_range[1] >= 0.66
    assert run_result.output.probability_disclosure_payload.gap_total is not None
    assert run_result.output.probability_disclosure_payload.widening_method == "wilson_plus_gap_total"
    assert run_result.resolved_result_category in {"formal_strict_result", "formal_estimated_result", "degraded_formal_result"}


def test_disclosure_bridge_applies_fixed_gap_widening_formula() -> None:
    primary = _make_primary_result()
    challenger = _make_secondary_result(
        recipe_name="challenger_regime_conditioned_block_bootstrap_v1",
        role="challenger",
        success_probability=0.54,
        success_range=(0.50, 0.58),
    )
    stress = _make_secondary_result(
        recipe_name="stress_downside_tail_v1",
        role="stress",
        success_probability=0.50,
        success_range=(0.45, 0.54),
    )

    run_result = assemble_probability_run_result(
        primary=primary,
        challengers=[challenger],
        stresses=[stress],
        success_event_spec=_make_success_event_spec(),
    )

    assert run_result.output is not None
    payload = run_result.output.probability_disclosure_payload
    assert payload.published_point == 0.62
    assert payload.challenger_gap == pytest.approx(0.08)
    assert payload.stress_gap == pytest.approx(0.12)
    assert payload.gap_total == pytest.approx(0.12)
    assert payload.published_range == pytest.approx((0.52, 0.72))
    assert payload.confidence_level == "low"
    assert payload.disclosure_level == "range_only"
    assert run_result.run_outcome_status == "degraded"
    assert run_result.resolved_result_category == "degraded_formal_result"


def test_disclosure_bridge_requires_primary_result() -> None:
    run_result = assemble_probability_run_result(
        primary=None,
        challengers=[],
        stresses=[],
        success_event_spec=_make_success_event_spec(),
    )

    assert run_result.run_outcome_status == "failure"
    assert run_result.resolved_result_category == "null"
    assert run_result.output is None
    assert run_result.failure_artifact is not None
    assert run_result.failure_artifact.failure_code == "missing_primary_result"
