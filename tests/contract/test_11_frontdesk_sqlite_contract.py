from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


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
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "frontdesk_onboarding"},
        raw_inputs=bundle.raw_inputs,
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
    assert user_state["latest_result"]["status"] == "completed"
    assert user_state["decision_card"]["card_type"] == "goal_baseline"
    assert user_state["decision_card"]["input_provenance"]["counts"]["user_provided"] >= 1
    assert user_state["execution_feedback"]["source_run_id"] == result.run_id
    assert user_state["execution_feedback"]["recommended_action"] == result.decision_card["recommended_action"]
    assert user_state["execution_feedback"]["feedback_status"] == "pending"


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
