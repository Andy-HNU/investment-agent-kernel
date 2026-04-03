from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontdesk.service import run_frontdesk_followup, run_frontdesk_onboarding
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.http_snapshot_server import serve_json_routes


def _profile(*, account_profile_id: str = "external_fetch_user") -> UserOnboardingProfile:
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


def _write_external_snapshot(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_uri()


@pytest.mark.contract
def test_frontdesk_onboarding_fetches_external_snapshot_and_marks_provenance(tmp_path):
    profile = _profile(account_profile_id="external_onboarding_user")
    external_payload = {
        "market_raw": {
            "raw_volatility": {
                "equity_cn": 0.33,
                "bond_cn": 0.05,
                "gold": 0.10,
                "satellite": 0.24,
            },
            "liquidity_scores": {"equity_cn": 0.92, "bond_cn": 0.96, "gold": 0.84, "satellite": 0.64},
            "valuation_z_scores": {"equity_cn": -0.15, "bond_cn": 0.10, "gold": -0.05, "satellite": 0.95},
            "expected_returns": {"equity_cn": 0.10, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.11},
        },
        "behavior_raw": {
            "recent_chase_risk": "high",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 2.0,
            "override_count_90d": 3,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.15,
        },
    }

    with serve_json_routes({"/snapshot": (200, external_payload)}) as base_url:
        summary = run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "frontdesk.sqlite",
            external_snapshot_source=f"{base_url}/snapshot",
        )

    provenance = summary["user_state"]["decision_card"]["input_provenance"]
    serialized = json.dumps(provenance, ensure_ascii=False, sort_keys=True)

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert provenance["counts"]["externally_fetched"] >= 2
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
        external_snapshot_source="http://127.0.0.1:9/missing_snapshot.json",
    )

    provenance = summary["user_state"]["decision_card"]["input_provenance"]

    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fallback"
    assert summary["external_snapshot_error"] is not None
    assert provenance["counts"]["externally_fetched"] >= 1


@pytest.mark.contract
def test_frontdesk_monthly_fetch_can_override_runtime_account_snapshot(tmp_path):
    profile = _profile(account_profile_id="external_monthly_user")
    db_path = tmp_path / "frontdesk.sqlite"
    onboarding_summary = run_frontdesk_onboarding(profile, db_path=db_path)
    assert onboarding_summary["status"] in {"completed", "degraded"}

    external_payload = {
        "account_raw": {
            "weights": {
                "equity_cn": 0.20,
                "bond_cn": 0.50,
                "gold": 0.20,
                "satellite": 0.10,
            },
            "total_value": 88_000.0,
            "available_cash": 8_000.0,
            "remaining_horizon_months": 60,
        }
    }

    with serve_json_routes({"/monthly": (200, external_payload)}) as base_url:
        summary = run_frontdesk_followup(
            account_profile_id=profile.account_profile_id,
            workflow_type="monthly",
            db_path=db_path,
            external_snapshot_source=f"{base_url}/monthly",
        )

    provenance = summary["decision_card"]["input_provenance"]
    assert summary["status"] in {"completed", "degraded"}
    assert summary["external_snapshot_status"] == "fetched"
    assert provenance["counts"]["externally_fetched"] >= 1
    assert any(
        item["field"] == "account_raw" and item["value"]["total_value"] == 88_000.0
        for item in provenance["externally_fetched"]
    )


@pytest.mark.contract
def test_formal_frontdesk_rejects_local_file_external_snapshot_source(tmp_path):
    profile = _profile(account_profile_id="external_local_source_user")
    payload_path = tmp_path / "snapshot.json"
    payload_path.write_text(json.dumps({"market_raw": {"expected_returns": {"equity_cn": 0.1}}}), encoding="utf-8")

    with pytest.raises(ValueError, match="formal frontdesk flow requires remote http/https external_snapshot_source"):
        run_frontdesk_onboarding(
            profile,
            db_path=tmp_path / "frontdesk.sqlite",
            external_snapshot_source=payload_path.as_uri(),
        )
