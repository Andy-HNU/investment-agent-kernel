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
