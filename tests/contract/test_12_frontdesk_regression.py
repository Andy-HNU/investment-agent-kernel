from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile

import pytest

from frontdesk.service import (
    approve_frontdesk_execution_plan,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from frontdesk.storage import FrontdeskStore
from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


def _profile(*, account_profile_id: str = "frontdesk_andy") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=12_000.0,
        goal_amount=1_000_000.0,
        goal_horizon_months=60,
        risk_preference="中等",
        max_drawdown_tolerance=0.10,
        current_holdings="portfolio",
        restrictions=[],
        current_weights={
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
    )


def _result_payload(profile: UserOnboardingProfile, *, as_of: str = "2026-03-30T00:00:00Z") -> tuple[dict, dict]:
    bundle = build_user_onboarding_inputs(profile, as_of=as_of)
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": f"{profile.account_profile_id}_{as_of}"},
        raw_inputs=bundle.raw_inputs,
    )
    return result.to_dict(), bundle.input_provenance


@pytest.mark.contract
def test_frontdesk_repeated_onboarding_and_monthly_keep_history(tmp_path):
    profile = _profile(account_profile_id="history_user")
    db_path = tmp_path / "frontdesk.sqlite"

    first_onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    second_onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    first_monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
    )
    second_monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
    )

    store = FrontdeskStore(db_path)
    with store.connect() as conn:
        counts = {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("workflow_runs", "frontdesk_baselines", "decision_cards", "onboarding_sessions")
        }
        run_ids = [
            row[0]
            for row in conn.execute(
                "select run_id from workflow_runs where account_profile_id = ? order by id",
                (profile.account_profile_id,),
            ).fetchall()
        ]

    assert first_onboarding["status"] == "completed"
    assert second_onboarding["status"] == "completed"
    assert first_monthly["status"] == "completed"
    assert second_monthly["status"] == "completed"
    assert counts["workflow_runs"] == 4
    assert counts["onboarding_sessions"] == 2
    assert counts["decision_cards"] == 4
    assert len(run_ids) == 4
    assert len(set(run_ids)) == 4


@pytest.mark.parametrize(
    ("status", "expected_baseline_count"),
    [
        ("blocked", 0),
        ("degraded", 1),
    ],
)
@pytest.mark.contract
def test_frontdesk_blocked_or_partial_onboarding_baseline_gate(tmp_path, status, expected_baseline_count):
    profile = _profile(account_profile_id=f"{status}_user")
    db_path = tmp_path / f"{status}.sqlite"
    store = FrontdeskStore(db_path)
    store.initialize()

    result_payload, input_provenance = _result_payload(profile)
    result_payload["status"] = status
    result_payload["decision_card"]["status_badge"] = status
    result_payload["decision_card"]["summary"] = f"{status} onboarding"
    if status == "blocked":
        result_payload["decision_card"]["card_type"] = "blocked"

    store.save_onboarding_result(
        account_profile=profile.to_dict(),
        onboarding_result=result_payload,
        input_provenance=input_provenance,
    )

    with store.connect() as conn:
        baseline_count = conn.execute(
            "select count(*) from frontdesk_baselines where account_profile_id = ?",
            (profile.account_profile_id,),
        ).fetchone()[0]

    assert baseline_count == expected_baseline_count
    if expected_baseline_count == 0:
        assert store.get_latest_baseline(profile.account_profile_id) is None
    else:
        assert store.get_latest_baseline(profile.account_profile_id) is not None


@pytest.mark.contract
def test_frontdesk_followup_persists_decision_card_and_provenance(tmp_path):
    profile = _profile(account_profile_id="followup_user")
    db_path = tmp_path / "frontdesk.sqlite"

    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    followup_summary = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
    )

    store = FrontdeskStore(db_path)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    assert snapshot is not None
    latest_run = snapshot["latest_run"]
    latest_decision_card = latest_run["decision_card"]
    serialized = json.dumps(latest_decision_card, ensure_ascii=False, sort_keys=True)

    assert onboarding_summary["status"] == "completed"
    assert followup_summary["status"] == "completed"
    assert latest_run["workflow_type"] == "monthly"
    assert latest_decision_card["card_type"] == "runtime_action"
    assert latest_decision_card["input_provenance"]["counts"]["user_provided"] == 0
    assert latest_decision_card["input_provenance"]["counts"]["system_inferred"] >= 1
    for label in ("用户提供", "系统推断", "默认假设"):
        assert label in serialized


@pytest.mark.contract
def test_frontdesk_execution_feedback_roundtrip_updates_snapshot(tmp_path):
    profile = _profile(account_profile_id="feedback_user")
    db_path = tmp_path / "frontdesk.sqlite"

    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    source_run_id = onboarding_summary["run_id"]

    store = FrontdeskStore(db_path)
    updated = store.record_execution_feedback(
        account_profile_id=profile.account_profile_id,
        source_run_id=source_run_id,
        user_executed=True,
        actual_action="rebalance_partial",
        executed_at="2026-03-31T08:00:00Z",
        note="执行了部分调仓",
        recorded_at="2026-03-31T08:30:00Z",
    )
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    user_state = store.load_user_state(profile.account_profile_id)

    assert updated.feedback_status == "executed"
    assert snapshot["execution_feedback"]["source_run_id"] == source_run_id
    assert snapshot["execution_feedback"]["actual_action"] == "rebalance_partial"
    assert snapshot["execution_feedback_summary"]["counts"]["executed"] == 1
    assert user_state["execution_feedback"]["note"] == "执行了部分调仓"


@pytest.mark.contract
def test_frontdesk_execution_feedback_requires_seeded_run(tmp_path):
    profile = _profile(account_profile_id="feedback_missing_seed")
    db_path = tmp_path / "frontdesk.sqlite"

    run_frontdesk_onboarding(profile, db_path=db_path)
    store = FrontdeskStore(db_path)

    with pytest.raises(ValueError, match="no execution feedback seed"):
        store.record_execution_feedback(
            account_profile_id=profile.account_profile_id,
            source_run_id="missing_run_id",
            user_executed=False,
            note="未执行",
            recorded_at="2026-03-31T09:00:00Z",
        )


@pytest.mark.contract
def test_frontdesk_approve_execution_plan_promotes_pending_and_supersedes_previous_active(tmp_path):
    profile = _profile(account_profile_id="approve_plan_user")
    db_path = tmp_path / "frontdesk.sqlite"

    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] == "completed"

    store = FrontdeskStore(db_path)
    first_pending = store.get_frontdesk_snapshot(profile.account_profile_id)["pending_execution_plan"]
    assert first_pending is not None

    approval_summary = approve_frontdesk_execution_plan(
        account_profile_id=profile.account_profile_id,
        plan_id=first_pending["plan_id"],
        plan_version=int(first_pending["plan_version"]),
        approved_at="2026-03-31T00:00:00Z",
        db_path=db_path,
    )

    assert approval_summary["status"] == "approved"
    assert approval_summary["approved_execution_plan"]["plan_id"] == first_pending["plan_id"]
    assert approval_summary["approved_execution_plan"]["status"] == "approved"
    assert approval_summary["user_state"]["active_execution_plan"]["plan_id"] == first_pending["plan_id"]
    assert approval_summary["user_state"]["pending_execution_plan"] is None

    second_onboarding = run_frontdesk_onboarding(profile, db_path=db_path)
    assert second_onboarding["status"] == "completed"
    next_pending = second_onboarding["user_state"]["pending_execution_plan"]
    assert next_pending is not None
    assert next_pending["plan_id"] != first_pending["plan_id"]

    second_approval = approve_frontdesk_execution_plan(
        account_profile_id=profile.account_profile_id,
        plan_id=next_pending["plan_id"],
        plan_version=int(next_pending["plan_version"]),
        approved_at="2026-04-01T00:00:00Z",
        db_path=db_path,
    )

    first_record = store.get_execution_plan_record(
        profile.account_profile_id,
        plan_id=first_pending["plan_id"],
        plan_version=int(first_pending["plan_version"]),
    )
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)

    assert second_approval["approved_execution_plan"]["plan_id"] == next_pending["plan_id"]
    assert second_approval["approved_execution_plan"]["status"] == "approved"
    assert first_record is not None
    assert first_record.status == "superseded"
    assert first_record.superseded_by_plan_id == next_pending["plan_id"]
    assert snapshot["active_execution_plan"]["plan_id"] == next_pending["plan_id"]
    assert snapshot["pending_execution_plan"] is None


@pytest.mark.contract
def test_frontdesk_monthly_rejects_goal_profile_updates(tmp_path):
    profile = _profile(account_profile_id="goal_change_user")
    db_path = tmp_path / "frontdesk.sqlite"

    run_frontdesk_onboarding(profile, db_path=db_path)

    updated_profile = profile.to_dict()
    updated_profile["goal_amount"] = 1_200_000.0

    with pytest.raises(ValueError, match="use quarterly or onboarding"):
        run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
            profile=updated_profile,
        )
