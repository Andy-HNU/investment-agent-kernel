from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from frontdesk.service import (
    DEFAULT_DB_PATH,
    approve_frontdesk_execution_plan,
    load_frontdesk_snapshot,
    load_user_state,
    record_frontdesk_execution_feedback,
    run_frontdesk_followup,
    run_frontdesk_onboarding,
)
from shared.onboarding import UserOnboardingProfile


def _parse_float(value: str) -> float:
    return float(str(value).strip().replace(",", ""))


def _parse_int(value: str) -> int:
    return int(str(value).strip())


def _prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    rendered = input(f"{label}{suffix}: ").strip()
    if rendered:
        return rendered
    if default is not None:
        return default
    raise ValueError(f"{label} is required")


def _prompt_profile(args: argparse.Namespace) -> UserOnboardingProfile:
    account_profile_id = args.account_profile_id or _prompt_text("账户ID", "user001")
    display_name = args.display_name or _prompt_text("账户名")
    current_total_assets = (
        args.current_total_assets
        if args.current_total_assets is not None
        else _parse_float(_prompt_text("当前总资产", "50000"))
    )
    monthly_contribution = (
        args.monthly_contribution
        if args.monthly_contribution is not None
        else _parse_float(_prompt_text("每月投入", "12000"))
    )
    goal_amount = (
        args.goal_amount
        if args.goal_amount is not None
        else _parse_float(_prompt_text("目标期末总资产", "1000000"))
    )
    goal_horizon_months = (
        args.goal_horizon_months
        if args.goal_horizon_months is not None
        else _parse_int(_prompt_text("目标期限（月）", "60"))
    )
    risk_preference = args.risk_preference or _prompt_text("风险偏好", "中等")
    max_drawdown_tolerance = (
        args.max_drawdown_tolerance
        if args.max_drawdown_tolerance is not None
        else _parse_float(_prompt_text("最大可接受回撤(填10或0.1都可以)", "10"))
    )
    current_holdings = args.current_holdings or _prompt_text("当前持仓描述", "cash")
    restrictions = [item.strip() for item in (args.restrictions or "").split(",") if item.strip()]
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name=display_name,
        current_total_assets=float(current_total_assets),
        monthly_contribution=float(monthly_contribution),
        goal_amount=float(goal_amount),
        goal_horizon_months=int(goal_horizon_months),
        risk_preference=risk_preference,
        max_drawdown_tolerance=float(max_drawdown_tolerance),
        current_holdings=current_holdings,
        restrictions=restrictions,
        goal_priority=getattr(args, "goal_priority", None),
        goal_amount_basis=str(getattr(args, "goal_amount_basis", "nominal") or "nominal"),
        goal_amount_scope=str(getattr(args, "goal_amount_scope", "total_assets") or "total_assets"),
        tax_assumption=str(getattr(args, "tax_assumption", "pre_tax") or "pre_tax"),
        fee_assumption=str(getattr(args, "fee_assumption", "transaction_cost_only") or "transaction_cost_only"),
        contribution_commitment_confidence=getattr(args, "contribution_commitment_confidence", None),
    )


def _profile_from_json(source: str | Path) -> UserOnboardingProfile:
    payload = _json_payload_from_source(source)
    return UserOnboardingProfile(**payload)


def _profile_override_from_json(source: str | Path) -> dict[str, Any]:
    payload = _json_payload_from_source(source)
    if not isinstance(payload, dict):
        raise SystemExit("profile-json must decode to an object")
    return payload


def _json_object_from_source(source: str | Path, *, option_name: str) -> dict[str, Any]:
    payload = _json_payload_from_source(source)
    if not isinstance(payload, dict):
        raise SystemExit(f"{option_name} must decode to an object")
    return payload


def _json_payload_from_source(source: str | Path) -> Any:
    source_text = str(source)
    try:
        source_path = Path(source_text)
        if source_path.exists():
            return json.loads(source_path.read_text(encoding="utf-8"))
    except OSError:
        pass
    return json.loads(source_text)


def _profile_from_non_interactive_args(args: argparse.Namespace) -> UserOnboardingProfile:
    required_fields = {
        "account_profile_id": args.account_profile_id,
        "display_name": args.display_name,
        "current_total_assets": args.current_total_assets,
        "monthly_contribution": args.monthly_contribution,
        "goal_amount": args.goal_amount,
        "goal_horizon_months": args.goal_horizon_months,
        "risk_preference": args.risk_preference,
        "max_drawdown_tolerance": args.max_drawdown_tolerance,
        "current_holdings": args.current_holdings,
    }
    missing = [field for field, value in required_fields.items() if value is None]
    if missing:
        raise SystemExit(
            "non-interactive onboarding requires --profile-json or explicit values for: "
            + ", ".join(missing)
        )
    return UserOnboardingProfile(
        account_profile_id=str(args.account_profile_id),
        display_name=str(args.display_name),
        current_total_assets=float(args.current_total_assets),
        monthly_contribution=float(args.monthly_contribution),
        goal_amount=float(args.goal_amount),
        goal_horizon_months=int(args.goal_horizon_months),
        risk_preference=str(args.risk_preference),
        max_drawdown_tolerance=float(args.max_drawdown_tolerance),
        current_holdings=str(args.current_holdings),
        restrictions=[item.strip() for item in (args.restrictions or "").split(",") if item.strip()],
        goal_priority=getattr(args, "goal_priority", None),
        goal_amount_basis=str(getattr(args, "goal_amount_basis", "nominal") or "nominal"),
        goal_amount_scope=str(getattr(args, "goal_amount_scope", "total_assets") or "total_assets"),
        tax_assumption=str(getattr(args, "tax_assumption", "pre_tax") or "pre_tax"),
        fee_assumption=str(getattr(args, "fee_assumption", "transaction_cost_only") or "transaction_cost_only"),
        contribution_commitment_confidence=getattr(args, "contribution_commitment_confidence", None),
    )


def _render_provenance_block(input_provenance: dict[str, Any]) -> list[str]:
    counts = input_provenance.get("counts") or {}
    return [
        "input_provenance: "
        + ", ".join(
            f"{label}={counts.get(label, len(input_provenance.get(label, [])))}"
            for label in ("user_provided", "system_inferred", "default_assumed", "externally_fetched")
        )
    ]


def _render_input_source_summary(input_provenance: dict[str, Any]) -> list[str]:
    summary = input_provenance.get("summary")
    if isinstance(summary, list) and summary:
        return [f"input_sources={'; '.join(str(item) for item in summary)}"]
    source_labels = input_provenance.get("source_labels") or {}
    counts = input_provenance.get("counts") or {}
    parts: list[str] = []
    for source_type in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        label = source_labels.get(source_type) or source_type
        count = counts.get(source_type, len(input_provenance.get(source_type, [])))
        parts.append(f"{label} {count} 项")
    return [f"input_sources={'; '.join(parts)}"]


def _render_candidate_lines(options: list[dict[str, Any]], *, prefix: str) -> list[str]:
    lines: list[str] = []
    for index, option in enumerate(options[:3], start=1):
        lines.append(
            f"{prefix}_{index}={option.get('label')} | {option.get('highlight')} | "
            f"success={option.get('success_probability')} "
            f"bucket_success={option.get('bucket_success_probability')} "
            f"product_success={option.get('product_adjusted_success_probability')} "
            f"probability_method={option.get('product_probability_method')} "
            f"required_return={option.get('implied_required_annual_return')} "
            f"dd90={option.get('max_drawdown_90pct')} "
            f"shortfall={option.get('shortfall_probability')}"
        )
        if option.get("description"):
            lines.append(f"{prefix}_{index}_note={option.get('description')}")
        if option.get("risk_label") or option.get("liquidity_label") or option.get("complexity_label"):
            lines.append(
                f"{prefix}_{index}_tags="
                f"risk={option.get('risk_label')} "
                f"liquidity={option.get('liquidity_label')} "
                f"complexity={option.get('complexity_label')}"
            )
    return lines


def _render_refresh_block(refresh_summary: dict[str, Any]) -> list[str]:
    if not refresh_summary:
        return []
    lines = [
        "refresh: "
        + ", ".join(
            [
                f"state={refresh_summary.get('freshness_state')}",
                f"label={refresh_summary.get('freshness_label')}",
                f"external_status={refresh_summary.get('external_status')}",
                f"next_action={refresh_summary.get('next_action')}",
            ]
        )
    ]
    if refresh_summary.get("next_action_label"):
        lines.append(f"refresh_next_action_label={refresh_summary.get('next_action_label')}")
    if refresh_summary.get("provider_name"):
        lines.append(f"refresh_provider={refresh_summary.get('provider_name')}")
    if refresh_summary.get("fetched_at"):
        lines.append(f"last_refresh_at={refresh_summary.get('fetched_at')}")
    if refresh_summary.get("source_ref"):
        lines.append(f"refresh_source={refresh_summary.get('source_ref')}")
    if refresh_summary.get("domains"):
        lines.append("refresh_domains=" + ",".join(refresh_summary.get("domains") or []))
    for item in list(refresh_summary.get("domain_details") or [])[:4]:
        lines.append(
            f"refresh_{item.get('domain')}="
            f"{item.get('source_label') or item.get('source_type')} | "
            f"{item.get('freshness_label') or item.get('freshness_state')}"
        )
    if refresh_summary.get("error"):
        lines.append(f"refresh_error={refresh_summary.get('error')}")
    return lines


def _render_goal_semantics_block(goal_semantics: dict[str, Any] | None) -> list[str]:
    semantics = goal_semantics or {}
    if not semantics:
        return []
    lines = [
        "goal_semantics: "
        + ", ".join(
            [
                f"basis={semantics.get('goal_amount_basis')}",
                f"scope={semantics.get('goal_amount_scope')}",
                f"tax={semantics.get('tax_assumption')}",
                f"fee={semantics.get('fee_assumption')}",
                f"contribution_confidence={semantics.get('contribution_commitment_confidence')}",
            ]
        )
    ]
    explanation = semantics.get("explanation")
    if explanation:
        lines.append(f"goal_semantics_note={explanation}")
    for line in list(semantics.get("disclosure_lines") or [])[:3]:
        lines.append(f"goal_semantics_disclosure={line}")
    return lines


def _render_profile_dimensions_block(profile_dimensions: dict[str, Any] | None) -> list[str]:
    model_inputs = dict((profile_dimensions or {}).get("model_inputs") or {})
    if not model_inputs:
        return []
    return [
        "profile_model: "
        + ", ".join(
            [
                f"goal_priority={model_inputs.get('goal_priority')}",
                f"risk_tolerance={model_inputs.get('risk_tolerance_score')}",
                f"risk_capacity={model_inputs.get('risk_capacity_score')}",
                f"loss_limit={model_inputs.get('loss_limit')}",
                f"liquidity_need={model_inputs.get('liquidity_need_level')}",
                f"contribution_confidence={model_inputs.get('contribution_commitment_confidence')}",
            ]
        )
    ]


def _render_feedback_block(
    execution_feedback: dict[str, Any] | None,
    execution_feedback_summary: dict[str, Any] | None,
) -> list[str]:
    lines: list[str] = []
    counts = dict((execution_feedback_summary or {}).get("counts") or {})
    if counts:
        lines.append(
            "execution_feedback: "
            + ", ".join(f"{key}={counts.get(key, 0)}" for key in ("pending", "executed", "skipped"))
        )
    if execution_feedback:
        lines.append(
            "latest_feedback: "
            + ", ".join(
                [
                    f"run_id={execution_feedback.get('source_run_id')}",
                    f"status={execution_feedback.get('feedback_status')}",
                    f"recommended={execution_feedback.get('recommended_action')}",
                    f"actual={execution_feedback.get('actual_action')}",
                ]
            )
        )
        if execution_feedback.get("executed_at"):
            lines.append(f"latest_feedback_executed_at={execution_feedback.get('executed_at')}")
    return lines


def _render_execution_plan_block(
    execution_plan: dict[str, Any] | None,
    *,
    label: str,
) -> list[str]:
    if not execution_plan:
        return []
    lines = [
        f"{label}: "
        + ", ".join(
            [
                f"plan_id={execution_plan.get('plan_id')}",
                f"version={execution_plan.get('plan_version')}",
                f"status={execution_plan.get('status')}",
                f"items={execution_plan.get('item_count')}",
                f"confirmation_required={execution_plan.get('confirmation_required')}",
                f"runtime_candidates={execution_plan.get('runtime_candidate_count')}",
            ]
        )
    ]
    if execution_plan.get("registry_candidate_count") is not None:
        lines.append(f"{label}_registry_candidates={execution_plan.get('registry_candidate_count')}")
    if execution_plan.get("candidate_filter_dropped_reasons"):
        lines.append(
            f"{label}_candidate_filter_drop_reasons={execution_plan.get('candidate_filter_dropped_reasons')}"
        )
    if execution_plan.get("valuation_audit_summary"):
        lines.append(f"{label}_valuation_audit={execution_plan.get('valuation_audit_summary')}")
    if execution_plan.get("policy_news_audit_summary"):
        lines.append(f"{label}_policy_news_audit={execution_plan.get('policy_news_audit_summary')}")
    if execution_plan.get("approved_at"):
        lines.append(f"{label}_approved_at={execution_plan.get('approved_at')}")
    if execution_plan.get("superseded_by_plan_id"):
        lines.append(f"{label}_superseded_by={execution_plan.get('superseded_by_plan_id')}")
    return lines


def _render_execution_plan_comparison_block(comparison: dict[str, Any] | None) -> list[str]:
    if not comparison:
        return []
    lines = [
        "execution_plan_comparison: "
        + ", ".join(
            [
                f"change_level={comparison.get('change_level')}",
                f"recommendation={comparison.get('recommendation')}",
                f"changed_buckets={comparison.get('changed_bucket_count')}",
                f"product_switches={comparison.get('product_switch_count')}",
                f"max_weight_delta={comparison.get('max_weight_delta')}",
            ]
        )
    ]
    for item in comparison.get("bucket_changes") or []:
        lines.append(
            "execution_plan_change: "
            + ", ".join(
                [
                    f"bucket={item.get('asset_bucket')}",
                    f"active={item.get('active_target_weight')}",
                    f"pending={item.get('pending_target_weight')}",
                    f"delta={item.get('weight_delta')}",
                    f"product_changed={item.get('product_changed')}",
                ]
            )
        )
    return lines


def _render_execution_plan_guidance_block(guidance: dict[str, Any] | None) -> list[str]:
    if not guidance:
        return []
    lines = [
        "execution_plan_guidance: "
        + ", ".join(
            [
                f"recommendation={guidance.get('recommendation')}",
                f"change_level={guidance.get('change_level')}",
                f"changed_buckets={guidance.get('changed_bucket_count')}",
                f"product_switches={guidance.get('product_switch_count')}",
                f"max_weight_delta={guidance.get('max_weight_delta')}",
            ]
        )
    ]
    if guidance.get("headline"):
        lines.append(f"execution_plan_guidance_headline={guidance.get('headline')}")
    return lines


def _unique_text_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        rendered = str(item).strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        ordered.append(rendered)
    return ordered


def _append_scope(scope: list[str], value: str | None) -> None:
    rendered = str(value or "").strip()
    if rendered:
        scope.append(rendered)


def _formal_path_visibility(
    decision_card: dict[str, Any] | None,
    refresh_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    card = decision_card or {}
    refresh = refresh_summary or {}
    degraded_scope: list[str] = []
    fallback_scope: list[str] = []

    for item in list(card.get("guardrails") or []) + list(card.get("execution_notes") or []):
        text = str(item).strip()
        if text.startswith("bundle_quality="):
            _append_scope(degraded_scope, "bundle")
        elif text.startswith("calibration_quality="):
            _append_scope(degraded_scope, "calibration")
        elif text.startswith("candidate_poverty="):
            _append_scope(degraded_scope, "runtime_candidates")
        elif text.startswith("cooldown_active=") or text.startswith("high_risk_request="):
            _append_scope(degraded_scope, "runtime_controls")

    refresh_state = str(refresh.get("freshness_state") or "").strip().lower()
    external_status = str(refresh.get("external_status") or "").strip().lower()
    if refresh_state in {"fallback", "degraded", "stale"} or external_status == "fallback":
        _append_scope(fallback_scope, "external_snapshot")
    for item in refresh.get("domain_details") or []:
        detail = item or {}
        domain = str(detail.get("domain") or "").strip()
        state = str(detail.get("freshness_state") or detail.get("source_type") or "").strip().lower()
        if state in {"fallback", "degraded", "stale"}:
            _append_scope(degraded_scope, domain)
            if state == "fallback":
                _append_scope(fallback_scope, domain)

    combined_text = " ".join(
        [
            str(card.get("summary") or "").strip(),
            *[str(item).strip() for item in card.get("recommendation_reason") or []],
        ]
    )
    if any(marker in combined_text for marker in ("临时参考", "不存在满足", "候选方案不足")):
        _append_scope(fallback_scope, "goal_solver")

    degraded_scope = _unique_text_items(degraded_scope)
    fallback_scope = _unique_text_items(fallback_scope)

    recommended_action = str(card.get("recommended_action") or "").strip()
    execution_eligible = True
    execution_eligibility_reason = "eligible"
    if str(card.get("card_type") or "") == "blocked":
        execution_eligible = False
        execution_eligibility_reason = "blocked_card"
    elif str(card.get("status_badge") or "") == "degraded":
        execution_eligible = False
        execution_eligibility_reason = "degraded_card"
    elif fallback_scope:
        execution_eligible = False
        execution_eligibility_reason = "fallback_used"
    elif any(item == "manual_review_required" for item in card.get("execution_notes") or []):
        execution_eligible = False
        execution_eligibility_reason = "manual_review_required"
    elif recommended_action in {"", "blocked", "review", "observe", "freeze"}:
        execution_eligible = False
        execution_eligibility_reason = "non_executable_recommendation"

    return {
        "degraded_scope": degraded_scope,
        "fallback_used": bool(fallback_scope),
        "fallback_scope": fallback_scope,
        "execution_eligible": execution_eligible,
        "execution_eligibility_reason": execution_eligibility_reason,
    }


def _render_formal_path_block(formal_path_visibility: dict[str, Any] | None) -> list[str]:
    if not formal_path_visibility:
        return []
    lines = [
        "formal_path: "
        + ", ".join(
            [
                f"status={formal_path_visibility.get('status')}",
                "degraded_scope=" + ",".join(formal_path_visibility.get("degraded_scope") or []),
                f"fallback_used={'true' if formal_path_visibility.get('fallback_used') else 'false'}",
                "fallback_scope=" + ",".join(formal_path_visibility.get("fallback_scope") or []),
                f"execution_eligible={'true' if formal_path_visibility.get('execution_eligible') else 'false'}",
                f"execution_eligibility_reason={formal_path_visibility.get('execution_eligibility_reason')}",
            ]
        )
    ]
    if formal_path_visibility.get("missing_audit_fields"):
        lines.append(
            "formal_path_missing_audit_fields="
            + ",".join(str(item) for item in formal_path_visibility.get("missing_audit_fields") or [])
        )
    return lines


def _augment_formal_path_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    top_level_visibility = result.get("formal_path_visibility")
    if "user_state" in result:
        user_state = dict(result.get("user_state") or {})
        decision_card = dict(user_state.get("decision_card") or {})
        refresh_summary = dict(result.get("refresh_summary") or {})
        visibility = (
            top_level_visibility
            or user_state.get("formal_path_visibility")
            or decision_card.get("formal_path_visibility")
            or _formal_path_visibility(decision_card, refresh_summary)
        )
        user_state["formal_path_visibility"] = visibility
        result["user_state"] = user_state
        result["formal_path_visibility"] = visibility
        return result
    decision_card = dict(result.get("decision_card") or {})
    refresh_summary = dict(result.get("refresh_summary") or {})
    result["formal_path_visibility"] = (
        top_level_visibility
        or decision_card.get("formal_path_visibility")
        or _formal_path_visibility(decision_card, refresh_summary)
    )
    return result


def render_frontdesk_summary(payload: dict[str, Any]) -> str:
    payload = _augment_formal_path_visibility(payload)
    external_lines = []
    if payload.get("external_snapshot_source") is not None:
        external_lines.append(f"external_snapshot_source={payload.get('external_snapshot_source')}")
    if payload.get("external_snapshot_config") is not None:
        external_lines.append(f"external_snapshot_config={payload.get('external_snapshot_config')}")
    if payload.get("external_snapshot_status") is not None:
        external_lines.append(f"external_snapshot_status={payload.get('external_snapshot_status')}")
    if payload.get("external_snapshot_error") is not None:
        external_lines.append(f"external_snapshot_error={payload.get('external_snapshot_error')}")

    if "user_state" in payload:
        user_state = payload.get("user_state") or {}
        profile = user_state.get("profile") or {}
        profile_payload = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
        goal_semantics_payload = profile_payload.get("goal_semantics") or payload.get("goal_semantics")
        profile_dimensions_payload = profile_payload.get("profile_dimensions") or payload.get("profile_dimensions")
        decision_card = user_state.get("decision_card") or {}
        active_execution_plan = payload.get("active_execution_plan") or user_state.get("active_execution_plan")
        pending_execution_plan = payload.get("pending_execution_plan") or user_state.get("pending_execution_plan")
        lines = [
            f"account_profile_id={profile.get('account_profile_id')}",
            f"display_name={profile.get('display_name')}",
            f"workflow={payload.get('workflow')}",
            f"status={payload.get('status')}",
        ]
        if decision_card:
            lines.extend(
                [
                    f"card_type={decision_card.get('card_type')}",
                    f"summary={decision_card.get('summary')}",
                    f"primary_recommendation={decision_card.get('primary_recommendation')}",
                    f"recommended_action={decision_card.get('recommended_action')}",
                ]
            )
        lines.extend(_render_provenance_block(decision_card.get("input_provenance") or {}))
        lines.extend(_render_input_source_summary(decision_card.get("input_provenance") or {}))
        lines.extend(_render_candidate_lines(decision_card.get("candidate_options") or [], prefix="candidate"))
        lines.extend(_render_candidate_lines(decision_card.get("goal_alternatives") or [], prefix="alternative"))
        lines.extend(_render_goal_semantics_block(goal_semantics_payload))
        lines.extend(_render_profile_dimensions_block(profile_dimensions_payload))
        if decision_card.get("model_disclaimer"):
            lines.append(f"model_disclaimer={decision_card.get('model_disclaimer')}")
        lines.extend(_render_execution_plan_block(active_execution_plan, label="active_execution_plan"))
        lines.extend(_render_execution_plan_block(pending_execution_plan, label="pending_execution_plan"))
        lines.extend(_render_execution_plan_comparison_block(payload.get("execution_plan_comparison") or user_state.get("execution_plan_comparison")))
        lines.extend(_render_execution_plan_guidance_block(decision_card.get("execution_plan_guidance")))
        lines.extend(_render_formal_path_block(payload.get("formal_path_visibility")))
        lines.extend(_render_refresh_block(payload.get("refresh_summary") or {}))
        lines.extend(
            _render_feedback_block(
                payload.get("execution_feedback"),
                payload.get("execution_feedback_summary"),
            )
        )
        lines.extend(external_lines)
        return "\n".join(lines)

    if payload.get("workflow") == "feedback":
        lines = [
            f"account_profile_id={payload['account_profile_id']}",
            f"status={payload['status']}",
            f"source_run_id={payload.get('source_run_id')}",
        ]
        lines.extend(
            _render_feedback_block(
                payload.get("execution_feedback"),
                payload.get("execution_feedback_summary"),
            )
        )
        lines.extend(_render_refresh_block(payload.get("refresh_summary") or {}))
        return "\n".join(lines)

    if payload.get("workflow") == "approve_plan":
        lines = [
            f"account_profile_id={payload['account_profile_id']}",
            f"status={payload['status']}",
            f"approved_at={payload.get('approved_at')}",
        ]
        lines.extend(
            _render_execution_plan_block(
                payload.get("approved_execution_plan"),
                label="approved_execution_plan",
            )
        )
        lines.extend(_render_execution_plan_block(payload.get("active_execution_plan"), label="active_execution_plan"))
        lines.extend(_render_execution_plan_block(payload.get("pending_execution_plan"), label="pending_execution_plan"))
        lines.extend(_render_execution_plan_comparison_block(payload.get("execution_plan_comparison")))
        lines.extend(_render_execution_plan_guidance_block((payload.get("user_state") or {}).get("decision_card", {}).get("execution_plan_guidance")))
        lines.extend(_render_formal_path_block(payload.get("formal_path_visibility")))
        lines.extend(_render_refresh_block(payload.get("refresh_summary") or {}))
        return "\n".join(lines)

    lines = [
        f"account_profile_id={payload['account_profile_id']}",
        f"display_name={payload['display_name']}",
        f"workflow={payload['workflow_type']}",
        f"status={payload['status']}",
    ]
    decision_card = payload.get("decision_card") or {}
    if decision_card:
        lines.extend(
            [
                f"card_type={decision_card.get('card_type')}",
                f"summary={decision_card.get('summary')}",
                f"primary_recommendation={decision_card.get('primary_recommendation')}",
                f"recommended_action={decision_card.get('recommended_action')}",
            ]
        )
    key_metrics = payload.get("key_metrics") or {}
    if key_metrics:
        for key in ("success_probability", "max_drawdown_90pct", "shortfall_probability", "expected_terminal_value"):
            value = key_metrics.get(key)
            if value is not None:
                lines.append(f"{key}={value}")
    lines.extend(_render_provenance_block(payload.get("input_provenance") or {}))
    lines.extend(_render_input_source_summary(payload.get("input_provenance") or {}))
    lines.extend(_render_refresh_block(payload.get("refresh_summary") or {}))
    lines.extend(_render_execution_plan_block(payload.get("active_execution_plan"), label="active_execution_plan"))
    lines.extend(_render_execution_plan_block(payload.get("pending_execution_plan"), label="pending_execution_plan"))
    lines.extend(_render_execution_plan_comparison_block(payload.get("execution_plan_comparison")))
    lines.extend(_render_execution_plan_guidance_block(decision_card.get("execution_plan_guidance")))
    lines.extend(_render_formal_path_block(payload.get("formal_path_visibility")))
    lines.extend(
        _render_feedback_block(
            payload.get("execution_feedback"),
            payload.get("execution_feedback_summary"),
        )
    )
    lines.extend(_render_goal_semantics_block(payload.get("goal_semantics")))
    lines.extend(_render_profile_dimensions_block(payload.get("profile_dimensions")))
    lines.extend(external_lines)
    lines.extend(_render_candidate_lines(payload.get("candidate_options") or [], prefix="candidate"))
    lines.extend(_render_candidate_lines(payload.get("goal_alternatives") or [], prefix="alternative"))
    if decision_card.get("model_disclaimer"):
        lines.append(f"model_disclaimer={decision_card.get('model_disclaimer')}")
    return "\n".join(lines)


def render_frontdesk_snapshot(payload: dict[str, Any]) -> str:
    payload = _augment_formal_path_visibility(payload)
    profile = payload.get("profile") or {}
    latest_run = payload.get("latest_run") or {}
    latest_baseline = payload.get("latest_baseline") or {}
    lines = [
        f"account_profile_id={profile.get('account_profile_id')}",
        f"display_name={profile.get('display_name')}",
        f"latest_run_id={latest_run.get('run_id')}",
        f"latest_workflow={latest_run.get('workflow_type')}",
        f"latest_status={latest_run.get('status')}",
        f"latest_baseline_run_id={latest_baseline.get('run_id')}",
        f"latest_baseline_workflow={latest_baseline.get('workflow_type')}",
    ]
    decision_card = latest_run.get("decision_card") or latest_baseline.get("decision_card") or {}
    if decision_card:
        lines.append(f"latest_summary={decision_card.get('summary')}")
        lines.extend(_render_provenance_block(decision_card.get("input_provenance") or {}))
    lines.extend(_render_goal_semantics_block((profile.get("profile") or {}).get("goal_semantics")))
    lines.extend(_render_profile_dimensions_block((profile.get("profile") or {}).get("profile_dimensions")))
    lines.extend(_render_refresh_block(payload.get("refresh_summary") or {}))
    lines.extend(_render_execution_plan_block(payload.get("active_execution_plan"), label="active_execution_plan"))
    lines.extend(_render_execution_plan_block(payload.get("pending_execution_plan"), label="pending_execution_plan"))
    lines.extend(_render_execution_plan_comparison_block(payload.get("execution_plan_comparison")))
    lines.extend(_render_execution_plan_guidance_block(decision_card.get("execution_plan_guidance")))
    lines.extend(_render_formal_path_block(payload.get("formal_path_visibility")))
    lines.extend(
        _render_feedback_block(
            payload.get("execution_feedback"),
            payload.get("execution_feedback_summary"),
        )
    )
    return "\n".join(lines)


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", "--db", dest="db_path", default=str(DEFAULT_DB_PATH), help="SQLite path for frontdesk state.")
    parser.add_argument("--external-snapshot-source", help="Optional JSON file path, inline JSON, or HTTP URL for external market/account/behavior snapshots.")
    parser.add_argument(
        "--external-snapshot-config",
        "--external-data-config",
        dest="external_data_config",
        help="Optional adapter config JSON file path or inline JSON for provider-backed external snapshot fetch.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of summary text.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive Codex frontdesk for the investment system.")
    _add_common_flags(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    onboarding = subparsers.add_parser("onboarding", help="Run first-time onboarding for a user.")
    _add_common_flags(onboarding)
    onboarding.add_argument("--profile-json", help="用户画像 JSON 文件路径或 inline JSON。")
    onboarding.add_argument("--non-interactive", action="store_true")
    onboarding.add_argument("--account-profile-id")
    onboarding.add_argument("--display-name")
    onboarding.add_argument("--current-total-assets", type=float)
    onboarding.add_argument("--monthly-contribution", type=float)
    onboarding.add_argument("--goal-amount", type=float)
    onboarding.add_argument("--goal-horizon-months", type=int)
    onboarding.add_argument("--risk-preference")
    onboarding.add_argument("--max-drawdown-tolerance", type=float)
    onboarding.add_argument("--current-holdings")
    onboarding.add_argument("--restrictions", help="Comma-separated restrictions.")
    onboarding.add_argument("--goal-priority", choices=["essential", "important", "aspirational"])
    onboarding.add_argument("--goal-amount-basis", choices=["nominal", "real"], default="nominal")
    onboarding.add_argument("--goal-amount-scope", choices=["total_assets", "incremental_gain", "spending_need"], default="total_assets")
    onboarding.add_argument("--tax-assumption", choices=["pre_tax", "after_tax", "unknown"], default="pre_tax")
    onboarding.add_argument("--fee-assumption", choices=["transaction_cost_only", "platform_fee_excluded", "unknown"], default="transaction_cost_only")
    onboarding.add_argument("--contribution-commitment-confidence", type=float)

    onboard = subparsers.add_parser("onboard", help="Run first-time onboarding for a user.")
    _add_common_flags(onboard)
    onboard.add_argument("--profile-json", help="用户画像 JSON 文件路径或 inline JSON。")
    onboard.add_argument("--non-interactive", action="store_true")
    onboard.add_argument("--account-profile-id")
    onboard.add_argument("--display-name")
    onboard.add_argument("--current-total-assets", type=float)
    onboard.add_argument("--monthly-contribution", type=float)
    onboard.add_argument("--goal-amount", type=float)
    onboard.add_argument("--goal-horizon-months", type=int)
    onboard.add_argument("--risk-preference")
    onboard.add_argument("--max-drawdown-tolerance", type=float)
    onboard.add_argument("--current-holdings")
    onboard.add_argument("--restrictions", help="Comma-separated restrictions.")
    onboard.add_argument("--goal-priority", choices=["essential", "important", "aspirational"])
    onboard.add_argument("--goal-amount-basis", choices=["nominal", "real"], default="nominal")
    onboard.add_argument("--goal-amount-scope", choices=["total_assets", "incremental_gain", "spending_need"], default="total_assets")
    onboard.add_argument("--tax-assumption", choices=["pre_tax", "after_tax", "unknown"], default="pre_tax")
    onboard.add_argument("--fee-assumption", choices=["transaction_cost_only", "platform_fee_excluded", "unknown"], default="transaction_cost_only")
    onboard.add_argument("--contribution-commitment-confidence", type=float)

    for name in ("monthly", "event", "quarterly", "show-user"):
        sub = subparsers.add_parser(name, help=f"Run {name} flow using saved SQLite state.")
        _add_common_flags(sub)
        sub.add_argument("--account-profile-id", required=True)
        if name in {"monthly", "event", "quarterly"}:
            sub.add_argument("--profile-json", help="更新画像的 JSON 文件路径或 inline JSON；follow-up 只允许部分字段覆盖。")
            sub.add_argument("--non-interactive", action="store_true", help="Accepted for parity with onboarding; follow-up flows do not prompt.")
        if name == "event":
            sub.add_argument("--event-request", action="store_true", help="Simulate a high-risk user action request.")
            sub.add_argument("--event-context-json", help="Optional JSON file path or inline JSON for event request context.")

    status = subparsers.add_parser("status", help="Read saved user state from SQLite.")
    _add_common_flags(status)
    status.add_argument("--user-id", required=True)

    feedback = subparsers.add_parser("feedback", help="Record whether the user executed a recommended action.")
    _add_common_flags(feedback)
    feedback.add_argument("--account-profile-id", required=True)
    feedback.add_argument("--run-id", required=True)
    feedback.add_argument("--executed", action="store_true", help="Mark the recommendation as executed.")
    feedback.add_argument("--skipped", action="store_true", help="Mark the recommendation as skipped.")
    feedback.add_argument("--actual-action", help="Optional actual action taken by the user.")
    feedback.add_argument("--executed-at", help="Optional execution timestamp (ISO-8601).")
    feedback.add_argument("--note", help="Optional note explaining what the user did.")
    feedback.add_argument("--feedback-source", default="user", help="Metadata source label for this feedback record.")

    approve_plan = subparsers.add_parser("approve-plan", help="Approve a pending execution plan and promote it to active.")
    _add_common_flags(approve_plan)
    approve_plan.add_argument("--account-profile-id", required=True)
    approve_plan.add_argument("--plan-id", required=True)
    approve_plan.add_argument("--plan-version", type=int, required=True)
    approve_plan.add_argument("--approved-at", help="Optional approval timestamp (ISO-8601).")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db_path)
    external_snapshot_source = getattr(args, "external_snapshot_source", None)
    external_data_config = getattr(args, "external_data_config", None)
    if external_snapshot_source is not None and external_data_config is not None:
        raise SystemExit("use either --external-snapshot-source or --external-snapshot-config, not both")

    if args.command in {"onboarding", "onboard"}:
        if getattr(args, "profile_json", None):
            profile = _profile_from_json(args.profile_json)
        elif getattr(args, "non_interactive", False):
            profile = _profile_from_non_interactive_args(args)
        else:
            profile = _prompt_profile(args)
        payload = run_frontdesk_onboarding(
            profile,
            db_path=db_path,
            external_snapshot_source=external_snapshot_source,
            external_data_config=external_data_config,
        )
        if args.command == "onboard":
            payload = {
                "workflow": "onboard",
                "status": payload["status"],
                "run_id": payload["run_id"],
                "user_state": payload["user_state"],
                "refresh_summary": payload.get("refresh_summary"),
                "external_snapshot_source": payload.get("external_snapshot_source"),
                "external_snapshot_config": payload.get("external_snapshot_config"),
                "external_snapshot_status": payload.get("external_snapshot_status"),
                "external_snapshot_error": payload.get("external_snapshot_error"),
            }
    elif args.command == "show-user":
        payload = load_frontdesk_snapshot(args.account_profile_id, db_path=db_path)
        if payload is None:
            raise SystemExit(f"no saved frontdesk state for {args.account_profile_id}")
    elif args.command == "status":
        payload = {
            "workflow": "status",
            "user_state": load_user_state(args.user_id, db_path=db_path),
        }
        if payload["user_state"] is None:
            raise SystemExit(f"no saved frontdesk state for {args.user_id}")
    elif args.command == "feedback":
        if args.executed and args.skipped:
            raise SystemExit("use either --executed or --skipped, not both")
        executed_flag = True if args.executed else False if args.skipped else None
        payload = record_frontdesk_execution_feedback(
            account_profile_id=args.account_profile_id,
            source_run_id=args.run_id,
            user_executed=executed_flag,
            actual_action=args.actual_action,
            executed_at=args.executed_at,
            note=args.note,
            feedback_source=args.feedback_source,
            db_path=db_path,
        )
    elif args.command == "approve-plan":
        payload = approve_frontdesk_execution_plan(
            account_profile_id=args.account_profile_id,
            plan_id=args.plan_id,
            plan_version=args.plan_version,
            approved_at=args.approved_at,
            db_path=db_path,
        )
    else:
        profile = None
        event_context = None
        if getattr(args, "profile_json", None):
            profile = _profile_override_from_json(args.profile_json)
        if getattr(args, "event_context_json", None):
            event_context = _json_object_from_source(args.event_context_json, option_name="event-context-json")
        payload = run_frontdesk_followup(
            account_profile_id=args.account_profile_id,
            workflow_type=args.command,
            db_path=db_path,
            event_request=bool(getattr(args, "event_request", False)),
            profile=profile,
            event_context=event_context,
            external_snapshot_source=external_snapshot_source,
            external_data_config=external_data_config,
        )

    payload = _augment_formal_path_visibility(payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "show-user":
        print(render_frontdesk_snapshot(payload))
    else:
        print(render_frontdesk_summary(payload))
    return 0
