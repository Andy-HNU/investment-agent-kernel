from __future__ import annotations

import json

import pytest

from demo_cli import main, run_demo_scenario


@pytest.mark.smoke
def test_full_lifecycle_demo_report_smoke():
    report = run_demo_scenario("full_lifecycle")

    assert report["scenario"] == "full_lifecycle"
    assert report["summary"]["phase_order"] == ["onboarding", "monthly", "event", "quarterly"]
    assert set(report["summary"]["results"].keys()) == {
        "onboarding",
        "monthly",
        "event",
        "quarterly",
    }
    assert report["summary"]["results"]["onboarding"]["card_type"] == "goal_baseline"
    assert report["summary"]["results"]["monthly"]["card_type"] == "runtime_action"
    assert report["summary"]["results"]["event"]["recommended_action"] == "freeze"
    assert report["summary"]["results"]["quarterly"]["card_type"] == "quarterly_review"


@pytest.mark.smoke
def test_monthly_replay_override_demo_report_smoke():
    report = run_demo_scenario("monthly_replay_override")
    result = report["result"]
    meta = result["calibration_result"]["param_version_meta"]

    assert report["bootstrap"]["workflow_type"] == "onboarding"
    assert result["workflow_type"] == "event"
    assert result["decision_card"]["card_type"] == "runtime_action"
    assert result["audit_record"]["control_flags"]["manual_override_requested"] is True
    assert meta["updated_reason"] == "manual_review"
    assert "manual_review" in result["decision_card"]["next_steps"]


@pytest.mark.smoke
def test_provenance_blocked_demo_report_smoke():
    report = run_demo_scenario("monthly_provenance_blocked")
    result = report["result"]

    assert report["scenario"] == "provenance_blocked"
    assert report["requested_scenario"] == "monthly_provenance_blocked"
    assert result["status"] == "blocked"
    assert result["decision_card"]["card_type"] == "blocked"
    assert "calibration.source_bundle_id mismatch with bundle_id" in result["blocking_reasons"]


@pytest.mark.smoke
def test_provenance_relaxed_alias_demo_report_smoke():
    report = run_demo_scenario("monthly_provenance_relaxed")
    result = report["result"]

    assert report["scenario"] == "provenance_relaxed"
    assert report["requested_scenario"] == "monthly_provenance_relaxed"
    assert result["status"] != "blocked"
    assert result["audit_record"]["control_flags"]["enforce_provenance_checks"] is False
    assert result["decision_card"]["trace_refs"]["bundle_id"] == "bundle_demo_raw_override"


@pytest.mark.smoke
def test_demo_cli_json_smoke(capsys):
    exit_code = main(["--scenario", "full_lifecycle", "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["scenario"] == "full_lifecycle"
    assert payload["summary"]["results"]["quarterly"]["card_type"] == "quarterly_review"
