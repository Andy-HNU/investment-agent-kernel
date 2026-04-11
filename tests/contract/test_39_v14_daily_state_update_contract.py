from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json

import pytest

from calibration.engine import run_calibration
from calibration.types import CalibrationResult
from probability_engine.path_generator import DailyEngineRuntimeInput, simulate_primary_paths
from probability_engine.factor_library import FIXED_FACTOR_DICTIONARY
from probability_engine.dependence import FactorLevelDccProvider
from probability_engine.jumps import (
    idiosyncratic_jump_profile,
    regime_adjusted_systemic_jump_dispersion,
    load_jump_state_snapshot,
    systemic_jump_probability,
)
from probability_engine.recipes import SimulationRecipe
from probability_engine.regime import load_regime_state_snapshot, sample_next_regime
from probability_engine.volatility import update_garch_state


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v14"


@pytest.mark.contract
def test_daily_state_update_uses_pre_jump_residuals_only() -> None:
    h_next = update_garch_state(
        previous_variance=0.0004,
        pre_jump_residual=-0.01,
        omega=0.00002,
        alpha=0.08,
        beta=0.90,
    )

    assert round(h_next, 8) == round(0.00002 + 0.08 * 0.0001 + 0.90 * 0.0004, 8)


@pytest.mark.contract
def test_dcc_update_returns_next_correlation_only_for_next_step() -> None:
    provider = FactorLevelDccProvider(alpha=0.04, beta=0.93)
    state = provider.initialize(
        ["CN_EQ_BROAD", "GOLD_GLOBAL"],
        {"long_run_correlation": [[1.0, 0.2], [0.2, 1.0]]},
    )
    before_update = provider.current_correlation(state)
    next_state = provider.update([1.2, -0.4], state)
    expected_q_next = [
        [0.96 * 1.0 + 0.04 * (1.2**2), 0.96 * 0.2 + 0.04 * (1.2 * -0.4)],
        [0.96 * 0.2 + 0.04 * (-0.4 * 1.2), 0.96 * 1.0 + 0.04 * ((-0.4) ** 2)],
    ]

    assert before_update[0][1] == pytest.approx(0.2)
    assert provider.current_correlation(state)[0][1] == pytest.approx(0.2)
    assert next_state is not state
    assert next_state.q_matrix[0][0] == pytest.approx(expected_q_next[0][0])
    assert next_state.q_matrix[0][1] == pytest.approx(expected_q_next[0][1])
    assert next_state.q_matrix[1][0] == pytest.approx(expected_q_next[1][0])
    assert next_state.q_matrix[1][1] == pytest.approx(expected_q_next[1][1])
    assert provider.current_correlation(next_state)[0][1] != pytest.approx(before_update[0][1])
    assert provider.current_correlation(state)[0][1] == pytest.approx(before_update[0][1])


@pytest.mark.contract
def test_fixture_backed_regime_and_jump_snapshots_rehydrate_typed_state() -> None:
    regime_state = load_regime_state_snapshot(FIXTURE_DIR / "regime_state_snapshot.json")
    jump_state = load_jump_state_snapshot(FIXTURE_DIR / "jump_state_snapshot.json")

    assert regime_state.current_regime == "normal"
    assert regime_state.transition_matrix[0][0] == pytest.approx(0.86)
    assert regime_state.transition_matrix[0][1] == pytest.approx(0.11)
    assert sample_next_regime(regime_state, random_state=7) == "normal"
    assert systemic_jump_probability(jump_state) == pytest.approx(0.012)
    assert systemic_jump_probability(jump_state, regime_state) == pytest.approx(0.012)
    assert systemic_jump_probability(jump_state, regime_state, regime_name="stress") == pytest.approx(0.0216)
    assert idiosyncratic_jump_profile(jump_state, "cn_equity_balanced_fund")["probability_1d"] == pytest.approx(0.018)
    assert regime_adjusted_systemic_jump_dispersion(jump_state, regime_state) == pytest.approx(0.018)


@pytest.mark.contract
def test_regime_snapshot_rejects_negative_transition_entries(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "bad_regime_state_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "regime_names": ["normal", "stress"],
                "current_regime": "normal",
                "transition_matrix": [[1.2, -0.2], [0.3, 0.7]],
                "regime_mean_adjustments": {"normal": {}, "stress": {}},
                "regime_vol_adjustments": {"normal": {}, "stress": {}},
                "regime_jump_adjustments": {"normal": {}, "stress": {}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="negative probabilities"):
        load_regime_state_snapshot(snapshot_path)


@pytest.mark.contract
def test_run_calibration_exposes_typed_v14_state_artifacts() -> None:
    result = run_calibration(
        {
            "bundle_id": "bundle_v14_state_artifacts",
            "created_at": datetime(2026, 4, 9, tzinfo=timezone.utc),
            "account_profile_id": "acct_v14",
            "bundle_quality": "full",
            "market": {
                "raw_volatility": {"equity_cn": 0.18},
                "liquidity_scores": {"equity_cn": 0.9},
                "valuation_z_scores": {"equity_cn": 0.2},
            },
            "account": {
                "weights": {"equity_cn": 1.0},
                "total_value": 100000.0,
                "available_cash": 5000.0,
                "remaining_horizon_months": 12,
            },
            "goal": {
                "goal_amount": 120000.0,
                "horizon_months": 12,
                "goal_description": "v14 state artifact contract",
                "success_prob_threshold": 0.6,
            },
            "constraint": {
                "ips_bucket_boundaries": {"equity_cn": (0.0, 1.0)},
                "satellite_cap": 0.15,
                "theme_caps": {},
                "qdii_cap": 0.2,
                "liquidity_reserve_min": 0.05,
                "max_drawdown_tolerance": 0.2,
                "bucket_category": {"equity_cn": "core"},
                "bucket_to_theme": {"equity_cn": None},
            },
            "behavior": None,
            "remaining_horizon_months": 12,
        },
        prior_calibration=None,
    )

    assert isinstance(result, CalibrationResult)
    assert result.factor_dynamics is not None
    assert result.regime_state is not None
    assert result.jump_state is not None
    assert tuple(result.factor_dynamics.factor_names) == tuple(FIXED_FACTOR_DICTIONARY.keys())
    assert result.regime_state.current_regime in {"normal", "risk_off", "stress"}
    assert result.jump_state.systemic_jump_probability_1d > 0.0
    assert isinstance(result.jump_state.idio_jump_profile_by_product, dict)
    assert all(str(key).strip() for key in result.jump_state.idio_jump_profile_by_product)
    assert set(result.jump_state.idio_jump_profile_by_product).isdisjoint(FIXED_FACTOR_DICTIONARY)


@pytest.mark.contract
def test_primary_path_does_not_regime_adjust_fallback_product_jump_profiles() -> None:
    runtime_input = DailyEngineRuntimeInput.from_any(
        {
            "as_of": "2026-04-10",
            "path_horizon_days": 1,
            "trading_calendar": ["2026-04-11"],
            "products": [
                {
                    "product_id": "fallback_jump_product",
                    "asset_bucket": "equity_cn",
                    "factor_betas": {"CN_EQ_BROAD": 0.0},
                    "innovation_family": "gaussian",
                    "tail_df": None,
                    "volatility_process": "garch_t",
                    "garch_params": {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "long_run_variance": 0.0},
                    "idiosyncratic_jump_profile": {"probability_1d": 1.0, "loss_mean": -0.02, "loss_std": 0.0},
                    "carry_profile": {},
                    "valuation_profile": {},
                    "mapping_confidence": "high",
                    "factor_mapping_source": "prior",
                    "factor_mapping_evidence": [],
                    "observed_series_ref": "obs://fallback_jump_product",
                }
            ],
            "factor_dynamics": {
                "factor_names": ["CN_EQ_BROAD"],
                "factor_series_ref": "factor://cn_eq_broad",
                "innovation_family": "gaussian",
                "tail_df": None,
                "garch_params_by_factor": {
                    "CN_EQ_BROAD": {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "long_run_variance": 0.0}
                },
                "dcc_params": {"alpha": 0.04, "beta": 0.93},
                "long_run_covariance": {"CN_EQ_BROAD": {"CN_EQ_BROAD": 1.0}},
                "covariance_shrinkage": 0.2,
                "calibration_window_days": 252,
            },
            "regime_state": {
                "regime_names": ["normal", "stress"],
                "current_regime": "normal",
                "transition_matrix": [[0.0, 1.0], [0.0, 1.0]],
                "regime_mean_adjustments": {"normal": {}, "stress": {}},
                "regime_vol_adjustments": {"normal": {}, "stress": {}},
                "regime_jump_adjustments": {
                    "normal": {},
                    "stress": {
                        "idio_jump_probability_multiplier": 2.0,
                        "idio_loss_multiplier": 3.0,
                        "idio_loss_std_multiplier": 5.0,
                    },
                },
            },
            "jump_state": {
                "systemic_jump_probability_1d": 0.0,
                "systemic_jump_impact_by_factor": {"CN_EQ_BROAD": 0.0},
                "systemic_jump_dispersion": 0.01,
                "idio_jump_profile_by_product": {},
            },
            "current_positions": [
                {
                    "product_id": "fallback_jump_product",
                    "units": 0.0,
                    "market_value": 100.0,
                    "weight": 1.0,
                    "cost_basis": None,
                    "tradable": True,
                }
            ],
            "contribution_schedule": [],
            "withdrawal_schedule": [],
            "rebalancing_policy": {
                "policy_type": "none",
                "calendar_frequency": None,
                "threshold_band": None,
                "execution_timing": "end_of_day_after_return",
                "transaction_cost_bps": 0.0,
                "min_trade_amount": None,
            },
            "success_event_spec": {
                "horizon_days": 1,
                "horizon_months": 1,
                "target_type": "goal_amount",
                "target_value": 98.0,
                "drawdown_constraint": 1.0,
                "benchmark_ref": None,
                "contribution_policy": "none",
                "withdrawal_policy": "none",
                "rebalancing_policy_ref": "none",
                "return_basis": "nominal",
                "fee_basis": "net",
                "success_logic": "joint_target_and_drawdown",
            },
            "recipes": [],
            "evidence_bundle_ref": "evidence://fallback_jump",
            "random_seed": 7,
        }
    )
    recipe = SimulationRecipe(
        recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
        role="primary",
        innovation_layer="student_t",
        volatility_layer="factor_and_product_garch",
        dependency_layer="factor_level_dcc",
        jump_layer="systemic_plus_idio",
        regime_layer="markov_regime",
        estimation_basis="daily_product_formal",
        dependency_scope="factor",
        path_count=1,
    )

    result = simulate_primary_paths(runtime_input, recipe)

    expected_terminal = 100.0 * (1.0 - 0.02)
    assert result.path_stats.path_count == 1
    assert result.path_stats.terminal_value_mean == pytest.approx(expected_terminal, abs=1e-3)


@pytest.mark.contract
def test_run_calibration_prefers_explicit_bundle_v14_artifacts_over_prior_calibration() -> None:
    result = run_calibration(
        {
            "bundle_id": "bundle_v14_explicit_state",
            "created_at": datetime(2026, 4, 10, tzinfo=timezone.utc),
            "account_profile_id": "acct_v14",
            "bundle_quality": "full",
            "market": {
                "raw_volatility": {"equity_cn": 0.18},
                "liquidity_scores": {"equity_cn": 0.9},
                "valuation_z_scores": {"equity_cn": 0.2},
                "historical_dataset": {
                    "dataset_id": "explicit_state_history",
                    "version_id": "explicit_state_history_v1",
                    "as_of": "2026-04-10T00:00:00Z",
                    "source_name": "explicit_state_history",
                    "source_ref": "historical://explicit_state",
                    "lookback_months": 12,
                    "frequency": "monthly",
                    "coverage_status": "verified",
                    "return_series": {
                        "equity_cn": [0.01, -0.02, 0.015, 0.01],
                        "bond_cn": [0.002, 0.001, 0.0025, 0.0015],
                    },
                    "audit_window": {
                        "start_date": "2025-01-01",
                        "end_date": "2026-04-10",
                        "trading_days": 252,
                        "observed_days": 252,
                        "inferred_days": 0,
                    },
                },
            },
            "account": {
                "weights": {"equity_cn": 1.0},
                "total_value": 100000.0,
                "available_cash": 5000.0,
                "remaining_horizon_months": 12,
            },
            "goal": {
                "goal_amount": 120000.0,
                "horizon_months": 12,
                "goal_description": "v14 explicit state artifact contract",
                "success_prob_threshold": 0.6,
            },
            "constraint": {
                "ips_bucket_boundaries": {"equity_cn": (0.0, 1.0)},
                "satellite_cap": 0.15,
                "theme_caps": {},
                "qdii_cap": 0.2,
                "liquidity_reserve_min": 0.05,
                "max_drawdown_tolerance": 0.2,
                "bucket_category": {"equity_cn": "core"},
                "bucket_to_theme": {"equity_cn": None},
            },
            "behavior": None,
            "remaining_horizon_months": 12,
            "probability_engine_v14": {
                "factor_dynamics": {
                    "factor_names": list(FIXED_FACTOR_DICTIONARY.keys()),
                    "factor_series_ref": "bundle://explicit_factor_series",
                    "innovation_family": "student_t",
                    "tail_df": 9.0,
                    "garch_params_by_factor": {
                        factor_id: {
                            "omega": 0.00001,
                            "alpha": 0.05,
                            "beta": 0.91,
                            "nu": 9.0,
                            "long_run_variance": 0.0004,
                        }
                        for factor_id in FIXED_FACTOR_DICTIONARY
                    },
                    "dcc_params": {"alpha": 0.05, "beta": 0.9},
                    "long_run_covariance": {
                        factor_id: {
                            peer_id: (0.0004 if factor_id == peer_id else 0.0001)
                            for peer_id in FIXED_FACTOR_DICTIONARY
                        }
                        for factor_id in FIXED_FACTOR_DICTIONARY
                    },
                    "covariance_shrinkage": 0.2,
                    "calibration_window_days": 252,
                },
                "regime_state": {
                    "regime_names": ["normal", "risk_off", "stress"],
                    "current_regime": "risk_off",
                    "transition_matrix": [[0.8, 0.15, 0.05], [0.2, 0.6, 0.2], [0.1, 0.2, 0.7]],
                    "regime_mean_adjustments": {"normal": {}, "risk_off": {}, "stress": {}},
                    "regime_vol_adjustments": {"normal": {}, "risk_off": {}, "stress": {}},
                    "regime_jump_adjustments": {"normal": {}, "risk_off": {}, "stress": {}},
                },
                "jump_state": {
                    "systemic_jump_probability_1d": 0.02,
                    "systemic_jump_impact_by_factor": {factor_id: -0.01 for factor_id in FIXED_FACTOR_DICTIONARY},
                    "systemic_jump_dispersion": 0.03,
                    "idio_jump_profile_by_product": {"explicit_product": {"probability_1d": 0.05, "loss_mean": -0.02, "loss_std": 0.01}},
                },
            },
        },
        prior_calibration={
            "factor_dynamics": {"factor_names": ["stale_factor"], "factor_series_ref": "stale", "innovation_family": "student_t", "tail_df": 5.0, "garch_params_by_factor": {"stale_factor": {"omega": 0.1, "alpha": 0.1, "beta": 0.8, "nu": 5.0, "long_run_variance": 0.1}}, "dcc_params": {"alpha": 0.1, "beta": 0.8}, "long_run_covariance": {"stale_factor": {"stale_factor": 0.1}}, "covariance_shrinkage": 0.5, "calibration_window_days": 999},
            "regime_state": {"regime_names": ["stale"], "current_regime": "stale", "transition_matrix": [[1.0]], "regime_mean_adjustments": {"stale": {}}, "regime_vol_adjustments": {"stale": {}}, "regime_jump_adjustments": {"stale": {}}},
            "jump_state": {"systemic_jump_probability_1d": 0.9, "systemic_jump_impact_by_factor": {"stale_factor": -0.9}, "systemic_jump_dispersion": 0.9, "idio_jump_profile_by_product": {"stale_product": {"probability_1d": 0.9, "loss_mean": -0.9, "loss_std": 0.9}}},
        },
    )

    assert result.factor_dynamics.factor_series_ref == "bundle://explicit_factor_series"
    assert result.regime_state.current_regime == "risk_off"
    assert result.jump_state.systemic_jump_probability_1d == pytest.approx(0.02)
    assert "explicit_product" in result.jump_state.idio_jump_profile_by_product


@pytest.mark.contract
def test_run_calibration_uses_zero_calibration_window_days_without_history() -> None:
    result = run_calibration(
        {
            "bundle_id": "bundle_v14_no_history",
            "created_at": datetime(2026, 4, 11, tzinfo=timezone.utc),
            "account_profile_id": "acct_v14",
            "bundle_quality": "full",
            "market": {
                "raw_volatility": {"equity_cn": 0.18},
                "liquidity_scores": {"equity_cn": 0.9},
                "valuation_z_scores": {"equity_cn": 0.2},
            },
            "account": {
                "weights": {"equity_cn": 1.0},
                "total_value": 100000.0,
                "available_cash": 5000.0,
                "remaining_horizon_months": 12,
            },
            "goal": {
                "goal_amount": 120000.0,
                "horizon_months": 12,
                "goal_description": "v14 zero history contract",
                "success_prob_threshold": 0.6,
            },
            "constraint": {
                "ips_bucket_boundaries": {"equity_cn": (0.0, 1.0)},
                "satellite_cap": 0.15,
                "theme_caps": {},
                "qdii_cap": 0.2,
                "liquidity_reserve_min": 0.05,
                "max_drawdown_tolerance": 0.2,
                "bucket_category": {"equity_cn": "core"},
                "bucket_to_theme": {"equity_cn": None},
            },
            "behavior": None,
            "remaining_horizon_months": 12,
        },
        prior_calibration=None,
    )

    assert result.factor_dynamics.calibration_window_days == 0
