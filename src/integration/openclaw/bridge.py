from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.explainability import (
    build_daily_monitor_summary,
    build_data_basis_explanation,
    build_execution_policy_explanation,
    build_plan_change_explanation,
    build_probability_explanation,
)
from agent.nli_router import Intent, parse_followup, parse_onboarding, parse_status, route
from frontdesk.service import (
    DEFAULT_DB_PATH,
    load_frontdesk_snapshot,
    load_user_state,
    record_frontdesk_execution_feedback,
    approve_frontdesk_execution_plan,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
    sync_observed_portfolio_import,
    sync_observed_portfolio_manual,
    sync_observed_portfolio_ocr,
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
    elif intent.name == "show_user":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path)
        invocation = {"tool": "frontdesk.show_user", **args}
        result = {"workflow": "show_user", "snapshot": snapshot}
    elif intent.name == "status":
        args = parse_status(task)
        user_state = load_user_state(args["account_profile_id"], db_path=db_path)
        invocation = {"tool": "frontdesk.status", **args}
        result = {"workflow": "status", "user_state": user_state}
    elif intent.name == "monthly":
        # Minimal monthly follow-up, no overrides
        args = parse_followup(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"], workflow_type="monthly", db_path=db_path
        )
        invocation = {"tool": "frontdesk.followup.monthly", **args}
        result = dict(summary)
    elif intent.name == "quarterly":
        args = parse_followup(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"], workflow_type="quarterly", db_path=db_path
        )
        invocation = {"tool": "frontdesk.followup.quarterly", **args}
        result = dict(summary)
    elif intent.name == "event":
        args = parse_followup(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"],
            workflow_type="event",
            db_path=db_path,
            event_request=True,
            event_context={"source": "openclaw_bridge", "raw_task": task},
        )
        invocation = {"tool": "frontdesk.followup.event", **args}
        result = dict(summary)
    elif intent.name == "approve_plan":
        # approve plan <plan_id> v<version> for user <id>
        plan_id = _extract(r"plan\s+([a-zA-Z0-9_\-:]+)", task) or "plan_0"
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
    elif intent.name == "sync_portfolio_manual":
        args = parse_status(task)
        holdings = _extract_json_holdings(task)
        summary = sync_observed_portfolio_manual(
            account_profile_id=args["account_profile_id"],
            holdings=holdings,
            observed_at=when,
            account_source="manual_sync",
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.sync_portfolio_manual", **args, "holding_count": len(holdings)}
        result = dict(summary)
    elif intent.name == "sync_portfolio_import":
        args = parse_status(task)
        import_path = _extract(r"(?:file|path)[:=]\s*([^\s]+)", task) or ""
        summary = sync_observed_portfolio_import(
            account_profile_id=args["account_profile_id"],
            import_path=import_path,
            observed_at=when,
            account_source="statement_import",
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.sync_portfolio_import", **args, "import_path": import_path}
        result = dict(summary)
    elif intent.name == "sync_portfolio_ocr":
        args = parse_status(task)
        holdings = _extract_json_holdings(task)
        summary = sync_observed_portfolio_ocr(
            account_profile_id=args["account_profile_id"],
            holdings=holdings,
            observed_at=when,
            account_source="ocr_sync",
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.sync_portfolio_ocr", **args, "holding_count": len(holdings)}
        result = dict(summary)
    elif intent.name == "explain_probability":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        invocation = {"tool": "frontdesk.explain_probability", **args}
        result = {"workflow": "explain_probability", "explanation": build_probability_explanation(snapshot)}
    elif intent.name == "explain_plan_change":
        args = parse_status(task)
        user_state = load_user_state(args["account_profile_id"], db_path=db_path) or {}
        invocation = {"tool": "frontdesk.explain_plan_change", **args}
        result = {"workflow": "explain_plan_change", "explanation": build_plan_change_explanation(user_state)}
    elif intent.name == "explain_data_basis":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        invocation = {"tool": "frontdesk.explain_data_basis", **args}
        result = {"workflow": "explain_data_basis", "explanation": build_data_basis_explanation(snapshot)}
    elif intent.name == "explain_execution_policy":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        invocation = {"tool": "frontdesk.explain_execution_policy", **args}
        result = {"workflow": "explain_execution_policy", "execution_policy": build_execution_policy_explanation(snapshot)}
    elif intent.name == "daily_monitor":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        user_state = load_user_state(args["account_profile_id"], db_path=db_path) or {}
        invocation = {"tool": "frontdesk.daily_monitor", **args}
        result = {"workflow": "daily_monitor", **build_daily_monitor_summary(snapshot, user_state)}
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


def _extract_json_holdings(task: str) -> list[dict[str, Any]]:
    if "json:" not in task:
        return []
    payload = task.split("json:", 1)[1].strip()
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, list):
        return [dict(item or {}) for item in loaded if isinstance(item, dict)]
    return []


def write_log_record(task: str, *, output: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"openclaw-bridge-{ts}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task}, ensure_ascii=False) + "\n")
        f.write(json.dumps(output, ensure_ascii=False) + "\n")
    return path
