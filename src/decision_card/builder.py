from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from decision_card.types import DecisionCard, DecisionCardBuildInput, DecisionCardType


_SAFE_ACTION_TYPES = {"freeze", "observe"}
_LOW_CONFIDENCE_FLAGS = {"low"}
_INPUT_REPAIR_MARKERS = ("missing", "mismatch", "degraded", "quality=")
_TOP_CANDIDATE_COUNT = 3

_BUCKET_LABELS = {
    "equity_cn": "权益",
    "bond_cn": "债券",
    "gold": "黄金",
    "satellite": "卫星",
}

_CANDIDATE_PRESENTATION = {
    "defense_heavy": {
        "label": "防守优先方案",
        "description": "优先压低波动和回撤，适合先稳住账户波动体验。",
    },
    "balanced_core": {
        "label": "均衡核心方案",
        "description": "在增长和防守之间取中位，适合长期稳定执行。",
    },
    "balanced_progression": {
        "label": "平衡推进方案",
        "description": "在提高目标达成率的同时，尽量把回撤控制在可接受区间。",
    },
    "growth_tilt": {
        "label": "增长倾向方案",
        "description": "提高权益暴露，争取更高终值，但波动也更明显。",
    },
    "liquidity_buffered": {
        "label": "流动性缓冲方案",
        "description": "保留更强缓冲和防守垫，适合先建立可持续起步仓位。",
    },
    "theme_tilt": {
        "label": "主题增强方案",
        "description": "保留核心仓位，同时提高主题和卫星暴露。",
    },
    "satellite_light": {
        "label": "低卫星简化方案",
        "description": "压缩卫星仓位，让结构更简单、更容易长期执行。",
    },
}

_PROVENANCE_SOURCE_LABELS = {
    "user_provided": "用户提供",
    "system_inferred": "系统推断",
    "default_assumed": "默认假设",
    "external_data": "外部数据",
    "externally_fetched": "外部抓取",
}


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(getattr(value, "value", value)).strip()
    return rendered or None


def _string_items(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            items.extend(_string_items(*value))
            continue
        if isinstance(value, dict):
            continue
        rendered = _text(value)
        if rendered is not None:
            items.append(rendered)
    return items


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _metric(value: Any) -> str:
    rendered = _text(value)
    return "" if rendered is None else rendered


def _percent_metric(value: Any) -> str:
    metric = _float_metric(value)
    if metric is None:
        return ""
    return f"{metric * 100:.2f}%"


def _currency_metric(value: Any) -> str:
    metric = _float_metric(value)
    if metric is None:
        return ""
    return f"{metric:,.0f}"


def _action_type(value: Any) -> str | None:
    data = _obj(value)
    if isinstance(data, dict):
        return _text(data.get("type") or data.get("action_type"))
    return _text(data)


def _float_metric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coalesce_metric(value: Any, fallback: float) -> float:
    metric = _float_metric(value)
    if metric is None:
        return fallback
    return metric


def _candidate_style_key(name: str) -> str:
    return name.split("__", 1)[0].strip().lower()


def _fallback_candidate_label(name: str) -> str:
    tokens = [part for part in _candidate_style_key(name).split("_") if part]
    if not tokens:
        return "候选方案"
    return " ".join(token.capitalize() for token in tokens)


def _candidate_label(name: Any) -> str:
    candidate_name = _metric(name)
    if not candidate_name:
        return "候选方案"
    style = _CANDIDATE_PRESENTATION.get(_candidate_style_key(candidate_name))
    if style is not None:
        return str(style["label"])
    return _fallback_candidate_label(candidate_name)


def _candidate_description(name: Any, fallback: Any = None) -> str:
    candidate_name = _metric(name)
    if candidate_name:
        style = _CANDIDATE_PRESENTATION.get(_candidate_style_key(candidate_name))
        if style is not None:
            return str(style["description"])
    fallback_text = _text(fallback)
    if fallback_text is not None:
        return fallback_text
    return "系统根据目标达成率、回撤约束和执行可持续性综合生成。"


def _candidate_mix(weights: Any) -> list[str]:
    data = _obj(weights)
    if not isinstance(data, dict):
        return []
    parts: list[str] = []
    for bucket, value in data.items():
        bucket_label = _BUCKET_LABELS.get(str(bucket), str(bucket))
        percent = _percent_metric(value)
        if percent:
            parts.append(f"{bucket_label} {percent}")
    return parts


def _risk_level(max_drawdown_90pct: Any) -> str:
    metric = _float_metric(max_drawdown_90pct)
    if metric is None:
        return "待补充"
    if metric <= 0.12:
        return "低波动"
    if metric <= 0.18:
        return "中等波动"
    return "较高波动"


def _liquidity_label(weights: Any) -> str:
    data = _obj(weights)
    if not isinstance(data, dict):
        return "待补充"
    bond_weight = _float_metric(data.get("bond_cn")) or 0.0
    gold_weight = _float_metric(data.get("gold")) or 0.0
    buffer_weight = bond_weight + gold_weight
    if buffer_weight >= 0.40:
        return "流动性缓冲较强"
    if buffer_weight >= 0.20:
        return "流动性缓冲适中"
    return "流动性缓冲偏弱"


def _model_disclaimer(goal_output: dict[str, Any]) -> str:
    disclaimer = _metric(goal_output.get("disclaimer"))
    if disclaimer:
        return disclaimer
    return "以下为模型模拟结果，不是历史回测收益承诺。"


def _goal_solver_notes(goal_output: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for note in goal_output.get("solver_notes", []):
        rendered = _text(note)
        if rendered is None:
            continue
        if rendered.startswith("warning=no_feasible_allocation"):
            notes.append("当前目标、期限和回撤约束组合偏紧，标准候选里没有完全满足约束的方案。")
            continue
        if rendered.startswith("fallback=closest_feasible_candidate"):
            continue
        if rendered.startswith("action_required=reassess_goal_amount_or_horizon_or_drawdown_or_candidate_allocations"):
            notes.append("建议优先调整目标期末总资产、目标期限、每月投入或回撤容忍度，再重新生成方案。")
            continue
        if rendered.startswith("warning=success_probability_below_threshold"):
            notes.append("当前推荐方案仍低于你的目标达成阈值，需要结合目标优先级进一步确认。")
            continue
        if rendered.startswith("warning=empty_candidate_allocations"):
            notes.append("候选方案不足，系统使用默认起步方案继续给出建议。")
            continue
    return _unique(notes)


def _goal_semantics(goal_solver_input: Any) -> dict[str, Any]:
    goal_input = _obj(goal_solver_input)
    if not isinstance(goal_input, dict):
        goal_input = {}
    explicit = _obj(goal_input.get("goal_semantics"))
    if isinstance(explicit, dict) and explicit:
        return dict(explicit)
    goal = _obj(goal_input.get("goal", {}))
    semantics = {
        "goal_amount_basis": _metric(goal.get("goal_amount_basis")) or "nominal",
        "goal_amount_scope": _metric(goal.get("goal_amount_scope")) or "total_assets",
        "tax_assumption": _metric(goal.get("tax_assumption")) or "pre_tax",
        "fee_assumption": _metric(goal.get("fee_assumption")) or "transaction_cost_only",
        "contribution_commitment_confidence": _float_metric(goal.get("contribution_commitment_confidence")),
    }
    scope = semantics["goal_amount_scope"]
    if scope == "total_assets":
        semantics["explanation"] = "这里的目标金额指目标期末总资产，不是收益。"
    elif scope == "incremental_gain":
        semantics["explanation"] = "这里的目标金额按收益口径理解，不等于账户期末总资产。"
    else:
        semantics["explanation"] = "这里的目标金额按支出需求口径理解，不等于账户期末总资产。"
    disclosures = [
        semantics["explanation"],
        (
            "当前按名义金额展示，尚未单独折算通胀。"
            if semantics["goal_amount_basis"] == "nominal"
            else "你要求按实际购买力理解目标，但当前只做透明披露，尚未单独折算通胀。"
        ),
        (
            "当前默认按税前口径展示，尚未单独建模税差。"
            if semantics["tax_assumption"] == "pre_tax"
            else "你要求按税后口径理解目标，但当前只做透明披露，尚未单独建模税差。"
        ),
        "当前不会把费用、税差、通胀伪装成已经完整进入 solver。",
    ]
    confidence = semantics["contribution_commitment_confidence"]
    if confidence is not None:
        disclosures.append(f"每月投入兑现置信度按 {confidence:.0%} 记录，当前主要用于解释与风险分层。")
    semantics["disclosure_lines"] = disclosures
    return semantics


def _goal_output_is_no_feasible(goal_output: dict[str, Any]) -> bool:
    result = _obj(goal_output.get("recommended_result", {}))
    if result and result.get("is_feasible") is False:
        return True
    return any(
        _metric(note).startswith("warning=no_feasible_allocation")
        for note in goal_output.get("solver_notes", [])
    )


def _candidate_catalog(goal_solver_input: Any) -> dict[str, dict[str, Any]]:
    goal_input = _obj(goal_solver_input)
    if not isinstance(goal_input, dict):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for item in goal_input.get("candidate_allocations", []):
        data = _obj(item)
        name = _metric(data.get("name"))
        if name:
            catalog[name] = data
    return catalog


def _rank_goal_candidates(
    results: list[dict[str, Any]],
    recommended_name: str,
) -> list[dict[str, Any]]:
    if not results:
        return []
    named_results = [item for item in results if _metric(item.get("allocation_name"))]
    by_name = {_metric(item.get("allocation_name")): item for item in named_results}
    pool = named_results

    ordered_names: list[str] = []
    if recommended_name in by_name:
        ordered_names.append(recommended_name)

    selectors = (
        lambda item: _coalesce_metric(item.get("success_probability"), float("-inf")),
        lambda item: -_coalesce_metric(_obj(item.get("risk_summary")).get("max_drawdown_90pct"), float("inf")),
        lambda item: -_coalesce_metric(_obj(item.get("risk_summary")).get("shortfall_probability"), float("inf")),
    )
    for selector in selectors:
        chosen = max(pool, key=selector, default=None)
        chosen_name = _metric(_obj(chosen).get("allocation_name")) if chosen is not None else None
        if chosen_name and chosen_name not in ordered_names:
            ordered_names.append(chosen_name)

    remaining = sorted(
        pool,
        key=lambda item: (
            -_coalesce_metric(item.get("success_probability"), float("-inf")),
            _coalesce_metric(_obj(item.get("risk_summary")).get("max_drawdown_90pct"), float("inf")),
        ),
    )
    for item in remaining:
        name = _metric(item.get("allocation_name"))
        if name and name not in ordered_names:
            ordered_names.append(name)

    return [by_name[name] for name in ordered_names if name in by_name]


def _candidate_highlight(
    result: dict[str, Any],
    *,
    recommended_name: str,
    highest_success_name: str | None,
    lowest_drawdown_name: str | None,
    lowest_shortfall_name: str | None,
    no_feasible: bool = False,
) -> str:
    name = _metric(result.get("allocation_name")) or ""
    if name == recommended_name:
        return "最接近可行" if no_feasible else "系统推荐"
    if name == highest_success_name:
        return "达成率更高"
    if name == lowest_drawdown_name:
        return "回撤更低"
    if name == lowest_shortfall_name:
        return "短缺风险更低"
    return "备选方案"


def _build_goal_candidate_options(inp: DecisionCardBuildInput, goal_output: dict[str, Any]) -> list[dict[str, Any]]:
    recommended = _obj(goal_output.get("recommended_allocation", {}))
    recommended_result = _obj(goal_output.get("recommended_result", {}))
    recommended_name = _metric(recommended_result.get("allocation_name") or recommended.get("name")) or ""
    all_results = [_obj(item) for item in goal_output.get("candidate_menu", [])]
    if not all_results:
        all_results = [_obj(item) for item in goal_output.get("all_results", [])]
    if not all_results and recommended_result:
        all_results = [recommended_result]

    catalog = _candidate_catalog(inp.goal_solver_input)
    metrics_pool = all_results
    highest_success_name = None
    lowest_drawdown_name = None
    lowest_shortfall_name = None
    if metrics_pool:
        highest_success_name = _metric(
            max(metrics_pool, key=lambda item: _coalesce_metric(item.get("success_probability"), float("-inf"))).get(
                "allocation_name"
            )
        )
        lowest_drawdown_name = _metric(
            min(
                metrics_pool,
                key=lambda item: _coalesce_metric(
                    _obj(item.get("risk_summary")).get("max_drawdown_90pct"),
                    float("inf"),
                ),
            ).get("allocation_name")
        )
        lowest_shortfall_name = _metric(
            min(
                metrics_pool,
                key=lambda item: _coalesce_metric(
                    _obj(item.get("risk_summary")).get("shortfall_probability"),
                    float("inf"),
                ),
            ).get("allocation_name")
        )
    no_feasible = _goal_output_is_no_feasible(goal_output)

    ranked_results = _rank_goal_candidates(all_results, recommended_name)[:_TOP_CANDIDATE_COUNT]
    options: list[dict[str, Any]] = []
    for result in ranked_results:
        risk_summary = _obj(result.get("risk_summary", {}))
        allocation_name = _metric(result.get("allocation_name")) or ""
        catalog_entry = catalog.get(allocation_name, {})
        complexity = _float_metric(catalog_entry.get("complexity_score"))
        label = _metric(result.get("display_name")) or _candidate_label(allocation_name)
        description = (
            _metric(result.get("summary"))
            or _metric(catalog_entry.get("user_summary"))
            or _candidate_description(allocation_name, catalog_entry.get("description"))
        )
        success_probability = _percent_metric(result.get("success_probability"))
        expected_terminal_value = _currency_metric(result.get("expected_terminal_value"))
        max_drawdown_90pct = _percent_metric(risk_summary.get("max_drawdown_90pct"))
        shortfall_probability = _percent_metric(risk_summary.get("shortfall_probability"))
        option = {
            "label": label,
            "highlight": _candidate_highlight(
                result,
                recommended_name=recommended_name,
                highest_success_name=highest_success_name,
                lowest_drawdown_name=lowest_drawdown_name,
                lowest_shortfall_name=lowest_shortfall_name,
                no_feasible=no_feasible,
            ),
            "description": description,
            "allocation_mix": _candidate_mix(result.get("weights")),
            "success_probability": success_probability,
            "expected_terminal_value": expected_terminal_value,
            "max_drawdown_90pct": max_drawdown_90pct,
            "shortfall_probability": shortfall_probability,
            "metrics": {
                "success_probability": success_probability,
                "expected_terminal_value": expected_terminal_value,
                "max_drawdown_90pct": max_drawdown_90pct,
                "shortfall_probability": shortfall_probability,
            },
            "is_recommended": allocation_name == recommended_name,
            "is_feasible": bool(result.get("is_feasible")),
            "infeasibility_reasons": _string_items(result.get("infeasibility_reasons")),
            "complexity_label": _metric(result.get("complexity_label")) or "",
            "risk_label": _risk_level(risk_summary.get("max_drawdown_90pct")),
            "liquidity_label": _liquidity_label(result.get("weights")),
            "why_selected": _candidate_highlight(
                result,
                recommended_name=recommended_name,
                highest_success_name=highest_success_name,
                lowest_drawdown_name=lowest_drawdown_name,
                lowest_shortfall_name=lowest_shortfall_name,
                no_feasible=no_feasible,
            ),
            "model_disclaimer": _model_disclaimer(goal_output),
            "evidence_source": "model_estimate",
        }
        if complexity is not None:
            option["complexity_score"] = f"{complexity:.2f}"
        options.append(option)
    return options


def _build_goal_fallback_options(goal_output: dict[str, Any]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for item in goal_output.get("fallback_suggestions", []):
        data = _obj(item)
        risk_summary = _obj(data.get("risk_summary", {}))
        options.append(
            {
                "label": _metric(data.get("label")) or "调整目标条件后重试",
                "highlight": "替代路径",
                "description": "重新计算后的替代方案，便于你快速判断下一步要放松哪项约束。",
                "success_probability": _percent_metric(data.get("success_probability")),
                "max_drawdown_90pct": _percent_metric(risk_summary.get("max_drawdown_90pct")),
                "shortfall_probability": _percent_metric(risk_summary.get("shortfall_probability")),
                "metrics": {
                    "success_probability": _percent_metric(data.get("success_probability")),
                    "max_drawdown_90pct": _percent_metric(risk_summary.get("max_drawdown_90pct")),
                    "shortfall_probability": _percent_metric(risk_summary.get("shortfall_probability")),
                },
                "model_disclaimer": _model_disclaimer(goal_output),
                "evidence_source": _metric(data.get("evidence_source")) or "model_estimate",
            }
        )
    return options


def _build_input_provenance(inp: DecisionCardBuildInput) -> dict[str, Any]:
    raw = _obj(inp.input_provenance)
    items: list[dict[str, str]] = []
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        source_items = raw.get("items", [])
    elif isinstance(raw, dict):
        source_items = []
        for field_name, value in raw.items():
            if field_name in _PROVENANCE_SOURCE_LABELS and isinstance(value, list):
                for item in value:
                    data = _obj(item)
                    if isinstance(data, dict):
                        source_items.append({"field": data.get("field") or field_name, **data, "source_type": field_name})
                    else:
                        source_items.append({"field": field_name, "source_type": field_name, "detail": _metric(item)})
                continue
            data = _obj(value)
            if isinstance(data, dict):
                source_items.append({"field": field_name, **data})
            else:
                source_items.append({"field": field_name, "source_type": _metric(value)})
    elif isinstance(raw, list):
        source_items = raw
    else:
        source_items = []

    for item in source_items:
        data = _obj(item)
        source_type = _metric(data.get("source_type")) or "default_assumed"
        if source_type == "external_data":
            source_type = "externally_fetched"
        items.append(
            {
                "field": _metric(data.get("field")) or "unknown",
                "label": _metric(data.get("label")) or _metric(data.get("field")) or "未知字段",
                "source_type": source_type,
                "source_label": _PROVENANCE_SOURCE_LABELS.get(source_type, source_type),
                "value": data.get("value"),
                "note": _metric(data.get("note")),
                "detail": _metric(data.get("detail")) or "",
                "source_ref": _metric(data.get("source_ref")) or _metric(data.get("value")) or "",
                "as_of": _metric(data.get("as_of")) or "",
                "fetched_at": _metric(data.get("fetched_at")) or "",
                "freshness_state": _metric(data.get("freshness_state")) or _metric(data.get("freshness_status")) or "",
                "data_status": _metric(data.get("data_status")) or "",
                "audit_window": data.get("audit_window"),
            }
        )

    counts = {
        source_type: sum(1 for item in items if item["source_type"] == source_type)
        for source_type in _PROVENANCE_SOURCE_LABELS
    }
    grouped = {
        source_type: [item for item in items if item["source_type"] == source_type]
        for source_type in _PROVENANCE_SOURCE_LABELS
    }
    return {
        "items": items,
        "counts": counts,
        "source_labels": dict(_PROVENANCE_SOURCE_LABELS),
        **grouped,
    }


def _input_source_sections(input_provenance: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for source_type, source_label in _PROVENANCE_SOURCE_LABELS.items():
        entries = list(input_provenance.get(source_type, []))
        if not entries:
            continue
        sections.append(
            {
                "source_type": source_type,
                "source_label": source_label,
                "count": len(entries),
                "items": [
                    {
                        "field": item.get("field"),
                        "label": item.get("label"),
                        "value": item.get("value"),
                        "note": item.get("note") or item.get("detail"),
                        "source_ref": item.get("source_ref"),
                        "as_of": item.get("as_of"),
                        "data_status": item.get("data_status"),
                        "audit_window": item.get("audit_window"),
                    }
                    for item in entries
                ],
            }
        )
    return sections


def _input_source_summary(input_provenance: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    for source_type, source_label in _PROVENANCE_SOURCE_LABELS.items():
        count = len(input_provenance.get(source_type, []))
        summary.append(f"{source_label} {count} 项")
    return summary


def _ranked_entries(ev_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [_obj(item) for item in ev_report.get("ranked_actions", [])]


def _eliminated_reasons(ev_report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for item in ev_report.get("eliminated_actions", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            reasons.extend(_string_items(_obj(item[1]).get("fail_reasons")))
    return _unique(reasons)


def _confidence_flag(ev_report: dict[str, Any]) -> str:
    return (_text(ev_report.get("confidence_flag")) or "").lower()


def _runner_up_action(ev_report: dict[str, Any]) -> str | None:
    ranked_actions = _ranked_entries(ev_report)
    if len(ranked_actions) < 2:
        return None
    return _action_type(ranked_actions[1].get("action"))


def _recommended_score_total(ev_report: dict[str, Any]) -> str:
    recommended_score = _obj(ev_report.get("recommended_score") or {})
    return _metric(recommended_score.get("total"))


def _delta_prob(ev_report: dict[str, Any]) -> str:
    baseline = _float_metric(ev_report.get("goal_solver_baseline"))
    after = _float_metric(ev_report.get("goal_solver_after_recommended"))
    if baseline is None or after is None:
        return ""
    return f"{after - baseline:.6f}"


def _candidate_poverty(runtime_result: dict[str, Any]) -> bool:
    return bool(runtime_result.get("candidate_poverty"))


def _is_low_confidence(
    inp: DecisionCardBuildInput,
    runtime_result: dict[str, Any],
    ev_report: dict[str, Any],
) -> bool:
    if inp.blocking_reasons or inp.degraded_notes or inp.escalation_reasons:
        return True
    if _candidate_poverty(runtime_result):
        return True
    return _confidence_flag(ev_report) in _LOW_CONFIDENCE_FLAGS


def _status_badge_for_runtime(
    inp: DecisionCardBuildInput,
    recommended_action: str | None,
    runtime_result: dict[str, Any],
    ev_report: dict[str, Any],
) -> str:
    if inp.blocking_reasons:
        return "blocked"
    if inp.degraded_notes:
        return "degraded"
    if recommended_action in _SAFE_ACTION_TYPES:
        return "observe"
    if _is_low_confidence(inp, runtime_result, ev_report):
        return "caution"
    if _confidence_flag(ev_report) == "high":
        return "ok"
    return "caution"


def _build_trace_refs(inp: DecisionCardBuildInput, runtime_result: dict[str, Any]) -> dict[str, str]:
    workflow_decision = _obj(inp.workflow_decision or {})
    audit_record = _obj(inp.audit_record or {})
    version_refs = _obj(audit_record.get("version_refs", {}))
    ev_report = _obj(runtime_result.get("ev_report", {}))
    trace_refs = {
        "run_id": inp.run_id,
        "bundle_id": inp.bundle_id or "",
        "calibration_id": inp.calibration_id or "",
        "solver_snapshot_id": inp.solver_snapshot_id or "",
        "state_snapshot_id": _metric(ev_report.get("state_snapshot_id")),
        "requested_workflow_type": _metric(workflow_decision.get("requested_workflow_type")),
        "selected_workflow_type": _metric(workflow_decision.get("selected_workflow_type")),
        "goal_solver_params_version": _metric(version_refs.get("goal_solver_params_version")),
        "runtime_optimizer_params_version": _metric(version_refs.get("runtime_optimizer_params_version")),
        "ev_params_version": _metric(version_refs.get("ev_params_version")),
        "runtime_run_timestamp": _metric(version_refs.get("runtime_run_timestamp")),
    }
    return {key: value for key, value in trace_refs.items() if value}


def _build_guardrails(
    inp: DecisionCardBuildInput,
    runtime_result: dict[str, Any],
    *,
    low_confidence: bool,
) -> list[str]:
    runtime_restriction = _obj(inp.runtime_restriction or {})
    extras: list[str] = []
    extras.extend(_string_items(runtime_restriction.get("restriction_reasons")))
    blocked_actions = _string_items(runtime_restriction.get("blocked_actions"))
    if blocked_actions:
        extras.append("blocked_actions=" + ",".join(blocked_actions))
    if runtime_restriction.get("forced_safe_action"):
        extras.append(f"forced_safe_action={runtime_restriction['forced_safe_action']}")
    if low_confidence:
        extras.append("low_confidence=true")
    return _unique(
        _string_items(
            inp.blocking_reasons,
            inp.degraded_notes,
            inp.control_directives,
            extras,
        )
    )


def _build_execution_notes(
    inp: DecisionCardBuildInput,
    runtime_result: dict[str, Any],
    *,
    low_confidence: bool,
) -> list[str]:
    audit_record = _obj(inp.audit_record or {})
    workflow_decision = _obj(inp.workflow_decision or {})
    runtime_restriction = _obj(inp.runtime_restriction or {})
    ev_report = _obj(runtime_result.get("ev_report", {}))
    notes = [
        f"trigger_type={_metric(ev_report.get('trigger_type') or inp.workflow_type)}",
        f"state_snapshot_id={_metric(ev_report.get('state_snapshot_id'))}",
        f"selection_reason={_metric(workflow_decision.get('selection_reason'))}",
        f"confidence_flag={_metric(ev_report.get('confidence_flag'))}",
        f"confidence_reason={_metric(ev_report.get('confidence_reason'))}",
    ]
    notes.extend(f"directive={item}" for item in inp.control_directives)
    if runtime_restriction.get("forced_safe_action"):
        notes.append(f"forced_safe_action={runtime_restriction['forced_safe_action']}")
    restriction_reasons = _string_items(runtime_restriction.get("restriction_reasons"))
    if "cooldown_active" in restriction_reasons:
        notes.append("review_condition=cooldown_active")
    if runtime_restriction.get("requires_escalation"):
        notes.append("manual_review_required")
    control_flags = _obj(audit_record.get("control_flags", {}))
    if control_flags.get("cooldown_until") is not None:
        notes.append(f"cooldown_until={control_flags['cooldown_until']}")
    if low_confidence:
        notes.append("treat_as_weak_signal")
    return [note for note in notes if not note.endswith("=")]


def _build_review_conditions(
    inp: DecisionCardBuildInput,
    runtime_result: dict[str, Any],
    *,
    recommended_action: str | None,
    low_confidence: bool,
) -> list[str]:
    audit_record = _obj(inp.audit_record or {})
    control_flags = _obj(audit_record.get("control_flags", {}))
    runtime_restriction = _obj(inp.runtime_restriction or {})
    conditions: list[str] = []

    if control_flags.get("cooldown_until") is not None:
        conditions.append(f"after_cooldown_until={control_flags['cooldown_until']}")
    if runtime_restriction.get("requires_escalation"):
        conditions.append("after_manual_review")
    if any(any(marker in item for marker in _INPUT_REPAIR_MARKERS) for item in inp.blocking_reasons):
        conditions.append("after_input_repair")
    if _candidate_poverty(runtime_result) or low_confidence:
        conditions.append("after_next_review_cycle")
    if recommended_action in _SAFE_ACTION_TYPES:
        conditions.append("after_clearer_signal")
    return _unique(conditions)


def _build_next_steps(
    inp: DecisionCardBuildInput,
    *,
    recommended_action: str,
    low_confidence: bool,
) -> list[str]:
    runtime_restriction = _obj(inp.runtime_restriction or {})
    next_steps: list[str] = []
    if inp.blocking_reasons:
        next_steps.append("resolve_blockers")
    if any("manual_review_required" in item for item in inp.control_directives) or runtime_restriction.get(
        "requires_escalation"
    ):
        next_steps.append("manual_review")
    if recommended_action in _SAFE_ACTION_TYPES:
        next_steps.append("hold_and_recheck")
    elif recommended_action not in {"blocked", "review"}:
        next_steps.append("execute_within_guardrails")
    # Plan replacement guidance
    for directive in inp.control_directives:
        text = _text(directive) or ""
        if text.startswith("plan_change="):
            value = text.split("=", 1)[-1].strip()
            if value == "replace_active":
                next_steps.append("adopt_pending_plan")
            elif value == "review_replace":
                next_steps.append("review_pending_plan")
            elif value == "keep_active":
                next_steps.append("keep_active_plan")
    if low_confidence:
        next_steps.append("treat_as_weak_signal")
    return _unique(next_steps)


def _build_runtime_evidence(
    inp: DecisionCardBuildInput,
    runtime_result: dict[str, Any],
    ev_report: dict[str, Any],
) -> list[str]:
    evidence = [
        f"confidence_flag={_metric(ev_report.get('confidence_flag'))}",
        f"goal_solver_baseline={_metric(ev_report.get('goal_solver_baseline'))}",
        f"goal_solver_after_recommended={_metric(ev_report.get('goal_solver_after_recommended'))}",
        f"candidate_poverty={str(_candidate_poverty(runtime_result)).lower()}",
    ]
    score_total = _recommended_score_total(ev_report)
    if score_total:
        evidence.append(f"recommended_score_total={score_total}")
    delta_prob = _delta_prob(ev_report)
    if delta_prob:
        evidence.append(f"delta_prob={delta_prob}")
    runner_up = _runner_up_action(ev_report)
    if runner_up:
        evidence.append(f"runner_up_action={runner_up}")
    evidence.extend(_eliminated_reasons(ev_report)[:2])
    return _unique([item for item in evidence if not item.endswith("=")])


def _build_goal_evidence(inp: DecisionCardBuildInput, goal_output: dict[str, Any]) -> list[str]:
    result = _obj(goal_output.get("recommended_result", {}))
    risk_summary = _obj(result.get("risk_summary", {}))
    structure_budget = _obj(goal_output.get("structure_budget", {}))
    evidence = [
        f"success_probability={_metric(result.get('success_probability'))}",
        f"max_drawdown_90pct={_metric(risk_summary.get('max_drawdown_90pct'))}",
        f"shortfall_probability={_metric(risk_summary.get('shortfall_probability'))}",
        f"core_weight={_metric(structure_budget.get('core_weight'))}",
        f"satellite_weight={_metric(structure_budget.get('satellite_weight'))}",
    ]
    formatted = [
        f"success_probability_display={_percent_metric(result.get('success_probability'))}",
        f"max_drawdown_90pct_display={_percent_metric(risk_summary.get('max_drawdown_90pct'))}",
        f"shortfall_probability_display={_percent_metric(risk_summary.get('shortfall_probability'))}",
        f"core_weight_display={_percent_metric(structure_budget.get('core_weight'))}",
        f"satellite_weight_display={_percent_metric(structure_budget.get('satellite_weight'))}",
    ]
    return _unique(
        [item for item in evidence + formatted if not item.endswith("=")]
        + _goal_solver_notes(goal_output)
        + _string_items(goal_output.get("disclaimer"))
    )


def _build_blocked_evidence(inp: DecisionCardBuildInput) -> list[str]:
    return _unique(
        _string_items(
            inp.blocking_reasons,
            inp.degraded_notes,
            inp.escalation_reasons,
            inp.control_directives,
        )
    )


def _finalize_card(card: DecisionCard) -> dict[str, Any]:
    if not card.input_source_summary:
        card.input_source_summary = _input_source_summary(card.input_provenance)
    if not card.input_source_sections:
        card.input_source_sections = _input_source_sections(card.input_provenance)
    return card.to_dict()


def _execution_plan_summary(inp: DecisionCardBuildInput) -> dict[str, Any]:
    return dict(inp.execution_plan_summary or {})


def _first_title(workflow_type: str, preferred: Any, fallback: str) -> str:
    title = _text(preferred)
    if title is not None:
        return title
    return f"{workflow_type} {fallback}"


def _build_runtime_action_card(inp: DecisionCardBuildInput, runtime_result: dict[str, Any]) -> dict[str, Any]:
    ev_report = _obj(runtime_result.get("ev_report", {}))
    ranked_actions = _ranked_entries(ev_report)
    first_ranked = ranked_actions[0] if ranked_actions else {}
    recommended_action = _action_type(
        ev_report.get("recommended_action") or first_ranked.get("action")
    )
    if recommended_action is None:
        raise ValueError("runtime_action card requires recommended_action or ranked_actions")
    low_confidence = _is_low_confidence(inp, runtime_result, ev_report)
    reasons = _unique(
        _string_items(
            first_ranked.get("recommendation_reason"),
            ev_report.get("confidence_reason"),
            inp.degraded_notes if recommended_action in _SAFE_ACTION_TYPES else [],
        )
    )
    if not reasons:
        reasons = ["runtime action"]

    runner_up = _runner_up_action(ev_report)
    not_recommended_reason = _unique(
        _string_items(
            ranked_actions[1].get("recommendation_reason") if len(ranked_actions) > 1 else None,
            _eliminated_reasons(ev_report)[:2],
        )
    )
    alternatives = _unique(
        [
            action_type
            for action_type in (_action_type(item.get("action")) for item in ranked_actions[1:])
            if action_type is not None
        ]
    )

    if recommended_action == "freeze":
        summary = "当前建议 freeze，先维持现状"
        if low_confidence:
            summary += "，本轮信号较弱"
    elif recommended_action == "observe":
        summary = "当前建议 observe，先观察并复核"
        if low_confidence:
            summary += "，本轮信号较弱"
    else:
        summary = f"当前建议执行 {recommended_action}"
        if low_confidence:
            summary += "，但本轮信号较弱"

    card = DecisionCard(
        card_id=inp.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        card_type=DecisionCardType.RUNTIME_ACTION,
        workflow_type=inp.workflow_type,
        title=f"{inp.workflow_type} runtime action",
        status_badge=_status_badge_for_runtime(inp, recommended_action, runtime_result, ev_report),
        summary=summary,
        primary_recommendation=recommended_action,
        recommendation_reason=reasons,
        not_recommended_reason=not_recommended_reason,
        key_metrics={
            "confidence": _metric(ev_report.get("confidence_flag") or "low"),
            "baseline": _metric(ev_report.get("goal_solver_baseline")),
            "after": _metric(ev_report.get("goal_solver_after_recommended")),
            "delta_prob": _delta_prob(ev_report),
            "recommended_score_total": _recommended_score_total(ev_report),
            "candidates_after_filter": _metric(runtime_result.get("candidates_after_filter")),
        },
        alternatives=alternatives,
        guardrails=_build_guardrails(inp, runtime_result, low_confidence=low_confidence),
        execution_notes=_build_execution_notes(inp, runtime_result, low_confidence=low_confidence),
        trace_refs=_build_trace_refs(inp, runtime_result),
        recommended_action=recommended_action,
        reasons=reasons,
        evidence_highlights=_build_runtime_evidence(inp, runtime_result, ev_report),
        input_provenance=_build_input_provenance(inp),
        review_conditions=_build_review_conditions(
            inp,
            runtime_result,
            recommended_action=recommended_action,
            low_confidence=low_confidence,
        ),
        next_steps=_build_next_steps(
            inp,
            recommended_action=recommended_action,
            low_confidence=low_confidence,
        ),
        runner_up_action=runner_up,
        low_confidence=low_confidence,
        execution_plan_summary=_execution_plan_summary(inp),
    )
    return _finalize_card(card)


def _build_goal_baseline_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    goal_output = _obj(inp.goal_solver_output or {})
    recommended = _obj(goal_output.get("recommended_allocation", {}))
    result = _obj(goal_output.get("recommended_result", {}))
    risk_summary = _obj(result.get("risk_summary", {}))
    candidate_options = _build_goal_candidate_options(inp, goal_output)
    fallback_options = _build_goal_fallback_options(goal_output)
    model_disclaimer = _model_disclaimer(goal_output)
    goal_semantics = _goal_semantics(inp.goal_solver_input)
    no_feasible = _goal_output_is_no_feasible(goal_output)
    recommended_name = _metric(result.get("allocation_name") or recommended.get("name"))
    recommended_label = (
        _metric(candidate_options[0].get("label"))
        if candidate_options
        else _candidate_label(recommended_name)
    )
    recommended_description = (
        _metric(candidate_options[0].get("description"))
        if candidate_options
        else _candidate_description(recommended_name, recommended.get("description"))
    )
    reasons = _unique(
        _string_items(
            candidate_options[0].get("description") if candidate_options else recommended_description,
            f"模型模拟下目标期末总资产达成概率约 { _percent_metric(result.get('success_probability')) }" if _percent_metric(result.get("success_probability")) else None,
            f"90% 情况下最大回撤约 { _percent_metric(risk_summary.get('max_drawdown_90pct')) }" if _percent_metric(risk_summary.get("max_drawdown_90pct")) else None,
            _goal_solver_notes(goal_output),
            goal_semantics.get("disclosure_lines", [])[:2],
        )
    )
    if no_feasible:
        reasons = _unique(
            [
                "当前不存在满足你回撤约束的配置。",
                "下面展示的是最接近可行的临时参考，不是正式推荐。",
            ]
            + reasons
        )
    if not reasons:
        reasons = ["系统综合目标达成率、回撤约束和执行复杂度后，给出当前起步方案。"]
    low_confidence = bool(inp.degraded_notes) or no_feasible
    if no_feasible:
        summary = (
            "当前不存在满足你回撤约束的配置。"
            f"下面先展示“{recommended_label}”作为最接近可行的临时参考，不应当作正式推荐。"
        )
    else:
        summary = f"当前建议先采用“{recommended_label}”，作为你的起步基线方案。"
    if recommended_description and not no_feasible:
        summary += recommended_description
    if model_disclaimer:
        summary += f" {model_disclaimer}"
    user_visible_alternatives = fallback_options or candidate_options[1:]
    review_conditions = _build_review_conditions(
        inp,
        {},
        recommended_action="adopt_recommended_plan",
        low_confidence=low_confidence,
    )
    next_steps = _build_next_steps(
        inp,
        recommended_action="adopt_recommended_plan",
        low_confidence=low_confidence,
    )
    if no_feasible:
        review_conditions = _unique(review_conditions + ["after_relaxing_goal_or_drawdown"])
        next_steps = _unique(["reassess_goal_constraints"] + next_steps)
    card = DecisionCard(
        card_id=inp.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        card_type=DecisionCardType.GOAL_BASELINE,
        workflow_type=inp.workflow_type,
        title=_first_title(inp.workflow_type, goal_output.get("goal_description"), "goal baseline"),
        status_badge="degraded" if low_confidence else "ok",
        summary=summary,
        primary_recommendation=recommended_label,
        recommendation_reason=reasons,
        not_recommended_reason=[],
        key_metrics={
            "success_probability": _percent_metric(result.get("success_probability")),
            "expected_terminal_value": _currency_metric(result.get("expected_terminal_value")),
            "max_drawdown_90pct": _percent_metric(risk_summary.get("max_drawdown_90pct")),
            "shortfall_probability": _percent_metric(risk_summary.get("shortfall_probability")),
        },
        alternatives=user_visible_alternatives,
        guardrails=_build_guardrails(inp, {}, low_confidence=low_confidence),
        execution_notes=_build_execution_notes(inp, {}, low_confidence=low_confidence),
        trace_refs=_build_trace_refs(inp, {}),
        recommended_action="adopt_recommended_plan",
        reasons=reasons,
        evidence_highlights=_build_goal_evidence(inp, goal_output),
        model_disclaimer=model_disclaimer,
        input_provenance=_build_input_provenance(inp),
        candidate_options=candidate_options,
        goal_alternatives=user_visible_alternatives,
        review_conditions=review_conditions,
        next_steps=next_steps,
        low_confidence=low_confidence,
        goal_semantics=goal_semantics,
        execution_plan_summary=_execution_plan_summary(inp),
    )
    return _finalize_card(card)


def _build_blocked_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    reasons = _unique(_string_items(inp.blocking_reasons, inp.degraded_notes, inp.escalation_reasons))
    if not reasons:
        reasons = ["blocked"]
    degraded_only = not inp.blocking_reasons and bool(inp.degraded_notes)
    primary_recommendation = inp.control_directives[0] if inp.control_directives else "resolve blockers"
    recommended_action = "review" if degraded_only else "blocked"
    card = DecisionCard(
        card_id=inp.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        card_type=DecisionCardType.BLOCKED,
        workflow_type=inp.workflow_type,
        title=f"{inp.workflow_type} blocked",
        status_badge="degraded" if degraded_only else "blocked",
        summary=reasons[0],
        primary_recommendation=primary_recommendation,
        recommendation_reason=reasons,
        not_recommended_reason=[],
        key_metrics={},
        alternatives=[],
        guardrails=_build_guardrails(inp, {}, low_confidence=True),
        execution_notes=_build_execution_notes(inp, {}, low_confidence=True),
        trace_refs=_build_trace_refs(inp, {}),
        recommended_action=recommended_action,
        reasons=reasons,
        evidence_highlights=_build_blocked_evidence(inp),
        input_provenance=_build_input_provenance(inp),
        review_conditions=_build_review_conditions(
            inp,
            {},
            recommended_action=recommended_action,
            low_confidence=True,
        ),
        next_steps=_build_next_steps(
            inp,
            recommended_action=recommended_action,
            low_confidence=True,
        ),
        low_confidence=True,
        execution_plan_summary=_execution_plan_summary(inp),
    )
    return _finalize_card(card)


def _build_quarterly_review_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    runtime_result = _obj(inp.runtime_result or {})
    goal_output = _obj(inp.goal_solver_output or {})
    ev_report = _obj(runtime_result.get("ev_report", {}))
    result = _obj(goal_output.get("recommended_result", {}))
    ranked_actions = _ranked_entries(ev_report)
    quarterly_runtime_action = _action_type(
        ev_report.get("recommended_action") or (ranked_actions[0].get("action") if ranked_actions else None)
    ) or "observe"
    low_confidence = _is_low_confidence(inp, runtime_result, ev_report)
    reasons = _unique(
        _string_items(
            inp.escalation_reasons,
            inp.degraded_notes,
            _goal_solver_notes(goal_output),
            ranked_actions[0].get("recommendation_reason") if ranked_actions else None,
            ev_report.get("confidence_reason"),
            "quarterly review",
        )
    )
    alternatives = _unique(
        [
            action_type
            for action_type in (_action_type(item.get("action")) for item in ranked_actions[1:])
            if action_type is not None
        ]
    )
    not_recommended_reason = _unique(
        _string_items(
            ranked_actions[1].get("recommendation_reason") if len(ranked_actions) > 1 else None,
            _eliminated_reasons(ev_report)[:2],
        )
    )
    risk_summary = _obj(result.get("risk_summary", {}))
    candidate_options = _build_goal_candidate_options(inp, goal_output)
    model_disclaimer = _model_disclaimer(goal_output)
    recommended_baseline_label = _candidate_label(
        result.get("allocation_name") or _obj(goal_output.get("recommended_allocation", {})).get("name")
    )
    card = DecisionCard(
        card_id=inp.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        card_type=DecisionCardType.QUARTERLY_REVIEW,
        workflow_type=inp.workflow_type,
        title=f"{inp.workflow_type} review",
        status_badge="degraded" if inp.degraded_notes else ("caution" if low_confidence else "ok"),
        summary=(
            f"季度复审已生成。新的基线候选以“{recommended_baseline_label}”为主，"
            f"运行时建议先执行 {quarterly_runtime_action} 并完成复核。{model_disclaimer}"
        ),
        primary_recommendation="review",
        recommendation_reason=reasons,
        not_recommended_reason=not_recommended_reason,
        key_metrics={
            "new_baseline_success_probability": _percent_metric(result.get("success_probability")),
            "new_baseline_max_drawdown_90pct": _percent_metric(risk_summary.get("max_drawdown_90pct")),
            "quarterly_action_confidence": _metric(ev_report.get("confidence_flag")),
            "quarterly_runtime_action": quarterly_runtime_action,
        },
        alternatives=alternatives,
        guardrails=_build_guardrails(inp, runtime_result, low_confidence=low_confidence),
        execution_notes=_build_execution_notes(inp, runtime_result, low_confidence=low_confidence),
        trace_refs=_build_trace_refs(inp, runtime_result),
        recommended_action="review",
        reasons=reasons,
        evidence_highlights=_unique(
            _build_goal_evidence(inp, goal_output) + _build_runtime_evidence(inp, runtime_result, ev_report)
        ),
        model_disclaimer=model_disclaimer,
        input_provenance=_build_input_provenance(inp),
        candidate_options=candidate_options,
        goal_alternatives=candidate_options[1:],
        review_conditions=_build_review_conditions(
            inp,
            runtime_result,
            recommended_action="review",
            low_confidence=low_confidence,
        ),
        next_steps=_build_next_steps(
            inp,
            recommended_action="review",
            low_confidence=low_confidence,
        ),
        runner_up_action=_runner_up_action(ev_report),
        low_confidence=low_confidence,
        execution_plan_summary=_execution_plan_summary(inp),
    )
    return _finalize_card(card)


def build_decision_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    if not isinstance(inp, DecisionCardBuildInput):
        raise TypeError("build_decision_card expects DecisionCardBuildInput")
    inp.validate()
    runtime_result = _obj(inp.runtime_result or {})
    if inp.card_type == DecisionCardType.GOAL_BASELINE:
        return _build_goal_baseline_card(inp)
    if inp.card_type == DecisionCardType.RUNTIME_ACTION:
        return _build_runtime_action_card(inp, runtime_result)
    if inp.card_type == DecisionCardType.QUARTERLY_REVIEW:
        return _build_quarterly_review_card(inp)
    if inp.card_type == DecisionCardType.BLOCKED:
        return _build_blocked_card(inp)
    raise ValueError(f"unsupported card_type: {inp.card_type}")
