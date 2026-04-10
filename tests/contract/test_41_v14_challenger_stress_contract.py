from __future__ import annotations

import pytest

from probability_engine.challengers import ChallengerBootstrapDiagnostics, build_stress_recipe_result, run_challenger_bootstrap
from probability_engine.contracts import PathStatsSummary, ProbabilityEngineRunResult, RecipeSimulationResult, SuccessEventSpec
from probability_engine.disclosure_bridge import DisclosureEvidenceSpec, assemble_probability_run_result
from probability_engine.portfolio_policy import CurrentPosition


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


def _make_secondary_result(
    *,
    recipe_name: str,
    role: str,
    success_probability: float,
    success_range: tuple[float, float],
) -> RecipeSimulationResult:
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


def test_challenger_bootstrap_advances_regime_and_preserves_portfolio_weights() -> None:
    history_matrix = [
        [0.030, -0.010, 0.020, -0.020, 0.015, 0.010, -0.010, 0.020],
        [-0.010, 0.020, 0.010, 0.005, -0.005, 0.030, 0.010, 0.015],
    ]
    regime_labels = [
        "risk_off",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
    ]

    weighted = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=2,
        path_count=3,
        horizon_days=4,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.8, 0.2],
        random_seed=11,
    )
    equal_weighted = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=2,
        path_count=1,
        horizon_days=4,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.5, 0.5],
        random_seed=11,
    )

    assert isinstance(weighted, ChallengerBootstrapDiagnostics)
    assert weighted.result.role == "challenger"
    assert len(weighted.selected_block_starts_by_path) == 3
    assert len(weighted.selected_block_regimes_by_path) == 3
    assert weighted.selected_block_regimes_by_path[0] == ["risk_off", "normal"]
    assert weighted.selected_block_starts_by_path[0][0] == 0
    assert weighted.result.path_stats.terminal_value_mean != equal_weighted.result.path_stats.terminal_value_mean


def test_challenger_bootstrap_uses_position_scale_for_success_evaluation() -> None:
    success_event_spec = SuccessEventSpec(
        horizon_days=2,
        horizon_months=1,
        target_type="goal_amount",
        target_value=105.0,
        drawdown_constraint=0.50,
        benchmark_ref=None,
        contribution_policy="fixed",
        withdrawal_policy="none",
        rebalancing_policy_ref="none",
        return_basis="nominal",
        fee_basis="net",
        success_logic="joint_target_and_drawdown",
    )
    diagnostics = run_challenger_bootstrap(
        history_matrix=[
            [0.05, 0.00, 0.05, 0.00],
            [0.05, 0.00, 0.05, 0.00],
        ],
        regime_labels=["risk_off", "normal", "risk_off", "normal"],
        current_regime="risk_off",
        block_size=2,
        path_count=1,
        horizon_days=2,
        success_event_spec=success_event_spec,
        current_positions=[
            CurrentPosition(product_id="a", units=0.0, market_value=60.0, weight=0.6, cost_basis=None, tradable=True),
            CurrentPosition(product_id="b", units=0.0, market_value=40.0, weight=0.4, cost_basis=None, tradable=True),
        ],
        random_seed=3,
    )

    assert diagnostics.result.path_stats.success_count == 1
    assert diagnostics.result.success_probability == 1.0


def test_challenger_bootstrap_rejects_mismatched_initial_value_for_current_positions() -> None:
    success_event_spec = SuccessEventSpec(
        horizon_days=2,
        horizon_months=1,
        target_type="goal_amount",
        target_value=105.0,
        drawdown_constraint=0.50,
        benchmark_ref=None,
        contribution_policy="fixed",
        withdrawal_policy="none",
        rebalancing_policy_ref="none",
        return_basis="nominal",
        fee_basis="net",
        success_logic="joint_target_and_drawdown",
    )

    with pytest.raises(ValueError, match="initial_portfolio_value must match"):
        run_challenger_bootstrap(
            history_matrix=[
                [0.05, 0.00, 0.05, 0.00],
                [0.05, 0.00, 0.05, 0.00],
            ],
            regime_labels=["risk_off", "normal", "risk_off", "normal"],
            current_regime="risk_off",
            block_size=2,
            path_count=1,
            horizon_days=2,
            success_event_spec=success_event_spec,
            current_positions=[
                CurrentPosition(product_id="a", units=0.0, market_value=60.0, weight=0.6, cost_basis=None, tradable=True),
                CurrentPosition(product_id="b", units=0.0, market_value=40.0, weight=0.4, cost_basis=None, tradable=True),
            ],
            initial_portfolio_value=120.0,
            random_seed=3,
        )


def test_stress_recipe_result_summarizes_explicit_stressed_paths() -> None:
    stressed_result = build_stress_recipe_result(
        stressed_path_returns=[
            [-0.03, -0.01, 0.00, -0.02],
            [-0.02, -0.03, -0.01, -0.02],
        ],
        success_event_spec=_make_success_event_spec(),
    )

    assert stressed_result.role == "stress"
    assert stressed_result.sample_count == 2
    assert stressed_result.success_probability == 0.0
    assert stressed_result.path_stats.success_count == 0
    assert stressed_result.path_stats.path_count == 2
    assert stressed_result.calibration_link_ref == "stress://explicit_stress_paths"


def test_stress_recipe_result_supports_explicit_portfolio_scale() -> None:
    success_event_spec = SuccessEventSpec(
        horizon_days=2,
        horizon_months=1,
        target_type="goal_amount",
        target_value=105.0,
        drawdown_constraint=0.50,
        benchmark_ref=None,
        contribution_policy="fixed",
        withdrawal_policy="none",
        rebalancing_policy_ref="none",
        return_basis="nominal",
        fee_basis="net",
        success_logic="joint_target_and_drawdown",
    )
    stressed_result = build_stress_recipe_result(
        stressed_path_returns=[[0.05, 0.00]],
        success_event_spec=success_event_spec,
        initial_portfolio_value=100.0,
    )

    assert stressed_result.path_stats.success_count == 1
    assert stressed_result.success_probability == 1.0


def test_stress_recipe_result_requires_explicit_portfolio_scale_for_non_normalized_targets() -> None:
    success_event_spec = SuccessEventSpec(
        horizon_days=2,
        horizon_months=1,
        target_type="goal_amount",
        target_value=105.0,
        drawdown_constraint=0.50,
        benchmark_ref=None,
        contribution_policy="fixed",
        withdrawal_policy="none",
        rebalancing_policy_ref="none",
        return_basis="nominal",
        fee_basis="net",
        success_logic="joint_target_and_drawdown",
    )

    with pytest.raises(ValueError, match="initial_portfolio_value"):
        build_stress_recipe_result(
            stressed_path_returns=[[0.05, 0.00]],
            success_event_spec=success_event_spec,
        )


def test_challenger_bootstrap_records_each_path_block_trace() -> None:
    history_matrix = [
        [0.030, -0.010, 0.020, -0.020, 0.015, 0.010, -0.010, 0.020],
        [-0.010, 0.020, 0.010, 0.005, -0.005, 0.030, 0.010, 0.015],
    ]
    regime_labels = [
        "risk_off",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
        "normal",
    ]

    result = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=2,
        path_count=3,
        horizon_days=4,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.8, 0.2],
        random_seed=11,
    )

    assert len(result.selected_block_starts_by_path) == 3
    assert len(result.selected_block_regimes_by_path) == 3
    assert all(len(path_starts) == 2 for path_starts in result.selected_block_starts_by_path)
    assert all(len(path_regimes) == 2 for path_regimes in result.selected_block_regimes_by_path)
    assert result.selected_block_regimes_by_path[0] == ["risk_off", "normal"]


def test_disclosure_bridge_uses_evidence_to_emit_exact_formal_strict_disclosure() -> None:
    primary = _make_primary_result()
    challenger = _make_secondary_result(
        recipe_name="challenger_regime_conditioned_block_bootstrap_v1",
        role="challenger",
        success_probability=0.62,
        success_range=(0.58, 0.66),
    )
    stress = _make_secondary_result(
        recipe_name="stress_downside_tail_v1",
        role="stress",
        success_probability=0.62,
        success_range=(0.58, 0.66),
    )

    run_result = assemble_probability_run_result(
        primary=primary,
        challengers=[challenger],
        stresses=[stress],
        evidence=DisclosureEvidenceSpec(
            daily_product_path_available=True,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=1.0,
            observed_weight_adjusted_coverage=0.98,
            estimated_weight_adjusted_coverage=0.02,
            factor_mapping_confidence="high",
            distribution_readiness="ready",
            calibration_quality="strong",
            challenger_available=True,
            stress_available=True,
            execution_policy="FORMAL_STRICT",
        ),
    )

    assert isinstance(run_result, ProbabilityEngineRunResult)
    assert run_result.output is not None
    assert run_result.run_outcome_status == "success"
    assert run_result.resolved_result_category == "formal_strict_result"
    payload = run_result.output.probability_disclosure_payload
    assert payload.published_point == 0.62
    assert payload.published_range == (0.58, 0.66)
    assert payload.widening_method == "wilson_plus_gap_total"
    assert payload.disclosure_level == "point_and_range"
    assert payload.confidence_level == "high"
    assert run_result.output.primary_result.role == "primary"
    assert run_result.output.challenger_results[0].role == "challenger"
    assert run_result.output.stress_results[0].role == "stress"


def test_disclosure_bridge_uses_evidence_to_emit_formal_estimated_disclosure() -> None:
    primary = _make_primary_result()
    run_result = assemble_probability_run_result(
        primary=primary,
        challengers=[],
        stresses=[],
        evidence=DisclosureEvidenceSpec(
            daily_product_path_available=True,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=0.72,
            observed_weight_adjusted_coverage=0.72,
            estimated_weight_adjusted_coverage=0.28,
            factor_mapping_confidence="high",
            distribution_readiness="ready",
            calibration_quality="strong",
            challenger_available=False,
            stress_available=False,
            execution_policy="FORMAL_ESTIMATION_ALLOWED",
        ),
    )

    assert isinstance(run_result, ProbabilityEngineRunResult)
    assert run_result.output is not None
    assert run_result.run_outcome_status == "degraded"
    assert run_result.resolved_result_category == "formal_estimated_result"
    payload = run_result.output.probability_disclosure_payload
    assert payload.disclosure_level == "range_only"
    assert payload.confidence_level == "medium"
    assert payload.widening_method == "wilson_plus_gap_total"


def test_disclosure_bridge_requires_real_challenger_and_stress_results_for_confidence_credit() -> None:
    primary = _make_primary_result()
    run_result = assemble_probability_run_result(
        primary=primary,
        challengers=[],
        stresses=[],
        evidence=DisclosureEvidenceSpec(
            daily_product_path_available=True,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=1.0,
            observed_weight_adjusted_coverage=0.98,
            estimated_weight_adjusted_coverage=0.02,
            factor_mapping_confidence="high",
            distribution_readiness="ready",
            calibration_quality="acceptable",
            challenger_available=True,
            stress_available=True,
            execution_policy="FORMAL_STRICT",
        ),
    )

    assert run_result.output is not None
    assert run_result.output.probability_disclosure_payload.confidence_level == "medium"


def test_disclosure_bridge_requires_primary_result() -> None:
    run_result = assemble_probability_run_result(
        primary=None,
        challengers=[],
        stresses=[],
        evidence=DisclosureEvidenceSpec(
            daily_product_path_available=False,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=0.0,
            observed_weight_adjusted_coverage=0.0,
            estimated_weight_adjusted_coverage=0.0,
            factor_mapping_confidence="low",
            distribution_readiness="not_ready",
            calibration_quality="failed",
            challenger_available=False,
            stress_available=False,
            execution_policy="FORMAL_STRICT",
        ),
    )

    assert run_result.run_outcome_status == "failure"
    assert run_result.resolved_result_category == "null"
    assert run_result.output is None
    assert run_result.failure_artifact is not None
    assert run_result.failure_artifact.failure_code == "missing_primary_result"
