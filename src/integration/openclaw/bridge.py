from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.nli_router import Intent, parse_onboarding, parse_status, route
from frontdesk.service import (
    DEFAULT_DB_PATH,
    load_user_state,
    record_frontdesk_execution_feedback,
    approve_frontdesk_execution_plan,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from shared.onboarding import UserOnboardingProfile


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def handle_task(task: str, *, db_path: str | Path = DEFAULT_DB_PATH, now: Optional[str] = None) -> dict[str, Any]:
    """Route an OpenClaw-style NL task into frontdesk workflows.

    Returns a JSON-serializable dict: {intent, invocation, result}.
    """
    intent: Intent = route(task)
    db_path = Path(db_path)
    result: dict[str, Any]
    invocation: dict[str, Any]
    when = now or _now_iso()

    if intent.name == "onboarding":
        payload = parse_onboarding(task)
        profile = UserOnboardingProfile(**payload)
        summary = run_frontdesk_onboarding(profile, db_path=db_path)
        invocation = {"tool": "frontdesk.onboarding", **payload}
        result = dict(summary)
    elif intent.name == "status":
        args = parse_status(task)
        user_state = load_user_state(args["account_profile_id"], db_path=db_path)
        invocation = {"tool": "frontdesk.status", **args}
        result = {"workflow": "status", "user_state": user_state}
    elif intent.name == "monthly":
        # Minimal monthly follow-up, no overrides
        args = parse_status(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"], workflow_type="monthly", db_path=db_path
        )
        invocation = {"tool": "frontdesk.followup.monthly", **args}
        result = dict(summary)
    elif intent.name == "approve_plan":
        # approve plan <plan_id> v<version> for user <id>
        plan_id = _extract(r"plan\s+([a-zA-Z0-9_\-]+)", task) or "plan_0"
        plan_version = int(_extract(r"v(\d+)", task) or 1)
        args = parse_status(task)
        summary = approve_frontdesk_execution_plan(
            account_profile_id=args["account_profile_id"], plan_id=plan_id, plan_version=plan_version, db_path=db_path
        )
        invocation = {"tool": "frontdesk.approve_plan", **args, "plan_id": plan_id, "plan_version": plan_version}
        result = dict(summary)
    elif intent.name == "feedback":
        run_id = _extract(r"run[_\-]?id\s+([a-zA-Z0-9_\-]+)", task) or ""
        executed = None
        if re.search(r"\bexecuted\b", task, flags=re.I):
            executed = True
        elif re.search(r"\bskipped\b", task, flags=re.I):
            executed = False
        args = parse_status(task)
        summary = record_frontdesk_execution_feedback(
            account_profile_id=args["account_profile_id"],
            source_run_id=run_id,
            user_executed=executed,
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.feedback", **args, "run_id": run_id, "executed": executed}
        result = dict(summary)
    else:
        invocation = {"tool": "unknown"}
        result = {"workflow": "unknown", "status": "unsupported", "note": "intent not recognized"}

    return {
        "intent": asdict(intent),
        "invocation": invocation,
        "result": result,
        "at": when,
    }


def _extract(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, flags=re.I)
    return m.group(1) if m else None


def write_log_record(task: str, *, output: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"openclaw-bridge-{ts}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task}, ensure_ascii=False) + "\n")
        f.write(json.dumps(output, ensure_ascii=False) + "\n")
    return path

