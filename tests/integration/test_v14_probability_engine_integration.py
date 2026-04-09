from __future__ import annotations

import json
from pathlib import Path

from probability_engine.engine import run_probability_engine
from probability_engine.contracts import ProbabilityEngineRunResult


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
