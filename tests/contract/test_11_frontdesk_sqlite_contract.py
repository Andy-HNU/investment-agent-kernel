from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from snapshot_ingestion.real_source_market import build_real_source_market_snapshot


def _build_profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_andy",
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=[],
    )


def _build_onboarding_result():
    profile = _build_profile()
    bundle = build_user_onboarding_inputs(profile, as_of="2026-03-30T00:00:00Z")
    market_snapshot = build_real_source_market_snapshot(as_of="2026-03-30T00:00:00Z")
    raw_inputs = dict(bundle.raw_inputs)
    raw_inputs["market_raw"] = market_snapshot.market_raw
    raw_inputs["historical_dataset_metadata"] = market_snapshot.historical_dataset_metadata
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "frontdesk_onboarding"},
        raw_inputs=raw_inputs,
    )
    return profile, bundle, result


@pytest.mark.contract
def test_frontdesk_sqlite_initializes_schema_and_persists_onboarding_result(tmp_path):
    from frontdesk.store import FrontdeskStore

    profile, bundle, result = _build_onboarding_result()
    db_path = tmp_path / "frontdesk.sqlite"

    store = FrontdeskStore(db_path)
    store.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type='table'")
        }

    expected_tables = {
        "user_profiles",
        "onboarding_sessions",
        "workflow_runs",
        "decision_cards",
        "execution_plan_records",
        "input_provenance_records",
        "execution_feedback_records",
    }
    assert expected_tables.issubset(tables)

    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=result.to_dict(),
        input_provenance=bundle.input_provenance,
    )
    user_state = store.load_user_state(profile.account_profile_id)

    assert user_state["profile"]["account_profile_id"] == profile.account_profile_id
    assert user_state["profile"]["display_name"] == "Andy"
    assert user_state["latest_result"]["workflow_type"] == "onboarding"
    assert user_state["latest_result"]["status"] in {"completed", "degraded"}
    assert user_state["decision_card"]["card_type"] == "goal_baseline"
    assert user_state["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1
    assert user_state["active_execution_plan"] is None
    assert user_state["pending_execution_plan"]["source_run_id"] == result.run_id
    assert user_state["pending_execution_plan"]["plan_version"] == 1
    assert user_state["pending_execution_plan"]["status"] == "draft"
    assert user_state["pending_execution_plan"]["item_count"] >= 1
    assert user_state["pending_execution_plan"]["quarterly_execution_policy"]["cash_reserve_target"] > 0
    assert (
        user_state["decision_card"]["execution_plan_summary"]["plan_id"]
        == user_state["pending_execution_plan"]["plan_id"]
    )
    assert user_state["execution_feedback"]["source_run_id"] == result.run_id
    assert user_state["execution_feedback"]["recommended_action"] == result.decision_card["recommended_action"]
    assert user_state["execution_feedback"]["feedback_status"] == "pending"
    assert (
        user_state["execution_feedback"]["payload"]["persistence_execution_record"]["plan_id"]
        == user_state["pending_execution_plan"]["plan_id"]
    )


@pytest.mark.contract
def test_frontdesk_active_execution_plan_prefers_latest_approved_unsuperseded_version(tmp_path):
    from frontdesk.store import FrontdeskStore

    profile, bundle, result = _build_onboarding_result()
    db_path = tmp_path / "frontdesk.sqlite"

    store = FrontdeskStore(db_path)
    store.initialize()
    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=result.to_dict(),
        input_provenance=bundle.input_provenance,
    )
    pending_plan = store.get_frontdesk_snapshot(profile.account_profile_id)["pending_execution_plan"]
    assert pending_plan is not None

    approved_payload = {
        **dict(result.execution_plan.to_dict()),
        "status": "approved",
        "plan_version": 2,
        "approved_at": "2026-03-31T00:00:00Z",
    }
    store.save_execution_plan_record(
        account_profile_id=profile.account_profile_id,
        plan_id=str(result.execution_plan.plan_id),
        plan_version=2,
        source_run_id=str(result.execution_plan.source_run_id),
        source_allocation_id=str(result.execution_plan.source_allocation_id),
        status="approved",
        confirmation_required=result.execution_plan.confirmation_required,
        payload=approved_payload,
        created_at="2026-03-31T00:00:00Z",
        updated_at="2026-03-31T00:00:00Z",
    )

    user_state = store.load_user_state(profile.account_profile_id)

    assert user_state["active_execution_plan"]["plan_id"] == result.execution_plan.plan_id
    assert user_state["active_execution_plan"]["plan_version"] == 2
    assert user_state["active_execution_plan"]["status"] == "approved"
    assert user_state["active_execution_plan"]["approved_at"] == "2026-03-31T00:00:00Z"
    assert user_state["pending_execution_plan"] is None


@pytest.mark.contract
def test_frontdesk_persisted_summary_exposes_input_source_labels(tmp_path):
    from frontdesk.store import FrontdeskStore

    profile, bundle, result = _build_onboarding_result()
    db_path = tmp_path / "frontdesk.sqlite"

    store = FrontdeskStore(db_path)
    store.initialize()
    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=result.to_dict(),
        input_provenance=bundle.input_provenance,
    )

    user_state = store.load_user_state(profile.account_profile_id)
    serialized = json.dumps(user_state, ensure_ascii=False, sort_keys=True)

    for label in ("用户提供", "系统推断", "默认假设", "外部抓取"):
        assert label in serialized
