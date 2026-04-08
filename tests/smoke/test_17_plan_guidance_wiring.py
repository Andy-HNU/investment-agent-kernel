from __future__ import annotations

import pytest

from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import write_formal_snapshot_source
from frontdesk.service import (
    approve_frontdesk_execution_plan,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)


def _profile(*, account_profile_id: str = "frontdesk_plan_guidance_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="PlanGuidance",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )


def _has_any_plan_step(card: dict) -> bool:
    next_steps = list(card.get("next_steps") or [])
    tokens = {"adopt_pending_plan", "review_pending_plan", "keep_active_plan"}
    return any(step in tokens for step in next_steps)


@pytest.mark.smoke
def test_quarterly_card_emits_plan_guidance_next_steps(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="user_quarterly_guidance")

    onboard = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    pending = onboard["user_state"]["pending_execution_plan"]
    assert pending is not None

    approve_frontdesk_execution_plan(
        account_profile_id=profile.account_profile_id,
        plan_id=pending["plan_id"],
        plan_version=pending["plan_version"],
        approved_at="2026-03-31T00:00:00Z",
        db_path=db_path,
    )

    quarterly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="quarterly",
        db_path=db_path,
    )
    card = quarterly["decision_card"]
    if card.get("card_type") != "blocked":
        assert _has_any_plan_step(card), f"missing plan guidance in next_steps: {card.get('next_steps')}"


@pytest.mark.smoke
def test_monthly_card_consumes_plan_guidance_next_steps(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="user_monthly_guidance")

    onboard = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    pending = onboard["user_state"]["pending_execution_plan"]
    assert pending is not None

    approve_frontdesk_execution_plan(
        account_profile_id=profile.account_profile_id,
        plan_id=pending["plan_id"],
        plan_version=pending["plan_version"],
        approved_at="2026-03-31T00:00:00Z",
        db_path=db_path,
    )

    # Generate a new pending plan by onboarding with changed restrictions (stable)
    updated_profile = _profile(account_profile_id=profile.account_profile_id)
    updated_profile.restrictions = ["不碰股票"]
    run_frontdesk_onboarding(
        updated_profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, updated_profile),
    )

    monthly = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
    )
    card = monthly["decision_card"]
    assert card["card_type"] == "runtime_action"
    assert _has_any_plan_step(card), f"missing plan guidance in next_steps: {card.get('next_steps')}"
