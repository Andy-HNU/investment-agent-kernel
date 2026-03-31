from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calibration.engine import run_calibration
from orchestrator.engine import run_orchestrator
from orchestrator.types import WorkflowStatus, WorkflowType
from snapshot_ingestion.engine import build_snapshot_bundle


def _allocation_input(goal_solver_input_base: dict) -> dict:
    return {
        "account_profile": {
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "risk_preference": goal_solver_input_base["goal"]["risk_preference"],
            "complexity_tolerance": "medium",
            "preferred_themes": ["technology"],
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


def _market_raw(goal_solver_input_base: dict) -> dict:
    assumptions = goal_solver_input_base["solver_params"]["market_assumptions"]
    return {
        "raw_volatility": {
            "equity_cn": 0.18,
            "bond_cn": 0.04,
            "gold": 0.12,
            "satellite": 0.22,
        },
        "liquidity_scores": {
            "equity_cn": 0.9,
            "bond_cn": 0.95,
            "gold": 0.85,
            "satellite": 0.6,
        },
        "valuation_z_scores": {
            "equity_cn": 0.2,
            "bond_cn": 0.1,
            "gold": -0.3,
            "satellite": 1.8,
        },
        "expected_returns": assumptions["expected_returns"],
    }


def _account_raw(goal_solver_input_base: dict, live_portfolio_base: dict) -> dict:
    return {
        "weights": live_portfolio_base["weights"],
        "total_value": live_portfolio_base["total_value"],
        "available_cash": live_portfolio_base["available_cash"],
        "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
    }


def _goal_raw(goal_solver_input_base: dict) -> dict:
    return dict(goal_solver_input_base["goal"])


def _constraint_raw(goal_solver_input_base: dict) -> dict:
    constraints = dict(goal_solver_input_base["constraints"])
    constraints.update(
        {
            "rebalancing_band": 0.10,
            "forbidden_actions": [],
            "cooling_period_days": 3,
            "soft_preferences": {},
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
            "transaction_fee_rate": {"equity_cn": 0.003, "bond_cn": 0.001},
        }
    )
    return constraints


@pytest.mark.smoke
def test_snapshot_to_calibration_to_orchestrator_onboarding_smoke(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )
    calibration = run_calibration(bundle, prior_calibration=None)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_raw_to_card"},
        raw_inputs={
            "bundle_id": bundle.bundle_id,
            "snapshot_bundle": bundle.to_dict(),
            "calibration_result": calibration,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert result.workflow_type == WorkflowType.ONBOARDING
    assert result.status == WorkflowStatus.COMPLETED
    assert result.decision_card is not None
    assert result.bundle_id == bundle.bundle_id
    assert result.calibration_id == calibration.calibration_id
    assert result.decision_card["trace_refs"]["bundle_id"] == bundle.bundle_id
    assert result.decision_card["trace_refs"]["calibration_id"] == calibration.calibration_id


@pytest.mark.smoke
def test_raw_snapshots_to_orchestrator_onboarding_smoke_without_prebuilt_03_05_artifacts(
    goal_solver_input_base,
    live_portfolio_base,
):
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_raw_direct"},
        raw_inputs={
            "account_profile_id": goal_solver_input_base["account_profile_id"],
            "as_of": "2026-03-29T12:00:00Z",
            "market_raw": _market_raw(goal_solver_input_base),
            "account_raw": _account_raw(goal_solver_input_base, live_portfolio_base),
            "goal_raw": _goal_raw(goal_solver_input_base),
            "constraint_raw": _constraint_raw(goal_solver_input_base),
            "behavior_raw": {
                "recent_chase_risk": "low",
                "recent_panic_risk": "none",
                "trade_frequency_30d": 1.0,
                "override_count_90d": 0,
                "cooldown_active": False,
                "cooldown_until": None,
                "behavior_penalty_coeff": 0.0,
            },
            "remaining_horizon_months": goal_solver_input_base["goal"]["horizon_months"],
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert result.workflow_type == WorkflowType.ONBOARDING
    assert result.status == WorkflowStatus.COMPLETED
    assert result.snapshot_bundle is not None
    assert result.calibration_result is not None
    assert result.bundle_id == "acc001_20260329T120000Z"
    assert result.calibration_id == "acc001_20260329T120000Z"
    assert result.decision_card is not None
    assert result.audit_record is not None
    assert result.audit_record.artifact_refs["snapshot_bundle_origin"] == "generated"
    assert result.audit_record.artifact_refs["calibration_origin"] == "generated"
    assert result.audit_record.version_refs["bundle_id"] == "acc001_20260329T120000Z"
    assert result.audit_record.version_refs["calibration_id"] == "acc001_20260329T120000Z"
    assert result.decision_card["trace_refs"]["run_id"] == "smoke_raw_direct"
    assert result.decision_card["trace_refs"]["bundle_id"] == "acc001_20260329T120000Z"
    assert result.decision_card["trace_refs"]["calibration_id"] == "acc001_20260329T120000Z"


@pytest.mark.smoke
def test_partial_calibration_from_real_05_stays_degraded_but_not_blocked(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc),
        market_raw=_market_raw(goal_solver_input_base),
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=None,
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )
    calibration = run_calibration(bundle, prior_calibration=calibration_result_base)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_partial_real_05"},
        raw_inputs={
            "bundle_id": bundle.bundle_id,
            "snapshot_bundle": bundle.to_dict(),
            "calibration_result": calibration,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert calibration.calibration_quality == "partial"
    assert result.status == WorkflowStatus.DEGRADED
    assert result.decision_card is not None
    assert "calibration_quality=partial" in result.degraded_notes
    assert "calibration_quality=partial" in result.decision_card["guardrails"]
    assert result.decision_card["status_badge"] == "degraded"


@pytest.mark.smoke
def test_degraded_calibration_from_real_05_blocks_orchestrator(
    goal_solver_input_base,
    live_portfolio_base,
    calibration_result_base,
):
    market_raw = _market_raw(goal_solver_input_base)
    market_raw.pop("raw_volatility")
    bundle = build_snapshot_bundle(
        account_profile_id=goal_solver_input_base["account_profile_id"],
        as_of=datetime(2026, 3, 29, 14, 0, tzinfo=timezone.utc),
        market_raw=market_raw,
        account_raw=_account_raw(goal_solver_input_base, live_portfolio_base),
        goal_raw=_goal_raw(goal_solver_input_base),
        constraint_raw=_constraint_raw(goal_solver_input_base),
        behavior_raw=calibration_result_base["behavior_state"],
        remaining_horizon_months=goal_solver_input_base["goal"]["horizon_months"],
    )
    calibration = run_calibration(bundle, prior_calibration=calibration_result_base)

    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "smoke_degraded_real_05"},
        raw_inputs={
            "bundle_id": bundle.bundle_id,
            "snapshot_bundle": bundle.to_dict(),
            "calibration_result": calibration,
            "allocation_engine_input": _allocation_input(goal_solver_input_base),
            "goal_solver_input": goal_solver_input_base,
        },
    )

    assert calibration.calibration_quality == "degraded"
    assert result.status == WorkflowStatus.BLOCKED
    assert result.decision_card is not None
    assert "calibration_quality=degraded" in result.blocking_reasons
    assert "calibration_quality=degraded" in result.decision_card["guardrails"]
    assert result.decision_card["status_badge"] == "blocked"
