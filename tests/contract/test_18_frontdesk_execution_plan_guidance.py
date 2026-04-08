from __future__ import annotations

import pytest

from frontdesk.service import approve_frontdesk_execution_plan, run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import write_formal_snapshot_source


def _profile(
    *,
    account_profile_id: str = "phase1b_guidance_user",
    risk_preference: str = "中等",
    restrictions: list[str] | None = None,
) -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=50_000.0,
        monthly_contribution=10_000.0,
        goal_amount=450_000.0,
        goal_horizon_months=36,
        risk_preference=risk_preference,
        max_drawdown_tolerance=0.10,
        current_holdings="cash",
        restrictions=list(restrictions or []),
    )


@pytest.mark.contract
def test_quarterly_followup_surfaces_execution_plan_guidance_when_pending_differs_from_active(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    baseline_profile = _profile()
    first = run_frontdesk_onboarding(
        baseline_profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, baseline_profile),
    )
    pending = first["user_state"]["pending_execution_plan"]
    approve_frontdesk_execution_plan(
        account_profile_id="phase1b_guidance_user",
        plan_id=pending["plan_id"],
        plan_version=pending["plan_version"],
        db_path=db_path,
    )

    summary = run_frontdesk_followup(
        account_profile_id="phase1b_guidance_user",
        workflow_type="quarterly",
        db_path=db_path,
        profile=_profile(risk_preference="进取", restrictions=["只接受黄金和现金"]),
        external_snapshot_source=write_formal_snapshot_source(
            tmp_path,
            _profile(
                account_profile_id="phase1b_guidance_user",
                risk_preference="进取",
                restrictions=["只接受黄金和现金"],
            ),
        ),
    )

    guidance = (summary["decision_card"] or {}).get("execution_plan_guidance")
    assert guidance is not None
    assert guidance["recommendation"] in {"keep_active", "review_replace", "replace_active"}
    assert summary["decision_card"]["next_steps"][0] in {"keep_active_plan", "approve_pending_plan", "review_plan_delta"}
    assert "execution_plan_delta" in " ".join(summary["decision_card"]["evidence_highlights"])
