from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json

import pytest

from calibration.engine import run_calibration
from calibration.types import CalibrationResult
from probability_engine.factor_library import FIXED_FACTOR_DICTIONARY
from probability_engine.dependence import FactorLevelDccProvider
from probability_engine.jumps import (
    idiosyncratic_jump_profile,
    regime_adjusted_systemic_jump_dispersion,
    load_jump_state_snapshot,
    systemic_jump_probability,
)
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
    assert result.jump_state.idio_jump_profile_by_product == {}
