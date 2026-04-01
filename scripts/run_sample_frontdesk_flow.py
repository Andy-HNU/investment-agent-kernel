from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from frontdesk.service import approve_frontdesk_execution_plan, run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile


def _profile() -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id="sample_user",
        display_name="Sample User",
        current_total_assets=86000.0,
        monthly_contribution=6000.0,
        goal_amount=400000.0,
        goal_horizon_months=48,
        risk_preference="中等",
        max_drawdown_tolerance=0.12,
        current_holdings="50%沪深300 30%债券 20%货基",
        restrictions=[],
    )


def main() -> None:
    db_path = Path("/tmp/investment_agent_kernel_sample.sqlite")
    fixture_path = ROOT / "tests" / "fixtures" / "provider_snapshot_local.json"
    if db_path.exists():
        db_path.unlink()
    onboarding = run_frontdesk_onboarding(
        _profile(),
        db_path=db_path,
        external_data_config={
            "adapter": "local_json",
            "snapshot_path": str(fixture_path),
            "provider_name": "fixture_local_json",
        },
    )
    pending = onboarding["user_state"]["pending_execution_plan"]
    approve_frontdesk_execution_plan(
        account_profile_id=_profile().account_profile_id,
        plan_id=pending["plan_id"],
        plan_version=pending["plan_version"],
        db_path=db_path,
    )
    quarterly = run_frontdesk_followup(
        account_profile_id=_profile().account_profile_id,
        workflow_type="quarterly",
        db_path=db_path,
        profile=UserOnboardingProfile(
            **{**_profile().to_dict(), "restrictions": ["不碰QDII"], "risk_preference": "进取"}
        ),
        external_data_config={
            "adapter": "local_json",
            "snapshot_path": str(fixture_path),
            "provider_name": "fixture_local_json",
        },
    )
    print(json.dumps({"onboarding": onboarding, "quarterly": quarterly}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
