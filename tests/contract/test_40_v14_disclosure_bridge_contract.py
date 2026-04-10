from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from probability_engine.contracts import ProbabilityDisclosurePayload, ProbabilityEngineRunResult
from probability_engine.engine import run_probability_engine


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "v14" / "formal_daily_engine_input.json"


def _load_v14_formal_daily_input() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_task4_primary_only_run_emits_minimal_typed_disclosure_payload() -> None:
    result = run_probability_engine(_load_v14_formal_daily_input())

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.output is not None
    assert result.output.challenger_results == []
    assert result.output.stress_results == []
    assert result.output.model_disagreement == {}
    assert isinstance(result.output.probability_disclosure_payload, ProbabilityDisclosurePayload)
    assert result.output.probability_disclosure_payload.widening_method == "task4_primary_only"
    assert result.output.probability_disclosure_payload.disclosure_level in {"point_and_range", "range_only"}
    assert result.output.probability_disclosure_payload.confidence_level in {"high", "medium", "low"}


def test_successful_task4_run_uses_internal_formal_strict_result() -> None:
    sim_input = deepcopy(_load_v14_formal_daily_input())
    for product in sim_input["products"]:
        product["mapping_confidence"] = "high"

    result = run_probability_engine(sim_input)

    assert isinstance(result, ProbabilityEngineRunResult)
    assert result.run_outcome_status == "success"
    assert result.resolved_result_category == "formal_strict_result"
    assert result.output is not None
    assert result.output.probability_disclosure_payload.disclosure_level == "point_and_range"


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
