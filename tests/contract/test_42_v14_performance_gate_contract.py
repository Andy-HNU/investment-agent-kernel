from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

import pytest

from probability_engine.contracts import (
    PathStatsSummary,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    RecipeSimulationResult,
)
import probability_engine.engine as probability_engine_engine
from probability_engine.engine import run_probability_engine


FORMAL_INPUT_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"

def _load_formal_daily_input() -> dict[str, object]:
    return json.loads(FORMAL_INPUT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_benchmark_input() -> dict[str, object]:
    payload = _load_formal_daily_input()
    anchor = date.fromisoformat(str(payload["as_of"]))
    trading_calendar: list[str] = []
    current = anchor
    while len(trading_calendar) < 756:
        current += timedelta(days=1)
        if current.weekday() < 5:
            trading_calendar.append(current.isoformat())
    payload["trading_calendar"] = trading_calendar
    payload["path_horizon_days"] = 756
    payload["success_event_spec"]["horizon_days"] = 756
    payload["success_event_spec"]["horizon_months"] = 36
    payload["recipes"][0]["path_count"] = 32
    return payload


def _primary_result() -> RecipeSimulationResult:
    return RecipeSimulationResult(
        recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
        role="primary",
        success_probability=0.68,
        success_probability_range=(0.64, 0.72),
        cagr_range=(0.04, 0.09),
        drawdown_range=(0.06, 0.13),
        sample_count=64,
        path_stats=PathStatsSummary(
            terminal_value_mean=124_000.0,
            terminal_value_p05=109_000.0,
            terminal_value_p50=123_000.0,
            terminal_value_p95=141_000.0,
            cagr_p05=0.03,
            cagr_p50=0.06,
            cagr_p95=0.08,
            max_drawdown_p05=0.05,
            max_drawdown_p50=0.09,
            max_drawdown_p95=0.13,
            success_count=44,
            path_count=64,
        ),
        calibration_link_ref="evidence://contract/v14/performance",
    )


def test_v14_formal_baseline_stays_daily_and_exposes_gap_total_within_gate() -> None:
    sim_input = _load_benchmark_input()

    started = perf_counter()
    result = run_probability_engine(sim_input)
    elapsed_ms = (perf_counter() - started) * 1000.0

    assert sim_input["path_horizon_days"] == 756
    assert elapsed_ms < 20_000.0
    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert isinstance(result.output, ProbabilityEngineOutput)
    assert result.output.primary_result.path_stats.path_count == 32
    assert result.output.probability_disclosure_payload is not None
    assert isinstance(result.output.probability_disclosure_payload, ProbabilityDisclosurePayload)
    assert result.output.probability_disclosure_payload.gap_total is not None
    assert result.output.probability_disclosure_payload.gap_total >= 0.0
    assert result.output.probability_disclosure_payload.gap_total == pytest.approx(
        result.output.model_disagreement["gap_total"]
    )
    assert result.output.probability_disclosure_payload.widening_method == "wilson_plus_gap_total"
    assert result.output.probability_disclosure_payload.disclosure_level in {"point_and_range", "range_only"}
    assert result.output.probability_disclosure_payload.confidence_level in {"high", "medium", "low"}
    assert result.run_outcome_status in {"success", "degraded"}
    assert result.resolved_result_category in {
        "formal_strict_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }


def test_live_primary_engine_payload_exposes_non_null_gap_total(monkeypatch) -> None:
    monkeypatch.setattr(
        probability_engine_engine,
        "simulate_primary_paths",
        lambda runtime_input, selected_recipe: _primary_result(),
    )

    result = run_probability_engine(_load_formal_daily_input())

    assert result.output is not None
    payload = result.output.probability_disclosure_payload
    assert payload.gap_total is not None
    assert payload.gap_total >= 0.0
