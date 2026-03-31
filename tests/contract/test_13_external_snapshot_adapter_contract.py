from __future__ import annotations

import pytest

from snapshot_ingestion.adapters import (
    ExternalSnapshotAdapterError,
    HttpJsonSnapshotAdapterConfig,
    fetch_http_json_snapshot,
)
from tests.support.http_snapshot_server import serve_json_routes


@pytest.mark.contract
def test_http_json_snapshot_adapter_fetches_allowed_overrides_and_provenance():
    market_raw = {
        "raw_volatility": {"equity_cn": 0.21},
        "liquidity_scores": {"equity_cn": 0.91},
        "valuation_z_scores": {"equity_cn": -0.4},
        "expected_returns": {"equity_cn": 0.09},
    }
    behavior_raw = {
        "recent_chase_risk": "low",
        "recent_panic_risk": "none",
        "trade_frequency_30d": 0.0,
        "override_count_90d": 0,
        "cooldown_active": False,
        "cooldown_until": None,
        "behavior_penalty_coeff": 0.2,
    }
    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "market_raw": market_raw,
                    "behavior_raw": behavior_raw,
                    "ignored_field": {"hello": "world"},
                },
            )
        }
    ) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping({"snapshot_url": f"{base_url}/snapshot"})
        result = fetch_http_json_snapshot(
            config,
            workflow_type="monthly",
            account_profile_id="frontdesk_andy",
            as_of="2026-03-30T00:00:00Z",
        )

    assert result.raw_overrides["market_raw"] == market_raw
    assert result.raw_overrides["behavior_raw"] == behavior_raw
    assert {item["field"] for item in result.provenance_items} == {"behavior_raw", "market_raw"}
    assert any("ignored external snapshot keys" in warning for warning in result.warnings)


@pytest.mark.contract
def test_http_json_snapshot_adapter_uses_source_ref_in_provenance():
    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "market_raw": {
                        "raw_volatility": {"equity_cn": 0.21},
                        "liquidity_scores": {"equity_cn": 0.91},
                        "valuation_z_scores": {"equity_cn": -0.4},
                        "expected_returns": {"equity_cn": 0.09},
                    },
                    "source_ref": "provider://snapshot/v2026-03-30",
                },
            )
        }
    ) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping({"snapshot_url": f"{base_url}/snapshot"})
        result = fetch_http_json_snapshot(
            config,
            workflow_type="monthly",
            account_profile_id="frontdesk_andy",
            as_of="2026-03-30T00:00:00Z",
        )

    assert result.source_ref == "provider://snapshot/v2026-03-30"
    assert {item["value"] for item in result.provenance_items} == {"provider://snapshot/v2026-03-30"}


@pytest.mark.contract
def test_http_json_snapshot_adapter_preserves_provider_freshness_metadata():
    with serve_json_routes(
        {
            "/snapshot": (
                200,
                {
                    "market_raw": {
                        "raw_volatility": {"equity_cn": 0.21},
                        "liquidity_scores": {"equity_cn": 0.91},
                        "valuation_z_scores": {"equity_cn": -0.4},
                        "expected_returns": {"equity_cn": 0.09},
                    },
                    "provider_name": "broker_http_json",
                    "fetched_at": "2026-03-30T08:00:00Z",
                    "as_of": "2026-03-30T07:30:00Z",
                    "domains": {
                        "market_raw": {
                            "status": "fresh",
                            "fetched_at": "2026-03-30T08:00:00Z",
                            "as_of": "2026-03-30T07:30:00Z",
                        }
                    },
                },
            )
        }
    ) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping({"snapshot_url": f"{base_url}/snapshot"})
        result = fetch_http_json_snapshot(
            config,
            workflow_type="monthly",
            account_profile_id="frontdesk_andy",
            as_of="2026-03-30T09:00:00Z",
        )

    assert result.provider_name == "broker_http_json"
    assert result.fetched_at == "2026-03-30T08:00:00Z"
    assert result.freshness["as_of"] == "2026-03-30T07:30:00Z"
    assert result.freshness["domains"]["market_raw"]["status"] == "fresh"
    assert result.provenance_items[0]["freshness"]["status"] == "fresh"


@pytest.mark.contract
def test_http_json_snapshot_adapter_fail_open_returns_warning():
    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping(
            {
                "snapshot_url": f"{base_url}/snapshot",
                "fail_open": True,
            }
        )
        result = fetch_http_json_snapshot(
            config,
            workflow_type="onboarding",
            account_profile_id="frontdesk_andy",
            as_of="2026-03-30T00:00:00Z",
        )

    assert result.raw_overrides == {}
    assert result.provenance_items == []
    assert result.warnings


@pytest.mark.contract
def test_http_json_snapshot_adapter_fail_open_handles_malformed_payload():
    with serve_json_routes({"/snapshot": (200, {"market_raw": "bad-shape"})}) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping(
            {
                "snapshot_url": f"{base_url}/snapshot",
                "fail_open": True,
            }
        )
        result = fetch_http_json_snapshot(
            config,
            workflow_type="onboarding",
            account_profile_id="frontdesk_andy",
            as_of="2026-03-30T00:00:00Z",
        )

    assert result.raw_overrides == {}
    assert result.provenance_items == []
    assert any("必须是对象" in warning for warning in result.warnings)


@pytest.mark.contract
def test_http_json_snapshot_adapter_fail_closed_raises():
    with serve_json_routes({"/snapshot": (500, {"error": "boom"})}) as base_url:
        config = HttpJsonSnapshotAdapterConfig.from_mapping(
            {
                "snapshot_url": f"{base_url}/snapshot",
                "fail_open": False,
            }
        )
        with pytest.raises(ExternalSnapshotAdapterError, match="external snapshot fetch failed"):
            fetch_http_json_snapshot(
                config,
                workflow_type="quarterly",
                account_profile_id="frontdesk_andy",
                as_of="2026-03-30T00:00:00Z",
            )
