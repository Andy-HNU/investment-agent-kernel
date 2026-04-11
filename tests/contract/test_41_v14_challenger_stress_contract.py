from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

import probability_engine.challengers as challengers_module
import probability_engine.engine as probability_engine_engine
from probability_engine.challengers import (
    STRESS_RECIPE_V14,
    ChallengerBootstrapDiagnostics,
    build_stress_recipe_result,
    run_challenger_bootstrap,
)
from probability_engine.contracts import PathStatsSummary, ProbabilityEngineRunResult, RecipeSimulationResult, SuccessEventSpec
from probability_engine.disclosure_bridge import DisclosureEvidenceSpec, assemble_probability_run_result
from probability_engine.engine import _observed_weight_adjusted_coverage, run_probability_engine
from probability_engine.path_generator import DailyEngineRuntimeInput
from probability_engine.portfolio_policy import CurrentPosition


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"
_MIN_LIVE_HISTORY_DAYS = 40
_MIN_STRICT_HISTORY_DAYS = 126


def _load_v14_formal_daily_input(*, minimum_history_days: int = _MIN_LIVE_HISTORY_DAYS) -> dict[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    labels = list(payload.get("observed_regime_labels") or [])
    target_days = max(minimum_history_days, int(payload.get("path_horizon_days") or 0))
    if labels and len(labels) < target_days:
        repeats = (target_days + len(labels) - 1) // len(labels)
        payload["observed_regime_labels"] = (labels * repeats)[:target_days]
        for product in list(payload.get("products") or []):
            returns = list(product.get("observed_daily_returns") or [])
            if returns:
                product["observed_daily_returns"] = (returns * repeats)[:target_days]
    return payload


def _build_long_horizon_balanced_input(*, path_count: int = 128, horizon_days: int = 252) -> dict[str, object]:
    payload = _load_v14_formal_daily_input(minimum_history_days=126)
    as_of = date.fromisoformat(str(payload["as_of"]))
    trading_calendar: list[str] = []
    cursor = as_of
    while len(trading_calendar) < int(horizon_days):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            trading_calendar.append(cursor.isoformat())
    payload["trading_calendar"] = trading_calendar
    payload["path_horizon_days"] = int(horizon_days)
    success_event = dict(payload["success_event_spec"])
    success_event["horizon_days"] = int(horizon_days)
    success_event["horizon_months"] = max(1, int(round(horizon_days / 21.0)))
    payload["success_event_spec"] = success_event
    payload["recipes"] = [
        {
            "recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1",
            "role": "primary",
            "path_count": int(path_count),
        }
    ]
    payload["challenger_path_count"] = 8
    payload["stress_path_count"] = 8

    balanced_patterns = {
        "cn_equity_balanced_fund": [0.0035, -0.0040, 0.0022, -0.0025, 0.0014, -0.0016, 0.0028, 0.0004],
        "cn_bond_short_history": [0.0006, 0.0003, -0.0004, 0.0005, 0.0003, -0.0001, 0.0004, 0.0002],
        "cn_equity_empty_holdings": [0.0050, -0.0060, 0.0030, -0.0035, 0.0020, -0.0025, 0.0040, 0.0006],
    }
    observed_regime_pattern = ["risk_off", "risk_off", "normal", "normal", "risk_off", "normal", "normal", "risk_off"]
    repeats = (126 + len(observed_regime_pattern) - 1) // len(observed_regime_pattern)
    payload["observed_regime_labels"] = (observed_regime_pattern * repeats)[:126]
    for product in list(payload.get("products") or []):
        pattern = balanced_patterns[str(product["product_id"])]
        product_repeats = (126 + len(pattern) - 1) // len(pattern)
        product["observed_daily_returns"] = (pattern * product_repeats)[:126]
        product["mapping_confidence"] = "high"
    return payload


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
        [0.030] * 19 + [0.020] + [-0.010] * 20,
        [-0.010] * 19 + [0.015] + [0.010] * 20,
    ]
    regime_labels = [
        *["risk_off"] * 19,
        "normal",
        *["normal"] * 20,
    ]

    weighted = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=20,
        path_count=3,
        horizon_days=40,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.8, 0.2],
        random_seed=11,
    )
    equal_weighted = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=20,
        path_count=1,
        horizon_days=40,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.5, 0.5],
        random_seed=11,
    )

    assert isinstance(weighted, ChallengerBootstrapDiagnostics)
    assert weighted.result.role == "challenger"
    assert len(weighted.selected_block_starts_by_path) == 3
    assert len(weighted.selected_block_regimes_by_path) == 3
    assert weighted.selected_block_regimes_by_path[0] == ["risk_off", "normal"]
    assert weighted.selected_block_starts_by_path[0][0] >= 0
    assert weighted.result.path_stats.terminal_value_mean != equal_weighted.result.path_stats.terminal_value_mean


def test_challenger_bootstrap_rejects_short_histories_under_the_frozen_contract() -> None:
    history_matrix = [
        [0.010] * 39,
        [-0.005] * 39,
    ]

    with pytest.raises(ValueError, match="history is too short"):
        run_challenger_bootstrap(
            history_matrix=history_matrix,
            regime_labels=["risk_off"] * 39,
            current_regime="risk_off",
            block_size=20,
            path_count=1,
            horizon_days=20,
            success_event_spec=_make_success_event_spec(),
            random_seed=11,
        )


def test_challenger_bootstrap_uses_position_scale_for_success_evaluation() -> None:
    success_event_spec = SuccessEventSpec(
        horizon_days=20,
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
            [0.05] * 20 + [0.00] * 20,
            [0.05] * 20 + [0.00] * 20,
        ],
        regime_labels=[*["risk_off"] * 19, "normal", *["normal"] * 20],
        current_regime="risk_off",
        block_size=20,
        path_count=1,
        horizon_days=20,
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
        horizon_days=20,
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
                [0.05] * 20 + [0.00] * 20,
                [0.05] * 20 + [0.00] * 20,
            ],
            regime_labels=[*["risk_off"] * 19, "normal", *["normal"] * 20],
            current_regime="risk_off",
            block_size=20,
            path_count=1,
            horizon_days=20,
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


def test_stress_recipe_helper_uses_primary_model_with_stress_parameter_table(monkeypatch) -> None:
    runtime_input = DailyEngineRuntimeInput.from_any(deepcopy(_load_v14_formal_daily_input()))
    captured: dict[str, object] = {}

    def _capture(runtime_input_arg: DailyEngineRuntimeInput, recipe_arg):
        captured["runtime_input"] = runtime_input_arg
        captured["recipe"] = recipe_arg
        return _make_secondary_result(
            recipe_name=str(recipe_arg.recipe_name),
            role=str(recipe_arg.role),
            success_probability=0.41,
            success_range=(0.36, 0.46),
        )

    monkeypatch.setattr(challengers_module, "simulate_primary_paths", _capture)

    result = challengers_module.build_stress_recipe_result_from_runtime_input(
        runtime_input,
        path_count=4,
    )

    assert result.role == "stress"
    assert result.recipe_name == STRESS_RECIPE_V14.recipe_name
    assert captured["recipe"].path_count == 4
    assert captured["recipe"].recipe_name == STRESS_RECIPE_V14.recipe_name
    assert captured["recipe"].role == "stress"
    stressed_runtime_input = captured["runtime_input"]
    assert isinstance(stressed_runtime_input, DailyEngineRuntimeInput)
    assert stressed_runtime_input.factor_dynamics.tail_df < runtime_input.factor_dynamics.tail_df
    assert stressed_runtime_input.jump_state.systemic_jump_probability_1d > runtime_input.jump_state.systemic_jump_probability_1d
    assert stressed_runtime_input.jump_state.systemic_jump_dispersion > runtime_input.jump_state.systemic_jump_dispersion
    risk_off_index = stressed_runtime_input.regime_state.regime_names.index("risk_off")
    assert (
        stressed_runtime_input.regime_state.transition_matrix[risk_off_index][risk_off_index]
        > runtime_input.regime_state.transition_matrix[risk_off_index][risk_off_index]
    )


def test_probability_engine_stress_recipe_stays_finite_and_downside_bounded_on_long_horizon_balanced_input() -> None:
    result = run_probability_engine(_build_long_horizon_balanced_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.stress_results, "expected live stress result"

    primary = result.output.primary_result
    stress = result.output.stress_results[0]

    assert math.isfinite(float(stress.path_stats.terminal_value_mean))
    assert math.isfinite(float(stress.path_stats.terminal_value_p95))
    assert math.isfinite(float(stress.path_stats.cagr_p95))
    assert stress.path_stats.terminal_value_p95 <= primary.path_stats.terminal_value_p95 * 1.05
    assert stress.path_stats.cagr_p95 <= primary.path_stats.cagr_p95 + 0.10


def test_challenger_bootstrap_records_each_path_block_trace() -> None:
    history_matrix = [
        [0.030] * 19 + [0.020] + [-0.010] * 20,
        [-0.010] * 19 + [0.015] + [0.010] * 20,
    ]
    regime_labels = [
        *["risk_off"] * 19,
        "normal",
        *["normal"] * 20,
    ]

    result = run_challenger_bootstrap(
        history_matrix=history_matrix,
        regime_labels=regime_labels,
        current_regime="risk_off",
        block_size=20,
        path_count=3,
        horizon_days=40,
        success_event_spec=_make_success_event_spec(),
        portfolio_weights=[0.8, 0.2],
        random_seed=11,
    )

    assert len(result.selected_block_starts_by_path) == 3
    assert len(result.selected_block_regimes_by_path) == 3
    assert all(len(path_starts) == 2 for path_starts in result.selected_block_starts_by_path)
    assert all(len(path_regimes) == 2 for path_regimes in result.selected_block_regimes_by_path)
    assert result.selected_block_regimes_by_path[0] == ["risk_off", "normal"]


def test_probability_engine_skips_challenger_when_history_is_shorter_than_two_frozen_blocks() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    for product in sim_input["products"]:
        product["observed_daily_returns"] = list(product["observed_daily_returns"][:39])
    sim_input["observed_regime_labels"] = list(sim_input["observed_regime_labels"][:39])
    sim_input["observed_current_regime"] = "risk_off"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.challenger_results == []
    assert result.output.model_disagreement["best_challenger_probability"] is None
    assert result.output.probability_disclosure_payload.challenger_gap is None
    assert result.output.probability_disclosure_payload.stress_gap is not None


def test_probability_engine_does_not_forge_challenger_availability_by_rewriting_regime_labels() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["observed_regime_labels"] = ["normal"] * len(sim_input["observed_regime_labels"])
    sim_input["observed_current_regime"] = "risk_off"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.challenger_results == []
    assert result.output.model_disagreement["best_challenger_probability"] is None
    assert result.output.probability_disclosure_payload.challenger_gap is None


def test_probability_engine_emits_formal_strict_result_when_all_products_are_observed_and_high_confidence() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input(minimum_history_days=_MIN_STRICT_HISTORY_DAYS))
    for product in sim_input["products"]:
        product["mapping_confidence"] = "high"
        product["factor_mapping_source"] = "blended"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.run_outcome_status == "success"
    assert result.resolved_result_category == "formal_strict_result"
    assert result.output.probability_disclosure_payload.disclosure_level == "point_and_range"


def test_observed_coverage_treats_full_product_observation_as_complete_even_when_forecast_horizon_is_longer() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    target_days = 126
    labels = list(sim_input.get("observed_regime_labels") or [])
    repeats = (target_days + len(labels) - 1) // len(labels)
    sim_input["observed_regime_labels"] = (labels * repeats)[:target_days]
    sim_input["path_horizon_days"] = 783
    for product in sim_input["products"]:
        returns = list(product.get("observed_daily_returns") or [])
        if returns:
            product["observed_daily_returns"] = (returns * repeats)[:target_days]
        product["mapping_confidence"] = "high"
        product["factor_mapping_source"] = "blended"

    runtime_input = DailyEngineRuntimeInput.from_any(sim_input)
    history_matrix = runtime_input.observed_history_matrix()
    assert history_matrix is not None

    observed_coverage = _observed_weight_adjusted_coverage(runtime_input, history_matrix)

    assert observed_coverage == pytest.approx(1.0)


def test_probability_engine_uses_recipe_level_stress_run_instead_of_overlay(monkeypatch) -> None:
    monkeypatch.setattr(
        probability_engine_engine,
        "build_stress_recipe_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stress overlay path must not be used")),
    )

    result = run_probability_engine(_load_v14_formal_daily_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.stress_results
    assert result.output.stress_results[0].role == "stress"
    assert result.output.stress_results[0].recipe_name == STRESS_RECIPE_V14.recipe_name


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


def test_disclosure_bridge_uses_actual_challenger_and_stress_results_even_if_evidence_flags_are_false() -> None:
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
            calibration_quality="acceptable",
            challenger_available=False,
            stress_available=False,
            execution_policy="FORMAL_STRICT",
        ),
    )

    assert run_result.output is not None
    assert run_result.output.probability_disclosure_payload.confidence_level == "high"


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
