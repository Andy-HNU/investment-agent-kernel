from __future__ import annotations

import json
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
