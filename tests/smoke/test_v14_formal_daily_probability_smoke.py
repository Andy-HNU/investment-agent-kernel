from __future__ import annotations

import pytest

from frontdesk.service import run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile
from tests.support.formal_snapshot_helpers import write_formal_snapshot_source


def _profile(*, account_profile_id: str = "frontdesk_v14_formal_daily_smoke") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="FormalDailySmoke",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )


@pytest.mark.smoke
def test_frontdesk_onboarding_surfaces_v14_formal_daily_probability_summary(tmp_path):
    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile()

    result = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )

    assert result["run_outcome_status"] in {"success", "degraded"}
    assert result["resolved_result_category"] in {
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert result["monthly_fallback_used"] is False
    assert result["bucket_fallback_used"] is False
    assert isinstance(result["disclosure_decision"], dict)
    assert result["disclosure_decision"]
    assert isinstance(result["evidence_bundle"], dict)
    assert result["evidence_bundle"]

    assert result.get("probability_engine_result") is not None
