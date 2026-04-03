from __future__ import annotations

import json
from pathlib import Path
import os


def test_bridge_handles_onboarding_from_natural_language(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / 'frontdesk.sqlite'
    task = (
        "please onboard user demo_user with current assets 50000, "
        "monthly 12000, goal 1000000 in 60 months, risk moderate"
    )
    result = handle_task(task, db_path=str(db))
    assert result['intent']['name'] == 'onboarding'
    assert result['invocation']['account_profile_id'] == 'demo_user'
    assert result['result']['status'] in {'ok', 'success', 'completed'} or result['result']['status'] == 'onboarding_completed'
    # Should persist state; follow-up monthly should now be allowed


def test_bridge_handles_status_query(tmp_path):
    # First, onboard a user so status exists
    from integration.openclaw.bridge import handle_task
    db = tmp_path / 'frontdesk.sqlite'
    handle_task("onboard user status_user assets 10000 monthly 1000 goal 50000 in 24 months", db_path=str(db))

    result = handle_task("show status for user status_user", db_path=str(db))
    assert result['intent']['name'] == 'status'
    assert result['result']['user_state']['profile']['account_profile_id'] == 'status_user'


def test_bridge_handles_quarterly_event_show_user_and_explanations(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / 'frontdesk.sqlite'
    handle_task("onboard user bridge_wave4 assets 50000 monthly 5000 goal 200000 in 36 months risk moderate", db_path=str(db))

    quarterly = handle_task("run quarterly review for user bridge_wave4", db_path=str(db))
    show_user = handle_task("show-user for user bridge_wave4", db_path=str(db))
    event = handle_task("event review for user bridge_wave4 after drawdown and rebalance", db_path=str(db))
    explain_probability = handle_task("why did the probability change for user bridge_wave4", db_path=str(db))
    explain_plan = handle_task("why replace active plan for user bridge_wave4", db_path=str(db))

    assert quarterly["intent"]["name"] == "quarterly"
    assert quarterly["result"]["workflow_type"] == "quarterly"
    assert show_user["intent"]["name"] == "show_user"
    assert show_user["result"]["snapshot"]["profile"]["account_profile_id"] == "bridge_wave4"
    assert event["intent"]["name"] == "event"
    assert event["result"]["workflow_type"] == "event"
    assert explain_probability["intent"]["name"] == "explain_probability"
    assert explain_probability["result"]["status"] == "explained"
    assert explain_probability["result"]["explanation"]
    assert explain_plan["intent"]["name"] == "explain_plan_change"
    assert explain_plan["result"]["status"] == "explained"
    assert explain_plan["result"]["explanation"]


def test_bridge_routes_feedback_even_when_run_id_contains_monthly_and_colons(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    onboarding = handle_task(
        "onboard user bridge_feedback assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )
    run_id = onboarding["result"]["run_id"]

    feedback = handle_task(
        f"用户 bridge_feedback 已执行，run_id: {run_id} actual_action: rebalance_partial 备注：已处理",
        db_path=str(db),
    )

    assert feedback["intent"]["name"] == "feedback"
    assert feedback["invocation"]["tool"] == "frontdesk.feedback"
    assert feedback["result"]["execution_feedback"]["source_run_id"] == run_id
    assert feedback["result"]["execution_feedback"]["feedback_status"] == "executed"


def test_bridge_routes_feedback_to_latest_run_when_run_id_is_omitted(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    onboarding = handle_task(
        "onboard user bridge_feedback_latest assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )
    run_id = onboarding["result"]["run_id"]

    feedback = handle_task(
        "用户 bridge_feedback_latest 暂不执行，actual_action: hold 备注：继续观察",
        db_path=str(db),
    )

    assert feedback["intent"]["name"] == "feedback"
    assert feedback["result"]["execution_feedback"]["source_run_id"] == run_id
    assert feedback["result"]["execution_feedback"]["feedback_status"] == "skipped"


def test_bridge_can_approve_single_pending_plan_without_explicit_plan_id(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    onboarding = handle_task(
        "onboard user bridge_approve assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )

    pending = onboarding["result"]["user_state"]["pending_execution_plan"]
    assert pending

    approved = handle_task("confirm plan for user bridge_approve", db_path=str(db))

    assert approved["intent"]["name"] == "approve_plan"
    assert approved["result"]["status"] == "approved"
    assert approved["result"]["approved_execution_plan"]["plan_id"] == pending["plan_id"]


def test_bridge_can_approve_pending_plan_with_version_only_phrase(tmp_path):
    from integration.openclaw.bridge import handle_task

    db = tmp_path / "frontdesk.sqlite"
    onboarding = handle_task(
        "onboard user bridge_approve_v assets 50000 monthly 5000 goal 200000 in 36 months risk moderate",
        db_path=str(db),
    )
    pending = onboarding["result"]["user_state"]["pending_execution_plan"]
    assert pending

    approved = handle_task("confirm plan v2 for user bridge_approve_v", db_path=str(db))

    assert approved["intent"]["name"] == "approve_plan"
    assert approved["result"]["status"] == "approved"
    assert approved["result"]["approved_execution_plan"]["plan_id"] == pending["plan_id"]


def test_acceptance_cli_writes_logs(tmp_path, capsys):
    # Smoke test the CLI wrapper to ensure it writes a log file
    import sys
    import subprocess
    script = Path('scripts/openclaw_bridge_cli.py').resolve()
    db = tmp_path / 'frontdesk.sqlite'
    env = dict(**os.environ)
    env['OPENCLAW_BRIDGE_DB'] = str(db)
    proc = subprocess.run(
        [sys.executable, str(script), '--task', 'onboard user acc_cli assets 50000 monthly 5000 goal 200000 in 36 months'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    out = proc.stdout.strip()
    assert out
    # The script should print the path to a created log file
    log_path = Path(out.splitlines()[-1].split('=')[-1].strip())
    assert log_path.exists()
    logs = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert logs and isinstance(logs[0], dict)


def test_acceptance_harness_reads_task_file_and_writes_jsonl_logs(tmp_path):
    import subprocess
    import sys

    script = Path("scripts/accept_openclaw_bridge.py").resolve()
    db = tmp_path / "frontdesk.sqlite"
    tasks = tmp_path / "tasks.txt"
    tasks.write_text(
        "\n".join(
            [
                "onboard user acc_accept assets 50000 monthly 5000 goal 200000 in 36 months",
                "show status for user acc_accept",
            ]
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--file",
            str(tasks),
            "--db",
            str(db),
            "--artifacts",
            str(artifacts),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    out = proc.stdout.strip()
    assert out.startswith("log_path=")
    log_path = Path(out.splitlines()[-1].split("=", 1)[-1].strip())
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 4
    assert lines[0]["task"].startswith("onboard user acc_accept")
    assert lines[1]["intent"]["name"] == "onboarding"
    assert lines[2]["task"].startswith("show status for user acc_accept")
    assert lines[3]["intent"]["name"] == "status"
