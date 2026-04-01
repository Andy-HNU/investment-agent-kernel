from __future__ import annotations

import json
from pathlib import Path

import pytest


AS_OF = "2026-03-30T00:00:00Z"


def _snapshot_payload(total_value: float) -> dict:
    return {
        "market_raw": {
            "raw_volatility": {"equity_cn": 0.19, "bond_cn": 0.05, "gold": 0.10, "satellite": 0.22},
            "liquidity_scores": {"equity_cn": 0.90, "bond_cn": 0.96, "gold": 0.83, "satellite": 0.60},
            "valuation_z_scores": {"equity_cn": -0.1, "bond_cn": 0.05, "gold": -0.15, "satellite": 0.9},
            "expected_returns": {"equity_cn": 0.09, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.10},
        },
        "account_raw": {
            "weights": {"equity_cn": 0.48, "bond_cn": 0.32, "gold": 0.12, "satellite": 0.08},
            "total_value": total_value,
            "available_cash": 2_000.0,
            "remaining_horizon_months": 60,
        },
        "behavior_raw": {
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 1.0,
            "override_count_90d": 0,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.1,
        },
        "provider_name": "file_json_fixture",
        "fetched_at": "2026-03-30T08:00:00Z",
        "as_of": "2026-03-30T07:30:00Z",
        "domains": {
            "market_raw": {"status": "fresh"},
            "account_raw": {"status": "fresh"},
            "behavior_raw": {"status": "fresh"},
        },
        "warnings": [],
    }


@pytest.mark.contract
def test_registry_resolves_http_json_adapter_backward_compatibility(tmp_path, monkeypatch):
    # Import at test-time to pick up registry
    from frontdesk.external_data import fetch_external_snapshot
    from tests.support.http_snapshot_server import serve_json_routes

    with serve_json_routes({"/snapshot": (200, _snapshot_payload(total_value=61000.0))}) as base_url:
        fetched = fetch_external_snapshot(
            {
                "adapter": "http_json",
                "snapshot_url": f"{base_url}/snapshot",
                "query_params": {"source": "registry-test"},
            },
            workflow_type="onboarding",
            account_profile_id="registry_user",
            as_of=AS_OF,
        )

    assert fetched is not None
    assert fetched.raw_overrides.get("account_raw", {}).get("total_value") == 61000.0
    assert any(item.get("field") == "account_raw" for item in fetched.provenance_items)


@pytest.mark.contract
def test_file_json_provider_fetches_from_local_fixture(tmp_path):
    from frontdesk.external_data import fetch_external_snapshot

    fixture = tmp_path / "external_snapshot.json"
    fixture.write_text(json.dumps(_snapshot_payload(total_value=64000.0), ensure_ascii=False, indent=2), encoding="utf-8")

    fetched = fetch_external_snapshot(
        {
            "adapter": "file_json",
            "file_path": str(fixture),
        },
        workflow_type="monthly",
        account_profile_id="registry_user_file",
        as_of=AS_OF,
    )

    assert fetched is not None
    assert fetched.raw_overrides["account_raw"]["total_value"] == 64000.0
    assert fetched.provider_name == "file_json_fixture"
    assert fetched.freshness.get("as_of") == "2026-03-30T07:30:00Z"
    assert {i["field"] for i in fetched.provenance_items} >= {"market_raw", "account_raw", "behavior_raw"}

