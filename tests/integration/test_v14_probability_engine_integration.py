from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from probability_engine.engine import run_probability_engine
from probability_engine.contracts import ProbabilityEngineRunResult
from probability_engine.path_generator import _student_t_scale
from probability_engine.portfolio_policy import (
    PortfolioState,
    RebalancingPolicySpec,
    apply_daily_cashflows_and_rebalance,
)


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"


def _load_v14_formal_daily_input() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


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


class _FixedChiSquareRng:
    def chisquare(self, df: float) -> float:
        return float(df)


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
