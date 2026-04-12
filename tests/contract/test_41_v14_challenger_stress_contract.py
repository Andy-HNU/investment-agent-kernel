from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

import probability_engine.challengers as challengers_module
from probability_engine.challengers import (
    STRESS_RECIPE_V14,
    ChallengerBootstrapDiagnostics,
    _apply_observed_roughness_guard,
    _max_drawdown_from_returns,
    _simulate_portfolio_path,
    build_stress_recipe_result,
    build_stress_recipe_result_from_runtime_input,
    run_challenger_bootstrap,
)
from probability_engine.contracts import PathStatsSummary, ProbabilityEngineRunResult, RecipeSimulationResult, SuccessEventSpec
from probability_engine.disclosure_bridge import DisclosureEvidenceSpec, assemble_probability_run_result
from probability_engine.engine import _observed_weight_adjusted_coverage, run_probability_engine
from probability_engine.jumps import JumpStateSpec
from probability_engine.path_generator import DailyEngineRuntimeInput, ProductMarginalSpec, simulate_primary_paths
from probability_engine.pressure import build_deteriorated_runtime_input, compute_market_pressure_snapshot, scenario_pressure_level
from probability_engine.portfolio_policy import ContributionInstruction, CurrentPosition, RebalancingPolicySpec, WithdrawalInstruction
from probability_engine.recipes import PRIMARY_RECIPE_V14
from probability_engine.regime import RegimeStateSpec
from probability_engine.volatility import FactorDynamicsSpec


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


@pytest.mark.contract
def test_challenger_time_weighted_return_includes_rebalance_transaction_costs() -> None:
    initial_positions = [
        CurrentPosition(
            product_id="product_a",
            units=100.0,
            market_value=100.0,
            weight=0.5,
            cost_basis=100.0,
            tradable=True,
        ),
        CurrentPosition(
            product_id="product_b",
            units=0.0,
            market_value=0.0,
            weight=0.5,
            cost_basis=0.0,
            tradable=True,
        ),
    ]

    terminal_value, cagr, max_drawdown, success = _simulate_portfolio_path(
        [{"product_a": 0.0, "product_b": 0.0}],
        initial_state=challengers_module.initialize_portfolio_state(initial_positions),
        success_event_spec=SuccessEventSpec(
            horizon_days=1,
            horizon_months=1,
            target_type="goal_amount",
            target_value=0.0,
            drawdown_constraint=None,
            benchmark_ref=None,
            contribution_policy="fixed",
            withdrawal_policy="none",
            rebalancing_policy_ref="threshold",
            return_basis="nominal",
            fee_basis="net",
            success_logic="joint_target_and_drawdown",
        ),
        rebalancing_policy=RebalancingPolicySpec(
            policy_type="threshold",
            calendar_frequency=None,
            threshold_band=0.0,
            execution_timing="end_of_day_after_return",
            transaction_cost_bps=100.0,
            min_trade_amount=None,
        ),
        step_dates=["2026-04-10"],
    )

    assert terminal_value == pytest.approx(99.5)
    assert cagr < 0.0
    assert max_drawdown > 0.0
    assert success is True


@pytest.mark.contract
def test_challenger_time_weighted_return_excludes_unexecuted_withdrawal_amount() -> None:
    initial_positions = [
        CurrentPosition(
            product_id="product_a",
            units=100.0,
            market_value=100.0,
            weight=1.0,
            cost_basis=100.0,
            tradable=True,
        )
    ]

    terminal_value, cagr, max_drawdown, success = _simulate_portfolio_path(
        [{"product_a": 0.0}],
        initial_state=challengers_module.initialize_portfolio_state(initial_positions),
        success_event_spec=SuccessEventSpec(
            horizon_days=1,
            horizon_months=1,
            target_type="goal_amount",
            target_value=0.0,
            drawdown_constraint=None,
            benchmark_ref=None,
            contribution_policy="fixed",
            withdrawal_policy="scheduled",
            rebalancing_policy_ref="none",
            return_basis="nominal",
            fee_basis="net",
            success_logic="joint_target_and_drawdown",
        ),
        rebalancing_policy=RebalancingPolicySpec(
            policy_type="none",
            calendar_frequency=None,
            threshold_band=None,
            execution_timing="end_of_day_after_return",
            transaction_cost_bps=0.0,
            min_trade_amount=None,
        ),
        withdrawal_schedule=[
            WithdrawalInstruction(
                date="2026-04-10",
                amount=150.0,
                execution_rule="cash_first",
                target_products=None,
            )
        ],
        step_dates=["2026-04-10"],
    )

    assert terminal_value == pytest.approx(0.0)
    assert cagr == pytest.approx(0.0, abs=1e-12)
    assert max_drawdown == pytest.approx(1.0)
    assert success is True


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


def _build_benign_positive_drift_runtime_input() -> DailyEngineRuntimeInput:
    return DailyEngineRuntimeInput(
        as_of="2026-04-09",
        path_horizon_days=20,
        trading_calendar=[
            "2026-04-10",
            "2026-04-13",
            "2026-04-14",
            "2026-04-15",
            "2026-04-16",
            "2026-04-17",
            "2026-04-20",
            "2026-04-21",
            "2026-04-22",
            "2026-04-23",
            "2026-04-24",
            "2026-04-27",
            "2026-04-28",
            "2026-04-29",
            "2026-04-30",
            "2026-05-04",
            "2026-05-05",
            "2026-05-06",
            "2026-05-07",
            "2026-05-08",
        ],
        products=[
            ProductMarginalSpec.from_any(
                {
                    "product_id": "benign_equity",
                    "asset_bucket": "equity_cn",
                    "factor_betas": {"CN_EQ_BROAD": 1.0},
                    "observed_daily_returns": [0.001] * 40,
                    "innovation_family": "student_t",
                    "tail_df": 7.0,
                    "volatility_process": "product_garch_11",
                    "garch_params": {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "nu": 7.0, "long_run_variance": 0.0},
                    "idiosyncratic_jump_profile": {"probability_1d": 0.0, "loss_mean": -0.01, "loss_std": 0.0},
                    "carry_profile": {"carry_drag": 0.0, "tracking_drag": 0.0},
                    "valuation_profile": {"valuation_drag": 0.0},
                    "mapping_confidence": "high",
                    "factor_mapping_source": "observed",
                    "factor_mapping_evidence": [],
                    "observed_series_ref": "observed://benign_equity",
                    "observed_return_series": [0.001] * 40,
                    "observed_dates": [f"2026-03-{day:02d}" for day in range(1, 29)] + [f"2026-04-{day:02d}" for day in range(1, 13)],
                }
            )
        ],
        factor_dynamics=FactorDynamicsSpec(
            factor_names=["CN_EQ_BROAD"],
            factor_series_ref="observed://factor/cn_eq_broad",
            innovation_family="student_t",
            tail_df=7.0,
            garch_params_by_factor={
                "CN_EQ_BROAD": {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "nu": 7.0, "long_run_variance": 0.0}
            },
            dcc_params={"alpha": 0.0, "beta": 0.0},
            long_run_covariance={"CN_EQ_BROAD": {"CN_EQ_BROAD": 0.0}},
            covariance_shrinkage=0.0,
            calibration_window_days=252,
            expected_return_by_factor={"CN_EQ_BROAD": 0.08},
            expected_return_basis="market_anchor",
        ),
        regime_state=RegimeStateSpec(
            regime_names=["normal"],
            transition_matrix=[[1.0]],
            current_regime="normal",
            regime_mean_adjustments={"normal": {"mean_shift": 0.0}},
            regime_vol_adjustments={"normal": {"volatility_multiplier": 1.0}},
            regime_jump_adjustments={"normal": {"systemic_jump_probability_multiplier": 1.0}},
        ),
        jump_state=JumpStateSpec(
            systemic_jump_probability_1d=0.0,
            systemic_jump_dispersion=1e-12,
            systemic_jump_impact_by_factor={"CN_EQ_BROAD": 0.0},
            idio_jump_profile_by_product={"benign_equity": {"probability_1d": 0.0, "loss_mean": -0.01, "loss_std": 0.0}},
        ),
        current_positions=[
            CurrentPosition(
                product_id="benign_equity",
                units=100.0,
                market_value=100.0,
                weight=1.0,
                cost_basis=100.0,
                tradable=True,
            )
        ],
        contribution_schedule=[],
        withdrawal_schedule=[],
        rebalancing_policy=RebalancingPolicySpec(
            policy_type="none",
            calendar_frequency=None,
            threshold_band=None,
            execution_timing="end_of_day_after_return",
            transaction_cost_bps=0.0,
            min_trade_amount=None,
        ),
        success_event_spec=SuccessEventSpec(
            horizon_days=20,
            horizon_months=1,
            target_type="goal_amount",
            target_value=100.30,
            drawdown_constraint=0.50,
            benchmark_ref=None,
            contribution_policy="fixed",
            withdrawal_policy="none",
            rebalancing_policy_ref="none",
            return_basis="nominal",
            fee_basis="net",
            success_logic="joint_target_and_drawdown",
        ),
        recipes=[PRIMARY_RECIPE_V14],
        evidence_bundle_ref="benign://runtime",
        random_seed=17,
        challenger_regime_labels=["normal"] * 40,
        observed_regime_labels=("normal",) * 40,
        observed_current_regime="normal",
        challenger_block_size=20,
        challenger_path_count=8,
        stress_path_count=8,
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


def test_challenger_bootstrap_applies_contributions_without_treating_them_as_return() -> None:
    diagnostics = run_challenger_bootstrap(
        history_matrix=[
            [0.0] * 40,
        ],
        regime_labels=[*["risk_off"] * 20, *["normal"] * 20],
        current_regime="risk_off",
        block_size=20,
        path_count=1,
        horizon_days=20,
        success_event_spec=SuccessEventSpec(
            horizon_days=20,
            horizon_months=1,
            target_type="goal_amount",
            target_value=150.0,
            drawdown_constraint=1.0,
            benchmark_ref=None,
            contribution_policy="fixed",
            withdrawal_policy="none",
            rebalancing_policy_ref="none",
            return_basis="nominal",
            fee_basis="net",
            success_logic="joint_target_and_drawdown",
        ),
        current_positions=[
            CurrentPosition(product_id="a", units=0.0, market_value=100.0, weight=1.0, cost_basis=None, tradable=True),
        ],
        contribution_schedule=[
            ContributionInstruction(
                date="2026-04-11",
                amount=50.0,
                allocation_mode="target_weights",
                target_weights={"a": 1.0},
            )
        ],
        withdrawal_schedule=[],
        rebalancing_policy=RebalancingPolicySpec(
            policy_type="none",
            calendar_frequency=None,
            threshold_band=None,
            execution_timing="end_of_day_after_return",
            transaction_cost_bps=0.0,
            min_trade_amount=None,
        ),
        step_dates=["2026-04-11"] + [f"2026-04-{12 + idx:02d}" for idx in range(19)],
        random_seed=5,
    )

    assert diagnostics.result.path_stats.terminal_value_mean == pytest.approx(150.0, abs=1e-9)
    assert diagnostics.result.path_stats.cagr_p50 == pytest.approx(0.0, abs=1e-9)
    assert diagnostics.result.cagr_range == pytest.approx((0.0, 0.0), abs=1e-9)


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
    assert stressed_runtime_input.factor_dynamics.expected_return_by_factor == runtime_input.factor_dynamics.expected_return_by_factor
    assert stressed_runtime_input.factor_dynamics.expected_return_basis == runtime_input.factor_dynamics.expected_return_basis
    assert stressed_runtime_input.jump_state.systemic_jump_probability_1d > runtime_input.jump_state.systemic_jump_probability_1d
    assert stressed_runtime_input.jump_state.systemic_jump_dispersion > runtime_input.jump_state.systemic_jump_dispersion
    risk_off_index = stressed_runtime_input.regime_state.regime_names.index("risk_off")
    assert (
        stressed_runtime_input.regime_state.transition_matrix[risk_off_index][risk_off_index]
        > runtime_input.regime_state.transition_matrix[risk_off_index][risk_off_index]
    )


def test_stress_overlay_preserves_base_drift_contract_on_benign_runtime_input() -> None:
    runtime_input = _build_benign_positive_drift_runtime_input()

    primary_result = simulate_primary_paths(runtime_input, PRIMARY_RECIPE_V14)
    stress_result = build_stress_recipe_result_from_runtime_input(runtime_input, path_count=64)

    assert primary_result.success_probability > 0.0
    assert stress_result.success_probability <= primary_result.success_probability
    assert runtime_input.factor_dynamics.expected_return_by_factor["CN_EQ_BROAD"] > 0.0
    assert stress_result.path_stats.terminal_value_mean > 100.0
    assert stress_result.path_stats.terminal_value_mean < primary_result.path_stats.terminal_value_mean


def test_stress_tail_df_is_monotone_worse_near_low_df_boundary() -> None:
    stressed_df = challengers_module._stress_tail_df(2.05)

    assert stressed_df is not None
    assert stressed_df > 2.0
    assert stressed_df < 2.05


def test_scenario_pressure_level_maps_numeric_scores_to_labels() -> None:
    assert scenario_pressure_level(12.0) == "L0_宽松"
    assert scenario_pressure_level(43.0) == "L1_中性偏紧"
    assert scenario_pressure_level(61.0) == "L2_风险偏高"
    assert scenario_pressure_level(88.0) == "L3_高压"


def test_historical_replay_pressure_is_null() -> None:
    snapshot = compute_market_pressure_snapshot(_build_benign_positive_drift_runtime_input(), scenario_kind="historical_replay")

    assert snapshot.market_pressure_score is None
    assert snapshot.market_pressure_level is None


def test_market_pressure_score_is_monotonic_across_deterioration_levels() -> None:
    runtime_input = _build_benign_positive_drift_runtime_input()

    current = compute_market_pressure_snapshot(runtime_input, scenario_kind="current_market")
    mild = compute_market_pressure_snapshot(
        build_deteriorated_runtime_input(runtime_input, level="mild"),
        scenario_kind="deteriorated_mild",
    )
    moderate = compute_market_pressure_snapshot(
        build_deteriorated_runtime_input(runtime_input, level="moderate"),
        scenario_kind="deteriorated_moderate",
    )
    severe = compute_market_pressure_snapshot(
        build_deteriorated_runtime_input(runtime_input, level="severe"),
        scenario_kind="deteriorated_severe",
    )

    assert current.market_pressure_score is not None
    assert mild.market_pressure_score is not None
    assert moderate.market_pressure_score is not None
    assert severe.market_pressure_score is not None
    assert current.market_pressure_score < mild.market_pressure_score < moderate.market_pressure_score < severe.market_pressure_score


def test_probability_engine_stress_recipe_stays_finite_and_downside_bounded_on_long_horizon_balanced_input() -> None:
    result = run_probability_engine(_build_long_horizon_balanced_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.stress_results, "expected live stress result"

    primary = result.output.primary_result
    mild, moderate, severe = result.output.stress_results

    for stress in (mild, moderate, severe):
        assert math.isfinite(float(stress.path_stats.terminal_value_mean))
        assert math.isfinite(float(stress.path_stats.terminal_value_p95))
        assert math.isfinite(float(stress.path_stats.cagr_p95))

    assert mild.success_probability >= moderate.success_probability >= severe.success_probability
    assert severe.path_stats.terminal_value_p95 <= primary.path_stats.terminal_value_p95 * 1.05
    assert severe.path_stats.cagr_p95 <= primary.path_stats.cagr_p95 + 0.10


def test_observed_roughness_guard_increases_drawdown_for_overly_smooth_sample() -> None:
    sampled_product_returns = [{"product_a": 0.0012, "product_b": 0.0010} for _ in range(20)]
    observed_matrix = np.asarray(
        [
            [0.0030, -0.0090, 0.0040, -0.0100, 0.0035, -0.0085, 0.0025, -0.0075],
            [0.0020, -0.0060, 0.0030, -0.0070, 0.0025, -0.0055, 0.0015, -0.0045],
        ],
        dtype=float,
    )
    guarded_returns = _apply_observed_roughness_guard(
        sampled_product_returns,
        observed_matrix=observed_matrix,
        product_ids=["product_a", "product_b"],
        portfolio_weights=[0.5, 0.5],
        block_size=4,
    )

    original_portfolio_returns = np.asarray(
        [0.5 * day["product_a"] + 0.5 * day["product_b"] for day in sampled_product_returns],
        dtype=float,
    )
    guarded_portfolio_returns = np.asarray(
        [0.5 * day["product_a"] + 0.5 * day["product_b"] for day in guarded_returns],
        dtype=float,
    )

    assert len(guarded_returns) == len(sampled_product_returns)
    assert np.std(guarded_portfolio_returns) >= np.std(original_portfolio_returns)
    assert _max_drawdown_from_returns(guarded_portfolio_returns) > _max_drawdown_from_returns(original_portfolio_returns)


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


def test_probability_engine_exposes_three_level_stress_ladder() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert len(result.output.stress_results) == 3
    assert [item.role for item in result.output.stress_results] == ["stress", "stress", "stress"]
    assert [item.recipe_name for item in result.output.stress_results] == [
        "stress_deteriorated_mild_v1",
        "stress_deteriorated_moderate_v1",
        "stress_deteriorated_severe_v1",
    ]


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
