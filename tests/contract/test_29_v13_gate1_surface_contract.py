from __future__ import annotations

import json

from frontdesk.cli import render_frontdesk_summary
from frontdesk.service import run_frontdesk_onboarding
from frontdesk.storage import FrontdeskStore
from orchestrator.engine import (
    _build_input_provenance,
    _gate1_formal_evidence_degradation_reasons,
    run_orchestrator,
)
from orchestrator.types import WorkflowType
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from tests.support.formal_snapshot_helpers import (
    build_formal_snapshot_payload,
    write_formal_snapshot_source,
)


def _profile(*, account_profile_id: str) -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=124_203.16,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="现金12000，黄金6000",
        restrictions=["不买个股", "不碰科技", "不碰高风险产品"],
        current_weights=None,
    )


def test_orchestrator_onboarding_surfaces_gate1_contract_fields_end_to_end():
    profile = _profile(account_profile_id="gate1_surface_orchestrator")
    bundle = build_user_onboarding_inputs(profile, as_of="2026-04-07T00:00:00Z")
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "gate1_surface_run"},
        raw_inputs=bundle.raw_inputs,
    ).to_dict()

    assert result["run_outcome_status"] in {"completed", "degraded", "unavailable", "blocked"}
    assert result["resolved_result_category"] in {
        None,
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert result["disclosure_decision"]["disclosure_level"] in {
        "point_and_range",
        "range_only",
        "diagnostic_only",
        "unavailable",
    }
    assert result["evidence_bundle"]["run_outcome_status"] == result["run_outcome_status"]
    assert result["decision_card"]["run_outcome_status"] == result["run_outcome_status"]
    assert result["decision_card"]["resolved_result_category"] == result["resolved_result_category"]
    assert (
        result["decision_card"]["probability_explanation"]["run_outcome_status"]
        == result["run_outcome_status"]
    )
    assert (
        result["decision_card"]["probability_explanation"]["resolved_result_category"]
        == result["resolved_result_category"]
    )


def test_frontdesk_summary_storage_and_cli_surface_gate1_contract_fields(tmp_path):
    profile = _profile(account_profile_id="gate1_surface_frontdesk")
    db_path = tmp_path / "gate1_surface.sqlite"

    summary = run_frontdesk_onboarding(profile, db_path=db_path)
    store = FrontdeskStore(db_path)
    snapshot = store.get_frontdesk_snapshot(profile.account_profile_id)

    assert summary["run_outcome_status"] in {"completed", "degraded", "unavailable", "blocked"}
    assert summary["resolved_result_category"] in {
        None,
        "formal_independent_result",
        "formal_estimated_result",
        "degraded_formal_result",
    }
    assert summary["decision_card"]["run_outcome_status"] == summary["run_outcome_status"]
    assert summary["decision_card"]["resolved_result_category"] == summary["resolved_result_category"]
    assert summary["disclosure_decision"]["disclosure_level"] in {
        "point_and_range",
        "range_only",
        "diagnostic_only",
        "unavailable",
    }
    assert summary["evidence_bundle"]["run_outcome_status"] == summary["run_outcome_status"]

    assert snapshot is not None
    latest_run = snapshot["latest_run"]
    assert latest_run["result_payload"]["run_outcome_status"] == summary["run_outcome_status"]
    assert latest_run["result_payload"]["resolved_result_category"] == summary["resolved_result_category"]

    output = render_frontdesk_summary(summary)
    assert f"run_outcome_status={summary['run_outcome_status']}" in output
    assert f"resolved_result_category={summary['resolved_result_category']}" in output
    assert "disclosure_level=" in output


def test_frontdesk_onboarding_with_complete_formal_snapshot_degrades_when_formal_path_uses_static_gaussian(
    tmp_path,
):
    profile = _profile(account_profile_id="gate1_surface_formal_snapshot")
    db_path = tmp_path / "gate1_surface_formal_snapshot.sqlite"

    summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=write_formal_snapshot_source(tmp_path, profile),
    )

    assert summary["run_outcome_status"] == "degraded"
    assert summary["resolved_result_category"] == "degraded_formal_result"
    assert summary["disclosure_decision"]["disclosure_level"] == "range_only"
    assert summary["disclosure_decision"]["confidence_level"] == "low"
    assert summary["formal_path_visibility"]["status"] == "degraded"
    assert "static_gaussian" in " ".join(summary["evidence_bundle"]["degradation_reasons"])


def test_frontdesk_onboarding_external_snapshot_primary_does_not_bootstrap_runtime_market_inputs(
    monkeypatch,
    tmp_path,
):
    profile = _profile(account_profile_id="gate1_surface_snapshot_primary")
    db_path = tmp_path / "gate1_surface_snapshot_primary.sqlite"
    snapshot_path = tmp_path / "gate1_surface_snapshot_primary.json"
    payload = build_formal_snapshot_payload(profile)
    payload["market_raw"].pop("product_universe_result", None)
    payload["market_raw"].pop("product_valuation_result", None)
    historical_dataset = dict(payload["market_raw"].get("historical_dataset") or {})
    historical_dataset.pop("product_simulation_input", None)
    payload["market_raw"]["historical_dataset"] = historical_dataset
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr("product_mapping.runtime_inputs._tinyshare_has_token", lambda: True)

    def _unexpected_runtime_bootstrap(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("external formal snapshot should remain snapshot-primary")

    monkeypatch.setattr(
        "product_mapping.runtime_inputs.load_tinyshare_runtime_catalog",
        _unexpected_runtime_bootstrap,
    )
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.build_tinyshare_runtime_valuation_result",
        _unexpected_runtime_bootstrap,
    )

    summary = run_frontdesk_onboarding(
        profile,
        db_path=db_path,
        external_snapshot_source=snapshot_path,
    )

    assert summary["run_outcome_status"] == "degraded"
    assert summary["resolved_result_category"] == "degraded_formal_result"
    assert summary["disclosure_decision"]["disclosure_level"] == "range_only"
    assert summary["evidence_bundle"]["input_refs"].get("provider_signature") in {None, ""}


def test_gate1_formal_evidence_domain_aliases_cover_synthesized_provenance_fields():
    provenance = _build_input_provenance(
        {
            "market_raw": {"historical_dataset": {"source_name": "observed"}},
            "account_raw": {"total_value": 18_000.0},
            "behavior_raw": {"cooldown_active": False},
            "live_portfolio": {"total_value": 18_000.0},
        },
        WorkflowType.ONBOARDING,
        has_prior_baseline=False,
    )

    reasons = _gate1_formal_evidence_degradation_reasons(input_provenance=provenance)

    assert "market_raw formal audit record missing" not in reasons
    assert "account_raw formal audit record missing" not in reasons
    assert "behavior_raw formal audit record missing" not in reasons
    assert "live_portfolio formal audit record missing" not in reasons
