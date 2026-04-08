from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontdesk.service import run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.formal_snapshot_helpers import (
    build_formal_snapshot_payload,
    write_formal_snapshot_source,
)


def _profile(*, account_profile_id: str = "external_fetch_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金 12000 黄金 6000",
        restrictions=[],
    )


def _write_external_snapshot(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_uri()


@pytest.mark.contract
def test_frontdesk_onboarding_fetches_external_snapshot_and_marks_provenance(tmp_path):
    profile = _profile(account_profile_id="external_onboarding_user")
    bundle = build_user_onboarding_inputs(profile, as_of="2026-03-30T00:00:00Z")
    external_payload = build_formal_snapshot_payload(
        profile,
        market_raw_overrides={
            "raw_volatility": {
                **bundle.raw_inputs["market_raw"]["raw_volatility"],
                "equity_cn": 0.33,
            },
        },
        behavior_raw_overrides={
            "recent_chase_risk": "high",
            "override_count_90d": 3,
        },
    )

    summary = run_frontdesk_onboarding(
        profile,
        db_path=tmp_path / "frontdesk.sqlite",
        external_snapshot_source=_write_external_snapshot(tmp_path / "snapshot.json", external_payload),
    )

    provenance = summary["user_state"]["decision_card"]["input_provenance"]
    serialized = json.dumps(provenance, ensure_ascii=False, sort_keys=True)

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert provenance["counts"]["externally_fetched"] >= 4
    assert any(
        item["field"] == "market_raw" and item["value"]["raw_volatility"]["equity_cn"] == 0.33
        for item in provenance["externally_fetched"]
    )
    assert any(
        item["field"] == "behavior_raw" and item["value"]["recent_chase_risk"] == "high"
        for item in provenance["externally_fetched"]
    )
    assert "外部抓取" in serialized


@pytest.mark.contract
def test_frontdesk_onboarding_fetch_failure_falls_back_without_blocking(tmp_path):
    profile = _profile(account_profile_id="external_fallback_user")

    summary = run_frontdesk_onboarding(
        profile,
        db_path=tmp_path / "frontdesk.sqlite",
        external_snapshot_source=(tmp_path / "missing_snapshot.json").as_uri(),
    )

    provenance = summary["user_state"]["decision_card"]["input_provenance"]

    assert summary["status"] == "blocked"
    assert summary["external_snapshot_status"] == "fallback"
    assert summary["external_snapshot_error"] is not None
    assert provenance["counts"]["externally_fetched"] == 0


@pytest.mark.contract
def test_frontdesk_monthly_fetch_can_override_runtime_account_snapshot(tmp_path):
    profile = _profile(account_profile_id="external_monthly_user")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    assert onboarding_summary["status"] in {"completed", "degraded"}

    external_payload = build_formal_snapshot_payload(
        profile,
        account_raw_overrides={
            "weights": {
                "equity_cn": 0.20,
                "bond_cn": 0.50,
                "gold": 0.20,
                "satellite": 0.10,
            },
            "total_value": 88_000.0,
            "available_cash": 8_000.0,
            "remaining_horizon_months": 60,
        },
        live_portfolio_overrides={
            "weights": {
                "equity_cn": 0.20,
                "bond_cn": 0.50,
                "gold": 0.20,
                "satellite": 0.10,
            },
            "total_value": 88_000.0,
            "available_cash": 8_000.0,
            "remaining_horizon_months": 60,
        },
    )

    summary = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=db_path,
        external_snapshot_source=_write_external_snapshot(tmp_path / "monthly.json", external_payload),
    )

    provenance = summary["decision_card"]["input_provenance"]
    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert provenance["counts"]["externally_fetched"] >= 4
    assert any(
        item["field"] == "account_raw" and item["value"]["total_value"] == 88_000.0
        for item in provenance["externally_fetched"]
    )
