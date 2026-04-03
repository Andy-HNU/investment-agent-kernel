from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest
from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin

from tests.fixtures.factories import (
    make_action,
    make_behavior_state,
    make_calibration_result,
    make_constraint_state,
    make_ev_params,
    make_goal_solver_input,
    make_goal_solver_output,
    make_live_portfolio_snapshot,
    make_market_assumptions,
    make_market_state,
    make_runtime_optimizer_params,
)


@pytest.fixture
def seed() -> int:
    return 42


@pytest.fixture
def tolerance() -> float:
    return 1e-6


@pytest.fixture
def market_state_base():
    return make_market_state()


@pytest.fixture
def constraint_state_base():
    return make_constraint_state()


@pytest.fixture
def behavior_state_base():
    return make_behavior_state()


@pytest.fixture
def ev_params_base():
    return make_ev_params()


@pytest.fixture
def runtime_optimizer_params_base():
    return make_runtime_optimizer_params()


@pytest.fixture
def goal_solver_input_base():
    return make_goal_solver_input()


@pytest.fixture
def goal_solver_output_base(goal_solver_input_base):
    return make_goal_solver_output(goal_solver_input_base)


@pytest.fixture
def live_portfolio_base():
    return make_live_portfolio_snapshot()


@pytest.fixture
def calibration_result_base():
    return make_calibration_result()


@pytest.fixture
def candidate_actions_base():
    return [
        make_action("freeze"),
        make_action("observe"),
    ]


@pytest.fixture(scope="session", autouse=True)
def real_source_market_cache(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("real_source_market_cache")
    fixture_dir = ROOT / "tests" / "fixtures" / "real_source"
    cache = DatasetCache(base_dir=cache_dir)
    for fixture_path in sorted(fixture_dir.glob("*.json")):
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        if not {"provider", "dataset_id", "symbol", "version_id", "source_ref", "rows"}.issubset(payload):
            continue
        spec = DatasetSpec(
            kind="timeseries",
            dataset_id=str(payload["dataset_id"]),
            provider=str(payload["provider"]),
            symbol=str(payload["symbol"]),
        )
        pin = VersionPin(version_id=str(payload["version_id"]), source_ref=str(payload["source_ref"]))
        cache.write(spec, pin, list(payload["rows"]))
    previous = os.environ.get("INVESTMENT_MARKET_HISTORY_CACHE_DIR")
    os.environ["INVESTMENT_MARKET_HISTORY_CACHE_DIR"] = str(cache_dir)
    try:
        yield cache_dir
    finally:
        if previous is None:
            os.environ.pop("INVESTMENT_MARKET_HISTORY_CACHE_DIR", None)
        else:
            os.environ["INVESTMENT_MARKET_HISTORY_CACHE_DIR"] = previous
