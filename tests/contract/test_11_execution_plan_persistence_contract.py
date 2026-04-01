from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.engine import run_orchestrator
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs


def _build_profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="frontdesk_plan_contract",
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
        trigger={"workflow_type": "onboarding", "run_id": "frontdesk_plan_persistence"},
        raw_inputs=bundle.raw_inputs,
    )
    return profile, bundle, result


@pytest.mark.contract
def test_frontdesk_sqlite_persists_execution_plan_as_first_class_record(tmp_path):
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

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(execution_plan_records)")
        }
        row = conn.execute(
            """
            SELECT account_profile_id, plan_id, plan_version, source_run_id, status, payload_json
            FROM execution_plan_records
            WHERE account_profile_id = ?
            """,
            (profile.account_profile_id,),
        ).fetchone()

    assert {
        "account_profile_id",
        "plan_id",
        "plan_version",
        "source_run_id",
        "status",
        "payload_json",
    }.issubset(columns)
    assert row is not None

    payload = json.loads(row[5])

    assert row[0] == profile.account_profile_id
    assert row[2] == 1
    assert row[3] == result.run_id
    assert row[4] == "draft"
    assert payload["plan_id"] == row[1]
    assert payload["source_run_id"] == result.run_id
    assert payload["source_allocation_id"] == result.goal_solver_output.recommended_allocation.name
    assert payload["items"]


@pytest.mark.contract
def test_execution_plan_storage_supports_version_history_per_plan_id(tmp_path):
    from frontdesk.store import FrontdeskStore

    db_path = tmp_path / "frontdesk.sqlite"
    store = FrontdeskStore(db_path)
    store.initialize()

    base_payload = {
        "plan_id": "plan_hist",
        "plan_version": 1,
        "source_run_id": "run_hist",
        "source_allocation_id": "allocation_hist",
        "status": "draft",
        "confirmation_required": True,
        "warnings": [],
        "items": [{"asset_bucket": "gold"}],
        "approved_at": None,
        "superseded_by_plan_id": None,
    }
    store.save_execution_plan_record(
        account_profile_id="hist_user",
        plan_id="plan_hist",
        plan_version=1,
        source_run_id="run_hist",
        source_allocation_id="allocation_hist",
        status="draft",
        confirmation_required=True,
        payload=base_payload,
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-30T00:00:00Z",
    )
    version_two = {
        **base_payload,
        "plan_version": 2,
        "status": "approved",
        "approved_at": "2026-03-31T00:00:00Z",
    }
    store.save_execution_plan_record(
        account_profile_id="hist_user",
        plan_id="plan_hist",
        plan_version=2,
        source_run_id="run_hist",
        source_allocation_id="allocation_hist",
        status="approved",
        confirmation_required=False,
        payload=version_two,
        created_at="2026-03-30T00:00:00Z",
        updated_at="2026-03-31T00:00:00Z",
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT plan_id, plan_version, status, approved_at, superseded_by_plan_id
            FROM execution_plan_records
            WHERE account_profile_id = ?
            ORDER BY plan_version
            """,
            ("hist_user",),
        ).fetchall()

    assert rows == [
        ("plan_hist", 1, "draft", None, None),
        ("plan_hist", 2, "approved", "2026-03-31T00:00:00Z", None),
    ]
