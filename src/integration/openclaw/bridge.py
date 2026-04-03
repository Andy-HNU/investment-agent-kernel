from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.nli_router import (
    Intent,
    parse_approve_plan,
    parse_event_context,
    parse_feedback,
    parse_onboarding,
    parse_status,
    route,
)
from frontdesk.service import (
    DEFAULT_DB_PATH,
    load_frontdesk_snapshot,
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
        args = parse_status(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"], workflow_type="monthly", db_path=db_path
        )
        invocation = {"tool": "frontdesk.followup.monthly", **args}
        result = dict(summary)
    elif intent.name == "quarterly":
        args = parse_status(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"], workflow_type="quarterly", db_path=db_path
        )
        invocation = {"tool": "frontdesk.followup.quarterly", **args}
        result = dict(summary)
    elif intent.name == "event":
        args = parse_status(task)
        event_context = parse_event_context(task)
        summary = run_frontdesk_followup(
            account_profile_id=args["account_profile_id"],
            workflow_type="event",
            db_path=db_path,
            event_request=bool(event_context),
            event_context=event_context or None,
        )
        invocation = {"tool": "frontdesk.followup.event", **args, "event_context": event_context}
        result = dict(summary)
    elif intent.name == "approve_plan":
        args = parse_approve_plan(task)
        summary = approve_frontdesk_execution_plan(
            account_profile_id=args["account_profile_id"],
            plan_id=args["plan_id"],
            plan_version=args["plan_version"],
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.approve_plan", **args}
        result = dict(summary)
    elif intent.name == "feedback":
        args = parse_feedback(task)
        summary = record_frontdesk_execution_feedback(
            account_profile_id=args["account_profile_id"],
            source_run_id=args["run_id"],
            user_executed=args["executed"],
            actual_action=args["actual_action"],
            note=args["note"],
            db_path=db_path,
        )
        invocation = {"tool": "frontdesk.feedback", **args}
        result = dict(summary)
    elif intent.name == "explain_probability":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        result = _explain_probability(snapshot)
        invocation = {"tool": "frontdesk.explain.probability", **args}
    elif intent.name == "explain_plan_change":
        args = parse_status(task)
        snapshot = load_frontdesk_snapshot(args["account_profile_id"], db_path=db_path) or {}
        result = _explain_plan_change(snapshot)
        invocation = {"tool": "frontdesk.explain.plan_change", **args}
    else:
        invocation = {"tool": "unknown"}
        result = {"workflow": "unknown", "status": "unsupported", "note": "intent not recognized"}

    return {
        "intent": asdict(intent),
        "invocation": invocation,
        "result": result,
        "at": when,
    }


def _explain_probability(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_run = dict(snapshot.get("latest_run") or {})
    decision_card = dict(latest_run.get("decision_card") or {})
    key_metrics = dict(decision_card.get("key_metrics") or {})
    highest = dict((latest_run.get("result_payload") or {}).get("highest_probability_result") or {})
    calibration_result = dict((latest_run.get("result_payload") or {}).get("calibration_result") or {})
    market_state = dict(calibration_result.get("market_state") or {})

    current_success = key_metrics.get("success_probability")
    highest_success = key_metrics.get("highest_probability_success")
    implied_return = key_metrics.get("implied_required_annual_return")
    simulation_mode = key_metrics.get("simulation_mode") or (latest_run.get("result_payload") or {}).get("simulation_mode_used")
    market_regime = market_state.get("risk_environment")
    volatility_regime = market_state.get("volatility_regime")

    lines: list[str] = []
    if current_success and highest_success:
        lines.append(f"当前推荐方案达成率为 {current_success}，最高概率方案达成率为 {highest_success}。")
    elif current_success:
        lines.append(f"当前推荐方案达成率为 {current_success}。")
    if implied_return:
        lines.append(f"当前目标隐含所需年化约为 {implied_return}。")
    if simulation_mode:
        lines.append(f"当前概率是基于 {simulation_mode} 模拟模式得出的。")
    if market_regime or volatility_regime:
        lines.append(
            "当前市场状态"
            f"{'风险环境=' + str(market_regime) if market_regime else ''}"
            f"{'，波动状态=' + str(volatility_regime) if volatility_regime else ''}。"
        )
    if highest.get("allocation_name") and highest_success and current_success and highest_success != current_success:
        lines.append(
            f"最高概率方案是 {highest.get('allocation_name')}，"
            "但系统推荐方案还会同时考虑回撤、约束与执行复杂度。"
        )
    explanation = "".join(lines) if lines else "当前缺少足够的决策卡指标，暂时无法解释概率变化。"
    return {
        "workflow": "explain_probability",
        "status": "explained",
        "explanation": explanation,
        "metrics": {
            "success_probability": current_success,
            "highest_probability_success": highest_success,
            "implied_required_annual_return": implied_return,
            "simulation_mode": simulation_mode,
            "market_regime": market_regime,
            "volatility_regime": volatility_regime,
        },
    }


def _explain_plan_change(snapshot: dict[str, Any]) -> dict[str, Any]:
    comparison = dict(snapshot.get("execution_plan_comparison") or {})
    latest_run = dict(snapshot.get("latest_run") or {})
    decision_card = dict(latest_run.get("decision_card") or {})
    guidance = dict(decision_card.get("execution_plan_guidance") or {})

    recommendation = guidance.get("recommendation") or comparison.get("recommendation")
    change_level = guidance.get("change_level") or comparison.get("change_level")
    changed_bucket_count = guidance.get("changed_bucket_count") or comparison.get("changed_bucket_count")
    product_switch_count = guidance.get("product_switch_count") or comparison.get("product_switch_count")
    max_weight_delta = guidance.get("max_weight_delta") or comparison.get("max_weight_delta")
    headline = guidance.get("headline")

    lines: list[str] = []
    if recommendation:
        lines.append(f"当前计划变更建议为 {recommendation}，变化级别是 {change_level or 'unknown'}。")
    if changed_bucket_count is not None or product_switch_count is not None:
        lines.append(
            f"本次共有 {changed_bucket_count or 0} 个资金桶发生变化，"
            f"{product_switch_count or 0} 个主产品发生切换。"
        )
    if max_weight_delta is not None:
        lines.append(f"最大权重变化约为 {max_weight_delta}。")
    if headline:
        lines.append(str(headline))
    explanation = "".join(lines) if lines else "当前没有可解释的 active vs pending plan 差异。"
    return {
        "workflow": "explain_plan_change",
        "status": "explained",
        "explanation": explanation,
        "comparison": comparison or None,
        "guidance": guidance or None,
    }


def write_log_record(task: str, *, output: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"openclaw-bridge-{ts}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task}, ensure_ascii=False) + "\n")
        f.write(json.dumps(output, ensure_ascii=False) + "\n")
    return path
