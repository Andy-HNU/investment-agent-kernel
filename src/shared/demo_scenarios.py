from __future__ import annotations

import re
from typing import Any

from demo_scenarios import (
    build_demo_aligned_prior_solver_input,
    build_demo_goal_solver_input,
    build_demo_live_portfolio,
    build_demo_monthly_raw_payload,
    build_demo_onboarding_payload,
    build_demo_quarterly_payload,
)
from orchestrator.engine import run_orchestrator


CANONICAL_DEMO_SCENARIOS = (
    "full_lifecycle",
    "onboarding",
    "monthly_followup",
    "monthly_replay_override",
    "quarterly_review",
    "provenance_blocked",
    "provenance_relaxed",
)

DEMO_SCENARIO_ALIASES = {
    "journey": "full_lifecycle",
    "quarterly_full_chain": "quarterly_review",
    "monthly_provenance_blocked": "provenance_blocked",
    "monthly_provenance_relaxed": "provenance_relaxed",
    "provenance_bypass": "provenance_relaxed",
}

DEMO_SCENARIOS = CANONICAL_DEMO_SCENARIOS + tuple(DEMO_SCENARIO_ALIASES)

_CANDIDATE_LABELS = {
    "defense_heavy": "防守优先方案",
    "balanced_core": "均衡核心方案",
    "growth_tilt": "增长倾向方案",
    "liquidity_buffered": "流动性缓冲方案",
    "theme_tilt": "主题增强方案",
    "satellite_light": "低卫星简化方案",
}
_CANDIDATE_ID_PATTERN = re.compile(r"^(?P<style>[a-z_]+)__(?P<risk>[a-z]+)__(?P<index>\d+)$")


def normalize_demo_scenario_name(name: str) -> str:
    scenario = DEMO_SCENARIO_ALIASES.get(name, name)
    if scenario not in CANONICAL_DEMO_SCENARIOS:
        raise ValueError(f"unsupported demo scenario: {name}")
    return scenario


def _serialize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        data = result.to_dict()
    else:
        data = dict(result)
    return _sanitize_user_payload(data)


def _sanitize_candidate_identifier(value: str) -> str:
    match = _CANDIDATE_ID_PATTERN.match(value)
    if not match:
        return value
    return _CANDIDATE_LABELS.get(match.group("style"), value)


def _sanitize_user_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_user_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_user_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_user_payload(item) for item in value)
    if isinstance(value, str):
        sanitized = _sanitize_candidate_identifier(value)
        if " allocation=" in sanitized:
            prefix, allocation = sanitized.split(" allocation=", 1)
            sanitized = f"{prefix} allocation={_sanitize_candidate_identifier(allocation)}"
        return sanitized
    return value


def _with_input_provenance(payload: dict[str, Any], *, workflow: str, event_request: bool = False) -> dict[str, Any]:
    enriched = dict(payload)
    if workflow == "onboarding":
        enriched["input_provenance"] = {
            "items": [
                {
                    "field": "profile",
                    "label": "账户画像",
                    "source_type": "user_provided",
                    "detail": "demo 假设这部分来自首次建档问答。",
                },
                {
                    "field": "holdings",
                    "label": "当前资产与持仓",
                    "source_type": "user_provided",
                    "detail": "demo 假设这部分来自用户提交的首次资产快照。",
                },
                {
                    "field": "goal",
                    "label": "目标与期限",
                    "source_type": "user_provided",
                    "detail": "demo 假设这部分来自用户设置的目标金额、期限和月投入。",
                },
                {
                    "field": "constraints",
                    "label": "风险约束",
                    "source_type": "user_provided",
                    "detail": "demo 假设这部分来自用户建档时填写的约束。",
                },
                {
                    "field": "market",
                    "label": "市场数据",
                    "source_type": "default_assumed",
                    "detail": "demo 使用内置市场假设，未连接实时行情源。",
                },
                {
                    "field": "behavior",
                    "label": "行为信号",
                    "source_type": "default_assumed",
                    "detail": "demo 未读取真实行为轨迹，采用默认行为值。",
                },
            ]
        }
        return enriched

    items = [
        {
            "field": "baseline",
            "label": "已有基线方案",
            "source_type": "system_inferred",
            "detail": "来自上一轮 onboarding 输出的基线方案。",
        },
        {
            "field": "goal",
            "label": "目标与期限",
            "source_type": "system_inferred",
            "detail": "本轮沿用首次建档时确认过的目标。",
        },
        {
            "field": "constraints",
            "label": "风险约束",
            "source_type": "system_inferred",
            "detail": "本轮默认沿用首次建档的约束设置。",
        },
        {
            "field": "holdings",
            "label": "当前资产与持仓",
            "source_type": "default_assumed",
            "detail": "demo 使用内置持仓快照，未连接券商或托管数据。",
        },
        {
            "field": "market",
            "label": "市场数据",
            "source_type": "default_assumed",
            "detail": "demo 使用内置市场快照，未连接实时行情源。",
        },
        {
            "field": "behavior",
            "label": "行为信号",
            "source_type": "system_inferred" if workflow == "event" else "default_assumed",
            "detail": (
                "demo 根据事件触发和人工复核标记生成行为信号。"
                if workflow == "event"
                else "demo 未读取真实行为轨迹，采用默认行为值。"
            ),
        },
    ]
    if event_request:
        items.append(
            {
                "field": "user_request",
                "label": "用户指令",
                "source_type": "user_provided",
                "detail": "demo 注入了一次用户主动要求调仓的事件请求。",
            }
        )
    enriched["input_provenance"] = {"items": items}
    return enriched


def _summary_from_result(result: Any) -> dict[str, Any]:
    data = _serialize_result(result)
    card = data.get("decision_card") or {}
    return {
        "run_id": data.get("run_id"),
        "workflow_type": data.get("workflow_type"),
        "status": data.get("status"),
        "bundle_id": data.get("bundle_id"),
        "calibration_id": data.get("calibration_id"),
        "solver_snapshot_id": data.get("solver_snapshot_id"),
        "card_type": card.get("card_type"),
        "status_badge": card.get("status_badge"),
        "summary": card.get("summary"),
        "recommended_action": card.get("recommended_action"),
        "primary_recommendation": card.get("primary_recommendation"),
        "guardrails": card.get("guardrails", []),
        "input_provenance": card.get("input_provenance", {}),
        "candidate_options": card.get("candidate_options", []),
        "review_conditions": card.get("review_conditions", []),
        "next_steps": card.get("next_steps", []),
        "trace_refs": card.get("trace_refs", {}),
    }


def _bootstrap_onboarding_result() -> Any:
    return run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": "demo_onboarding"},
        raw_inputs=_with_input_provenance(build_demo_onboarding_payload(), workflow="onboarding"),
    )


def _bootstrap_context(onboarding_result: Any | None = None) -> tuple[Any, dict[str, Any]]:
    onboarding_result = onboarding_result or _bootstrap_onboarding_result()
    aligned_prior_input = build_demo_aligned_prior_solver_input(onboarding_result.goal_solver_output)
    return onboarding_result, aligned_prior_input


def run_demo_onboarding() -> Any:
    return _bootstrap_onboarding_result()


def run_demo_monthly_followup(onboarding_result: Any | None = None) -> Any:
    onboarding_result, aligned_prior_input = _bootstrap_context(onboarding_result)
    return run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "demo_monthly_followup"},
        raw_inputs=_with_input_provenance(
            build_demo_monthly_raw_payload(as_of="2026-03-29T14:00:00Z"),
            workflow="monthly",
        ),
        prior_solver_output=onboarding_result.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=onboarding_result.calibration_result,
    )


def run_demo_monthly_replay_override(onboarding_result: Any | None = None) -> Any:
    onboarding_result, aligned_prior_input = _bootstrap_context(onboarding_result)
    return run_orchestrator(
        trigger={
            "workflow_type": "monthly",
            "run_id": "demo_monthly_replay_override",
            "manual_override_requested": True,
        },
        raw_inputs=_with_input_provenance(
            build_demo_monthly_raw_payload(
                as_of="2026-03-29T15:00:00Z",
                replay_mode=True,
            ),
            workflow="monthly",
        ),
        prior_solver_output=onboarding_result.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=onboarding_result.calibration_result,
    )


def run_demo_quarterly_review(*, prior_calibration: Any | None = None) -> Any:
    return run_orchestrator(
        trigger={"workflow_type": "quarterly", "run_id": "demo_quarterly_review"},
        raw_inputs=_with_input_provenance(
            build_demo_quarterly_payload(as_of="2026-03-29T13:00:00Z"),
            workflow="quarterly",
        ),
        prior_calibration=prior_calibration,
    )


def run_demo_provenance_blocked(onboarding_result: Any | None = None) -> Any:
    onboarding_result, aligned_prior_input = _bootstrap_context(onboarding_result)
    return run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "demo_provenance_blocked"},
        raw_inputs=_with_input_provenance(
            {
                "bundle_id": "bundle_demo_runtime_new",
                "snapshot_bundle": {"bundle_id": "bundle_demo_runtime_new"},
                "calibration_result": onboarding_result.calibration_result,
                "live_portfolio": build_demo_live_portfolio(),
            },
            workflow="monthly",
        ),
        prior_solver_output=onboarding_result.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=onboarding_result.calibration_result,
    )


def run_demo_provenance_relaxed(onboarding_result: Any | None = None) -> Any:
    onboarding_result, aligned_prior_input = _bootstrap_context(onboarding_result)
    return run_orchestrator(
        trigger={"workflow_type": "monthly", "run_id": "demo_provenance_relaxed"},
        raw_inputs=_with_input_provenance(
            {
                "bundle_id": "bundle_demo_raw_override",
                "snapshot_bundle": {"bundle_id": "bundle_demo_snapshot"},
                "calibration_result": onboarding_result.calibration_result,
                "live_portfolio": build_demo_live_portfolio(),
                "control_flags": {"disable_provenance_checks": True},
            },
            workflow="monthly",
        ),
        prior_solver_output=onboarding_result.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=onboarding_result.calibration_result,
    )


def _run_demo_event_manual_review(
    onboarding_result: Any,
    monthly_result: Any,
    aligned_prior_input: dict[str, Any],
) -> Any:
    event_payload = build_demo_monthly_raw_payload(
        as_of="2026-03-29T15:00:00Z",
        cooldown_active=True,
        cooldown_until="2026-04-05T00:00:00Z",
    )
    event_payload["user_request_context"] = {"requested_action": "rebalance_full"}
    event_payload = _with_input_provenance(event_payload, workflow="event", event_request=True)
    return run_orchestrator(
        trigger={
            "run_id": "demo_event",
            "behavior_event": True,
            "manual_review_requested": True,
        },
        raw_inputs=event_payload,
        prior_solver_output=onboarding_result.goal_solver_output,
        prior_solver_input=aligned_prior_input,
        prior_calibration=monthly_result.calibration_result,
    )


def run_demo_lifecycle() -> dict[str, Any]:
    onboarding, aligned_prior_input = _bootstrap_context()
    monthly = run_demo_monthly_followup(onboarding)
    event = _run_demo_event_manual_review(onboarding, monthly, aligned_prior_input)
    quarterly = run_orchestrator(
        trigger={"workflow_type": "quarterly", "run_id": "demo_quarterly"},
        raw_inputs=_with_input_provenance(
            build_demo_quarterly_payload(as_of="2026-03-29T13:00:00Z"),
            workflow="quarterly",
        ),
    )

    return {
        "inputs": {
            "goal_solver_input": build_demo_goal_solver_input(),
            "live_portfolio": build_demo_live_portfolio(),
        },
        "results": {
            "onboarding": onboarding,
            "monthly": monthly,
            "event": event,
            "quarterly": quarterly,
        },
    }


def summarize_demo_lifecycle(lifecycle: dict[str, Any]) -> dict[str, Any]:
    results = lifecycle["results"]
    return {
        "phase_order": ["onboarding", "monthly", "event", "quarterly"],
        "results": {
            phase: _summary_from_result(results[phase])
            for phase in ("onboarding", "monthly", "event", "quarterly")
        },
    }


def build_demo_report(scenario: str) -> dict[str, Any]:
    requested_scenario = scenario
    scenario = normalize_demo_scenario_name(scenario)

    if scenario == "full_lifecycle":
        lifecycle = run_demo_lifecycle()
        report = {
            "scenario": scenario,
            "summary": summarize_demo_lifecycle(lifecycle),
            "results": {
                phase: _serialize_result(result)
                for phase, result in lifecycle["results"].items()
            },
        }
        if requested_scenario != scenario:
            report["requested_scenario"] = requested_scenario
        return report

    if scenario == "onboarding":
        report = {
            "scenario": scenario,
            "bootstrap": None,
            "result": _serialize_result(run_demo_onboarding()),
        }
        if requested_scenario != scenario:
            report["requested_scenario"] = requested_scenario
        return report

    if scenario == "monthly_followup":
        bootstrap = run_demo_onboarding()
        report = {
            "scenario": scenario,
            "bootstrap": _serialize_result(bootstrap),
            "result": _serialize_result(run_demo_monthly_followup(bootstrap)),
        }
    elif scenario == "monthly_replay_override":
        bootstrap = run_demo_onboarding()
        report = {
            "scenario": scenario,
            "bootstrap": _serialize_result(bootstrap),
            "result": _serialize_result(run_demo_monthly_replay_override(bootstrap)),
        }
    elif scenario == "quarterly_review":
        report = {
            "scenario": scenario,
            "bootstrap": None,
            "result": _serialize_result(run_demo_quarterly_review()),
        }
    elif scenario == "provenance_blocked":
        bootstrap = run_demo_onboarding()
        report = {
            "scenario": scenario,
            "bootstrap": _serialize_result(bootstrap),
            "result": _serialize_result(run_demo_provenance_blocked(bootstrap)),
        }
    else:
        bootstrap = run_demo_onboarding()
        report = {
            "scenario": scenario,
            "bootstrap": _serialize_result(bootstrap),
            "result": _serialize_result(run_demo_provenance_relaxed(bootstrap)),
        }

    if requested_scenario != scenario:
        report["requested_scenario"] = requested_scenario
    return report


def render_demo_report(report: dict[str, Any]) -> str:
    if report["scenario"] == "full_lifecycle":
        summary = report["summary"]
        lines = [f"scenario={report['scenario']}"]
        if report.get("requested_scenario"):
            lines.append(f"requested_scenario={report['requested_scenario']}")
        for phase in summary["phase_order"]:
            phase_result = summary["results"][phase]
            lines.extend(
                [
                    f"{phase}.status={phase_result['status']}",
                    f"{phase}.workflow={phase_result['workflow_type']}",
                    f"{phase}.card_type={phase_result['card_type']}",
                    f"{phase}.recommended_action={phase_result['recommended_action']}",
                ]
            )
        return "\n".join(lines)

    result = report["result"]
    card = result.get("decision_card") or {}
    lines = [f"scenario={report['scenario']}"]
    if report.get("requested_scenario"):
        lines.append(f"requested_scenario={report['requested_scenario']}")
    bootstrap = report.get("bootstrap")
    if bootstrap is not None:
        lines.extend(
            [
                f"bootstrap.status={bootstrap['status']}",
                f"bootstrap.workflow={bootstrap['workflow_type']}",
                f"bootstrap.bundle_id={bootstrap.get('bundle_id')}",
            ]
        )
    lines.extend(
        [
            f"result.status={result['status']}",
            f"result.workflow={result['workflow_type']}",
            f"result.run_id={result['run_id']}",
            f"card.card_type={card.get('card_type')}",
            f"card.status_badge={card.get('status_badge')}",
            f"card.primary_recommendation={card.get('primary_recommendation')}",
            f"card.summary={card.get('summary')}",
        ]
    )
    input_provenance = card.get("input_provenance") or {}
    provenance_items = input_provenance.get("items") or []
    if provenance_items:
        lines.append(
            "card.input_provenance="
            + "; ".join(
                f"{item.get('label')}:{item.get('source_type')}"
                for item in provenance_items
            )
        )
    candidate_options = card.get("candidate_options") or []
    for index, option in enumerate(candidate_options[:3], start=1):
        metrics = option.get("metrics") or {}
        lines.append(
            f"card.candidate_{index}="
            f"{option.get('label')}|{option.get('highlight')}|"
            f"success={metrics.get('success_probability')}|"
            f"drawdown={metrics.get('max_drawdown_90pct')}"
        )
    if card.get("guardrails"):
        lines.append("card.guardrails=" + ", ".join(card["guardrails"]))
    if card.get("review_conditions"):
        lines.append("card.review_conditions=" + ", ".join(card["review_conditions"]))
    if card.get("next_steps"):
        lines.append("card.next_steps=" + ", ".join(card["next_steps"]))
    return "\n".join(lines)
