from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from probability_engine.contracts import (
    MarketPressureSnapshot,
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
    ScenarioComparisonResult,
)
from probability_engine.disclosure_bridge import DisclosureEvidenceSpec, assemble_probability_run_result
from probability_engine.engine import run_probability_engine


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"
_CONTRACT_PATH_COUNT = 32
_MIN_LIVE_HISTORY_DAYS = 40
_MIN_STRICT_HISTORY_DAYS = 126


def _load_v14_formal_daily_input(*, minimum_history_days: int = _MIN_LIVE_HISTORY_DAYS) -> dict[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    recipes = list(payload.get("recipes") or [])
    if recipes:
        recipes[0] = {**dict(recipes[0]), "path_count": _CONTRACT_PATH_COUNT}
        payload["recipes"] = recipes
    labels = list(payload.get("observed_regime_labels") or [])
    target_days = max(minimum_history_days, int(payload.get("path_horizon_days") or 0))
    if labels and len(labels) < target_days:
        repeats = (target_days + len(labels) - 1) // len(labels)
        extended_labels = (labels * repeats)[:target_days]
        payload["observed_regime_labels"] = extended_labels
        for product in list(payload.get("products") or []):
            returns = list(product.get("observed_daily_returns") or [])
            if returns:
                product["observed_daily_returns"] = (returns * repeats)[:target_days]
    return payload


def test_task4_primary_only_run_emits_minimal_typed_disclosure_payload() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.challenger_results
    assert result.output.stress_results
    assert result.output.model_disagreement["best_challenger_probability"] is not None
    assert result.output.model_disagreement["stress_probability"] is not None
    assert result.output.model_disagreement["gap_total"] > 0.0
    assert result.output.model_disagreement["widening_method"] == "wilson_plus_gap_total"
    assert isinstance(result.output.probability_disclosure_payload, ProbabilityDisclosurePayload)
    assert result.output.probability_disclosure_payload.widening_method == "wilson_plus_gap_total"
    assert result.output.probability_disclosure_payload.gap_total is not None
    assert result.output.probability_disclosure_payload.gap_total > 0.0
    assert result.output.probability_disclosure_payload.disclosure_level in {"point_and_range", "range_only"}
    assert result.output.probability_disclosure_payload.confidence_level in {"high", "medium", "low"}


def test_successful_task4_run_uses_internal_formal_strict_result() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input(minimum_history_days=_MIN_STRICT_HISTORY_DAYS))
    for product in sim_input["products"]:
        product["mapping_confidence"] = "high"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "success"
    assert result.resolved_result_category == "formal_strict_result"
    assert result.output is not None
    assert result.output.probability_disclosure_payload.disclosure_level == "point_and_range"


def test_low_mapping_confidence_task4_run_does_not_emit_formal_strict_result() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input(minimum_history_days=_MIN_STRICT_HISTORY_DAYS))
    for product in sim_input["products"]:
        product["mapping_confidence"] = "low"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "degraded"
    assert result.resolved_result_category == "formal_estimated_result"
    assert result.output is not None
    assert result.output.probability_disclosure_payload.confidence_level != "high"
    assert result.output.probability_disclosure_payload.disclosure_level == "range_only"


def test_missing_trading_calendar_blocks_formal_task4_output() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input.pop("trading_calendar")

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "trading_calendar" in result.failure_artifact.message


def test_short_trading_calendar_blocks_formal_task4_output() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["trading_calendar"] = sim_input["trading_calendar"][:-1]

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "trading_calendar" in result.failure_artifact.message


def test_invalid_task4_formal_scope_does_not_publish_disclosure_payload() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    sim_input["success_event_spec"]["horizon_days"] = sim_input["path_horizon_days"] + 1

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "failure"
    assert result.resolved_result_category == "null"
    assert result.output is None
    assert result.failure_artifact is not None
    assert "success_event_spec" in result.failure_artifact.message


def test_disclosure_bridge_preserves_current_market_pressure() -> None:
    primary = RecipeSimulationResult(
        recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
        role="primary",
        success_probability=0.62,
        success_probability_range=(0.56, 0.67),
        cagr_range=(0.03, 0.08),
        drawdown_range=(0.02, 0.10),
        sample_count=64,
        path_stats=PathStatsSummary(
            terminal_value_mean=118000.0,
            terminal_value_p05=109000.0,
            terminal_value_p50=117500.0,
            terminal_value_p95=125000.0,
            cagr_p05=0.02,
            cagr_p50=0.05,
            cagr_p95=0.08,
            max_drawdown_p05=0.01,
            max_drawdown_p50=0.05,
            max_drawdown_p95=0.10,
            success_count=40,
            path_count=64,
        ),
        calibration_link_ref="primary-calibration",
    )
    pressure = MarketPressureSnapshot(
        scenario_kind="current_market",
        market_pressure_score=42.0,
        market_pressure_level="L1_中性偏紧",
        current_regime="risk_off",
        regime_component=55.0,
        drift_haircut_component=20.0,
        volatility_component=37.5,
        jump_probability_component=18.0,
        tail_severity_component=10.0,
        effective_daily_drift=0.00021,
        volatility_multiplier=1.15,
        systemic_jump_probability_multiplier=1.30,
        idio_jump_probability_multiplier=1.15,
        systemic_jump_dispersion_multiplier=1.05,
    )
    scenario = ScenarioComparisonResult(
        scenario_kind="current_market",
        label="当前市场延续",
        pressure=pressure,
        recipe_result=primary,
    )

    assembled = assemble_probability_run_result(
        primary=primary,
        challengers=[],
        stresses=[],
        evidence=DisclosureEvidenceSpec(
            daily_product_path_available=True,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=1.0,
            observed_weight_adjusted_coverage=1.0,
            estimated_weight_adjusted_coverage=0.0,
            factor_mapping_confidence="high",
            distribution_readiness="ready",
            calibration_quality="strong",
            challenger_available=False,
            stress_available=False,
            execution_policy="FORMAL_STRICT",
        ),
        current_market_pressure=pressure,
        scenario_comparison=[scenario],
    )

    assert assembled.output is not None
    assert assembled.output.current_market_pressure is not None
    assert assembled.output.current_market_pressure.market_pressure_level == "L1_中性偏紧"
    assert [item.scenario_kind for item in assembled.output.scenario_comparison] == ["current_market"]
