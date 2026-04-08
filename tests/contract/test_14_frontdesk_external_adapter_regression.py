from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from shared.onboarding import OnboardingBuildResult, UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.formal_snapshot_helpers import (
    build_formal_snapshot_payload,
    formal_market_raw_overrides,
    write_formal_snapshot_source,
)


def _profile(*, account_profile_id: str = "frontdesk_external_user") -> UserOnboardingProfile:
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


def _write_fixture(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_uri()


def _fetch_json(url: str, requests: list[str]) -> dict[str, Any]:
    requests.append(url)
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _external_onboarding_bundle_factory(market_url: str, behavior_url: str, requests: list[str]):
    def _factory(profile: UserOnboardingProfile) -> OnboardingBuildResult:
        base = build_user_onboarding_inputs(profile)
        market_raw = _fetch_json(market_url, requests)
        behavior_raw = _fetch_json(behavior_url, requests)
        formal_payload = build_formal_snapshot_payload(
            profile,
            market_raw_overrides=market_raw,
            behavior_raw_overrides=behavior_raw,
        )

        raw_inputs = deepcopy(base.raw_inputs)
        raw_inputs["market_raw"] = deepcopy(formal_payload["market_raw"])
        raw_inputs["account_raw"] = deepcopy(formal_payload["account_raw"])
        raw_inputs["behavior_raw"] = deepcopy(formal_payload["behavior_raw"])

        input_provenance = deepcopy(formal_payload["input_provenance"])
        return OnboardingBuildResult(
            profile=base.profile,
            input_provenance=input_provenance,
            goal_solver_input=deepcopy(base.goal_solver_input),
            raw_inputs=raw_inputs,
            live_portfolio=deepcopy(formal_payload["live_portfolio"]),
        )

    return _factory


def _external_followup_raw_inputs_factory(market_url: str, behavior_url: str, requests: list[str]):
    from frontdesk.service import _workflow_raw_inputs as original_workflow_raw_inputs

    def _factory(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raw_inputs = original_workflow_raw_inputs(*args, **kwargs)
        market_raw = _fetch_json(market_url, requests)
        behavior_raw = _fetch_json(behavior_url, requests)
        merged_market_raw = deepcopy(formal_market_raw_overrides())
        for key, value in market_raw.items():
            merged_market_raw[key] = value
        raw_inputs["market_raw"] = merged_market_raw
        raw_inputs["behavior_raw"] = behavior_raw
        raw_inputs.setdefault("input_provenance", {}).setdefault("externally_fetched", []).extend(
            [
                {
                    "field": "market_raw",
                    "label": "市场输入",
                    "value": market_raw,
                    "source_ref": market_url,
                    "as_of": str(raw_inputs.get("as_of") or ""),
                    "fetched_at": str(raw_inputs.get("as_of") or ""),
                    "data_status": "observed",
                    "freshness_state": "fresh",
                    "audit_window": {
                        "start_date": "2024-01-01",
                        "end_date": "2026-03-31",
                        "trading_days": 500,
                        "observed_days": 500,
                        "inferred_days": 0,
                    },
                    "note": "fetched from local fixture JSON",
                },
                {
                    "field": "behavior_raw",
                    "label": "行为输入",
                    "value": behavior_raw,
                    "source_ref": behavior_url,
                    "as_of": str(raw_inputs.get("as_of") or ""),
                    "fetched_at": str(raw_inputs.get("as_of") or ""),
                    "data_status": "observed",
                    "freshness_state": "fresh",
                    "audit_window": {
                        "start_date": str(raw_inputs.get("as_of") or "")[:10],
                        "end_date": str(raw_inputs.get("as_of") or "")[:10],
                        "trading_days": 1,
                        "observed_days": 1,
                        "inferred_days": 0,
                    },
                    "note": "fetched from local fixture JSON",
                },
            ]
        )
        return raw_inputs

    return _factory


@pytest.mark.contract
def test_frontdesk_onboarding_persists_externally_fetched_provenance_from_fixture_json(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_onboarding
    from frontdesk.storage import FrontdeskStore

    profile = _profile(account_profile_id="external_fetch_user")
    requests: list[str] = []
    market_url = _write_fixture(
        tmp_path / "market.json",
        {
            "raw_volatility": {"equity_cn": 0.20, "bond_cn": 0.05, "gold": 0.10, "satellite": 0.25},
            "liquidity_scores": {"equity_cn": 0.88, "bond_cn": 0.96, "gold": 0.87, "satellite": 0.66},
            "valuation_z_scores": {"equity_cn": 0.15, "bond_cn": 0.08, "gold": -0.12, "satellite": 1.7},
            "expected_returns": {"equity_cn": 0.09, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.11},
        },
    )
    behavior_url = _write_fixture(
        tmp_path / "behavior.json",
        {
            "recent_chase_risk": "low",
            "recent_panic_risk": "none",
            "trade_frequency_30d": 1.0,
            "override_count_90d": 0,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.0,
        },
    )

    monkeypatch.setattr(
        "frontdesk.service.build_user_onboarding_inputs",
        _external_onboarding_bundle_factory(market_url, behavior_url, requests),
    )

    summary = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk.sqlite")

    store = FrontdeskStore(tmp_path / "frontdesk.sqlite")
    user_state = store.load_user_state(profile.account_profile_id)
    assert summary["status"] in {"completed", "degraded"}
    assert requests == [market_url, behavior_url]
    assert user_state is not None
    assert user_state["decision_card"]["input_provenance"]["counts"]["externally_fetched"] >= 2
    assert user_state["decision_card"]["input_provenance"]["externally_fetched"][0]["field"] == "market_raw"
    serialized = json.dumps(user_state, ensure_ascii=False, sort_keys=True)
    assert "外部抓取" in serialized


@pytest.mark.contract
def test_frontdesk_onboarding_falls_back_to_default_data_when_fixture_fetch_fails(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_onboarding
    from frontdesk.storage import FrontdeskStore

    profile = _profile(account_profile_id="external_fetch_fallback_user")
    requests: list[str] = []
    market_url = _write_fixture(
        tmp_path / "market.json",
        {
            "raw_volatility": {"equity_cn": 0.18, "bond_cn": 0.04, "gold": 0.12, "satellite": 0.22},
            "liquidity_scores": {"equity_cn": 0.9, "bond_cn": 0.95, "gold": 0.85, "satellite": 0.6},
            "valuation_z_scores": {"equity_cn": 0.2, "bond_cn": 0.1, "gold": -0.3, "satellite": 1.8},
            "expected_returns": {"equity_cn": 0.08, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.10},
        },
    )
    behavior_url = (tmp_path / "missing_behavior.json").as_uri()

    def _fallback_bundle_factory(profile: UserOnboardingProfile) -> OnboardingBuildResult:
        base = build_user_onboarding_inputs(profile)
        try:
            _fetch_json(market_url, requests)
            _fetch_json(behavior_url, requests)
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            return base
        return base

    monkeypatch.setattr(
        "frontdesk.service.build_user_onboarding_inputs",
        _fallback_bundle_factory,
    )

    summary = run_frontdesk_onboarding(profile, db_path=tmp_path / "frontdesk.sqlite")

    store = FrontdeskStore(tmp_path / "frontdesk.sqlite")
    user_state = store.load_user_state(profile.account_profile_id)
    assert summary["status"] == "blocked"
    assert requests == [market_url, behavior_url]
    assert user_state is not None
    assert user_state["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 0
    assert user_state["decision_card"]["input_provenance"]["counts"]["default_assumed"] >= 1


@pytest.mark.contract
def test_frontdesk_monthly_followup_can_apply_fixture_fetch_override(
    tmp_path,
    monkeypatch,
):
    from frontdesk.service import run_frontdesk_followup, run_frontdesk_onboarding
    from frontdesk.storage import FrontdeskStore

    profile = _profile(account_profile_id="external_followup_user")
    onboarding_db = tmp_path / "frontdesk.sqlite"
    requests: list[str] = []
    market_url = _write_fixture(
        tmp_path / "followup_market.json",
        {
            "raw_volatility": {"equity_cn": 0.14, "bond_cn": 0.05, "gold": 0.09, "satellite": 0.18},
            "liquidity_scores": {"equity_cn": 0.84, "bond_cn": 0.96, "gold": 0.9, "satellite": 0.7},
            "valuation_z_scores": {"equity_cn": 0.0, "bond_cn": 0.1, "gold": -0.2, "satellite": 1.4},
            "expected_returns": {"equity_cn": 0.08, "bond_cn": 0.03, "gold": 0.04, "satellite": 0.10},
        },
    )
    behavior_url = _write_fixture(
        tmp_path / "followup_behavior.json",
        {
            "recent_chase_risk": "medium",
            "recent_panic_risk": "low",
            "trade_frequency_30d": 2.0,
            "override_count_90d": 1,
            "cooldown_active": False,
            "cooldown_until": None,
            "behavior_penalty_coeff": 0.1,
        },
    )

    onboarding = run_frontdesk_onboarding(
        profile,
        db_path=onboarding_db,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )
    assert onboarding["status"] in {"completed", "degraded"}

    monkeypatch.setattr(
        "frontdesk.service._workflow_raw_inputs",
        _external_followup_raw_inputs_factory(market_url, behavior_url, requests),
    )

    summary = run_frontdesk_followup(
        account_profile_id=profile.account_profile_id,
        workflow_type="monthly",
        db_path=onboarding_db,
    )

    store = FrontdeskStore(onboarding_db)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)
    assert summary["status"] in {"completed", "degraded"}
    assert requests == [market_url, behavior_url]
    assert snapshot is not None
    latest_run = snapshot["latest_run"]
    assert latest_run["workflow_type"] == "monthly"
    assert latest_run["decision_card"]["input_provenance"]["counts"]["externally_fetched"] == 2
    assert latest_run["decision_card"]["input_provenance"]["externally_fetched"][0]["field"] == "market_raw"
    assert latest_run["decision_card"]["formal_path_visibility"]["status"] == "degraded"
    assert latest_run["decision_card"]["formal_path_visibility"]["missing_audit_fields"] == []
    serialized = json.dumps(latest_run["decision_card"], ensure_ascii=False, sort_keys=True)
    assert "外部抓取" in serialized
