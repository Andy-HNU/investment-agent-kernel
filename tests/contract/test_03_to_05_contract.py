from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from calibration.types import BehaviorState, CalibrationResult, ConstraintState, MarketState
from snapshot_ingestion.engine import build_snapshot_bundle


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.9,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.6,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
        "correlation_spike_alert": False,
    }


def _account_raw(goal_solver_input_base: dict, live_portfolio_base: dict) -> dict:
    return {
        "weights": live_portfolio_base["weights"],
        "total_value": live_portfolio_base["total_value"],
        "available_cash": live_portfolio_base["available_cash"],
        "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
    }


def _goal_raw(goal_solver_input_base: dict) -> dict:
    goal = goal_solver_input_base["goal"]
    return {
        "goal_amount": goal["goal_amount"],
        "horizon_months": goal["horizon_months"],
        "goal_description": goal["goal_description"],
        "success_prob_threshold": goal["success_prob_threshold"],
        "priority": goal["priority"],
        "risk_preference": goal["risk_preference"],
    }


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = goal_solver_input_base["constraints"]
    return {
        **constraints,
        "rebalancing_band": 0.10,
        "forbidden_actions": [],
        "cooling_period_days": 3,
        "soft_preferences": {},
        "bucket_category": {
            "equity_cn": "core",
            "bond_cn": "defense",
            "gold": "defense",
            "satellite": "satellite",
        },
        "bucket_to_theme": {
            "equity_cn": None,
            "bond_cn": None,
            "gold": None,
            "satellite": "technology",
        },
        "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
    }


@pytest.mark.contract
def test_build_snapshot_bundle_marks_missing_behavior_as_partial(
    goal_solver_input_base,
    live_portfolio_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    assert bundle.bundle_id.startswith("acc001_20260329T120000Z")
    assert bundle.bundle_quality.value == "partial"
    assert "behavior" in bundle.missing_domains
    assert any(flag.code == "BEHAVIOR_DOMAIN_MISSING" for flag in bundle.quality_summary)


@pytest.mark.contract
def test_build_snapshot_bundle_treats_all_cash_account_as_full_coverage(
    goal_solver_input_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw={
            "weights": {},
            "total_value": 50_000.0,
            "available_cash": 50_000.0,
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
        },
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    assert bundle.bundle_quality.value == "full"
    assert not any(flag.code == "PARTIAL_BUCKET_COVERAGE" for flag in bundle.quality_summary)


@pytest.mark.contract
def test_run_calibration_consumes_snapshot_bundle_and_emits_canonical_types(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert isinstance(result, CalibrationResult)
    assert isinstance(result.market_state, MarketState)
    assert isinstance(result.constraint_state, ConstraintState)
    assert isinstance(result.behavior_state, BehaviorState)
    assert result.source_bundle_id == bundle.bundle_id
    assert result.param_version_meta["source_bundle_id"] == bundle.bundle_id
    assert result.calibration_quality == "full"
    assert result.param_version_meta["version_id"].startswith("calibration_")
    assert result.param_version_meta["updated_reason"] == "monthly_calibration"
    assert result.param_version_meta["quality"] == "full"
    assert result.param_version_meta["is_temporary"] is False
    assert result.param_version_meta["can_be_replayed"] is True
    assert result.goal_solver_params.version.startswith("goal_solver_params_")
    assert result.runtime_optimizer_params.version.startswith("runtime_params_")
    assert result.ev_params.version.startswith("ev_params_")


@pytest.mark.contract
def test_run_calibration_marks_missing_market_volatility_as_degraded(
    goal_solver_input_base,
    live_portfolio_base,
):
    market_raw = _market_raw(goal_solver_input_base)
    market_raw.pop("raw_volatility")
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert result.calibration_quality == "degraded"
    assert "market" in result.degraded_domains
    assert result.param_version_meta["quality"] == "degraded"
    assert result.param_version_meta["is_temporary"] is True
    assert result.param_version_meta["can_be_replayed"] is False


@pytest.mark.contract
def test_run_calibration_reuses_prior_behavior_when_behavior_missing(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=calibration_result_base)

    assert result.calibration_quality == "partial"
    assert "behavior" in result.degraded_domains
    assert result.behavior_state.recent_chase_risk == calibration_result_base["behavior_state"]["recent_chase_risk"]
    assert result.behavior_state.source_bundle_id == bundle.bundle_id
    assert any("prior behavior state reused" in note for note in result.notes)
    assert result.param_version_meta["quality"] == "degraded"
    assert result.param_version_meta["is_temporary"] is True
    assert result.param_version_meta["can_be_replayed"] is False


@pytest.mark.contract
def test_run_calibration_manual_override_marks_param_meta_manual(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(
        bundle,
        prior_calibration=calibration_result_base,
        updated_reason="manual_review",
        manual_override=True,
    )

    assert result.calibration_quality == "full"
    assert result.param_version_meta["quality"] == "manual"
    assert result.param_version_meta["updated_reason"] == "manual_review"
    assert result.param_version_meta["is_temporary"] is False
    assert result.param_version_meta["can_be_replayed"] is True
    assert any("manual override applied" in note for note in result.notes)


@pytest.mark.contract
def test_run_calibration_degraded_market_reuses_prior_market_assumptions(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    market_raw = _market_raw(goal_solver_input_base)
    market_raw.pop("raw_volatility")
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=calibration_result_base)

    assert result.calibration_quality == "degraded"
    assert result.market_assumptions.expected_returns == calibration_result_base["market_assumptions"]["expected_returns"]
    assert result.market_assumptions.volatility == calibration_result_base["market_assumptions"]["volatility"]
    assert result.market_assumptions.correlation_matrix == calibration_result_base["market_assumptions"]["correlation_matrix"]
    assert result.market_assumptions.historical_backtest_used is False
    assert any("market assumptions reused from prior" in note for note in result.notes)
    assert result.param_version_meta["updated_reason"] == "degraded_replay"
    assert result.param_version_meta["is_temporary"] is True
    assert result.param_version_meta["can_be_replayed"] is False


@pytest.mark.contract
def test_run_calibration_market_warns_are_partial_not_degraded(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    market_raw = _market_raw(goal_solver_input_base)
    market_raw.pop("liquidity_scores")
    market_raw.pop("valuation_z_scores")
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=calibration_result_base)

    assert result.calibration_quality == "partial"
    assert result.degraded_domains == ["market"]
    assert "market_liquidity_scores_missing" in result.market_state.quality_flags
    assert "market_valuation_z_scores_missing" in result.market_state.quality_flags
    assert result.param_version_meta["is_temporary"] is True


@pytest.mark.contract
def test_run_calibration_constraint_conflict_requires_manual_review(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    constraint_raw = _constraint_raw(goal_solver_input_base)
    constraint_raw["ips_bucket_boundaries"] = {
        **constraint_raw["ips_bucket_boundaries"],
        "equity_cn": (0.8, 0.3),
    }
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=constraint_raw,
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )

    result = run_calibration(bundle, prior_calibration=calibration_result_base)

    assert result.calibration_quality == "degraded"
    assert "constraint" in result.degraded_domains
    assert any("CONSTRAINT_BOUNDS_CONFLICT:equity_cn" in note for note in result.notes)
    assert any("manual review required" in note for note in result.notes)
    assert result.param_version_meta["quality"] == "degraded"


@pytest.mark.contract
def test_run_calibration_replay_promotes_temporary_prior_to_replayable_full(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    degraded_market_raw = _market_raw(goal_solver_input_base)
    degraded_market_raw.pop("raw_volatility")
    degraded_bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=degraded_market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )
    temporary_result = run_calibration(degraded_bundle, prior_calibration=calibration_result_base)

    healthy_market_raw = _market_raw(goal_solver_input_base)
    healthy_market_raw["raw_volatility"]["equity_cn"] = 0.12
    healthy_bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        market_raw=healthy_market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )
    replay_result = run_calibration(
        healthy_bundle,
        prior_calibration=temporary_result,
        replay_mode=True,
    )

    assert temporary_result.param_version_meta["is_temporary"] is True
    assert replay_result.calibration_quality == "full"
    assert replay_result.param_version_meta["updated_reason"] == "replay_calibration"
    assert replay_result.param_version_meta["is_temporary"] is False
    assert replay_result.param_version_meta["can_be_replayed"] is True
    assert replay_result.param_version_meta["version_id"] != temporary_result.param_version_meta["version_id"]
    assert replay_result.market_assumptions.volatility["equity_cn"] == 0.12


@pytest.mark.contract
def test_build_snapshot_bundle_preserves_policy_news_signals_and_historical_dataset_metadata(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
        policy_news_signals=[
            {
                "signal_id": "signal-1",
                "as_of": "2026-03-29T10:00:00Z",
                "source_type": "policy",
                "source_refs": ["https://example.com/policy"],
                "macro_uncertainty": "high",
                "manual_review_required": True,
                "confidence": 0.88,
            }
        ],
        historical_dataset_metadata={
            "source_name": "frozen_fixture",
            "as_of": "2026-03-29",
            "lookback_months": 24,
            "return_series": {
                "equity_cn": [0.01, 0.02, -0.01],
                "bond_cn": [0.002, 0.003, 0.001],
            },
        },
    )

    assert bundle.policy_news_signals[0].signal_id == "signal-1"
    assert bundle.policy_news_signals[0].manual_review_required is True
    assert bundle.historical_dataset_metadata["source_name"] == "frozen_fixture"


@pytest.mark.contract
def test_run_calibration_uses_historical_dataset_metadata_for_market_assumptions(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
        historical_dataset_metadata={
            "source_name": "fixture_history",
            "as_of": "2026-03-29",
            "lookback_months": 36,
            "version_id": "fixture_history:2026-03-29:v1",
            "series_dates": ["2025-12-31", "2026-01-31", "2026-02-28", "2026-03-29"],
            "observed_history_days": 2520,
            "inferred_history_days": 365,
            "inference_method": "index_proxy",
            "coverage_status": "cycle_insufficient",
            "cycle_reasons": ["missing_downcycle"],
            "return_series": {
                "equity_cn": [0.01, 0.02, -0.01, 0.03],
                "bond_cn": [0.002, 0.004, 0.001, 0.003],
                "gold": [0.006, -0.002, 0.004, 0.003],
                "satellite": [0.015, 0.025, -0.02, 0.03],
            },
        },
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert result.market_assumptions.source_name == "fixture_history"
    assert result.market_assumptions.dataset_version == "fixture_history:2026-03-29:v1"
    assert result.market_assumptions.lookback_months == 36
    assert result.market_assumptions.historical_backtest_used is True
    assert result.market_assumptions.coverage_status == "cycle_insufficient"
    assert result.market_assumptions.cycle_reasons == ["missing_downcycle"]
    assert result.market_assumptions.observed_history_days == 2520
    assert result.market_assumptions.inferred_history_days == 365
    assert result.market_assumptions.inference_method == "index_proxy"
    assert result.market_state.historical_coverage_status == "cycle_insufficient"
    assert result.market_state.historical_cycle_reasons == ["missing_downcycle"]
    assert result.market_state.observed_history_days == 2520
    assert result.market_state.inferred_history_days == 365
    assert result.market_state.historical_inference_method == "index_proxy"
    assert result.goal_solver_params.market_assumptions.dataset_version == "fixture_history:2026-03-29:v1"
    assert any("historical_dataset_cycle coverage_status=cycle_insufficient" in note for note in result.notes)


@pytest.mark.contract
def test_run_calibration_policy_news_signal_surfaces_manual_review_and_market_notes(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
        policy_news_signals=[
            {
                "signal_id": "signal-high-uncertainty",
                "as_of": "2026-03-29T10:00:00Z",
                "source_type": "analysis",
                "source_refs": ["memo://macro"],
                "macro_uncertainty": "high",
                "liquidity_stress": "high",
                "manual_review_required": True,
                "confidence": 0.91,
            }
        ],
    )

    result = run_calibration(bundle, prior_calibration=None)

    assert "policy_signal_manual_review_required" in result.market_state.quality_flags
    assert result.constraint_state.soft_preferences["policy_manual_review_required"] is True
    assert any("policy_signal manual_review_required=true" in note for note in result.notes)
    assert any("macro_uncertainty=high" in note for note in result.notes)
