from __future__ import annotations

import json

import pytest

from shared.onboarding import UserOnboardingProfile


def _profile(*, account_profile_id: str = "observed_portfolio_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
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


def _observed_portfolio(*, snapshot_id: str, source_kind: str = "manual_json") -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "source_kind": source_kind,
        "data_status": "observed",
        "completeness_status": "complete",
        "as_of": "2026-04-05T08:00:00Z",
        "total_value": 62_000.0,
        "available_cash": 1_200.0,
        "weights": {
            "equity_cn": 0.50,
            "bond_cn": 0.30,
            "gold": 0.10,
            "satellite": 0.10,
        },
        "holdings": [
            {"asset_bucket": "equity_cn", "product_id": "fund_equity_cn", "weight": 0.50},
            {"asset_bucket": "bond_cn", "product_id": "fund_bond_cn", "weight": 0.30},
            {"asset_bucket": "gold", "product_id": "etf_gold", "weight": 0.10},
            {"asset_bucket": "satellite", "product_id": "fund_satellite", "weight": 0.10},
        ],
        "missing_fields": [],
        "audit_window": {
            "start": "2026-04-04T00:00:00Z",
            "end": "2026-04-05T08:00:00Z",
        },
        "source_ref": "manual:file",
    }


@pytest.mark.contract
def test_frontdesk_sync_observed_portfolio_persists_and_backfills_state(tmp_path):
    from frontdesk.service import load_frontdesk_snapshot, load_user_state, run_frontdesk_onboarding, sync_observed_portfolio

    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id="observed_portfolio_state_user")
    run_frontdesk_onboarding(profile, db_path=db_path)

    sync_result = sync_observed_portfolio(
        account_profile_id=profile.account_profile_id,
        observed_portfolio=_observed_portfolio(snapshot_id="manual_20260405"),
        db_path=db_path,
    )
    user_state = load_user_state(profile.account_profile_id, db_path=db_path)
    snapshot = load_frontdesk_snapshot(profile.account_profile_id, db_path=db_path)

    assert sync_result["workflow"] == "sync_portfolio"
    assert sync_result["status"] in {"synced", "completed"}
    assert sync_result["observed_portfolio"]["snapshot_id"] == "manual_20260405"
    assert sync_result["reconciliation_state"]["observed_snapshot_id"] == "manual_20260405"
    assert sync_result["reconciliation_state"]["status"] in {
        "aligned",
        "drifted",
        "pending_user_action",
        "no_observed_portfolio",
    }
    assert user_state is not None
    assert snapshot is not None
    assert user_state["observed_portfolio"]["snapshot_id"] == "manual_20260405"
    assert snapshot["observed_portfolio"]["source_kind"] == "manual_json"
    assert user_state["reconciliation_state"]["snapshot_id"] == "manual_20260405"
    assert snapshot["reconciliation_state"]["bucket_deltas"] is not None
    assert snapshot["reconciliation_state"]["product_deltas"] is not None
    assert "plan coverage" in json.dumps(snapshot["reconciliation_state"], ensure_ascii=False)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("payload", "expected_source_kind", "expected_snapshot_id"),
    [
        (
            {
                "observed_portfolio": _observed_portfolio(snapshot_id="manual_direct_20260405"),
            },
            "manual_json",
            "manual_direct_20260405",
        ),
        (
            {
                "merged_portfolio": {
                    "snapshot_id": "ocr_merged_20260405",
                    "source_kind": "ocr_snapshot",
                    "completeness_status": "partial",
                    "as_of": "2026-04-05T08:00:00Z",
                    "observed_portfolio": _observed_portfolio(
                        snapshot_id="ocr_merged_20260405",
                        source_kind="ocr_snapshot",
                    ),
                }
            },
            "ocr_snapshot",
            "ocr_merged_20260405",
        ),
    ],
)
def test_frontdesk_sync_observed_portfolio_accepts_direct_and_ocr_merged_shapes(
    tmp_path,
    payload,
    expected_source_kind,
    expected_snapshot_id,
):
    from frontdesk.service import load_user_state, run_frontdesk_onboarding, sync_observed_portfolio

    db_path = tmp_path / "frontdesk.sqlite"
    profile = _profile(account_profile_id=f"observed_portfolio_shape_{expected_snapshot_id}")
    run_frontdesk_onboarding(profile, db_path=db_path)

    sync_result = sync_observed_portfolio(
        account_profile_id=profile.account_profile_id,
        observed_portfolio=payload,
        db_path=db_path,
    )
    user_state = load_user_state(profile.account_profile_id, db_path=db_path)

    assert sync_result["observed_portfolio"]["snapshot_id"] == expected_snapshot_id
    assert sync_result["observed_portfolio"]["source_kind"] == expected_source_kind
    assert sync_result["reconciliation_state"]["observed_snapshot_id"] == expected_snapshot_id
    assert sync_result["reconciliation_state"]["status"] in {
        "aligned",
        "drifted",
        "pending_user_action",
        "no_observed_portfolio",
    }
    assert user_state is not None
    assert user_state["observed_portfolio"]["snapshot_id"] == expected_snapshot_id
