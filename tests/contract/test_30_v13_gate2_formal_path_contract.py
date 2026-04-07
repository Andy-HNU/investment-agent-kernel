from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus
from product_mapping.engine import build_candidate_product_context
from product_mapping.runtime_inputs import build_runtime_product_universe_context
from product_mapping.types import ProductCandidate


def _historical_dataset() -> dict[str, object]:
    return {
        "dataset_id": "market_history",
        "version_id": "tinyshare:2026-04-01:2026-04-03",
        "frequency": "daily",
        "as_of": "2026-04-03",
        "source_name": "tinyshare",
        "source_ref": "tinyshare://market_history?symbols=equity_cn:510300.SH",
        "lookback_months": 24,
        "return_series": {
            "equity_cn": [0.01, -0.02, 0.03],
            "bond_cn": [0.002, -0.001, 0.001],
            "gold": [0.005, 0.002, -0.001],
            "satellite": [0.03, -0.04, 0.02],
        },
        "coverage_status": "verified",
        "cached_at": "2026-04-05T08:00:00Z",
        "notes": [],
        "audit_window": {
            "start_date": "2026-04-01",
            "end_date": "2026-04-03",
            "trading_days": 3,
            "observed_days": 3,
            "inferred_days": 0,
        },
    }


def _runtime_pool() -> list[ProductCandidate]:
    return [
        ProductCandidate(
            product_id="ts_equity_core",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="510300.SH",
            tags=["core"],
        ),
        ProductCandidate(
            product_id="ts_bond_core",
            product_name="国债ETF",
            asset_bucket="bond_cn",
            product_family="defense",
            wrapper_type="etf",
            provider_source="tinyshare_runtime_catalog",
            provider_symbol="511010.SH",
            tags=["bond", "defense"],
        ),
    ]


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": [],
        },
        "goal": goal_solver_input_base["goal"],
        "cashflow_plan": goal_solver_input_base["cashflow_plan"],
        "constraints": goal_solver_input_base["constraints"],
        "universe": {
            "buckets": ["equity_cn", "bond_cn", "gold", "satellite"],
            "bucket_category": {
                "equity_cn": "core",
                "bond_cn": "defense",
                "gold": "defense",
                "satellite": "satellite",
            },
            "bucket_to_theme": {
                "equity_cn": None,
                "bond_cn": None,
                "gold": None,
                "satellite": "technology",
            },
            "liquidity_buckets": ["bond_cn"],
            "bucket_order": ["equity_cn", "bond_cn", "gold", "satellite"],
        },
    }


@pytest.mark.contract
def test_build_runtime_product_universe_context_blocks_strict_formal_mode_without_observed_source():
    inputs, result = build_runtime_product_universe_context(
        market_raw={"historical_dataset": _historical_dataset()},
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/v13_gate2_contract"),
        formal_path_required=True,
    )

    assert result is None
    assert inputs["formal_path_required"] is True
    assert inputs["formal_path_status"] == "blocked"
    assert inputs["failure_artifact"]["request_identity"]["component"] == "runtime_product_universe_probe"
    assert inputs["failure_artifact"]["requested_result_category"] == "formal_independent_result"
    assert inputs["failure_artifact"]["execution_policy"] == "formal_estimation_allowed"
    assert inputs["failure_artifact"]["failed_stage"] == "input_eligibility"
    assert inputs["failure_artifact"]["blocking_predicates"] == ["observed_runtime_source_unavailable"]
    assert inputs["failure_artifact"]["missing_evidence_refs"]["product_universe"] == "observed_runtime_product_universe"


@pytest.mark.contract
def test_build_candidate_product_context_marks_estimated_path_when_strict_product_coverage_is_incomplete(monkeypatch):
    runtime_pool = _runtime_pool()

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin):  # type: ignore[no-untyped-def]
        rows_by_symbol = {
            "510300.SH": [
                {"date": "2026-04-01", "close": 1.0},
                {"date": "2026-04-02", "close": 1.05},
                {"date": "2026-04-03", "close": 1.07},
            ],
        }
        if spec.symbol not in rows_by_symbol:
            raise RuntimeError("tinyshare_empty_dataset")
        return rows_by_symbol[spec.symbol], pin

    monkeypatch.setattr("product_mapping.engine.fetch_timeseries", _fake_fetch_timeseries)

    context = build_candidate_product_context(
        source_allocation_id="strict_formal_context",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.40},
        restrictions=[],
        runtime_candidates=runtime_pool,
        historical_dataset=_historical_dataset(),
        formal_path_required=True,
        execution_policy="formal_estimation_allowed",
    )

    assert context["product_probability_method"] == "product_estimated_path"
    assert context["formal_path_preflight"]["run_outcome_status"] == "degraded"
    assert context["formal_path_preflight"]["degradation_reasons"] == [
        "product_independent_coverage_incomplete"
    ]
    assert context["failure_artifact"]["failed_stage"] == "evidence_completeness"
    assert context["failure_artifact"]["blocking_predicates"] == [
        "product_independent_coverage_incomplete"
    ]


@pytest.mark.contract
def test_build_candidate_product_context_blocks_strict_execution_when_product_coverage_is_incomplete(monkeypatch):
    runtime_pool = _runtime_pool()

    def _fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin):  # type: ignore[no-untyped-def]
        rows_by_symbol = {
            "510300.SH": [
                {"date": "2026-04-01", "close": 1.0},
                {"date": "2026-04-02", "close": 1.05},
                {"date": "2026-04-03", "close": 1.07},
            ],
        }
        if spec.symbol not in rows_by_symbol:
            raise RuntimeError("tinyshare_empty_dataset")
        return rows_by_symbol[spec.symbol], pin

    monkeypatch.setattr("product_mapping.engine.fetch_timeseries", _fake_fetch_timeseries)

    context = build_candidate_product_context(
        source_allocation_id="strict_only_context",
        bucket_targets={"equity_cn": 0.60, "bond_cn": 0.40},
        restrictions=[],
        runtime_candidates=runtime_pool,
        historical_dataset=_historical_dataset(),
        formal_path_required=True,
        execution_policy="formal_strict",
    )

    assert context["product_probability_method"] == "product_estimated_path"
    assert context["formal_path_preflight"]["run_outcome_status"] == "blocked"
    assert context["formal_path_preflight"]["blocking_predicates"] == [
        "product_independent_coverage_incomplete"
    ]
    assert context["failure_artifact"]["execution_policy"] == "formal_strict"
    assert context["failure_artifact"]["failed_stage"] == "evidence_completeness"
    assert context["failure_artifact"]["blocking_predicates"] == [
        "product_independent_coverage_incomplete"
    ]


@pytest.mark.contract
def test_run_orchestrator_blocks_strict_formal_path_without_observed_runtime_inputs(
    goal_solver_input_base,
    calibration_result_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "run_onboarding_v13_gate2_blocked"},
        raw_inputs={
            "bundle_id": "bundle_acc001_20260329T120000Z",
            "snapshot_bundle": {"bundle_id": "bundle_acc001_20260329T120000Z"},
            "calibration_result": calibration_result_base,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
            "formal_path_required": True,
        },
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.goal_solver_output is None
    assert result.execution_plan is None
    assert result.run_outcome_status == "blocked"
    assert result.resolved_result_category is None
    assert any("candidate_product_context" in reason for reason in result.blocking_reasons)
    assert result.evidence_bundle["run_outcome_status"] == "blocked"
    assert result.evidence_bundle["execution_policy"] == "formal_estimation_allowed"
    assert result.evidence_bundle["failed_stage"] == "input_eligibility"
    assert result.disclosure_decision["disclosure_level"] == "unavailable"
