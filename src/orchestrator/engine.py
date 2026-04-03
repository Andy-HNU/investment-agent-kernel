from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from allocation_engine.engine import run_allocation_engine
from calibration.engine import run_calibration
from decision_card.builder import build_decision_card
from decision_card.types import DecisionCardBuildInput, DecisionCardType
from goal_solver.engine import run_goal_solver
from product_mapping import build_execution_plan
from runtime_optimizer.engine import run_runtime_optimizer
from runtime_optimizer.types import RuntimeOptimizerMode
from snapshot_ingestion.engine import build_snapshot_bundle

from orchestrator.types import (
    OrchestratorAuditRecord,
    OrchestratorPersistencePlan,
    OrchestratorResult,
    RuntimeRestriction,
    TriggerSignal,
    WorkflowDecision,
    WorkflowStatus,
    WorkflowType,
)


_GOAL_SOLVER_CONSTRAINT_FIELDS = (
    "max_drawdown_tolerance",
    "ips_bucket_boundaries",
    "satellite_cap",
    "theme_caps",
    "qdii_cap",
    "liquidity_reserve_min",
    "bucket_category",
    "bucket_to_theme",
)

_SAFE_ACTION_TYPES = ("freeze", "observe")
_HIGH_RISK_ACTION_TYPES = {
    "rebalance_full",
    "sell_all",
    "switch_all",
    "all_in_equity",
    "all_in_satellite",
    "chase_hot_theme",
    "add_cash_sat",
    "reduce_defense",
}


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    data = _obj(value)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(getattr(value, "value", value)).strip()
    return normalized or None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = _text(value)
    if text is None:
        return False
    normalized = text.lower()
    if normalized in {"0", "false", "no", "n", "off", "none", ""}:
        return False
    if normalized in {"1", "true", "yes", "y", "on", "required", "active"}:
        return True
    return bool(normalized)


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text is not None:
            return text
    return None


def _utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _has_any_raw_snapshot_inputs(envelope: dict[str, Any]) -> bool:
    return any(
        key in envelope
        for key in (
            "market_raw",
            "account_raw",
            "goal_raw",
            "constraint_raw",
            "behavior_raw",
            "as_of",
            "snapshot_as_of",
        )
    )


def _snapshot_build_context(
    envelope: dict[str, Any],
    prior_solver_input: Any | None,
) -> tuple[dict[str, Any], list[str]]:
    baseline_input = _as_dict(envelope.get("goal_solver_input") or prior_solver_input)
    allocation_input = _as_dict(envelope.get("allocation_engine_input"))
    allocation_profile = _as_dict(allocation_input.get("account_profile"))
    live_portfolio = _as_dict(envelope.get("live_portfolio"))

    account_profile_id = _first_text(
        envelope.get("account_profile_id"),
        baseline_input.get("account_profile_id"),
        allocation_profile.get("account_profile_id"),
    )
    as_of = _utc_datetime(envelope.get("as_of")) or _utc_datetime(envelope.get("snapshot_as_of"))
    market_raw = _as_dict(envelope.get("market_raw"))
    account_raw = _as_dict(envelope.get("account_raw")) or live_portfolio
    goal_raw = _as_dict(envelope.get("goal_raw")) or _as_dict(baseline_input.get("goal"))
    constraint_raw = _as_dict(envelope.get("constraint_raw")) or _as_dict(baseline_input.get("constraints"))
    behavior_raw = envelope.get("behavior_raw")
    remaining_horizon_months = envelope.get("remaining_horizon_months")
    if remaining_horizon_months is None:
        remaining_horizon_months = (
            _as_dict(goal_raw).get("horizon_months")
            or _as_dict(account_raw).get("remaining_horizon_months")
            or _as_dict(baseline_input.get("goal")).get("horizon_months")
        )

    missing: list[str] = []
    if account_profile_id is None:
        missing.append("account_profile_id")
    if as_of is None:
        missing.append("as_of")
    if not market_raw:
        missing.append("market_raw")
    if not account_raw:
        missing.append("account_raw")
    if not goal_raw:
        missing.append("goal_raw")
    if not constraint_raw:
        missing.append("constraint_raw")
    if remaining_horizon_months is None:
        missing.append("remaining_horizon_months")

    return (
        {
            "account_profile_id": account_profile_id,
            "as_of": as_of,
            "market_raw": market_raw,
            "account_raw": account_raw,
            "goal_raw": goal_raw,
            "constraint_raw": constraint_raw,
            "behavior_raw": None if behavior_raw is None else _as_dict(behavior_raw),
            "policy_news_signals": list(
                envelope.get("policy_news_signals")
                or _as_dict(market_raw).get("policy_news_signals")
                or []
            ),
            "remaining_horizon_months": remaining_horizon_months,
            "historical_dataset_metadata": _as_dict(envelope.get("historical_dataset_metadata")),
            "schema_version": _first_text(envelope.get("snapshot_schema_version"), "v1.0"),
        },
        missing,
    )


def _resolve_snapshot_bundle(
    envelope: dict[str, Any],
    prior_solver_input: Any | None,
    blocking_reasons: list[str],
) -> tuple[Any | None, str]:
    provided_snapshot_bundle = envelope.get("snapshot_bundle")
    if provided_snapshot_bundle is not None:
        return provided_snapshot_bundle, "provided"
    if not _has_any_raw_snapshot_inputs(envelope):
        return None, "absent"

    context, missing = _snapshot_build_context(envelope, prior_solver_input)
    if missing:
        blocking_reasons.append(
            "raw snapshot inputs incomplete: " + ", ".join(missing)
        )
        return None, "incomplete"

    return (
        build_snapshot_bundle(
            account_profile_id=str(context["account_profile_id"]),
            as_of=context["as_of"],
            market_raw=context["market_raw"],
            account_raw=context["account_raw"],
            goal_raw=context["goal_raw"],
            constraint_raw=context["constraint_raw"],
            behavior_raw=context["behavior_raw"],
            remaining_horizon_months=int(context["remaining_horizon_months"]),
            policy_news_signals=context["policy_news_signals"],
            historical_dataset_metadata=context["historical_dataset_metadata"] or None,
            schema_version=str(context["schema_version"]),
        ),
        "generated",
    )


def _snapshot_bundle_has_required_domains(snapshot_bundle: Any) -> bool:
    data = _as_dict(snapshot_bundle)
    return all(data.get(field) not in (None, {}) for field in ("market", "account", "goal", "constraint"))


def _calibration_manual_override_requested(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
) -> bool:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    request_context = _as_dict(envelope.get("user_request_context"))
    return any(
        _bool(value)
        for value in (
            control_flags.get("manual_override_requested"),
            control_flags.get("override_requested"),
            review_context.get("manual_override_requested"),
            request_context.get("manual_override_requested"),
            trigger.manual_override_requested,
            envelope.get("manual_override_requested"),
            envelope.get("override_requested"),
        )
    )


def _calibration_replay_mode(envelope: dict[str, Any]) -> bool:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    return any(
        _bool(value)
        for value in (
            control_flags.get("replay_mode"),
            control_flags.get("replay_requested"),
            review_context.get("replay_mode"),
            envelope.get("replay_mode"),
            envelope.get("replay_requested"),
        )
    )


def _calibration_updated_reason(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
    *,
    manual_override: bool,
    replay_mode: bool,
) -> str | None:
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    explicit = _first_text(
        control_flags.get("updated_reason"),
        review_context.get("updated_reason"),
        envelope.get("updated_reason"),
    )
    if explicit is not None:
        return explicit
    if manual_override or replay_mode:
        return None
    if trigger.workflow_type == WorkflowType.ONBOARDING:
        return "onboarding_calibration"
    if trigger.workflow_type == WorkflowType.QUARTERLY:
        return "quarterly_calibration"
    if trigger.workflow_type == WorkflowType.EVENT:
        return "event_calibration"
    return "monthly_calibration"


def _resolve_calibration_result(
    envelope: dict[str, Any],
    trigger: TriggerSignal,
    snapshot_bundle: Any | None,
    snapshot_bundle_origin: str,
    prior_calibration: Any | None,
    prior_solver_input: Any | None,
) -> tuple[Any | None, str]:
    provided_calibration = envelope.get("calibration_result")
    if provided_calibration is not None:
        return provided_calibration, "provided"
    if snapshot_bundle is None:
        if prior_calibration is None:
            return None, "absent"
        return prior_calibration, "prior"
    if snapshot_bundle_origin != "generated" and not _snapshot_bundle_has_required_domains(snapshot_bundle):
        if prior_calibration is None:
            return None, "absent"
        return prior_calibration, "prior"

    baseline_input = _as_dict(envelope.get("goal_solver_input") or prior_solver_input)
    manual_override = _calibration_manual_override_requested(envelope, trigger)
    replay_mode = _calibration_replay_mode(envelope)
    updated_reason = _calibration_updated_reason(
        envelope,
        trigger,
        manual_override=manual_override,
        replay_mode=replay_mode,
    )
    return (
        run_calibration(
            snapshot_bundle,
            prior_calibration=prior_calibration,
            default_goal_solver_params=baseline_input.get("solver_params"),
            default_runtime_params=envelope.get("default_runtime_optimizer_params"),
            default_ev_params=envelope.get("default_ev_params"),
            updated_reason=updated_reason,
            manual_override=manual_override,
            replay_mode=replay_mode,
        ),
        "generated",
    )


def _requested_workflow_from_any(value: TriggerSignal | dict[str, Any]) -> WorkflowType | None:
    if isinstance(value, TriggerSignal):
        return value.workflow_type
    data = _as_dict(value)
    if "workflow_type" not in data:
        return None
    raw = data.get("workflow_type")
    if raw in {None, "", "auto"}:
        return None
    return WorkflowType(str(getattr(raw, "value", raw)))


def _requested_action_from_inputs(envelope: dict[str, Any]) -> str | None:
    request_context = _as_dict(envelope.get("user_request_context"))
    control_flags = _as_dict(envelope.get("control_flags"))
    return _first_text(
        request_context.get("requested_action"),
        request_context.get("action_type"),
        request_context.get("request_type"),
        control_flags.get("requested_action"),
        control_flags.get("action_type"),
        envelope.get("requested_action"),
    )


def _is_high_risk_request(envelope: dict[str, Any]) -> bool:
    request_context = _as_dict(envelope.get("user_request_context"))
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    explicit_flag = any(
        _bool(value)
        for value in (
            request_context.get("high_risk_request"),
            request_context.get("high_risk_action_request"),
            request_context.get("high_heat_narrative_request"),
            request_context.get("hot_theme_request"),
            control_flags.get("high_risk_request"),
            control_flags.get("high_risk_action_request"),
            control_flags.get("high_heat_narrative_request"),
            review_context.get("high_risk_request"),
            envelope.get("high_risk_request"),
            envelope.get("high_risk_action_request"),
        )
    )
    if explicit_flag:
        return True

    risk_level = _first_text(
        request_context.get("risk_level"),
        request_context.get("requested_action_risk_level"),
        control_flags.get("risk_level"),
        envelope.get("risk_level"),
    )
    if risk_level is not None and risk_level.lower() in {"high", "elevated"}:
        return True

    requested_action = _requested_action_from_inputs(envelope)
    return requested_action is not None and requested_action.lower() in _HIGH_RISK_ACTION_TYPES


def _extract_control_flags(
    envelope: dict[str, Any],
    calibration_data: dict[str, Any],
    trigger: TriggerSignal,
) -> dict[str, Any]:
    behavior_state = _as_dict(calibration_data.get("behavior_state"))
    constraint_state = _as_dict(calibration_data.get("constraint_state"))
    control_flags = _as_dict(envelope.get("control_flags"))
    review_context = _as_dict(envelope.get("review_context"))
    request_context = _as_dict(envelope.get("user_request_context"))

    manual_review_requested = any(
        _bool(value)
        for value in (
            control_flags.get("manual_review_requested"),
            control_flags.get("require_manual_review"),
            review_context.get("manual_review_requested"),
            review_context.get("require_manual_review"),
            request_context.get("manual_review_requested"),
            trigger.manual_review_requested,
            envelope.get("manual_review_requested"),
            envelope.get("require_manual_review"),
        )
    )
    manual_override_requested = any(
        _bool(value)
        for value in (
            control_flags.get("manual_override_requested"),
            control_flags.get("override_requested"),
            review_context.get("manual_override_requested"),
            request_context.get("manual_override_requested"),
            trigger.manual_override_requested,
            envelope.get("manual_override_requested"),
            envelope.get("override_requested"),
        )
    )
    quarterly_review_requested = any(
        _bool(value)
        for value in (
            control_flags.get("quarterly_review"),
            control_flags.get("quarterly_review_requested"),
            review_context.get("quarterly_review"),
            review_context.get("quarterly_review_requested"),
            envelope.get("quarterly_review"),
            envelope.get("quarterly_review_requested"),
        )
    )
    force_full_recalc = any(
        _bool(value)
        for value in (
            control_flags.get("force_full_recalc"),
            control_flags.get("force_recompute_baseline"),
            review_context.get("force_full_recalc"),
            review_context.get("force_recompute_baseline"),
            trigger.force_full_review,
            envelope.get("force_full_recalc"),
            envelope.get("force_recompute_baseline"),
        )
    )
    major_parameter_update = any(
        _bool(value)
        for value in (
            control_flags.get("major_parameter_update"),
            review_context.get("major_parameter_update"),
            envelope.get("major_parameter_update"),
        )
    )
    high_risk_request = trigger.high_risk_request or _is_high_risk_request(envelope)
    requested_action = _requested_action_from_inputs(envelope)
    cooldown_active = any(
        _bool(value)
        for value in (
            behavior_state.get("cooldown_active"),
            constraint_state.get("cooldown_currently_active"),
        )
    )

    return {
        "manual_review_requested": manual_review_requested,
        "manual_override_requested": manual_override_requested,
        "quarterly_review_requested": quarterly_review_requested,
        "force_full_recalc": force_full_recalc,
        "major_parameter_update": major_parameter_update,
        "high_risk_request": high_risk_request,
        "requested_action": requested_action,
        "cooldown_active": cooldown_active,
        "override_count_90d": int(behavior_state.get("override_count_90d", 0) or 0),
        "cooldown_until": behavior_state.get("cooldown_until"),
        "audit_mode": any(
            _bool(value)
            for value in (
                control_flags.get("audit_mode"),
                envelope.get("audit_mode"),
            )
        ),
        "enforce_provenance_checks": not any(
            _bool(value)
            for value in (
                control_flags.get("disable_provenance_checks"),
                review_context.get("disable_provenance_checks"),
                envelope.get("disable_provenance_checks"),
            )
        ),
        "allow_degraded_continue": any(
            _bool(value)
            for value in (
                control_flags.get("allow_degraded_continue"),
                envelope.get("allow_degraded_continue"),
            )
        ),
    }


def _select_workflow(
    requested_workflow: WorkflowType | None,
    trigger: TriggerSignal,
    envelope: dict[str, Any],
    prior_solver_output: Any | None,
    prior_solver_input: Any | None,
    control_flags: dict[str, Any],
) -> WorkflowDecision:
    has_prior_baseline = prior_solver_output is not None and prior_solver_input is not None
    has_rebuild_inputs = (
        _has_any_raw_snapshot_inputs(envelope)
        or (
            envelope.get("allocation_engine_input") is not None
            and envelope.get("goal_solver_input") is not None
        )
    )
    has_event_signal = any(
        (
            trigger.structural_event,
            trigger.behavior_event,
            trigger.drawdown_event,
            trigger.satellite_event,
            control_flags["manual_review_requested"],
            control_flags["manual_override_requested"],
            control_flags["high_risk_request"],
        )
    )
    quarterly_signal = any(
        (
            control_flags["quarterly_review_requested"],
            control_flags["force_full_recalc"],
            control_flags["major_parameter_update"],
        )
    )

    if has_event_signal and has_prior_baseline:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.EVENT,
            selection_reason="event_signal_detected",
            auto_selected=requested_workflow != WorkflowType.EVENT,
        )
    if requested_workflow == WorkflowType.QUARTERLY or quarterly_signal:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.QUARTERLY,
            selection_reason="quarterly_review_requested",
            auto_selected=requested_workflow != WorkflowType.QUARTERLY,
        )
    if not has_prior_baseline and (has_rebuild_inputs or requested_workflow == WorkflowType.ONBOARDING):
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.ONBOARDING,
            selection_reason="missing_prior_baseline",
            auto_selected=requested_workflow != WorkflowType.ONBOARDING,
        )
    if requested_workflow == WorkflowType.EVENT:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.EVENT,
            selection_reason="explicit_event_request",
            auto_selected=False,
        )
    if requested_workflow == WorkflowType.ONBOARDING:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.ONBOARDING,
            selection_reason="explicit_onboarding_request",
            auto_selected=False,
        )
    if requested_workflow == WorkflowType.MONTHLY:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.MONTHLY,
            selection_reason="explicit_monthly_request",
            auto_selected=False,
        )
    if has_prior_baseline:
        return WorkflowDecision(
            requested_workflow_type=requested_workflow,
            selected_workflow_type=WorkflowType.MONTHLY,
            selection_reason="default_monthly_with_prior_baseline",
            auto_selected=True,
        )
    return WorkflowDecision(
        requested_workflow_type=requested_workflow,
        selected_workflow_type=WorkflowType.ONBOARDING,
        selection_reason="default_onboarding_without_prior_baseline",
        auto_selected=True,
    )


def _trigger_from_any(value: TriggerSignal | dict[str, Any]) -> TriggerSignal:
    if isinstance(value, TriggerSignal):
        return value
    data = dict(_obj(value))
    workflow_type_raw = data.get("workflow_type", WorkflowType.MONTHLY.value)
    if workflow_type_raw in {None, "", "auto"}:
        workflow_type = WorkflowType.MONTHLY
    else:
        workflow_type = WorkflowType(str(getattr(workflow_type_raw, "value", workflow_type_raw)))
    return TriggerSignal(
        workflow_type=workflow_type,
        run_id=str(data.get("run_id", "")),
        structural_event=bool(data.get("structural_event", False)),
        behavior_event=bool(data.get("behavior_event", False)),
        drawdown_event=bool(data.get("drawdown_event", False)),
        satellite_event=bool(data.get("satellite_event", False)),
        manual_review_requested=bool(data.get("manual_review_requested", False)),
        manual_override_requested=bool(data.get("manual_override_requested", False)),
        high_risk_request=bool(data.get("high_risk_request", False)),
        force_full_review=bool(data.get("force_full_review", False)),
    )


def _build_run_id(run_id: str, workflow_type: WorkflowType) -> str:
    if run_id:
        return run_id
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"{workflow_type.value}_{timestamp}"


def _card_type_for_workflow(
    workflow_type: WorkflowType,
    blocked: bool,
) -> DecisionCardType:
    if blocked:
        return DecisionCardType.BLOCKED
    if workflow_type == WorkflowType.ONBOARDING:
        return DecisionCardType.GOAL_BASELINE
    if workflow_type == WorkflowType.QUARTERLY:
        return DecisionCardType.QUARTERLY_REVIEW
    return DecisionCardType.RUNTIME_ACTION


def _build_input_provenance(
    envelope: dict[str, Any],
    workflow_type: WorkflowType,
    *,
    has_prior_baseline: bool,
) -> dict[str, Any]:
    explicit = envelope.get("input_provenance")
    if explicit is not None:
        data = _as_dict(explicit)
        if isinstance(data.get("items"), list):
            normalized = {
                "items": list(data.get("items", [])),
                "user_provided": [],
                "system_inferred": [],
                "default_assumed": [],
                "externally_fetched": [],
            }
            for item in data.get("items", []):
                entry = _as_dict(item)
                source_type = _text(entry.get("source_type")) or "default_assumed"
                if source_type == "external_data":
                    source_type = "externally_fetched"
                normalized.setdefault(source_type, []).append(entry)
            return normalized
        normalized = {
            "user_provided": list(data.get("user_provided", [])) if isinstance(data.get("user_provided", []), list) else [],
            "system_inferred": list(data.get("system_inferred", [])) if isinstance(data.get("system_inferred", []), list) else [],
            "default_assumed": list(data.get("default_assumed", [])) if isinstance(data.get("default_assumed", []), list) else [],
            "externally_fetched": list(data.get("externally_fetched", [])) if isinstance(data.get("externally_fetched", []), list) else [],
        }
        return normalized

    provenance = {
        "user_provided": [],
        "system_inferred": [],
        "default_assumed": [],
        "externally_fetched": [],
    }

    def add(field: str, label: str, source_type: str, detail: str) -> None:
        normalized_source = "externally_fetched" if source_type == "external_data" else source_type
        provenance.setdefault(normalized_source, []).append(
            {
                "field": field,
                "label": label,
                "source_type": normalized_source,
                "detail": detail,
            }
        )

    if workflow_type == WorkflowType.ONBOARDING:
        add(
            "profile",
            "账户画像",
            "user_provided" if envelope.get("account_profile_id") is not None else "default_assumed",
            "首次建档时录入的账户与风险偏好信息。",
        )
        add(
            "holdings",
            "当前资产与持仓",
            "user_provided" if any(key in envelope for key in ("account_raw", "live_portfolio")) else "default_assumed",
            "来自本轮建档时提交的资产快照；未显式标注时按用户输入处理。",
        )
        add(
            "goal",
            "目标与期限",
            "user_provided" if any(key in envelope for key in ("goal_raw", "goal_solver_input")) else "default_assumed",
            "来自首次建档时填写的目标期末总资产、期限和月投入。",
        )
        add(
            "constraints",
            "风险约束",
            "user_provided" if any(key in envelope for key in ("constraint_raw", "goal_solver_input")) else "default_assumed",
            "来自建档时填写的回撤约束和投资限制。",
        )
    else:
        add(
            "baseline",
            "已有基线方案",
            "system_inferred" if has_prior_baseline else "default_assumed",
            "来自上一轮建档或季度复审沉淀的正式基线。",
        )
        add(
            "goal",
            "目标与期限",
            "system_inferred" if has_prior_baseline else "user_provided",
            "本轮沿用上一轮确认过的目标与期限，除非用户重新提交。",
        )
        add(
            "constraints",
            "风险约束",
            "system_inferred" if has_prior_baseline else "user_provided",
            "本轮默认沿用上一轮约束配置，除非用户主动修改。",
        )

    add(
        "market",
        "市场数据",
        "external_data" if any(key in envelope for key in ("market_raw", "market_state")) else "default_assumed",
        "若未显式标注来源，则仅表示系统收到一份市场快照，并不保证为实时抓取。",
    )
    add(
        "behavior",
        "行为信号",
        "system_inferred" if envelope.get("behavior_raw") is not None else "default_assumed",
        "来自系统对近期行为、复核请求和冷静期状态的推断或默认值。",
    )
    if envelope.get("user_request_context") is not None:
        add(
            "user_request",
            "用户指令",
            "user_provided",
            "来自本轮用户明确提出的动作请求。",
        )

    return provenance


def _whole_number_text(value: Any) -> str:
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return _text(value) or ""


def _goal_amount_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _text(value) or ""
    if numeric >= 10000 and numeric % 10000 == 0:
        return f"{int(numeric / 10000)}万"
    return _whole_number_text(numeric)


def _horizon_text(months: Any) -> str:
    try:
        month_count = int(months)
    except (TypeError, ValueError):
        return _text(months) or ""
    if month_count > 0 and month_count % 12 == 0:
        return f"{month_count // 12}年"
    return f"{month_count}个月"


def _drawdown_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _text(value) or ""
    if numeric <= 1.0:
        numeric *= 100.0
    return f"{int(round(numeric))}%"


def _build_goal_fallback_suggestions(goal_solver_input: Any) -> list[dict[str, Any]]:
    baseline = _as_dict(goal_solver_input)
    if not baseline:
        return []

    goal = _as_dict(baseline.get("goal"))
    cashflow_plan = _as_dict(baseline.get("cashflow_plan"))
    constraints = _as_dict(baseline.get("constraints"))

    current_months = int(goal.get("horizon_months", 0) or 0)
    current_goal_amount = float(goal.get("goal_amount", 0.0) or 0.0)
    current_monthly = float(cashflow_plan.get("monthly_contribution", 0.0) or 0.0)
    current_drawdown = float(constraints.get("max_drawdown_tolerance", 0.0) or 0.0)

    scenario_inputs: list[tuple[str, dict[str, Any]]] = []

    extend_horizon = deepcopy(baseline)
    extend_horizon_goal = _as_dict(extend_horizon.get("goal"))
    extend_horizon_goal["horizon_months"] = current_months + 12
    extend_horizon["goal"] = extend_horizon_goal
    scenario_inputs.append(
        (
            f"把期限从{_horizon_text(current_months)}延长到{_horizon_text(current_months + 12)}",
            extend_horizon,
        )
    )

    reduce_goal = deepcopy(baseline)
    reduce_goal_goal = _as_dict(reduce_goal.get("goal"))
    reduced_goal_amount = round(current_goal_amount * 0.9, -4 if current_goal_amount >= 100000 else -3)
    reduce_goal_goal["goal_amount"] = reduced_goal_amount
    reduce_goal["goal"] = reduce_goal_goal
    scenario_inputs.append(
        (
            f"把目标期末总资产从{_goal_amount_text(current_goal_amount)}下调到{_goal_amount_text(reduced_goal_amount)}",
            reduce_goal,
        )
    )

    increase_monthly = deepcopy(baseline)
    increase_monthly_plan = _as_dict(increase_monthly.get("cashflow_plan"))
    increased_monthly = round(current_monthly * 1.25, -3)
    increase_monthly_plan["monthly_contribution"] = increased_monthly
    increase_monthly["cashflow_plan"] = increase_monthly_plan
    scenario_inputs.append(
        (
            f"把每月投入从{_whole_number_text(current_monthly)}提高到{_whole_number_text(increased_monthly)}",
            increase_monthly,
        )
    )

    relax_drawdown = deepcopy(baseline)
    relax_drawdown_constraints = _as_dict(relax_drawdown.get("constraints"))
    relaxed_drawdown = min(current_drawdown + 0.05, 0.35)
    relax_drawdown_constraints["max_drawdown_tolerance"] = relaxed_drawdown
    relax_drawdown["constraints"] = relax_drawdown_constraints
    scenario_inputs.append(
        (
            f"把最大回撤容忍度从{_drawdown_text(current_drawdown)}放宽到{_drawdown_text(relaxed_drawdown)}",
            relax_drawdown,
        )
    )

    suggestions: list[dict[str, Any]] = []
    for label, scenario_input in scenario_inputs:
        scenario_output = _obj(run_goal_solver(scenario_input))
        result = _as_dict(scenario_output.get("recommended_result"))
        suggestions.append(
            {
                "label": label,
                "success_probability": result.get("success_probability"),
                "risk_summary": _as_dict(result.get("risk_summary")),
                "evidence_source": "model_estimate",
            }
        )
    return suggestions


def _enrich_goal_solver_output(goal_solver_output: Any, goal_solver_input: Any) -> Any:
    output = _obj(goal_solver_output)
    if not output:
        return goal_solver_output
    notes = [_text(note) or "" for note in output.get("solver_notes", [])]
    if not any("warning=no_feasible_allocation" in note for note in notes):
        return goal_solver_output
    existing = output.get("fallback_suggestions", [])
    if existing:
        return goal_solver_output
    suggestions = _build_goal_fallback_suggestions(goal_solver_input)
    if isinstance(goal_solver_output, dict):
        goal_solver_output["fallback_suggestions"] = suggestions
        return goal_solver_output
    if hasattr(goal_solver_output, "fallback_suggestions"):
        goal_solver_output.fallback_suggestions = suggestions
    return goal_solver_output


def _build_card_input(
    *,
    run_id: str,
    workflow_type: WorkflowType,
    bundle_id: str | None,
    calibration_id: str | None,
    solver_snapshot_id: str | None,
    goal_solver_output: Any,
    goal_solver_input: Any,
    runtime_result: Any,
    workflow_decision: WorkflowDecision,
    runtime_restriction: RuntimeRestriction,
    execution_plan_summary: dict[str, Any],
    audit_record: OrchestratorAuditRecord | None,
    input_provenance: Any,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
    control_directives: list[str],
) -> DecisionCardBuildInput:
    return DecisionCardBuildInput(
        card_type=_card_type_for_workflow(workflow_type, bool(blocking_reasons)),
        workflow_type=workflow_type.value,
        run_id=run_id,
        bundle_id=bundle_id,
        calibration_id=calibration_id,
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        goal_solver_input=goal_solver_input,
        runtime_result=runtime_result,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        execution_plan_summary=execution_plan_summary,
        audit_record=audit_record,
        input_provenance=input_provenance,
        blocking_reasons=list(blocking_reasons),
        degraded_notes=list(degraded_notes),
        escalation_reasons=list(escalation_reasons),
        control_directives=list(control_directives),
    )


def _replace_candidate_allocations(
    goal_solver_input: dict[str, Any],
    candidate_allocations: list[Any],
    bundle_id: str | None,
) -> dict[str, Any]:
    updated = dict(goal_solver_input)
    updated["candidate_allocations"] = [
        allocation.to_dict() if hasattr(allocation, "to_dict") else dict(allocation)
        for allocation in candidate_allocations
    ]
    if bundle_id:
        updated["snapshot_id"] = bundle_id
    return updated


def _apply_calibration_to_goal_solver_input(
    goal_solver_input: dict[str, Any],
    calibration_data: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(goal_solver_input)
    constraint_state = _as_dict(calibration_data.get("constraint_state"))
    if constraint_state:
        constraints = _as_dict(updated.get("constraints"))
        for field_name in _GOAL_SOLVER_CONSTRAINT_FIELDS:
            if field_name in constraint_state:
                constraints[field_name] = constraint_state[field_name]
        if constraints:
            updated["constraints"] = constraints

    goal_solver_params = _as_dict(calibration_data.get("goal_solver_params"))
    if goal_solver_params:
        updated["solver_params"] = goal_solver_params
    else:
        solver_params = _as_dict(updated.get("solver_params"))
        market_assumptions = calibration_data.get("market_assumptions")
        if solver_params and market_assumptions is not None:
            solver_params["market_assumptions"] = _obj(market_assumptions)
            updated["solver_params"] = solver_params
    return updated


def _resolve_runtime_inputs(
    envelope: dict[str, Any],
    calibration_data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    resolved = {
        "live_portfolio": envelope.get("live_portfolio"),
        "market_state": envelope.get("market_state") or calibration_data.get("market_state"),
        "behavior_state": envelope.get("behavior_state") or calibration_data.get("behavior_state"),
        "constraint_state": envelope.get("constraint_state") or calibration_data.get("constraint_state"),
        "ev_params": envelope.get("ev_params") or calibration_data.get("ev_params"),
        "optimizer_params": envelope.get("optimizer_params") or calibration_data.get("runtime_optimizer_params"),
    }
    missing = [name for name, value in resolved.items() if value is None]
    return resolved, missing


def _validate_solver_baseline_pair(
    solver_output: Any,
    solver_input: Any,
    blocking_reasons: list[str],
) -> None:
    output_data = _as_dict(solver_output)
    solver_input_data = _as_dict(solver_input)
    output_snapshot_id = _text(output_data.get("input_snapshot_id"))
    solver_snapshot_id = _text(solver_input_data.get("snapshot_id"))
    if output_snapshot_id and solver_snapshot_id and output_snapshot_id != solver_snapshot_id:
        blocking_reasons.append("prior solver baseline snapshot mismatch")

    output_params_version = _text(output_data.get("params_version"))
    solver_params_version = _text(_as_dict(solver_input_data.get("solver_params")).get("version"))
    if output_params_version and solver_params_version and output_params_version != solver_params_version:
        blocking_reasons.append("prior solver baseline params_version mismatch")


def _status_from_flags(
    *,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> WorkflowStatus:
    if blocking_reasons:
        return WorkflowStatus.BLOCKED
    if escalation_reasons:
        return WorkflowStatus.ESCALATED
    if degraded_notes:
        return WorkflowStatus.DEGRADED
    return WorkflowStatus.COMPLETED


def _quality_value(value: Any, key: str) -> str:
    return (_text(_as_dict(value).get(key)) or "").lower()


def _evaluate_preflight_controls(
    raw_bundle_id: Any,
    snapshot_bundle: Any,
    calibration_result: Any,
) -> tuple[str | None, list[str], list[str]]:
    snapshot_data = _as_dict(snapshot_bundle)
    blocking_reasons: list[str] = []
    degraded_notes: list[str] = []
    raw_bundle_text = _text(raw_bundle_id)
    bundle_id = raw_bundle_text or _text(snapshot_data.get("bundle_id"))

    snapshot_bundle_id = _text(snapshot_data.get("bundle_id"))
    if raw_bundle_text and snapshot_bundle_id and raw_bundle_text != snapshot_bundle_id:
        blocking_reasons.append("bundle_id mismatch between raw_inputs and snapshot_bundle")

    bundle_quality = _quality_value(snapshot_data, "bundle_quality")
    if bundle_quality == "degraded":
        blocking_reasons.append("bundle_quality=degraded")
    elif bundle_quality and bundle_quality not in {"full"}:
        degraded_notes.append(f"bundle_quality={bundle_quality}")

    calibration_quality = _quality_value(calibration_result, "calibration_quality")
    if calibration_quality == "degraded":
        blocking_reasons.append("calibration_quality=degraded")
    elif calibration_quality == "partial":
        degraded_notes.append("calibration_quality=partial")
    elif calibration_quality not in {"", "full"}:
        degraded_notes.append(f"calibration_quality={calibration_quality}")

    return bundle_id, blocking_reasons, degraded_notes


def _append_bundle_provenance_checks(
    bundle_id: str | None,
    calibration_data: dict[str, Any],
    blocking_reasons: list[str],
) -> None:
    if bundle_id is None:
        return
    refs = (
        ("calibration.source_bundle_id", calibration_data.get("source_bundle_id")),
        (
            "param_version_meta.source_bundle_id",
            _as_dict(calibration_data.get("param_version_meta")).get("source_bundle_id"),
        ),
        (
            "market_state.source_bundle_id",
            _as_dict(calibration_data.get("market_state")).get("source_bundle_id"),
        ),
        (
            "constraint_state.source_bundle_id",
            _as_dict(calibration_data.get("constraint_state")).get("source_bundle_id"),
        ),
        (
            "behavior_state.source_bundle_id",
            _as_dict(calibration_data.get("behavior_state")).get("source_bundle_id"),
        ),
    )
    for label, source_bundle_id in refs:
        source_bundle_text = _text(source_bundle_id)
        if source_bundle_text is not None and source_bundle_text != bundle_id:
            blocking_reasons.append(f"{label} mismatch with bundle_id")


def _relax_provenance_blocking_reasons(blocking_reasons: list[str]) -> list[str]:
    return [reason for reason in blocking_reasons if "mismatch" not in reason]


def _control_directives_from_runtime_restriction(
    runtime_restriction: RuntimeRestriction,
) -> list[str]:
    directives: list[str] = []
    if runtime_restriction.allowed_actions:
        directives.append(
            "allowed_actions=" + ",".join(runtime_restriction.allowed_actions)
        )
    if runtime_restriction.blocked_actions:
        directives.append(
            "blocked_actions=" + ",".join(runtime_restriction.blocked_actions)
        )
    if runtime_restriction.forced_safe_action:
        directives.append(
            f"forced_safe_action={runtime_restriction.forced_safe_action}"
        )
    if runtime_restriction.requires_escalation:
        directives.append("manual_review_required")
    return directives


def _action_type_from_ranked_entry(entry: Any) -> str | None:
    entry_data = _as_dict(entry)
    action_data = _as_dict(entry_data.get("action"))
    return _text(action_data.get("type"))


def _safe_ranked_actions(ranked_actions: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    safe_actions: list[dict[str, Any]] = []
    blocked_action_types: list[str] = []
    for entry in ranked_actions:
        entry_data = _as_dict(entry)
        action_type = _action_type_from_ranked_entry(entry_data)
        if action_type in _SAFE_ACTION_TYPES:
            safe_actions.append(entry_data)
        elif action_type is not None and action_type not in blocked_action_types:
            blocked_action_types.append(action_type)
    return safe_actions, blocked_action_types


def _restrict_runtime_result(runtime_result: Any, forced_safe_action: str) -> tuple[Any, list[str]]:
    runtime_data = _as_dict(runtime_result)
    ev_report = _as_dict(runtime_data.get("ev_report"))
    ranked_actions = list(ev_report.get("ranked_actions", []))
    safe_ranked_actions, blocked_action_types = _safe_ranked_actions(ranked_actions)

    if safe_ranked_actions:
        preferred = next(
            (
                entry
                for entry in safe_ranked_actions
                if _action_type_from_ranked_entry(entry) == forced_safe_action
            ),
            safe_ranked_actions[0],
        )
        recommended_action = _as_dict(preferred.get("action"))
        recommended_score = preferred.get("score")
        after_value = ev_report.get("goal_solver_after_recommended")
        if recommended_score is None:
            after_value = ev_report.get("goal_solver_baseline")
    else:
        recommended_action = {"type": forced_safe_action}
        recommended_score = None
        after_value = ev_report.get("goal_solver_baseline")
        safe_ranked_actions = [
            {
                "action": {"type": forced_safe_action},
                "score": None,
                "rank": 1,
                "is_recommended": True,
                "recommendation_reason": f"{forced_safe_action} forced by orchestrator guardrail",
            }
        ]

    for index, entry in enumerate(safe_ranked_actions, start=1):
        entry["rank"] = index
        entry["is_recommended"] = index == 1

    ev_report["ranked_actions"] = safe_ranked_actions
    ev_report["recommended_action"] = recommended_action
    ev_report["recommended_score"] = recommended_score
    ev_report["goal_solver_after_recommended"] = after_value
    ev_report["confidence_flag"] = "low"
    base_reason = _first_text(ev_report.get("confidence_reason"), "restricted by orchestrator")
    ev_report["confidence_reason"] = f"{base_reason}; safe actions only"

    if not isinstance(runtime_result, dict) and hasattr(runtime_result, "ev_report"):
        runtime_result.ev_report = ev_report
    elif isinstance(runtime_result, dict):
        runtime_result["ev_report"] = ev_report
    else:
        runtime_data["ev_report"] = ev_report
        runtime_result = runtime_data

    return runtime_result, blocked_action_types


def _build_runtime_restriction(
    *,
    trigger: TriggerSignal,
    workflow_type: WorkflowType,
    control_flags: dict[str, Any],
    runtime_result: Any,
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> tuple[RuntimeRestriction, Any]:
    restriction_reasons: list[str] = []
    candidate_poverty = bool(
        runtime_result is not None and getattr(runtime_result, "candidate_poverty", False)
    )
    if control_flags["cooldown_active"]:
        restriction_reasons.append("cooldown_active")
    if control_flags["manual_review_requested"]:
        restriction_reasons.append("manual_review_requested")
    if control_flags["manual_override_requested"]:
        restriction_reasons.append("manual_override_requested")
    if control_flags["high_risk_request"]:
        restriction_reasons.append("high_risk_request")
    if candidate_poverty:
        restriction_reasons.append("candidate_poverty")

    forced_safe_action = "freeze" if restriction_reasons else None
    requires_escalation = False
    if control_flags["manual_review_requested"]:
        requires_escalation = True
    if control_flags["manual_override_requested"]:
        requires_escalation = True
    if control_flags["cooldown_active"] and control_flags["high_risk_request"]:
        requires_escalation = True
    if workflow_type == WorkflowType.EVENT and control_flags["cooldown_active"]:
        requires_escalation = True

    if control_flags["cooldown_active"]:
        degraded_notes.append("cooldown_active=true")
    if control_flags["high_risk_request"]:
        degraded_notes.append("high_risk_request=true")
    if control_flags["manual_review_requested"]:
        escalation_reasons.append("manual_review_requested")
    if control_flags["manual_override_requested"]:
        escalation_reasons.append("manual_override_requested")
    if control_flags["cooldown_active"] and control_flags["high_risk_request"]:
        escalation_reasons.append("high_risk_request_during_cooldown")
    elif workflow_type == WorkflowType.EVENT and control_flags["cooldown_active"]:
        escalation_reasons.append("event_requires_manual_review_under_cooldown")

    blocked_actions: list[str] = []
    if runtime_result is not None and forced_safe_action is not None:
        runtime_result, blocked_actions = _restrict_runtime_result(runtime_result, forced_safe_action)

    return (
        RuntimeRestriction(
            cooldown_active=bool(control_flags["cooldown_active"]),
            manual_review_requested=bool(control_flags["manual_review_requested"]),
            high_risk_request=bool(control_flags["high_risk_request"]),
            allowed_actions=list(_SAFE_ACTION_TYPES if forced_safe_action is not None else []),
            blocked_actions=blocked_actions,
            restriction_reasons=restriction_reasons,
            requires_escalation=requires_escalation,
            forced_safe_action=forced_safe_action,
        ),
        runtime_result,
    )


def _apply_runtime_controls(
    *,
    trigger: TriggerSignal,
    runtime_result: Any,
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> None:
    if runtime_result is None or not getattr(runtime_result, "candidate_poverty", False):
        return
    degraded_notes.append("candidate_poverty=true")
    if trigger.workflow_type == WorkflowType.QUARTERLY:
        escalation_reasons.append("quarterly_candidate_poverty")
    elif trigger.behavior_event:
        escalation_reasons.append("behavior_event_with_candidate_poverty")


def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _build_audit_record(
    *,
    workflow_decision: WorkflowDecision,
    trigger: TriggerSignal,
    control_flags: dict[str, Any],
    runtime_restriction: RuntimeRestriction,
    run_id: str,
    bundle_id: str | None,
    snapshot_bundle: Any,
    snapshot_bundle_origin: str,
    calibration_result: Any,
    calibration_origin: str,
    calibration_data: dict[str, Any],
    solver_snapshot_id: str | None,
    goal_solver_output: Any,
    runtime_result: Any,
    card_build_input: DecisionCardBuildInput | None,
    status: WorkflowStatus,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
) -> OrchestratorAuditRecord:
    goal_output_data = _as_dict(goal_solver_output)
    runtime_data = _as_dict(runtime_result)
    runtime_ev_report = _as_dict(runtime_data.get("ev_report"))
    return OrchestratorAuditRecord(
        requested_workflow_type=None
        if workflow_decision.requested_workflow_type is None
        else workflow_decision.requested_workflow_type.value,
        selected_workflow_type=workflow_decision.selected_workflow_type.value,
        selection_reason=workflow_decision.selection_reason,
        trigger_flags={
            "structural_event": trigger.structural_event,
            "behavior_event": trigger.behavior_event,
            "drawdown_event": trigger.drawdown_event,
            "satellite_event": trigger.satellite_event,
            "manual_review_requested": trigger.manual_review_requested,
            "manual_override_requested": trigger.manual_override_requested,
            "high_risk_request": trigger.high_risk_request,
            "force_full_review": trigger.force_full_review,
        },
        control_flags={
            "manual_review_requested": bool(control_flags["manual_review_requested"]),
            "manual_override_requested": bool(control_flags["manual_override_requested"]),
            "quarterly_review_requested": bool(control_flags["quarterly_review_requested"]),
            "force_full_recalc": bool(control_flags["force_full_recalc"]),
            "major_parameter_update": bool(control_flags["major_parameter_update"]),
            "high_risk_request": bool(control_flags["high_risk_request"]),
            "requested_action": control_flags["requested_action"],
            "cooldown_active": bool(control_flags["cooldown_active"]),
            "cooldown_until": control_flags["cooldown_until"],
            "override_count_90d": control_flags["override_count_90d"],
            "audit_mode": bool(control_flags["audit_mode"]),
            "enforce_provenance_checks": bool(control_flags["enforce_provenance_checks"]),
            "allow_degraded_continue": bool(control_flags["allow_degraded_continue"]),
        },
        version_refs={
            "run_id": run_id,
            "bundle_id": bundle_id,
            "calibration_id": calibration_data.get("calibration_id"),
            "solver_snapshot_id": solver_snapshot_id,
            "goal_solver_params_version": _first_text(
                goal_output_data.get("params_version"),
                _as_dict(calibration_data.get("goal_solver_params")).get("version"),
            ),
            "runtime_optimizer_params_version": _first_text(
                runtime_data.get("optimizer_params_version"),
                _as_dict(calibration_data.get("runtime_optimizer_params")).get("version"),
            ),
            "ev_params_version": _first_text(
                runtime_ev_report.get("params_version"),
                _as_dict(calibration_data.get("ev_params")).get("version"),
            ),
            "runtime_run_timestamp": runtime_data.get("run_timestamp"),
        },
        artifact_refs={
            "has_snapshot_bundle": snapshot_bundle is not None,
            "has_calibration_result": calibration_result is not None,
            "has_goal_solver_output": goal_solver_output is not None,
            "has_runtime_result": runtime_result is not None,
            "has_card_build_input": card_build_input is not None,
            "runtime_restriction_active": bool(runtime_restriction.restriction_reasons),
            "snapshot_bundle_origin": snapshot_bundle_origin,
            "calibration_origin": calibration_origin,
        },
        outcome={
            "status": status.value,
            "blocking_reasons": list(blocking_reasons),
            "degraded_notes": list(degraded_notes),
            "escalation_reasons": list(escalation_reasons),
            "allowed_actions": list(runtime_restriction.allowed_actions),
            "blocked_actions": list(runtime_restriction.blocked_actions),
            "forced_safe_action": runtime_restriction.forced_safe_action,
        },
    )


def _build_execution_plan_summary(execution_plan: Any) -> dict[str, Any]:
    if execution_plan is None:
        return {}
    if hasattr(execution_plan, "summary"):
        return _as_dict(execution_plan.summary())
    data = _as_dict(execution_plan)
    items = list(data.get("items") or [])
    return {
        "plan_id": data.get("plan_id"),
        "plan_version": data.get("plan_version"),
        "source_run_id": data.get("source_run_id"),
        "source_allocation_id": data.get("source_allocation_id"),
        "status": data.get("status"),
        "item_count": len(items),
        "confirmation_required": bool(data.get("confirmation_required", True)),
        "warning_count": len(list(data.get("warnings") or [])),
        "approved_at": data.get("approved_at"),
        "superseded_by_plan_id": data.get("superseded_by_plan_id"),
    }


def _execution_plan_item_index_from_payload(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    data = _as_dict(payload)
    items = list(data.get("items") or [])
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        entry = _as_dict(item)
        bucket = _first_text(entry.get("asset_bucket")) or ""
        if bucket:
            index[bucket] = entry
    return index


def _primary_product_id_from_payload(item: dict[str, Any]) -> str | None:
    direct = _first_text(_as_dict(item).get("primary_product_id"))
    if direct:
        return direct
    product = _as_dict(_as_dict(item).get("primary_product"))
    nested = _first_text(product.get("product_id"))
    return nested


def _compare_execution_plan_payloads(
    active_payload: dict[str, Any] | None,
    pending_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not active_payload or not pending_payload:
        return None
    active_items = _execution_plan_item_index_from_payload(active_payload)
    pending_items = _execution_plan_item_index_from_payload(pending_payload)
    bucket_changes: list[dict[str, Any]] = []
    product_switches: list[dict[str, Any]] = []
    max_weight_delta = 0.0
    for bucket in sorted(set(active_items) | set(pending_items)):
        a = active_items.get(bucket, {})
        p = pending_items.get(bucket, {})
        aw = round(float(_as_dict(a).get("target_weight", 0.0) or 0.0), 4)
        pw = round(float(_as_dict(p).get("target_weight", 0.0) or 0.0), 4)
        delta = round(pw - aw, 4)
        a_pid = _primary_product_id_from_payload(a)
        p_pid = _primary_product_id_from_payload(p)
        product_changed = a_pid != p_pid and bool(a_pid or p_pid)
        if abs(delta) <= 1e-6 and not product_changed:
            continue
        max_weight_delta = max(max_weight_delta, abs(delta))
        change = {
            "asset_bucket": bucket,
            "active_target_weight": aw,
            "pending_target_weight": pw,
            "weight_delta": delta,
            "active_primary_product_id": a_pid,
            "pending_primary_product_id": p_pid,
            "product_changed": product_changed,
        }
        bucket_changes.append(change)
        if product_changed:
            product_switches.append(
                {
                    "asset_bucket": bucket,
                    "active_primary_product_id": a_pid,
                    "pending_primary_product_id": p_pid,
                }
            )

    bucket_set_changed = any(
        (item["active_target_weight"] <= 1e-6) != (item["pending_target_weight"] <= 1e-6)
        for item in bucket_changes
    )
    changed_bucket_count = len(bucket_changes)
    product_switch_count = len(product_switches)
    if changed_bucket_count == 0 and product_switch_count == 0:
        change_level = "none"
        recommendation = "keep_active"
        summary = ["pending plan matches current active plan"]
    else:
        if bucket_set_changed or max_weight_delta >= 0.10 or changed_bucket_count >= 3:
            change_level = "major"
            recommendation = "replace_active"
        else:
            change_level = "minor"
            recommendation = "review_replace"
        summary = [f"{changed_bucket_count} bucket changes detected"]
        if product_switch_count:
            summary.append(f"{product_switch_count} primary product switches detected")
        if max_weight_delta > 0.0:
            summary.append(f"largest weight delta={max_weight_delta:.2%}")

    return {
        "change_level": change_level,
        "recommendation": recommendation,
        "changed_bucket_count": changed_bucket_count,
        "product_switch_count": product_switch_count,
        "max_weight_delta": round(max_weight_delta, 4),
        "bucket_changes": bucket_changes,
        "product_switches": product_switches,
        "summary": summary,
    }


def _extract_execution_plan_restrictions(envelope: dict[str, Any]) -> list[str]:
    direct = envelope.get("execution_plan_restrictions")
    if isinstance(direct, list):
        return [str(item).strip() for item in direct if str(item).strip()]
    provenance = _as_dict(envelope.get("input_provenance"))
    items = list(provenance.get("items") or [])
    if not items:
        for group_name in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
            items.extend(list(provenance.get(group_name) or []))
    for item in items:
        if _first_text(_as_dict(item).get("field")) != "account.restrictions":
            continue
        value = _as_dict(item).get("value")
        if isinstance(value, list):
            return [str(entry).strip() for entry in value if str(entry).strip()]
        if value is None:
            return []
        rendered = str(value).strip()
        return [rendered] if rendered else []
    return []


def _maybe_build_execution_plan(
    *,
    run_id: str,
    workflow_type: WorkflowType,
    status: WorkflowStatus,
    goal_solver_output: Any,
    envelope: dict[str, Any],
) -> Any | None:
    if status == WorkflowStatus.BLOCKED or workflow_type not in {
        WorkflowType.ONBOARDING,
        WorkflowType.QUARTERLY,
    }:
        return None
    goal_output = _as_dict(goal_solver_output)
    recommended = _as_dict(goal_output.get("recommended_allocation"))
    weights = _as_dict(recommended.get("weights"))
    allocation_name = _first_text(
        recommended.get("name"),
        _as_dict(goal_output.get("recommended_result")).get("allocation_name"),
    )
    if not weights or allocation_name is None:
        return None
    return build_execution_plan(
        source_run_id=run_id,
        source_allocation_id=allocation_name,
        bucket_targets={bucket: float(weight) for bucket, weight in weights.items()},
        restrictions=_extract_execution_plan_restrictions(envelope),
    )


def _build_persistence_plan(
    *,
    run_id: str,
    requested_workflow: WorkflowType | None,
    workflow_type: WorkflowType,
    status: WorkflowStatus,
    bundle_id: str | None,
    calibration_id: str | None,
    solver_snapshot_id: str | None,
    snapshot_bundle: Any,
    calibration_result: Any,
    goal_solver_output: Any,
    runtime_result: Any,
    execution_plan: Any,
    decision_card: Any,
    workflow_decision: WorkflowDecision,
    runtime_restriction: RuntimeRestriction,
    blocking_reasons: list[str],
    degraded_notes: list[str],
    escalation_reasons: list[str],
    control_flags: dict[str, Any],
) -> OrchestratorPersistencePlan:
    execution_plan_payload = _payload(execution_plan)
    execution_plan_summary = _build_execution_plan_summary(execution_plan)
    return OrchestratorPersistencePlan(
        run_record={
            "run_id": run_id,
            "requested_workflow_type": None
            if requested_workflow is None
            else requested_workflow.value,
            "workflow_type": workflow_type.value,
            "status": status.value,
            "bundle_id": bundle_id,
            "calibration_id": calibration_id,
            "solver_snapshot_id": solver_snapshot_id,
            "workflow_decision": _payload(workflow_decision),
            "runtime_restriction": _payload(runtime_restriction),
            "blocking_reasons": list(blocking_reasons),
            "degraded_notes": list(degraded_notes),
            "escalation_reasons": list(escalation_reasons),
        },
        artifact_records={
            "snapshot_bundle": None
            if snapshot_bundle is None
            else {"bundle_id": bundle_id, "payload": _payload(snapshot_bundle)},
            "calibration_result": None
            if calibration_result is None
            else {"calibration_id": calibration_id, "payload": _payload(calibration_result)},
            "goal_solver_output": None
            if goal_solver_output is None
            else {"solver_snapshot_id": solver_snapshot_id, "payload": _payload(goal_solver_output)},
            "runtime_result": None
            if runtime_result is None
            else {"run_id": run_id, "payload": _payload(runtime_result)},
            "execution_plan": None
            if execution_plan is None
            else {
                "plan_id": execution_plan_summary.get("plan_id"),
                "plan_version": execution_plan_summary.get("plan_version"),
                "source_run_id": execution_plan_summary.get("source_run_id"),
                "source_allocation_id": execution_plan_summary.get("source_allocation_id"),
                "status": execution_plan_summary.get("status"),
                "approved_at": execution_plan_summary.get("approved_at"),
                "superseded_by_plan_id": execution_plan_summary.get("superseded_by_plan_id"),
                "payload": execution_plan_payload,
            },
            "decision_card": None
            if decision_card is None
            else {
                "run_id": run_id,
                "card_id": _as_dict(decision_card).get("card_id"),
                "payload": _payload(decision_card),
            },
        },
        execution_record={
            "user_executed": None,
            "user_override_requested": bool(control_flags["manual_override_requested"]),
            "override_reason": None,
            "manual_review_requested": bool(control_flags["manual_review_requested"]),
            "plan_id": execution_plan_summary.get("plan_id"),
            "plan_version": execution_plan_summary.get("plan_version"),
            "source_run_id": execution_plan_summary.get("source_run_id"),
            "status": execution_plan_summary.get("status"),
            "approved_at": execution_plan_summary.get("approved_at"),
        },
    )


def run_orchestrator(
    trigger: TriggerSignal | dict[str, Any],
    raw_inputs: dict[str, Any],
    prior_solver_output: Any | None = None,
    prior_solver_input: Any | None = None,
    prior_calibration: Any | None = None,
) -> OrchestratorResult:
    envelope = dict(raw_inputs)
    requested_workflow = _requested_workflow_from_any(trigger)
    normalized_trigger = _trigger_from_any(trigger)
    resolution_blocking_reasons: list[str] = []
    snapshot_bundle, snapshot_bundle_origin = _resolve_snapshot_bundle(
        envelope,
        prior_solver_input,
        resolution_blocking_reasons,
    )
    calibration_result, calibration_origin = _resolve_calibration_result(
        envelope,
        normalized_trigger,
        snapshot_bundle,
        snapshot_bundle_origin,
        prior_calibration,
        prior_solver_input,
    )
    calibration_data = _as_dict(calibration_result)
    control_flags = _extract_control_flags(
        envelope,
        calibration_data,
        normalized_trigger,
    )
    workflow_decision = _select_workflow(
        requested_workflow=requested_workflow,
        trigger=normalized_trigger,
        envelope=envelope,
        prior_solver_output=envelope.get("goal_solver_output") or prior_solver_output,
        prior_solver_input=envelope.get("goal_solver_input") or prior_solver_input,
        control_flags=control_flags,
    )
    effective_trigger = TriggerSignal(
        workflow_type=workflow_decision.selected_workflow_type,
        run_id=normalized_trigger.run_id,
        structural_event=normalized_trigger.structural_event,
        behavior_event=normalized_trigger.behavior_event,
        drawdown_event=normalized_trigger.drawdown_event,
        satellite_event=normalized_trigger.satellite_event,
        manual_review_requested=normalized_trigger.manual_review_requested,
        manual_override_requested=normalized_trigger.manual_override_requested,
        high_risk_request=normalized_trigger.high_risk_request,
        force_full_review=normalized_trigger.force_full_review,
    )
    run_id = _build_run_id(
        normalized_trigger.run_id,
        workflow_decision.selected_workflow_type,
    )
    bundle_id, blocking_reasons, degraded_notes = _evaluate_preflight_controls(
        raw_bundle_id=envelope.get("bundle_id"),
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
    )
    blocking_reasons = list(resolution_blocking_reasons) + blocking_reasons
    if control_flags["enforce_provenance_checks"]:
        _append_bundle_provenance_checks(bundle_id, calibration_data, blocking_reasons)
    else:
        blocking_reasons = _relax_provenance_blocking_reasons(blocking_reasons)
    escalation_reasons: list[str] = []

    goal_solver_output = None
    goal_solver_input_used = envelope.get("goal_solver_input") or prior_solver_input
    runtime_result = None
    solver_snapshot_id = None
    has_prior_baseline = prior_solver_output is not None and prior_solver_input is not None

    if not blocking_reasons and effective_trigger.workflow_type in {
        WorkflowType.ONBOARDING,
        WorkflowType.QUARTERLY,
    }:
        allocation_input = envelope.get("allocation_engine_input")
        if allocation_input is None:
            blocking_reasons.append("allocation_engine_input is required")
        else:
            allocation_result = run_allocation_engine(allocation_input)
            if not allocation_result.candidate_allocations:
                blocking_reasons.append("allocation_engine returned no candidates")
            else:
                solver_input_source = envelope.get("goal_solver_input")
                if solver_input_source is None:
                    blocking_reasons.append("goal_solver_input is required")
                else:
                    solver_input = _replace_candidate_allocations(
                        _as_dict(solver_input_source),
                        allocation_result.candidate_allocations,
                        bundle_id,
                    )
                    solver_input = _apply_calibration_to_goal_solver_input(
                        solver_input,
                        calibration_data,
                    )
                    goal_solver_input_used = solver_input
                    goal_solver_output = run_goal_solver(solver_input)
                    goal_solver_output = _enrich_goal_solver_output(
                        goal_solver_output,
                        solver_input,
                    )
                    solver_snapshot_id = _obj(goal_solver_output).get("input_snapshot_id")
                    if effective_trigger.workflow_type == WorkflowType.QUARTERLY:
                        runtime_inputs, missing_runtime_inputs = _resolve_runtime_inputs(
                            envelope,
                            calibration_data,
                        )
                        if missing_runtime_inputs:
                            blocking_reasons.append(
                                "missing runtime inputs: " + ", ".join(missing_runtime_inputs)
                            )
                        else:
                            runtime_result = run_runtime_optimizer(
                                solver_output=goal_solver_output,
                                solver_baseline_inp=solver_input,
                                live_portfolio=runtime_inputs["live_portfolio"],
                                market_state=runtime_inputs["market_state"],
                                behavior_state=runtime_inputs["behavior_state"],
                                constraint_state=runtime_inputs["constraint_state"],
                                ev_params=runtime_inputs["ev_params"],
                                optimizer_params=runtime_inputs["optimizer_params"],
                                mode=RuntimeOptimizerMode.QUARTERLY,
                            )

    if not blocking_reasons and effective_trigger.workflow_type in {
        WorkflowType.MONTHLY,
        WorkflowType.EVENT,
    }:
        goal_solver_output = envelope.get("goal_solver_output") or prior_solver_output
        solver_input = envelope.get("goal_solver_input") or prior_solver_input
        goal_solver_input_used = solver_input
        if goal_solver_output is None or solver_input is None:
            blocking_reasons.append("prior solver baseline is required")
        else:
            _validate_solver_baseline_pair(goal_solver_output, solver_input, blocking_reasons)
            if not blocking_reasons:
                runtime_inputs, missing_runtime_inputs = _resolve_runtime_inputs(
                    envelope,
                    calibration_data,
                )
                if missing_runtime_inputs:
                    blocking_reasons.append(
                        "missing runtime inputs: " + ", ".join(missing_runtime_inputs)
                    )
                else:
                    solver_snapshot_id = _obj(goal_solver_output).get("input_snapshot_id")
                    runtime_result = run_runtime_optimizer(
                        solver_output=goal_solver_output,
                        solver_baseline_inp=solver_input,
                        live_portfolio=runtime_inputs["live_portfolio"],
                        market_state=runtime_inputs["market_state"],
                        behavior_state=runtime_inputs["behavior_state"],
                        constraint_state=runtime_inputs["constraint_state"],
                        ev_params=runtime_inputs["ev_params"],
                        optimizer_params=runtime_inputs["optimizer_params"],
                        mode=(
                            RuntimeOptimizerMode.EVENT
                            if effective_trigger.workflow_type == WorkflowType.EVENT
                            else RuntimeOptimizerMode.MONTHLY
                        ),
                        structural_event=effective_trigger.structural_event,
                        behavior_event=effective_trigger.behavior_event,
                        drawdown_event=effective_trigger.drawdown_event,
                        satellite_event=effective_trigger.satellite_event,
                    )

    _apply_runtime_controls(
        trigger=effective_trigger,
        runtime_result=runtime_result,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    runtime_restriction, runtime_result = _build_runtime_restriction(
        trigger=effective_trigger,
        workflow_type=effective_trigger.workflow_type,
        control_flags=control_flags,
        runtime_result=runtime_result,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    control_directives = _control_directives_from_runtime_restriction(runtime_restriction)
    blocking_reasons = _unique_items(blocking_reasons)
    degraded_notes = _unique_items(degraded_notes)
    escalation_reasons = _unique_items(escalation_reasons)
    control_directives = _unique_items(control_directives)

    status = _status_from_flags(
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    execution_plan = _maybe_build_execution_plan(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        goal_solver_output=goal_solver_output,
        envelope=envelope,
    )
    # Plan guidance from frontdesk context
    plan_context = _as_dict(envelope.get("frontdesk_execution_plan_context"))
    if effective_trigger.workflow_type == WorkflowType.QUARTERLY and execution_plan is not None:
        compare = _compare_execution_plan_payloads(
            _as_dict(plan_context.get("active")),
            _as_dict(_payload(execution_plan)),
        )
        if compare:
            control_directives.append(f"plan_change={compare.get('recommendation')}")
            control_directives.append(f"plan_change_level={compare.get('change_level')}")
    elif effective_trigger.workflow_type == WorkflowType.MONTHLY:
        comparison = _as_dict(plan_context.get("comparison"))
        recommendation = _first_text(comparison.get("recommendation"))
        if recommendation:
            control_directives.append(f"plan_change={recommendation}")
            change_level = _first_text(comparison.get("change_level"))
            if change_level:
                control_directives.append(f"plan_change_level={change_level}")
    control_directives = _unique_items(control_directives)

    # Prefer pending plan summary (if present) when monthly has no new plan
    execution_plan_summary = _build_execution_plan_summary(execution_plan)
    if (
        not execution_plan_summary
        and effective_trigger.workflow_type == WorkflowType.MONTHLY
        and plan_context.get("pending")
    ):
        execution_plan_summary = _build_execution_plan_summary(plan_context.get("pending"))
    card_build_input = _build_card_input(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        goal_solver_input=goal_solver_input_used,
        runtime_result=runtime_result,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        execution_plan_summary=execution_plan_summary,
        audit_record=None,
        input_provenance=_build_input_provenance(
            envelope,
            effective_trigger.workflow_type,
            has_prior_baseline=has_prior_baseline,
        ),
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
        control_directives=control_directives,
    )
    audit_record = _build_audit_record(
        workflow_decision=workflow_decision,
        trigger=effective_trigger,
        control_flags=control_flags,
        runtime_restriction=runtime_restriction,
        run_id=run_id,
        bundle_id=bundle_id,
        snapshot_bundle=snapshot_bundle,
        snapshot_bundle_origin=snapshot_bundle_origin,
        calibration_result=calibration_result,
        calibration_origin=calibration_origin,
        calibration_data=calibration_data,
        solver_snapshot_id=solver_snapshot_id,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        card_build_input=card_build_input,
        status=status,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
    card_build_input.audit_record = audit_record
    audit_record.artifact_refs["has_execution_plan"] = execution_plan is not None
    decision_card = build_decision_card(card_build_input)
    audit_record.artifact_refs["has_decision_card"] = decision_card is not None
    persistence_plan = _build_persistence_plan(
        run_id=run_id,
        requested_workflow=requested_workflow,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        execution_plan=execution_plan,
        decision_card=decision_card,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
        control_flags=control_flags,
    )
    audit_record.artifact_refs["has_persistence_plan"] = persistence_plan is not None
    return OrchestratorResult(
        run_id=run_id,
        workflow_type=effective_trigger.workflow_type,
        status=status,
        requested_workflow_type=requested_workflow,
        bundle_id=bundle_id,
        calibration_id=calibration_data.get("calibration_id"),
        solver_snapshot_id=solver_snapshot_id,
        snapshot_bundle=snapshot_bundle,
        calibration_result=calibration_result,
        goal_solver_output=goal_solver_output,
        runtime_result=runtime_result,
        execution_plan=execution_plan,
        card_build_input=card_build_input,
        decision_card=decision_card,
        workflow_decision=workflow_decision,
        runtime_restriction=runtime_restriction,
        audit_record=audit_record,
        persistence_plan=persistence_plan,
        blocking_reasons=blocking_reasons,
        degraded_notes=degraded_notes,
        escalation_reasons=escalation_reasons,
    )
