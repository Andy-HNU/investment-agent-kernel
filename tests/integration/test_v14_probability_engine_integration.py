from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from frontdesk.service import run_frontdesk_onboarding
from probability_engine.engine import run_probability_engine
from probability_engine.contracts import ProbabilityEngineRunResult
from probability_engine.path_generator import (
    DailyEngineRuntimeInput,
    PathOutcome,
    _student_t_scale,
    _summarize_outcomes,
    _trading_step_dates,
)
from probability_engine.portfolio_policy import (
    PortfolioState,
    RebalancingPolicySpec,
    apply_daily_cashflows_and_rebalance,
)
from probability_engine.recipes import PRIMARY_RECIPE_V14
from product_mapping import BucketCardinalityPreference, SearchExpansionRecommendation, build_execution_plan
from orchestrator.engine import (
    _build_execution_plan_summary,
    _build_probability_engine_run_input,
    _rescale_factor_runtime_state_from_selected_products,
)
from shared.onboarding import UserOnboardingProfile
from tests.contract.test_12_frontdesk_regression import _observed_external_snapshot_source


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"
_MIN_LIVE_HISTORY_DAYS = 40


def _load_v14_formal_daily_input() -> dict[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    labels = list(payload.get("observed_regime_labels") or [])
    target_days = max(_MIN_LIVE_HISTORY_DAYS, int(payload.get("path_horizon_days") or 0))
    if labels and len(labels) < target_days:
        repeats = (target_days + len(labels) - 1) // len(labels)
        payload["observed_regime_labels"] = (labels * repeats)[:target_days]
        for product in list(payload.get("products") or []):
            returns = list(product.get("observed_daily_returns") or [])
            if returns:
                product["observed_daily_returns"] = (returns * repeats)[:target_days]
    return payload


def _build_benign_profile_regression_input(*, path_count: int = 256, horizon_days: int = 756) -> dict[str, object]:
    payload = _load_v14_formal_daily_input()
    as_of = date.fromisoformat(str(payload["as_of"]))
    trading_calendar: list[str] = []
    cursor = as_of
    while len(trading_calendar) < int(horizon_days):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            trading_calendar.append(cursor.isoformat())

    payload["trading_calendar"] = trading_calendar
    payload["path_horizon_days"] = int(horizon_days)
    payload["success_event_spec"]["horizon_days"] = int(horizon_days)
    payload["success_event_spec"]["horizon_months"] = 36
    payload["success_event_spec"]["target_value"] = 120000.0
    payload["success_event_spec"]["drawdown_constraint"] = 0.20
    payload["recipes"] = [
        {
            "recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1",
            "role": "primary",
            "path_count": int(path_count),
        }
    ]
    payload["challenger_path_count"] = 64
    payload["stress_path_count"] = 32

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

    target_weights = {}
    for position in payload["current_positions"]:
        position["market_value"] *= 0.18
        position["units"] *= 0.18
        position["cost_basis"] *= 0.18
        target_weights[str(position["product_id"])] = float(position["weight"])

    contribution_schedule = []
    for month_index in range(1, 37):
        year = as_of.year + (as_of.month - 1 + month_index) // 12
        month = (as_of.month - 1 + month_index) % 12 + 1
        contribution_date = date(year, month, min(as_of.day, 28)).isoformat()
        target_date = next((item for item in trading_calendar if item >= contribution_date), trading_calendar[-1])
        contribution_schedule.append(
            {
                "date": target_date,
                "amount": 2500.0,
                "allocation_mode": "target_weights",
                "target_weights": dict(target_weights),
            }
        )
    payload["contribution_schedule"] = contribution_schedule
    payload["withdrawal_schedule"] = []
    return payload


def test_primary_recipe_returns_formal_output_for_full_daily_input() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status in {"success", "degraded"}
    assert result.output is not None
    assert result.output.primary_result.recipe_name == "primary_daily_factor_garch_dcc_jump_regime_v1"
    assert result.output.primary_result.role == "primary"
    assert result.output.primary_result.sample_count == 4000
    assert result.output.primary_result.path_stats.path_count == 4000
    assert result.output.probability_disclosure_payload is not None


def test_probability_engine_builder_residualizes_product_long_run_variance() -> None:
    run_input, _ = _build_probability_engine_run_input(
        run_id="residual_variance_builder",
        envelope={
            "as_of": "2026-04-09",
            "live_portfolio": {"total_value": 100.0},
        },
        calibration_result={
            "factor_dynamics": {
                "factor_names": ["CN_EQ_BROAD"],
                "tail_df": 7.0,
                "long_run_covariance": {
                    "CN_EQ_BROAD": {"CN_EQ_BROAD": 0.0001},
                },
            },
            "regime_state": {
                "regime_names": ["normal", "risk_off", "stress"],
                "transition_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "current_regime": "normal",
            },
            "jump_state": {},
        },
        goal_solver_input={
            "goal": {"horizon_months": 1},
            "constraints": {},
            "cashflow_plan": {},
            "current_portfolio_value": 100.0,
            "candidate_product_contexts": {
                "test_allocation": {
                    "product_simulation_input": {
                        "products": [
                            {
                                "product_id": "factor_clone_product",
                                "asset_bucket": "equity_cn",
                                "target_weight": 1.0,
                                "factor_betas": {"CN_EQ_BROAD": 1.0},
                                "return_series": [0.01, -0.01, 0.01, -0.01],
                                "observation_dates": [
                                    "2026-04-01",
                                    "2026-04-02",
                                    "2026-04-03",
                                    "2026-04-06",
                                ],
                            }
                        ]
                    }
                }
            },
        },
        goal_solver_output={
            "recommended_allocation_name": "test_allocation",
            "recommended_result": {"allocation_name": "test_allocation"},
        },
    )

    assert run_input is not None
    product = run_input["products"][0]
    raw_variance = 0.0001

    assert product["garch_params"]["long_run_variance"] < raw_variance
    assert product["garch_params"]["long_run_variance"] <= raw_variance * 0.05
    assert product["garch_params"]["omega"] < raw_variance * 0.03


def test_selected_product_rescaling_preserves_positive_drift_baseline_for_negative_observed_history() -> None:
    _, scaled_factor_dynamics, scaled_regime_state, _ = _rescale_factor_runtime_state_from_selected_products(
        factor_dynamics={
            "factor_names": ["CN_EQ_BROAD"],
            "expected_return_by_factor": {"CN_EQ_BROAD": 0.10},
            "garch_params_by_factor": {
                "CN_EQ_BROAD": {
                    "omega": 1e-6,
                    "alpha": 0.07,
                    "beta": 0.90,
                    "nu": 7.0,
                    "long_run_variance": 1e-4,
                }
            },
            "long_run_covariance": {
                "CN_EQ_BROAD": {"CN_EQ_BROAD": 1e-4},
            },
        },
        regime_state={
            "regime_names": ["normal", "risk_off", "stress"],
            "current_regime": "risk_off",
            "transition_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "regime_mean_adjustments": {
                "normal": {"mean_shift": 0.0},
                "risk_off": {"mean_shift": -0.0005},
                "stress": {"mean_shift": -0.0012},
            },
        },
        jump_state={
            "systemic_jump_probability_1d": 0.0005,
            "systemic_jump_dispersion": 0.01,
            "systemic_jump_impact_by_factor": {"CN_EQ_BROAD": -0.01},
            "idio_jump_profile_by_product": {},
        },
        products=[
            {
                "product_id": "negative_product",
                "observed_return_series": [-0.01] * 40,
                "factor_betas": {"CN_EQ_BROAD": 1.0},
                "garch_params": {
                    "omega": 1e-6,
                    "alpha": 0.07,
                    "beta": 0.90,
                    "nu": 7.0,
                    "long_run_variance": 1e-4,
                },
            }
        ],
        target_weights={"negative_product": 1.0},
        factor_names=["CN_EQ_BROAD"],
    )

    assert 0.0 < scaled_factor_dynamics["expected_return_by_factor"]["CN_EQ_BROAD"] < 0.10
    assert scaled_regime_state["regime_mean_adjustments"]["risk_off"]["mean_shift"] < 0.0
    assert abs(scaled_regime_state["regime_mean_adjustments"]["risk_off"]["mean_shift"]) < 0.0005
    assert scaled_regime_state["regime_mean_adjustments"]["stress"]["mean_shift"] < scaled_regime_state["regime_mean_adjustments"]["risk_off"]["mean_shift"]


def test_primary_recipe_populates_live_challenger_and_stress_gap_signals() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert result.output is not None
    assert result.output.challenger_results, "expected live challenger_results to be populated"
    assert result.output.stress_results, "expected live stress_results to be populated"
    assert result.output.model_disagreement["gap_total"] is not None

    disclosure_payload = result.output.probability_disclosure_payload
    assert disclosure_payload is not None
    assert disclosure_payload.challenger_gap is not None
    assert disclosure_payload.stress_gap is not None
    assert disclosure_payload.gap_total is not None


def test_benign_profile_regression_restores_positive_primary_and_orders_stress_below_primary() -> None:
    result = run_probability_engine(_build_benign_profile_regression_input())

    assert result.output is not None
    primary = result.output.primary_result
    assert primary.success_probability > 0.01
    assert result.output.challenger_results
    assert result.output.challenger_results[0].success_probability > 0.0
    assert result.output.stress_results
    assert result.output.stress_results[0].success_probability <= primary.success_probability


def test_probability_engine_output_exposes_current_market_pressure_and_scenario_ladder() -> None:
    result = run_probability_engine(_build_benign_profile_regression_input(path_count=64))

    assert result.output is not None
    assert result.output.current_market_pressure is not None
    assert result.output.current_market_pressure.scenario_kind == "current_market"
    assert result.output.current_market_pressure.market_pressure_score is not None
    assert result.output.current_market_pressure.market_pressure_level is not None

    scenario_kinds = [item.scenario_kind for item in result.output.scenario_comparison]
    assert scenario_kinds == [
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    ]
    assert result.output.scenario_comparison[0].pressure is None
    assert result.output.scenario_comparison[1].pressure is not None
    assert len(result.output.stress_results) == 3


def test_deteriorated_success_is_monotonic() -> None:
    result = run_probability_engine(_build_benign_profile_regression_input(path_count=64))

    assert result.output is not None
    by_kind = {item.scenario_kind: item.recipe_result.success_probability for item in result.output.scenario_comparison}
    assert by_kind["current_market"] >= by_kind["deteriorated_mild"] >= by_kind["deteriorated_moderate"] >= by_kind["deteriorated_severe"]


def test_observed_delivery_path_primary_success_stays_above_sixty_percent(tmp_path: Path) -> None:
    profile = UserOnboardingProfile(
        account_profile_id="observed_primary_success_regression",
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )
    original_recipe = PRIMARY_RECIPE_V14
    override = replace(PRIMARY_RECIPE_V14, path_count=128)
    import probability_engine.recipes as recipe_module

    recipe_module.PRIMARY_RECIPE_V14 = override
    recipe_module.RECIPE_REGISTRY[override.recipe_name] = override
    try:
        result = run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "observed_primary_success.sqlite",
            external_snapshot_source=_observed_external_snapshot_source(tmp_path, profile),
        )
    finally:
        recipe_module.PRIMARY_RECIPE_V14 = original_recipe
        recipe_module.RECIPE_REGISTRY[original_recipe.recipe_name] = original_recipe

    probability_result = dict(result.get("probability_engine_result") or {})
    output = dict(probability_result.get("output") or {})
    primary = dict(output.get("primary_result") or {})

    assert result["run_outcome_status"] == "completed"
    assert primary.get("success_probability", 0.0) >= 0.60


def test_observed_delivery_gap_between_historical_and_current_is_bounded(tmp_path: Path) -> None:
    profile = UserOnboardingProfile(
        account_profile_id="observed_gap_bounded_regression",
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )
    original_recipe = PRIMARY_RECIPE_V14
    override = replace(PRIMARY_RECIPE_V14, path_count=128)
    import probability_engine.recipes as recipe_module

    recipe_module.PRIMARY_RECIPE_V14 = override
    recipe_module.RECIPE_REGISTRY[override.recipe_name] = override
    try:
        result = run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "observed_gap_bounded.sqlite",
            external_snapshot_source=_observed_external_snapshot_source(tmp_path, profile),
        )
    finally:
        recipe_module.PRIMARY_RECIPE_V14 = original_recipe
        recipe_module.RECIPE_REGISTRY[original_recipe.recipe_name] = original_recipe

    scenario_comparison = list(result["probability_engine_result"]["output"]["scenario_comparison"])
    by_kind = {item["scenario_kind"]: float(item["recipe_result"]["success_probability"]) for item in scenario_comparison}

    assert by_kind["historical_replay"] - by_kind["current_market"] <= 0.15


def test_observed_delivery_path_scenario_ladder_meets_convergence_thresholds(tmp_path: Path) -> None:
    profile = UserOnboardingProfile(
        account_profile_id="observed_pressure_convergence_regression",
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )
    original_recipe = PRIMARY_RECIPE_V14
    override = replace(PRIMARY_RECIPE_V14, path_count=128)
    import probability_engine.recipes as recipe_module

    recipe_module.PRIMARY_RECIPE_V14 = override
    recipe_module.RECIPE_REGISTRY[override.recipe_name] = override
    try:
        result = run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "observed_pressure_convergence.sqlite",
            external_snapshot_source=_observed_external_snapshot_source(tmp_path, profile),
        )
    finally:
        recipe_module.PRIMARY_RECIPE_V14 = original_recipe
        recipe_module.RECIPE_REGISTRY[original_recipe.recipe_name] = original_recipe

    probability_result = dict(result.get("probability_engine_result") or {})
    output = dict(probability_result.get("output") or {})
    scenario_comparison = list(output.get("scenario_comparison") or [])
    by_kind = {
        item["scenario_kind"]: float(dict(item.get("recipe_result") or {}).get("success_probability", 0.0))
        for item in scenario_comparison
    }
    pressure_by_kind = {
        item["scenario_kind"]: float(dict(item.get("pressure") or {}).get("market_pressure_score", 0.0))
        for item in scenario_comparison
        if item.get("pressure") is not None
    }

    assert [item.get("scenario_kind") for item in scenario_comparison] == [
        "historical_replay",
        "current_market",
        "deteriorated_mild",
        "deteriorated_moderate",
        "deteriorated_severe",
    ]
    assert by_kind["historical_replay"] - by_kind["current_market"] <= 0.15
    assert by_kind["current_market"] - by_kind["deteriorated_mild"] <= 0.20
    assert by_kind["deteriorated_mild"] - by_kind["deteriorated_moderate"] <= 0.20
    assert by_kind["deteriorated_moderate"] - by_kind["deteriorated_severe"] <= 0.25
    assert (
        pressure_by_kind["current_market"]
        < pressure_by_kind["deteriorated_mild"]
        < pressure_by_kind["deteriorated_moderate"]
        < pressure_by_kind["deteriorated_severe"]
    )


def test_execution_plan_payload_exposes_bucket_construction_explanations() -> None:
    plan = build_execution_plan(
        source_run_id="integration_bucket_construction",
        source_allocation_id="allocation_bucket_construction",
        bucket_targets={
            "equity_cn": 0.40,
            "bond_cn": 0.20,
            "gold": 0.10,
            "satellite": 0.20,
            "cash_liquidity": 0.10,
        },
        goal_horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=30.0,
        implied_required_annual_return=0.09,
        bucket_count_preferences=[
            BucketCardinalityPreference(
                bucket="equity_cn",
                mode="target_count",
                target_count=2,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
            BucketCardinalityPreference(
                bucket="satellite",
                mode="target_count",
                target_count=5,
                min_count=None,
                max_count=None,
                source="user_requested",
            ),
        ],
    )

    payload = plan.to_dict()

    assert payload["bucket_construction_explanations"]["equity_cn"]["requested_count"] == 2
    assert payload["bucket_construction_explanations"]["satellite"]["requested_count"] == 5
    assert len([item for item in payload["items"] if item["asset_bucket"] == "equity_cn"]) == 2
    assert "equity_cn" not in payload["bucket_construction_suggestions"]
    assert payload["bucket_construction_suggestions"]["satellite"]["member_product_ids"]


def test_execution_plan_summary_threads_search_expansion_metadata_for_compact_primary() -> None:
    plan = build_execution_plan(
        source_run_id="integration_search_expansion_summary",
        source_allocation_id="allocation_search_expansion_summary",
        bucket_targets={
            "equity_cn": 0.45,
            "bond_cn": 0.30,
            "gold": 0.15,
            "cash_liquidity": 0.10,
        },
        goal_horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        current_market_pressure_score=28.0,
        implied_required_annual_return=0.08,
        search_expansion_level="L0_compact",
        search_expansion_recommendation=SearchExpansionRecommendation(
            search_expansion_level="L1_expanded",
            why_this_level_was_run="user_requested_deeper_search",
            why_search_stopped="requested_search_expansion_level_reached",
            new_product_ids_added=["cn_equity_low_vol_fund"],
            products_removed=["cn_equity_dividend_etf"],
        ),
    )

    summary = _build_execution_plan_summary(plan)

    assert summary["search_expansion_level"] == "L0_compact"
    assert summary["search_expansion_recommendation"]["search_expansion_level"] == "L1_expanded"
    assert summary["search_expansion_recommendation"]["new_product_ids_added"] == ["cn_equity_low_vol_fund"]


def test_same_month_twenty_trading_day_path_accepts_horizon_months_one() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["as_of"] = "2026-04-01"
    sim_input["trading_calendar"] = [
        "2026-04-02",
        "2026-04-03",
        "2026-04-06",
        "2026-04-07",
        "2026-04-08",
        "2026-04-09",
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
    ]
    sim_input["success_event_spec"]["horizon_months"] = 1

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status in {"success", "degraded"}
    assert result.output is not None


def test_fixture_cross_month_twenty_trading_day_path_accepts_horizon_months_one() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert result.run_outcome_status in {"success", "degraded"}
    assert result.output is not None


def test_explicit_trading_calendar_is_source_of_truth_for_formal_steps() -> None:
    sim_input = _load_v14_formal_daily_input()

    assert _trading_step_dates(sim_input["as_of"], sim_input["trading_calendar"], 5) == [
        "2026-04-10",
        "2026-04-13",
        "2026-04-14",
        "2026-04-15",
        "2026-04-16",
    ]
    assert "2026-05-01" not in _trading_step_dates(sim_input["as_of"], sim_input["trading_calendar"], sim_input["path_horizon_days"])


def test_holiday_date_not_in_trading_calendar_does_not_affect_engine_output() -> None:
    baseline_input = _load_v14_formal_daily_input()
    holiday_input = deepcopy(baseline_input)
    holiday_input["contribution_schedule"] = list(holiday_input["contribution_schedule"]) + [
        {
            "date": "2026-05-01",
            "amount": 999999.0,
            "allocation_mode": "target_weights",
            "target_weights": baseline_input["contribution_schedule"][0]["target_weights"],
        }
    ]

    baseline = run_probability_engine(baseline_input)
    holiday = run_probability_engine(holiday_input)

    assert baseline.output is not None
    assert holiday.output is not None
    assert holiday.output.to_dict() == baseline.output.to_dict()


def test_non_formal_primary_recipe_is_rejected() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["recipes"] = [
        {
            "recipe_name": "primary_monthly_static_gaussian_v0",
            "role": "primary",
            "innovation_layer": "gaussian",
            "volatility_layer": "historical_monthly",
            "dependency_layer": "none",
            "jump_layer": "none",
            "regime_layer": "none",
            "estimation_basis": "monthly_proxy_estimate",
            "dependency_scope": "product",
            "path_count": 1000,
        }
    ]

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "formal daily primary recipe" in result.failure_artifact.message


def test_registered_primary_recipe_allows_path_count_override() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["recipes"] = [
        {
            "recipe_name": "primary_daily_factor_garch_dcc_jump_regime_v1",
            "role": "primary",
            "path_count": 1,
        }
    ]

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status in {"success", "degraded"}
    assert result.output is not None
    assert result.output.primary_result.path_stats.path_count == 1


def test_explicit_recipe_list_without_primary_is_rejected() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["recipes"] = [
        {
            "recipe_name": "challenger_daily_factor_garch_dcc_jump_regime_v1",
            "role": "challenger",
            "innovation_layer": "student_t",
            "volatility_layer": "factor_and_product_garch",
            "dependency_layer": "factor_level_dcc",
            "jump_layer": "systemic_plus_idio",
            "regime_layer": "markov_regime",
            "estimation_basis": "daily_product_formal",
            "dependency_scope": "factor",
            "path_count": 4000,
        }
    ]

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status == "failure"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "primary recipe" in result.failure_artifact.message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_type", "wealth_percentile"),
        ("success_logic", "target_only"),
        ("return_basis", "real"),
        ("fee_basis", "gross"),
        ("benchmark_ref", "bench://csi300"),
        ("horizon_days", 21),
    ],
)
def test_invalid_formal_success_event_spec_is_rejected(field: str, value: object) -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["success_event_spec"][field] = value

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "success_event_spec" in result.failure_artifact.message


def test_conflicting_horizon_months_are_rejected() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["success_event_spec"]["horizon_months"] = 3

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status == "failure"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "horizon_months" in result.failure_artifact.message


def test_zero_horizon_is_rejected_for_formal_task4_runs() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["path_horizon_days"] = 0
    sim_input["trading_calendar"] = []
    sim_input["success_event_spec"]["horizon_days"] = 0
    sim_input["success_event_spec"]["horizon_months"] = 0
    for product in sim_input["products"]:
        product["mapping_confidence"] = "high"

    result = run_probability_engine(sim_input)

    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "path_horizon_days" in result.failure_artifact.message


class _FixedChiSquareRng:
    def chisquare(self, df: float) -> float:
        return float(df)


def _wilson_interval(success_count: int, total_count: int, z_score: float = 1.96) -> tuple[float, float]:
    probability = success_count / total_count
    z_squared = z_score**2
    denominator = 1.0 + (z_squared / total_count)
    center = (probability + (z_squared / (2.0 * total_count))) / denominator
    margin = (
        z_score
        * np.sqrt((probability * (1.0 - probability) + (z_squared / (4.0 * total_count))) / total_count)
        / denominator
    )
    return (center - margin, center + margin)


def test_student_t_scale_standardizes_to_unit_variance_before_sigma_scaling() -> None:
    scale = _student_t_scale(_FixedChiSquareRng(), 7.0)  # type: ignore[arg-type]

    assert scale == pytest.approx(np.sqrt(5.0 / 7.0))


def test_monthly_hybrid_rebalance_only_triggers_on_calendar_boundary() -> None:
    state = PortfolioState(
        product_values={"equity": 80.0, "bond": 20.0},
        cash=0.0,
        target_weights={"equity": 0.5, "bond": 0.5},
    )
    policy = RebalancingPolicySpec(
        policy_type="hybrid",
        calendar_frequency="monthly",
        threshold_band=0.40,
        execution_timing="end_of_day_after_return",
        transaction_cost_bps=0.0,
        min_trade_amount=None,
    )

    mid_month = apply_daily_cashflows_and_rebalance(
        portfolio_state=state,
        product_returns={},
        contributions=[],
        withdrawals=[],
        policy=policy,
        current_date="2026-04-10",
        previous_date="2026-04-09",
    )
    month_turn = apply_daily_cashflows_and_rebalance(
        portfolio_state=state,
        product_returns={},
        contributions=[],
        withdrawals=[],
        policy=policy,
        current_date="2026-05-01",
        previous_date="2026-04-30",
    )

    assert mid_month.product_values == {"equity": 80.0, "bond": 20.0}
    assert month_turn.product_values == {"equity": 50.0, "bond": 50.0}


def test_success_probability_range_uses_wilson_interval() -> None:
    runtime_input = DailyEngineRuntimeInput.from_any(_load_v14_formal_daily_input())
    outcomes = [
        PathOutcome(terminal_value=100000.0, cagr=0.0, max_drawdown=0.0, success=True),
        PathOutcome(terminal_value=100000.0, cagr=0.0, max_drawdown=0.0, success=True),
        PathOutcome(terminal_value=100000.0, cagr=0.0, max_drawdown=0.0, success=False),
        PathOutcome(terminal_value=100000.0, cagr=0.0, max_drawdown=0.0, success=False),
    ]

    result = _summarize_outcomes(runtime_input, PRIMARY_RECIPE_V14, outcomes)

    assert result.success_probability == pytest.approx(0.5)
    assert result.success_probability_range == pytest.approx(_wilson_interval(2, 4))
