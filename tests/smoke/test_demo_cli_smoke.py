from __future__ import annotations

import json

import pytest

from demo_cli import main


@pytest.mark.smoke
def test_demo_cli_quarterly_full_chain_json_smoke(capsys):
    exit_code = main(["quarterly_full_chain", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["scenario"] == "quarterly_review"
    assert payload["requested_scenario"] == "quarterly_full_chain"
    assert payload["result"]["workflow_type"] == "quarterly"
    assert payload["result"]["status"] == "completed"
    assert payload["result"]["decision_card"]["card_type"] == "quarterly_review"
    assert payload["result"]["decision_card"]["recommended_action"] == "review"


@pytest.mark.smoke
def test_demo_cli_monthly_replay_override_json_smoke(capsys):
    exit_code = main(["monthly_replay_override", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["scenario"] == "monthly_replay_override"
    assert payload["result"]["requested_workflow_type"] == "monthly"
    assert payload["result"]["workflow_type"] == "event"
    assert payload["result"]["status"] == "escalated"
    assert payload["result"]["audit_record"]["control_flags"]["manual_override_requested"] is True
    assert payload["result"]["decision_card"]["recommended_action"] == "freeze"
