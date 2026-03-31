from __future__ import annotations

import pytest

from tests.helpers.contracts import assert_run_ev_engine_signature

pytest.importorskip("runtime_optimizer.ev_engine.engine")
from runtime_optimizer.ev_engine.engine import run_ev_engine


@pytest.mark.contract
def test_run_ev_engine_signature_is_frozen():
    assert_run_ev_engine_signature(run_ev_engine)
