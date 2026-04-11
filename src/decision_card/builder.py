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


def _disclosure_decision(inp: DecisionCardBuildInput) -> dict[str, Any]:
    return _obj(inp.disclosure_decision or {})


def _disclosure_level(inp: DecisionCardBuildInput) -> str:
    disclosure = _disclosure_decision(inp)
    if not disclosure:
        return "point_and_range"
    return (_metric(disclosure.get("disclosure_level")) or "diagnostic_only").lower()


def _confidence_level(inp: DecisionCardBuildInput) -> str:
    disclosure = _disclosure_decision(inp)
    if not disclosure:
        return "high"
    return (_metric(disclosure.get("confidence_level")) or "low").lower()


def _calibration_quality(inp: DecisionCardBuildInput, goal_output: dict[str, Any]) -> str:
    disclosure = _disclosure_decision(inp)
    if not disclosure:
        return "acceptable"
    disclosure_quality = _metric(disclosure.get("calibration_quality"))
    if disclosure_quality:
        return disclosure_quality.lower()
    calibration_summary = _obj(goal_output.get("calibration_summary") or {})
    return (_metric(calibration_summary.get("calibration_quality")) or "insufficient_sample").lower()


def _range_width(
    *,
    kind: str,
    confidence_level: str,
    calibration_quality: str,
) -> float:
    base_widths = {
        "probability": {"high": 0.03, "medium": 0.05, "low": 0.08},
        "annual_return": {"high": 0.003, "medium": 0.006, "low": 0.010},
    }
    calibration_adjustments = {
        "strong": 0.0,
        "acceptable": 0.0,
        "weak": 0.01 if kind == "probability" else 0.002,
        "insufficient_sample": 0.02 if kind == "probability" else 0.003,
    }
    return base_widths[kind].get(confidence_level, base_widths[kind]["low"]) + calibration_adjustments.get(
        calibration_quality,
        calibration_adjustments["insufficient_sample"],
    )


def _percent_range_metric(
    value: Any,
    *,
    confidence_level: str,
    calibration_quality: str,
    kind: str,
) -> str:
    metric = _float_metric(value)
    if metric is None:
        return ""
    width = _range_width(
        kind=kind,
        confidence_level=confidence_level,
        calibration_quality=calibration_quality,
    )
    lower = max(0.0, metric - width)
    upper = metric + width
    if kind == "probability":
        upper = min(1.0, upper)
    return f"{lower * 100:.2f}% ~ {upper * 100:.2f}%"


def _disclosed_percent_fields(
    value: Any,
    *,
    inp: DecisionCardBuildInput,
    goal_output: dict[str, Any],
    kind: str,
    published_point: Any = None,
    published_range: Any = None,
    disclosure_level_override: str | None = None,
    confidence_level_override: str | None = None,
) -> tuple[str, str]:
    disclosure_level = disclosure_level_override or _disclosure_level(inp)
    if disclosure_level in {"diagnostic_only", "unavailable"}:
        return "", ""
    point_source = published_point if published_point is not None else value
    point = _percent_metric(point_source) if disclosure_level == "point_and_range" else ""
    range_display = ""
    if disclosure_level in {"point_and_range", "range_only"}:
        pair = _tuple_pair(published_range)
        if pair is not None:
            lower = _float_metric(pair[0])
            upper = _float_metric(pair[1])
            if lower is not None and upper is not None:
                range_display = f"{lower * 100:.2f}% ~ {upper * 100:.2f}%"
        if not range_display:
            range_display = _percent_range_metric(
                value,
                confidence_level=confidence_level_override or _confidence_level(inp),
                calibration_quality=_calibration_quality(inp, goal_output),
                kind=kind,
            )
    return point, range_display


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


def _tuple_pair(value: Any) -> tuple[Any, Any] | None:
    if value is None:
        return None
    pair = tuple(value)
    if len(pair) != 2:
        return None
    return pair


def _coalesce_metric(value: Any, fallback: float) -> float:
    metric = _float_metric(value)
    if metric is None:
        return fallback
    return metric


def _product_layer_success_value(data: dict[str, Any]) -> Any:
    for key in (
        "product_independent_success_probability",
        "product_proxy_adjusted_success_probability",
        "product_adjusted_success_probability",
        "success_probability",
    ):
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _product_proxy_success_value(data: dict[str, Any]) -> Any:
    for key in ("product_proxy_adjusted_success_probability", "product_adjusted_success_probability"):
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _probability_engine_formal_surface(inp: DecisionCardBuildInput) -> dict[str, Any]:
    probability_engine_result = _obj(inp.probability_engine_result or {})
    probability_output = _obj(probability_engine_result.get("output") or {})
    primary_result = _obj(probability_output.get("primary_result") or {})
    disclosure_payload = _obj(probability_output.get("probability_disclosure_payload") or {})
    primary_path_stats = _obj(primary_result.get("path_stats") or {})
    return {
        "primary_result": primary_result,
        "disclosure_payload": disclosure_payload,
        "published_point": disclosure_payload.get("published_point"),
        "published_range": disclosure_payload.get("published_range"),
        "disclosure_level": _metric(disclosure_payload.get("disclosure_level")) or "",
        "confidence_level": _metric(disclosure_payload.get("confidence_level")) or "",
        "annual_return_point": _float_metric(primary_path_stats.get("cagr_p50")),
        "annual_return_range": _tuple_pair(primary_result.get("cagr_range")),
        "product_probability_method": _canonical_product_probability_method(inp),
    }


def _canonical_product_probability_method(inp: DecisionCardBuildInput) -> str:
    probability_engine_result = _obj(getattr(inp, "probability_engine_result", {}) or {})
    internal_category = _metric(probability_engine_result.get("resolved_result_category"))
    if internal_category:
        if internal_category == "formal_strict_result":
            return "product_independent_path"
        if internal_category in {"formal_estimated_result", "degraded_formal_result"}:
            return "product_estimated_path"
        return ""
    truth_view = _obj(getattr(inp, "probability_truth_view", {}) or {})
    method = _metric(truth_view.get("product_probability_method"))
    if method:
        return method
    evidence_bundle = _obj(getattr(inp, "evidence_bundle", {}) or {})
    coverage_summary = _obj(evidence_bundle.get("coverage_summary") or {})
    monthly_fallback_used = str(evidence_bundle.get("monthly_fallback_used") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    bucket_fallback_used = str(evidence_bundle.get("bucket_fallback_used") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if (
        not monthly_fallback_used
        and not bucket_fallback_used
        and (_float_metric(coverage_summary.get("independent_weight_adjusted_coverage")) or 0.0) >= 0.999
        and (_float_metric(coverage_summary.get("independent_horizon_complete_coverage")) or 0.0) >= 0.999
        and (_float_metric(coverage_summary.get("distribution_ready_coverage")) or 0.0) >= 0.999
        and int(_float_metric(coverage_summary.get("selected_product_count")) or 0) > 0
    ):
        return "product_independent_path"
    mapped_category = _metric(inp.resolved_result_category)
    if mapped_category == "formal_independent_result":
        return "product_independent_path"
    if mapped_category in {"formal_estimated_result", "degraded_formal_result"}:
        return "product_estimated_path"
    goal_output = _obj(inp.goal_solver_output or {})
    recommended_result = _obj(goal_output.get("recommended_result") or {})
    method = _metric(recommended_result.get("product_probability_method"))
    if method:
        return method
    frontier_analysis = _obj(goal_output.get("frontier_analysis") or {})
    for key in ("recommended", "highest_probability", "target_return_priority", "drawdown_priority"):
        method = _metric(_obj(frontier_analysis.get(key) or {}).get("product_probability_method"))
        if method:
            return method
    return ""


def _product_probability_disclosure(probability_method: str) -> str:
    if probability_method == "product_independent_path":
        return "当前产品层概率使用逐产品独立路径估计，但仍建立在有限历史覆盖与代理补齐约束上。"
    if probability_method == "bucket_only_no_product_proxy_adjustment":
        return "当前产品层概率尚未启用代理修正，产品相关成功率字段只展示桶级基线，不应解读为逐产品独立模拟。"
    return "当前产品层概率使用代理修正口径，仍不是逐产品独立模拟。"


def _difficulty_source(frontier_diagnostics: dict[str, Any]) -> str:
    bindings = list(frontier_diagnostics.get("binding_constraints") or [])
    limitations = set(str(item) for item in list(frontier_diagnostics.get("structural_limitations") or []))
    if any(str(_obj(binding).get("constraint_name") or "") == "required_annual_return" for binding in bindings):
        return "constraint_binding"
    if any(str(_obj(binding).get("constraint_name") or "") == "max_drawdown_tolerance" for binding in bindings):
        return "constraint_binding"
    if bindings and limitations:
        return "mixed"
    if bindings:
        return "constraint_binding"
    if {
        "return_seeking_families_not_generated_under_current_solver_inputs",
        "satellite_cap_limits_high_beta_allocations",
        "qdii_cap_limits_overseas_exposure",
    } & limitations:
        return "universe_limited"
    if {"required_return_above_frontier_ceiling", "expected_return_shrinkage_applied"} & limitations:
        return "model_ceiling"
    return "market"


def _constraint_contributions(frontier_diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = int(frontier_diagnostics.get("raw_candidate_count") or 0)
    feasible_candidates = int(frontier_diagnostics.get("feasible_candidate_count") or 0)
    frontier_ceiling = _float_metric(frontier_diagnostics.get("frontier_max_expected_annual_return"))
    contributions: list[dict[str, Any]] = []
    for binding in list(frontier_diagnostics.get("binding_constraints") or []):
        data = _obj(binding)
        name = _metric(data.get("constraint_name")) or "unknown_constraint"
        reason = _metric(data.get("reason")) or ""
        required_value = _float_metric(data.get("required_value"))
        contributions.append(
            {
                "name": name,
                "is_binding": True,
                "before_candidates": raw_candidates,
                "after_candidates": feasible_candidates,
                "before_frontier_ceiling": frontier_ceiling,
                "after_frontier_ceiling": frontier_ceiling,
                "required_value": required_value,
                "explanation": reason,
            }
        )
    limitation_messages = {
        "required_return_above_frontier_ceiling": "当前目标收益高于候选前沿上限，说明主要矛盾不只是市场波动，而是收益门槛本身。",
        "satellite_cap_limits_high_beta_allocations": "卫星仓上限压住了更高 beta 暴露，可选更进攻方案被截断。",
        "qdii_cap_limits_overseas_exposure": "QDII/海外暴露上限压住了跨市场风险预算。",
        "expected_return_shrinkage_applied": "当前收益假设做了保守收缩，会主动压低前沿上限。",
        "return_seeking_families_not_generated_under_current_solver_inputs": "当前 solver 输入没有生成更激进的候选族。",
    }
    for limitation in list(frontier_diagnostics.get("structural_limitations") or []):
        name = str(limitation)
        contributions.append(
            {
                "name": name,
                "is_binding": False,
                "before_candidates": raw_candidates,
                "after_candidates": raw_candidates,
                "before_frontier_ceiling": frontier_ceiling,
                "after_frontier_ceiling": frontier_ceiling,
                "required_value": None,
                "explanation": limitation_messages.get(name, name),
            }
        )
    return contributions


def _evidence_layer(
    *,
    execution_plan_summary: dict[str, Any],
    probability_method: str,
) -> dict[str, Any]:
    universe = _obj(execution_plan_summary.get("product_universe_audit_summary", {}))
    valuation = _obj(execution_plan_summary.get("valuation_audit_summary", {}))
    policy = _obj(execution_plan_summary.get("policy_news_audit_summary", {}))
    formal_path = _obj(execution_plan_summary.get("formal_path_visibility", {}))
    observed_inputs = 0
    computed_inputs = 0
    prior_default_inputs = 0
    for payload in (universe, valuation, policy):
        source_status = _metric(payload.get("source_status")) or ""
        data_status = _metric(payload.get("data_status")) or ""
        if source_status == "observed":
            observed_inputs += 1
        if data_status == "computed_from_observed":
            computed_inputs += 1
        if data_status == "prior_default":
            prior_default_inputs += 1
    historical_window = (
        universe.get("audit_window")
        or valuation.get("audit_window")
        or policy.get("audit_window")
        or None
    )
    return {
        "product_probability_method": probability_method,
        "formal_path_status": _metric(formal_path.get("status")) or "",
        "formal_path_execution_eligible": bool(formal_path.get("execution_eligible")),
        "observed_inputs": observed_inputs,
        "computed_from_observed_inputs": computed_inputs,
        "prior_default_inputs": prior_default_inputs,
        "historical_window": historical_window,
        "product_universe_source_status": _metric(universe.get("source_status")) or "",
        "valuation_source_status": _metric(valuation.get("source_status")) or "",
        "policy_news_source_status": _metric(policy.get("source_status")) or "",
        "calibration_summary": _obj(execution_plan_summary.get("calibration_summary", {})),
    }


def _counterfactual_scenario_id(label: str) -> str:
    if "回撤" in label:
        return "keep_target_relax_drawdown"
    if "每月投入" in label:
        return "increase_monthly_contribution"
    if "期限" in label:
        return "extend_horizon"
    if "目标期末总资产" in label:
        return "reduce_goal_amount"
    return "fallback_counterfactual"


def _counterfactuals(goal_output: dict[str, Any]) -> list[dict[str, Any]]:
    counterfactuals: list[dict[str, Any]] = []
    for item in list(goal_output.get("fallback_suggestions") or []):
        data = _obj(item)
        label = _metric(data.get("label")) or "fallback"
        risk_summary = _obj(data.get("risk_summary", {}))
        counterfactuals.append(
            {
                "scenario": _counterfactual_scenario_id(label),
                "label": label,
                "success_probability": _percent_metric(data.get("success_probability")),
                "max_drawdown_90pct": _percent_metric(risk_summary.get("max_drawdown_90pct")),
                "shortfall_probability": _percent_metric(risk_summary.get("shortfall_probability")),
                "evidence_source": _metric(data.get("evidence_source")) or "model_estimate",
            }
        )
    return counterfactuals


def _product_contributions(execution_plan_summary: dict[str, Any]) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    for item in list(execution_plan_summary.get("items") or []):
        data = _obj(item)
        product_id = _metric(data.get("primary_product_id")) or ""
        if not product_id:
            continue
        asset_bucket = _metric(data.get("asset_bucket")) or ""
        target_weight = _float_metric(data.get("target_weight")) or 0.0
        risk_labels = {str(label) for label in list(data.get("risk_labels") or []) if str(label).strip()}
        valuation = _obj(data.get("valuation_audit", {}))
        policy = _obj(data.get("policy_news_audit", {}))
        success_support = 0.0
        drawdown_pressure = 0.0
        friction_drag = 0.0
        explanations: list[str] = []
        if asset_bucket in {"equity_cn", "satellite"}:
            success_support += target_weight * 0.6
            explanations.append("权益类产品提高了目标收益空间。")
        if valuation.get("passed_filters") is True:
            success_support += 0.08
            explanations.append("估值筛选通过，说明当前价格不在明显偏贵区。")
        if bool(policy.get("realtime_eligible")) and _float_metric(policy.get("score")):
            score = _float_metric(policy.get("score")) or 0.0
            success_support += max(score, 0.0) * 0.1
            drawdown_pressure += abs(min(score, 0.0)) * 0.1
            explanations.append("政策/新闻信号正在影响当前产品排序。")
        if asset_bucket == "satellite" or "主题波动" in risk_labels:
            drawdown_pressure += max(target_weight, 0.05) * 0.7
            explanations.append("卫星/主题仓会放大波动和回撤尾部。")
        if {"个股波动", "集中度"} & risk_labels:
            drawdown_pressure += 0.12
            explanations.append("个股或高集中度敞口会抬高回撤。")
        estimated_fee = _float_metric(data.get("estimated_fee"))
        estimated_slippage = _float_metric(data.get("estimated_slippage"))
        target_amount = max(_float_metric(data.get("target_amount")) or 0.0, 1.0)
        if estimated_fee is not None:
            friction_drag += estimated_fee / target_amount
        if estimated_slippage is not None:
            friction_drag += estimated_slippage / target_amount
        contributions.append(
            {
                "product_id": product_id,
                "asset_bucket": asset_bucket,
                "success_support": round(success_support, 4),
                "drawdown_pressure": round(drawdown_pressure, 4),
                "friction_drag": round(friction_drag, 4),
                "explanation": " ".join(explanations) or "当前主要通过权重配置影响成功率与回撤。",
            }
        )
    return sorted(
        contributions,
        key=lambda item: (
            -(float(item.get("success_support") or 0.0) + float(item.get("drawdown_pressure") or 0.0)),
            str(item.get("product_id") or ""),
        ),
    )


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
            max(
                metrics_pool,
                key=lambda item: _coalesce_metric(
                    _product_layer_success_value(_obj(item)),
                    float("-inf"),
                ),
            ).get("allocation_name")
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

    frontier_expected_returns: dict[str, Any] = {}
    for scenario in (
        _obj(_obj(goal_output.get("frontier_analysis", {})).get("recommended", {})),
        _obj(_obj(goal_output.get("frontier_analysis", {})).get("highest_probability", {})),
        _obj(_obj(goal_output.get("frontier_analysis", {})).get("target_return_priority", {})),
        _obj(_obj(goal_output.get("frontier_analysis", {})).get("drawdown_priority", {})),
        _obj(_obj(goal_output.get("frontier_analysis", {})).get("balanced_tradeoff", {})),
    ):
        allocation_name = _metric(scenario.get("allocation_name"))
        if allocation_name and scenario.get("expected_annual_return") is not None:
            frontier_expected_returns[allocation_name] = scenario.get("expected_annual_return")

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
        bucket_success_probability = _percent_metric(
            result.get("bucket_success_probability", result.get("success_probability"))
        )
        product_independent_success_probability = _percent_metric(
            result.get("product_independent_success_probability")
        )
        product_proxy_adjusted_success_probability = _percent_metric(
            _product_proxy_success_value(_obj(result))
        )
        product_probability_method = _metric(result.get("product_probability_method")) or "bucket_only_no_product_proxy_adjustment"
        implied_required_annual_return = _percent_metric(result.get("implied_required_annual_return"))
        expected_annual_return = _percent_metric(
            result.get("expected_annual_return", frontier_expected_returns.get(allocation_name))
        )
        expected_terminal_value = _currency_metric(result.get("expected_terminal_value"))
        max_drawdown_90pct = _percent_metric(risk_summary.get("max_drawdown_90pct"))
        shortfall_probability = _percent_metric(risk_summary.get("shortfall_probability"))
        option = {
            "allocation_name": allocation_name,
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
            "bucket_success_probability": bucket_success_probability,
            "product_proxy_adjusted_success_probability": product_proxy_adjusted_success_probability,
            "product_probability_method": product_probability_method,
            "implied_required_annual_return": implied_required_annual_return,
            "expected_annual_return": expected_annual_return,
            "expected_terminal_value": expected_terminal_value,
            "max_drawdown_90pct": max_drawdown_90pct,
            "shortfall_probability": shortfall_probability,
            "metrics": {
                "success_probability": success_probability,
                "bucket_success_probability": bucket_success_probability,
                "product_independent_success_probability": product_independent_success_probability,
                "product_proxy_adjusted_success_probability": product_proxy_adjusted_success_probability,
                "product_probability_method": product_probability_method,
                "implied_required_annual_return": implied_required_annual_return,
                "expected_annual_return": expected_annual_return,
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
            "product_independent_success_probability": product_independent_success_probability,
            "probability_disclosure": _product_probability_disclosure(product_probability_method),
            "why_selected": _candidate_highlight(
                result,
                recommended_name=recommended_name,
                highest_success_name=highest_success_name,
                lowest_drawdown_name=lowest_drawdown_name,
                lowest_shortfall_name=lowest_shortfall_name,
                no_feasible=no_feasible,
            ),
            "model_disclaimer": _model_disclaimer(goal_output),
            "simulation_mode_used": _metric(result.get("simulation_mode_used") or goal_output.get("simulation_mode_used")),
            "product_probability_method": product_probability_method,
            "evidence_source": "model_estimate",
        }
        if complexity is not None:
            option["complexity_score"] = f"{complexity:.2f}"
        options.append(option)
    return options


def _frontier_scenario(
    raw: Any,
    *,
    candidate_options: list[dict[str, Any]],
) -> dict[str, Any]:
    data = _obj(raw)
    if not isinstance(data, dict) or not data:
        return {}
    allocation_name = _metric(data.get("allocation_name"))
    explicit_label = _metric(data.get("display_name")) or _metric(data.get("label"))
    rationale = _metric(data.get("why_selected")) or _metric(data.get("rationale")) or ""
    if not allocation_name and not explicit_label and not rationale:
        return {}
    label = next(
        (
            _metric(item.get("label"))
            for item in candidate_options
            if allocation_name and _metric(item.get("allocation_name")) == allocation_name
        ),
        explicit_label or (_candidate_label(allocation_name) if allocation_name else ""),
    )
    risk_summary = _obj(data.get("risk_summary", {}))
    max_drawdown_90pct = _percent_metric(
        risk_summary.get("max_drawdown_90pct", data.get("max_drawdown_90pct"))
    )
    return {
        "allocation_name": allocation_name,
        "label": label,
        "success_probability": _percent_metric(
            _product_layer_success_value(data)
        ),
        "bucket_success_probability": _percent_metric(data.get("bucket_success_probability", data.get("success_probability"))),
        "product_independent_success_probability": _percent_metric(
            data.get("product_independent_success_probability")
        ),
        "product_proxy_adjusted_success_probability": _percent_metric(
            _product_proxy_success_value(data)
        ),
        "product_probability_method": _metric(data.get("product_probability_method"))
        or "bucket_only_no_product_proxy_adjustment",
        "selected_product_ids": list(data.get("selected_product_ids") or []),
        "bucket_expected_return_adjustments": dict(data.get("bucket_expected_return_adjustments") or {}),
        "bucket_volatility_multipliers": dict(data.get("bucket_volatility_multipliers") or {}),
        "simulation_coverage_summary": dict(data.get("simulation_coverage_summary") or {}),
        "expected_terminal_value": _currency_metric(data.get("expected_terminal_value")),
        "expected_annual_return": _percent_metric(
            data.get("expected_annual_return", data.get("scenario_expected_annual_return"))
        ),
        "implied_required_annual_return": _percent_metric(data.get("implied_required_annual_return")),
        "max_drawdown_90pct": max_drawdown_90pct,
        "why_selected": rationale,
    }


def _build_frontier_analysis(
    goal_output: dict[str, Any],
    candidate_options: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = _obj(goal_output.get("frontier_analysis", {}))
    if not isinstance(raw, dict):
        return {}
    scenarios: dict[str, Any] = {}
    for key in (
        "recommended",
        "highest_probability",
        "target_return_priority",
        "drawdown_priority",
        "balanced_tradeoff",
    ):
        scenario = _frontier_scenario(raw.get(key), candidate_options=candidate_options)
        if scenario:
            scenarios[key] = scenario
    scenario_status = _obj(raw.get("scenario_status"))
    if isinstance(scenario_status, dict) and scenario_status:
        scenarios["scenario_status"] = scenario_status
    diagnostics = _obj(goal_output.get("frontier_diagnostics"))
    if isinstance(diagnostics, dict) and diagnostics:
        scenarios["frontier_diagnostics"] = diagnostics
    return scenarios


def _future_value_with_monthly_contribution(
    *,
    initial_value: float,
    monthly_contribution: float,
    annual_return: float,
    horizon_months: int,
) -> float:
    balance = float(initial_value)
    monthly_rate = (1.0 + max(annual_return, -0.999999)) ** (1.0 / 12.0) - 1.0
    for _ in range(max(int(horizon_months), 0)):
        balance *= 1.0 + monthly_rate
        balance += float(monthly_contribution)
    return balance


def _goal_numeric_context(goal_solver_input: Any) -> dict[str, float | int | None]:
    payload = _obj(goal_solver_input) or {}
    goal = _obj(payload.get("goal", {}))
    cashflow = _obj(payload.get("cashflow_plan", {}))
    return {
        "goal_amount": _float_metric(goal.get("goal_amount")),
        "horizon_months": int(_float_metric(goal.get("horizon_months")) or 0),
        "monthly_contribution": _float_metric(cashflow.get("monthly_contribution")) or 0.0,
        "current_portfolio_value": _float_metric(payload.get("current_portfolio_value")) or 0.0,
    }


def _build_constraint_contributions(frontier_diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidate_count = int(_float_metric(frontier_diagnostics.get("raw_candidate_count")) or 0)
    feasible_candidate_count = int(_float_metric(frontier_diagnostics.get("feasible_candidate_count")) or 0)
    frontier_ceiling = _float_metric(frontier_diagnostics.get("frontier_max_expected_annual_return"))
    contributions: list[dict[str, Any]] = []
    for binding in list(frontier_diagnostics.get("binding_constraints") or []):
        entry = _obj(binding)
        name = _metric(entry.get("constraint_name")) or "unknown_constraint"
        reason = _metric(entry.get("reason")) or ""
        required_value = _float_metric(entry.get("required_value"))
        explanation = "当前候选里已有约束成为绑定条件。"
        if name == "required_annual_return":
            explanation = "目标所需年化高于当前 frontier 上限，收益目标约束正在直接卡住方案空间。"
        elif name == "max_drawdown_tolerance":
            explanation = "当前最大回撤约束会压缩高波动候选，直接限制更进攻的方案。"
        contributions.append(
            {
                "name": name,
                "is_binding": True,
                "reason": reason,
                "required_value": None if required_value is None else f"{required_value * 100:.2f}%",
                "before_candidates": raw_candidate_count,
                "after_candidates": feasible_candidate_count,
                "before_frontier_ceiling": None if frontier_ceiling is None else f"{frontier_ceiling * 100:.2f}%",
                "after_frontier_ceiling": None if frontier_ceiling is None else f"{frontier_ceiling * 100:.2f}%",
                "explanation": explanation,
            }
        )
    for limitation in list(frontier_diagnostics.get("structural_limitations") or []):
        rendered = str(limitation)
        if rendered in {"required_return_above_frontier_ceiling", "expected_return_shrinkage_applied"}:
            continue
        contributions.append(
            {
                "name": rendered,
                "is_binding": False,
                "reason": rendered,
                "required_value": "",
                "before_candidates": raw_candidate_count,
                "after_candidates": feasible_candidate_count,
                "before_frontier_ceiling": None if frontier_ceiling is None else f"{frontier_ceiling * 100:.2f}%",
                "after_frontier_ceiling": None if frontier_ceiling is None else f"{frontier_ceiling * 100:.2f}%",
                "explanation": "这是当前 universe/solver 的结构性边界，会压缩更进攻候选的生成空间。",
            }
        )
    return contributions


def _build_probability_evidence_summary(
    inp: DecisionCardBuildInput,
    goal_output: dict[str, Any],
    recommended_result: dict[str, Any],
) -> dict[str, Any]:
    execution_summary = _execution_plan_summary(inp)
    audit_record = _obj(inp.audit_record or {})
    formal_path_visibility = _obj(
        execution_summary.get("formal_path_visibility")
        or audit_record.get("formal_path_visibility")
        or {}
    )
    source_refs = [
        _metric(item.get("source_ref"))
        for item in list(_obj(inp.input_provenance or {}).get("externally_fetched") or [])
        if _metric(_obj(item).get("source_ref"))
    ]
    coverage_summary = dict(recommended_result.get("simulation_coverage_summary") or {})
    observed_inputs = 0
    computed_inputs = 0
    for payload in (
        _obj(execution_summary.get("product_universe_audit_summary") or {}),
        _obj(execution_summary.get("valuation_audit_summary") or {}),
        _obj(execution_summary.get("policy_news_audit_summary") or {}),
    ):
        if (_metric(payload.get("source_status")) or "") == "observed":
            observed_inputs += 1
        if (_metric(payload.get("data_status")) or "") == "computed_from_observed":
            computed_inputs += 1
    prior_default_inputs = len(list(_obj(inp.input_provenance or {}).get("default_assumed") or []))
    canonical_probability_method = _canonical_product_probability_method(inp)
    return {
        "product_probability_method": canonical_probability_method or "bucket_only_no_product_proxy_adjustment",
        "product_universe_source_status": _metric(
            _obj(execution_summary.get("product_universe_audit_summary") or {}).get("source_status")
        )
        or "not_requested",
        "valuation_source_status": _metric(
            _obj(execution_summary.get("valuation_audit_summary") or {}).get("source_status")
        )
        or "not_requested",
        "policy_news_source_status": _metric(
            _obj(execution_summary.get("policy_news_audit_summary") or {}).get("source_status")
        )
        or "unavailable",
        "formal_path_status": _metric(formal_path_visibility.get("status")) or "",
        "market_history_source_refs": _unique([item for item in source_refs if item]),
        "simulation_coverage_summary": coverage_summary,
        "selected_product_count": int(coverage_summary.get("selected_product_count") or 0),
        "observed_product_count": int(coverage_summary.get("observed_product_count") or 0),
        "missing_product_count": int(coverage_summary.get("missing_product_count") or 0),
        "observed_inputs": observed_inputs,
        "computed_from_observed_inputs": computed_inputs,
        "prior_default_inputs": prior_default_inputs,
        "calibration_summary": _obj(goal_output.get("calibration_summary") or {}),
    }


def _recommended_candidate_product_context(
    inp: DecisionCardBuildInput,
    allocation_name: str,
) -> dict[str, Any]:
    goal_solver_input = _obj(inp.goal_solver_input) or {}
    contexts = _obj(goal_solver_input.get("candidate_product_contexts") or {})
    if allocation_name and isinstance(contexts, dict):
        return _obj(contexts.get(allocation_name) or {})
    return {}


def _build_probability_evidence_layer(
    inp: DecisionCardBuildInput,
    goal_output: dict[str, Any],
    recommended_result: dict[str, Any],
) -> dict[str, Any]:
    evidence = _build_probability_evidence_summary(inp, goal_output, recommended_result)
    recommended_name = _metric(recommended_result.get("allocation_name")) or ""
    product_context = _recommended_candidate_product_context(inp, recommended_name)
    coverage_summary = _obj(recommended_result.get("simulation_coverage_summary") or {})
    if not coverage_summary:
        coverage_summary = _obj(product_context.get("simulation_coverage_summary") or {})
    if not coverage_summary:
        simulation_input = _obj(product_context.get("product_simulation_input") or {})
        coverage_summary = _obj(simulation_input.get("coverage_summary") or {})
    if coverage_summary:
        evidence["simulation_coverage_summary"] = coverage_summary
    explicit_status = _metric(evidence.get("formal_path_status")) or ""
    if not explicit_status:
        if int(evidence.get("prior_default_inputs") or 0) > 0:
            explicit_status = "degraded"
        elif int(evidence.get("observed_inputs") or 0) > 0:
            explicit_status = "ok"
        else:
            explicit_status = "not_requested"
    evidence["formal_path_status"] = explicit_status
    evidence["observed_product_count"] = int(
        _obj(evidence.get("simulation_coverage_summary") or {}).get("observed_product_count") or 0
    )
    evidence["selected_product_count"] = int(
        _obj(evidence.get("simulation_coverage_summary") or {}).get("selected_product_count") or 0
    )
    evidence["missing_product_count"] = int(
        _obj(evidence.get("simulation_coverage_summary") or {}).get("missing_product_count") or 0
    )
    return evidence


def _synthesized_constraint_contributions(
    *,
    target_status: dict[str, Any],
    drawdown_status: dict[str, Any],
) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    if target_status.get("available") is False:
        contributions.append(
            {
                "name": "required_annual_return",
                "is_binding": True,
                "reason": _metric(target_status.get("reason")) or "no_candidate_meets_required_annual_return",
                "required_value": "",
                "before_candidates": 0,
                "after_candidates": 0,
                "before_frontier_ceiling": "",
                "after_frontier_ceiling": "",
                "explanation": "目标收益优先方案不可用，说明当前收益门槛已经直接卡住候选空间。",
            }
        )
    if drawdown_status.get("available") is False:
        contributions.append(
            {
                "name": "max_drawdown_tolerance",
                "is_binding": True,
                "reason": _metric(drawdown_status.get("reason")) or "no_candidate_meets_max_drawdown_tolerance",
                "required_value": "",
                "before_candidates": 0,
                "after_candidates": 0,
                "before_frontier_ceiling": "",
                "after_frontier_ceiling": "",
                "explanation": "回撤优先方案不可用，说明当前回撤约束已经把候选压空。",
            }
        )
    return contributions


def _build_counterfactuals(
    *,
    goal_solver_input: Any,
    recommended_result: dict[str, Any],
    frontier_diagnostics: dict[str, Any],
    target_return_priority: dict[str, Any],
    drawdown_priority: dict[str, Any],
) -> dict[str, Any]:
    numeric = _goal_numeric_context(goal_solver_input)
    goal_amount = _float_metric(numeric.get("goal_amount"))
    horizon_months = int(numeric.get("horizon_months") or 0)
    monthly_contribution = _float_metric(numeric.get("monthly_contribution")) or 0.0
    current_portfolio_value = _float_metric(numeric.get("current_portfolio_value")) or 0.0
    required_return = _float_metric(recommended_result.get("implied_required_annual_return"))
    frontier_ceiling = _float_metric(frontier_diagnostics.get("frontier_max_expected_annual_return"))
    required_return_gap = ""
    extra_months = ""
    contribution_delta = ""
    if required_return is not None and frontier_ceiling is not None:
        required_return_gap = f"{max(required_return - frontier_ceiling, 0.0) * 100:.2f}%"
    if goal_amount is not None and frontier_ceiling is not None and horizon_months > 0:
        current_frontier_fv = _future_value_with_monthly_contribution(
            initial_value=current_portfolio_value,
            monthly_contribution=monthly_contribution,
            annual_return=frontier_ceiling,
            horizon_months=horizon_months,
        )
        monthly_rate = (1.0 + max(frontier_ceiling, -0.999999)) ** (1.0 / 12.0) - 1.0
        annuity_factor = sum((1.0 + monthly_rate) ** idx for idx in range(horizon_months))
        if annuity_factor > 0:
            contribution_delta_value = max((goal_amount - current_frontier_fv) / annuity_factor, 0.0)
            contribution_delta = f"{contribution_delta_value:,.0f}"
        projected = current_frontier_fv
        months = horizon_months
        while goal_amount > projected and months < 720:
            months += 1
            projected = _future_value_with_monthly_contribution(
                initial_value=current_portfolio_value,
                monthly_contribution=monthly_contribution,
                annual_return=frontier_ceiling,
                horizon_months=months,
            )
        if months > horizon_months:
            extra_months = str(months - horizon_months)
    return {
        "required_return_gap": required_return_gap,
        "monthly_contribution_delta_to_hit_goal_at_frontier_return": contribution_delta,
        "extra_horizon_months_to_hit_goal_at_frontier_return": extra_months,
        "target_return_priority_status": (
            _metric(target_return_priority.get("label")) or "unavailable"
        ),
        "drawdown_priority_status": (
            _metric(drawdown_priority.get("label")) or "unavailable"
        ),
    }


def _build_probability_counterfactuals(
    inp: DecisionCardBuildInput,
    goal_output: dict[str, Any],
    recommended_result: dict[str, Any],
    frontier_diagnostics: dict[str, Any],
    target_return_priority: dict[str, Any],
    drawdown_priority: dict[str, Any],
) -> dict[str, Any]:
    payload = _build_counterfactuals(
        goal_solver_input=inp.goal_solver_input,
        recommended_result=recommended_result,
        frontier_diagnostics=frontier_diagnostics,
        target_return_priority=target_return_priority,
        drawdown_priority=drawdown_priority,
    )
    fallback_scenarios = _counterfactuals(goal_output)
    if not fallback_scenarios and target_return_priority.get("label") in {"", None}:
        fallback_scenarios.append(
            {
                "scenario": "keep_target_relax_drawdown",
                "label": "保持目标收益时，需要放宽回撤或扩展风险预算。",
                "success_probability": "",
                "max_drawdown_90pct": "",
                "shortfall_probability": "",
                "evidence_source": "frontier_diagnostics",
            }
        )
    payload["fallback_scenarios"] = fallback_scenarios
    return payload


def _build_product_contributions(
    recommended_result: dict[str, Any],
    product_evidence_panel: dict[str, Any],
    execution_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    item_index: dict[str, dict[str, Any]] = {}
    for source_items in (
        list(_obj(execution_summary).get("items") or []),
        list(_obj(product_evidence_panel).get("items") or []),
    ):
        for item in source_items:
            payload = _obj(item)
            product_id = _metric(payload.get("primary_product_id"))
            if not product_id:
                continue
            merged = dict(item_index.get(product_id) or {})
            merged.update(payload)
            item_index[product_id] = merged
    contributions: list[dict[str, Any]] = []
    adjustments = dict(recommended_result.get("bucket_expected_return_adjustments") or {})
    vol_multipliers = dict(recommended_result.get("bucket_volatility_multipliers") or {})
    selected_product_ids = list(recommended_result.get("selected_product_ids") or [])
    if not selected_product_ids:
        selected_product_ids = list(item_index.keys())
    for product_id in selected_product_ids:
        item = item_index.get(str(product_id), {})
        bucket = _metric(item.get("asset_bucket")) or ""
        adjustment = _float_metric(adjustments.get(bucket)) or 0.0
        vol_multiplier = _float_metric(vol_multipliers.get(bucket)) or 1.0
        if bucket in {"bond_cn", "gold", "cash_liquidity"}:
            success_role = "execution_stability"
        elif adjustment > 0:
            success_role = "supports_probability"
        elif vol_multiplier > 1.05:
            success_role = "raises_drawdown"
        else:
            success_role = "neutral"
        valuation_audit = _obj(item.get("valuation_audit") or {})
        policy_news_audit = _obj(item.get("policy_news_audit") or {})
        contributions.append(
            {
                "product_id": str(product_id),
                "product_name": _metric(item.get("primary_product_name")) or "",
                "asset_bucket": bucket,
                "success_role": success_role,
                "expected_return_adjustment": f"{adjustment * 100:.2f}%",
                "volatility_multiplier": f"{vol_multiplier:.2f}x",
                "valuation_status": _metric(valuation_audit.get("status")) or "",
                "valuation_reason": _metric(valuation_audit.get("reason")) or "",
                "policy_news_status": _metric(policy_news_audit.get("status")) or "",
                "policy_news_score": _metric(policy_news_audit.get("score")) or "",
                "_sort_score": (
                    (2.0 if (_metric(policy_news_audit.get("status")) or "") == "observed" else 0.0)
                    + (1.0 if success_role == "supports_probability" else 0.0)
                    + (0.5 if success_role == "raises_drawdown" else 0.0)
                ),
            }
        )
    contributions.sort(
        key=lambda item: (
            -float(item.get("_sort_score") or 0.0),
            str(item.get("product_id") or ""),
        )
    )
    for item in contributions:
        item.pop("_sort_score", None)
    return contributions


def _build_probability_product_contributions(
    recommended_result: dict[str, Any],
    product_evidence_panel: dict[str, Any],
    execution_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    return _build_product_contributions(recommended_result, product_evidence_panel, execution_summary)


def _build_probability_explanation(
    inp: DecisionCardBuildInput,
    goal_output: dict[str, Any],
    candidate_options: list[dict[str, Any]],
) -> dict[str, Any]:
    frontier_analysis = _build_frontier_analysis(goal_output, candidate_options)
    scenario_status = _obj(frontier_analysis.get("scenario_status", {}))
    frontier_diagnostics = _obj(frontier_analysis.get("frontier_diagnostics", {}))
    recommended_result = _obj(goal_output.get("recommended_result", {}))
    formal_surface = _probability_engine_formal_surface(inp)
    formal_result = _obj(formal_surface.get("primary_result") or recommended_result)
    probability_method = formal_surface.get("product_probability_method") or "bucket_only_no_product_proxy_adjustment"
    recommended_name = _metric(recommended_result.get("allocation_name"))
    recommended_label = (
        frontier_analysis.get("recommended", {}).get("label")
        or (_metric(candidate_options[0].get("label")) if candidate_options else _candidate_label(recommended_name))
    )
    recommended_probability = _percent_metric(_product_layer_success_value(formal_result))
    recommended_probability_point, recommended_probability_range = _disclosed_percent_fields(
        _product_layer_success_value(formal_result),
        inp=inp,
        goal_output=goal_output,
        kind="probability",
        published_point=formal_surface.get("published_point"),
        published_range=formal_surface.get("published_range"),
        disclosure_level_override=formal_surface.get("disclosure_level") or None,
        confidence_level_override=formal_surface.get("confidence_level") or None,
    )
    recommended_independent_probability = _percent_metric(
        recommended_result.get("product_independent_success_probability")
    )
    recommended_expected_annual_return = _percent_metric(formal_surface.get("annual_return_point")) or _metric(
        frontier_analysis.get("recommended", {}).get("expected_annual_return")
    ) or ""
    recommended_expected_annual_return_point, recommended_expected_annual_return_range = _disclosed_percent_fields(
        formal_surface.get("annual_return_point")
        if formal_surface.get("annual_return_point") is not None
        else recommended_result.get(
            "expected_annual_return", _obj(goal_output.get("frontier_analysis", {})).get("recommended", {}).get("expected_annual_return")
        ),
        inp=inp,
        goal_output=goal_output,
        kind="annual_return",
        published_point=formal_surface.get("annual_return_point"),
        published_range=formal_surface.get("annual_return_range"),
        disclosure_level_override=formal_surface.get("disclosure_level") or None,
        confidence_level_override=formal_surface.get("confidence_level") or None,
    )
    highest_frontier = frontier_analysis.get("highest_probability", {})
    highest_name = _metric(highest_frontier.get("allocation_name"))
    highest_label = _metric(highest_frontier.get("label")) or _candidate_label(highest_name)
    highest_probability = _metric(highest_frontier.get("success_probability")) or ""
    highest_expected_annual_return = _metric(highest_frontier.get("expected_annual_return")) or ""
    if not highest_name:
        highest_candidate = max(
            [_obj(item) for item in goal_output.get("candidate_menu", []) or goal_output.get("all_results", [])],
            key=lambda item: _coalesce_metric(
                item.get(
                    "product_independent_success_probability",
                    item.get(
                        "product_proxy_adjusted_success_probability",
                        item.get("product_adjusted_success_probability", item.get("success_probability")),
                    ),
                ),
                float("-inf"),
            ),
            default=recommended_result,
        )
        highest_name = _metric(highest_candidate.get("allocation_name"))
        highest_label = next(
            (
                _metric(item.get("label"))
                for item in candidate_options
                if _metric(item.get("label")) and _metric(item.get("allocation_name")) == highest_name
            ),
            _metric(highest_candidate.get("display_name")) or _candidate_label(highest_name),
        )
        highest_probability = _percent_metric(
            _product_layer_success_value(highest_candidate)
        )
        highest_expected_annual_return = _percent_metric(highest_candidate.get("expected_annual_return"))
    if highest_name and recommended_name and highest_name != recommended_name:
        why_not = "当前推荐不是最高达成率方案，因为排序会同时权衡回撤、短缺风险和执行复杂度。"
    else:
        why_not = "当前推荐方案同时也是当前候选中的最高达成率方案。"
    product_probability_disclosure = _product_probability_disclosure(probability_method)

    target_return_priority = frontier_analysis.get("target_return_priority", {})
    drawdown_priority = frontier_analysis.get("drawdown_priority", {})
    target_label = _metric(target_return_priority.get("label")) or ""
    drawdown_label = _metric(drawdown_priority.get("label")) or ""
    target_expected_annual_return = _metric(target_return_priority.get("expected_annual_return")) or ""
    drawdown_expected_annual_return = _metric(drawdown_priority.get("expected_annual_return")) or ""
    target_status = _obj(scenario_status.get("target_return_priority", {}))
    drawdown_status = _obj(scenario_status.get("drawdown_priority", {}))

    if target_label:
        if target_label == recommended_label:
            target_explanation = f"坚持目标收益时，当前推荐方案“{recommended_label}”已经是最接近收益目标的选择。"
        else:
            target_explanation = (
                f"如果坚持目标收益，系统会更偏向“{target_label}”；"
                f"当前仍推荐“{recommended_label}”，因为还要同时权衡回撤和执行复杂度。"
            )
        why_not_target = ""
    elif target_status and target_status.get("available") is False:
        target_explanation = "当前候选里没有方案满足目标收益约束。"
        why_not_target = _metric(target_status.get("reason")) or "no_candidate_meets_required_annual_return"
    else:
        target_explanation = ""
        why_not_target = ""

    if drawdown_label:
        if drawdown_label == recommended_label:
            drawdown_explanation = f"优先压低回撤时，当前推荐方案“{recommended_label}”已经是更稳的选择。"
        else:
            drawdown_explanation = (
                f"如果优先压低回撤，系统会更偏向“{drawdown_label}”；"
                f"当前推荐“{recommended_label}”意味着系统接受了更高回撤来换取更高达成率。"
            )
        why_not_drawdown = ""
    elif drawdown_status and drawdown_status.get("available") is False:
        drawdown_explanation = "当前候选里没有方案满足最大回撤约束。"
        why_not_drawdown = _metric(drawdown_status.get("reason")) or "no_candidate_meets_max_drawdown_tolerance"
    else:
        drawdown_explanation = ""
        why_not_drawdown = ""

    constraint_contributions = _build_constraint_contributions(frontier_diagnostics)
    if not constraint_contributions:
        constraint_contributions = _synthesized_constraint_contributions(
            target_status=target_status,
            drawdown_status=drawdown_status,
        )
    evidence_layer = _build_probability_evidence_layer(inp, goal_output, recommended_result)
    counterfactuals = _build_probability_counterfactuals(
        inp,
        goal_output,
        recommended_result,
        frontier_diagnostics=frontier_diagnostics,
        target_return_priority=target_return_priority,
        drawdown_priority=drawdown_priority,
    )
    product_contributions = _build_probability_product_contributions(
        recommended_result,
        _product_evidence_panel(inp),
        _execution_plan_summary(inp),
    )
    difficulty_source = _difficulty_source(frontier_diagnostics)
    if difficulty_source == "market" and any(item.get("is_binding") for item in constraint_contributions):
        difficulty_source = "constraint_binding"
    result_layer = {
        "recommended": {
            "label": recommended_label,
            "success_probability": recommended_probability,
            "expected_annual_return": recommended_expected_annual_return,
        },
        "highest_probability": {
            "label": highest_label,
            "success_probability": highest_probability,
            "expected_annual_return": highest_expected_annual_return,
        },
        "target_return_priority": {
            "label": target_label,
            "success_probability": _metric(target_return_priority.get("success_probability")) or "",
            "expected_annual_return": target_expected_annual_return,
            "available": not bool(why_not_target),
        },
        "drawdown_priority": {
            "label": drawdown_label,
            "success_probability": _metric(drawdown_priority.get("success_probability")) or "",
            "expected_annual_return": drawdown_expected_annual_return,
            "available": not bool(why_not_drawdown),
        },
        "implied_required_annual_return": _percent_metric(recommended_result.get("implied_required_annual_return")),
        "product_independent_success_probability": recommended_independent_probability,
    }
    constraint_layer = {
        "difficulty_source": difficulty_source,
        "contributions": constraint_contributions,
    }
    counterfactual_layer = counterfactuals
    product_contribution_layer = product_contributions

    return {
        "run_outcome_status": _metric(inp.run_outcome_status) or "",
        "resolved_result_category": _metric(inp.resolved_result_category) or "",
        "disclosure_decision": dict(inp.disclosure_decision or {}),
        "evidence_bundle": dict(inp.evidence_bundle or {}),
        "recommended_allocation_label": recommended_label,
        "recommended_success_probability": recommended_probability,
        "recommended_expected_annual_return": recommended_expected_annual_return,
        "highest_probability_allocation_label": highest_label,
        "highest_probability_success_probability": highest_probability,
        "highest_probability_expected_annual_return": highest_expected_annual_return,
        "why_not_highest_probability": why_not,
        "target_return_priority_allocation_label": target_label,
        "target_return_priority_success_probability": _metric(target_return_priority.get("success_probability")) or "",
        "target_return_priority_expected_annual_return": target_expected_annual_return,
        "target_return_priority_explanation": target_explanation,
        "why_not_target_return_priority": why_not_target,
        "drawdown_priority_allocation_label": drawdown_label,
        "drawdown_priority_success_probability": _metric(drawdown_priority.get("success_probability")) or "",
        "drawdown_priority_expected_annual_return": drawdown_expected_annual_return,
        "drawdown_priority_explanation": drawdown_explanation,
        "why_not_drawdown_priority": why_not_drawdown,
        "implied_required_annual_return": _percent_metric(recommended_result.get("implied_required_annual_return")),
        "product_independent_success_probability": recommended_independent_probability,
        "success_probability_point": recommended_probability_point,
        "success_probability_range": recommended_probability_range,
        "expected_annual_return_point": recommended_expected_annual_return_point,
        "expected_annual_return_range": recommended_expected_annual_return_range,
        "confidence_level": _confidence_level(inp),
        "calibration_quality": _calibration_quality(inp, goal_output),
        "product_probability_method": probability_method,
        "product_probability_disclosure": product_probability_disclosure,
        "difficulty_source": difficulty_source,
        "constraint_contributions": constraint_contributions,
        "evidence_summary": evidence_layer,
        "evidence_layer": evidence_layer,
        "formal_path_evidence": evidence_layer,
        "counterfactuals": counterfactuals,
        "product_contributions": product_contributions,
        "result_layer": result_layer,
        "constraint_layer": constraint_layer,
        "counterfactual_layer": counterfactual_layer,
        "product_contribution_layer": product_contribution_layer,
    }


def _gate1_card_fields(inp: DecisionCardBuildInput) -> dict[str, Any]:
    return {
        "run_outcome_status": inp.run_outcome_status,
        "resolved_result_category": inp.resolved_result_category,
        "disclosure_decision": dict(inp.disclosure_decision or {}),
        "evidence_bundle": dict(inp.evidence_bundle or {}),
    }


def _product_evidence_panel(inp: DecisionCardBuildInput) -> dict[str, Any]:
    summary = _execution_plan_summary(inp)
    return dict(_obj(summary.get("product_evidence_panel", {})))


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


def _build_user_visible_candidate_alternatives(candidate_options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for item in candidate_options[1:]:
        data = _obj(item)
        visible.append(
            {
                "label": _metric(data.get("label")) or "备选方案",
                "highlight": _metric(data.get("highlight")) or "备选方案",
                "description": _metric(data.get("description")) or "",
                "success_probability": _metric(data.get("success_probability")) or "",
                "bucket_success_probability": _metric(data.get("bucket_success_probability")) or "",
                "product_proxy_adjusted_success_probability": _metric(
                    data.get(
                        "product_proxy_adjusted_success_probability",
                        data.get("product_adjusted_success_probability"),
                    )
                )
                or "",
                "product_probability_method": _metric(data.get("product_probability_method")) or "",
                "implied_required_annual_return": _metric(data.get("implied_required_annual_return")) or "",
                "expected_annual_return": _metric(data.get("expected_annual_return")) or "",
                "expected_terminal_value": _metric(data.get("expected_terminal_value")) or "",
                "max_drawdown_90pct": _metric(data.get("max_drawdown_90pct")) or "",
                "shortfall_probability": _metric(data.get("shortfall_probability")) or "",
                "metrics": dict(_obj(data.get("metrics"))),
                "probability_disclosure": _metric(data.get("probability_disclosure")) or "",
                "model_disclaimer": _metric(data.get("model_disclaimer")) or "",
                "evidence_source": _metric(data.get("evidence_source")) or "model_estimate",
            }
        )
    return visible


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
    frontier_diagnostics = _obj(goal_output.get("frontier_diagnostics", {}))
    evidence = [
        f"success_probability={_metric(result.get('success_probability'))}",
        f"bucket_success_probability={_metric(result.get('bucket_success_probability'))}",
        f"product_proxy_adjusted_success_probability={_metric(result.get('product_proxy_adjusted_success_probability', result.get('product_adjusted_success_probability')))}",
        f"product_probability_method={_metric(result.get('product_probability_method'))}",
        f"implied_required_annual_return={_metric(result.get('implied_required_annual_return'))}",
        f"max_drawdown_90pct={_metric(risk_summary.get('max_drawdown_90pct'))}",
        f"shortfall_probability={_metric(risk_summary.get('shortfall_probability'))}",
        f"core_weight={_metric(structure_budget.get('core_weight'))}",
        f"satellite_weight={_metric(structure_budget.get('satellite_weight'))}",
    ]
    formatted = [
        f"success_probability_display={_percent_metric(result.get('success_probability'))}",
        f"bucket_success_probability_display={_percent_metric(result.get('bucket_success_probability'))}",
        f"product_proxy_adjusted_success_probability_display={_percent_metric(result.get('product_proxy_adjusted_success_probability', result.get('product_adjusted_success_probability')))}",
        f"implied_required_annual_return_display={_percent_metric(result.get('implied_required_annual_return'))}",
        f"max_drawdown_90pct_display={_percent_metric(risk_summary.get('max_drawdown_90pct'))}",
        f"shortfall_probability_display={_percent_metric(risk_summary.get('shortfall_probability'))}",
        f"core_weight_display={_percent_metric(structure_budget.get('core_weight'))}",
        f"satellite_weight_display={_percent_metric(structure_budget.get('satellite_weight'))}",
    ]
    if frontier_diagnostics:
        evidence.extend(
            [
                f"frontier_raw_candidate_count={_metric(frontier_diagnostics.get('raw_candidate_count'))}",
                f"frontier_feasible_candidate_count={_metric(frontier_diagnostics.get('feasible_candidate_count'))}",
                f"frontier_max_expected_annual_return={_metric(frontier_diagnostics.get('frontier_max_expected_annual_return'))}",
            ]
        )
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
        **_gate1_card_fields(inp),
    )
    return _finalize_card(card)


def _build_goal_baseline_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    goal_output = _obj(inp.goal_solver_output or {})
    recommended = _obj(goal_output.get("recommended_allocation", {}))
    result = _obj(goal_output.get("recommended_result", {}))
    formal_surface = _probability_engine_formal_surface(inp)
    formal_result = _obj(formal_surface.get("primary_result") or result)
    canonical_probability_method = formal_surface.get("product_probability_method") or "bucket_only_no_product_proxy_adjustment"
    risk_summary = _obj(result.get("risk_summary", {}))
    candidate_options = _build_goal_candidate_options(inp, goal_output)
    fallback_options = _build_goal_fallback_options(goal_output)
    frontier_analysis = _build_frontier_analysis(goal_output, candidate_options)
    probability_explanation = _build_probability_explanation(inp, goal_output, candidate_options)
    product_evidence_panel = _product_evidence_panel(inp)
    model_disclaimer = _model_disclaimer(goal_output)
    goal_semantics = _goal_semantics(inp.goal_solver_input)
    no_feasible = _goal_output_is_no_feasible(goal_output)
    recommended_name = _metric(result.get("allocation_name") or recommended.get("name"))
    recommended_frontier = _obj(frontier_analysis.get("recommended", {}))
    raw_recommended_frontier = _obj(_obj(goal_output.get("frontier_analysis", {})).get("recommended", {}))
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
    user_visible_alternatives = fallback_options or _build_user_visible_candidate_alternatives(candidate_options)
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
    success_probability_point, success_probability_range = _disclosed_percent_fields(
        _product_layer_success_value(formal_result),
        inp=inp,
        goal_output=goal_output,
        kind="probability",
        published_point=formal_surface.get("published_point"),
        published_range=formal_surface.get("published_range"),
        disclosure_level_override=formal_surface.get("disclosure_level") or None,
        confidence_level_override=formal_surface.get("confidence_level") or None,
    )
    expected_annual_return_point, expected_annual_return_range = _disclosed_percent_fields(
        formal_surface.get("annual_return_point")
        if formal_surface.get("annual_return_point") is not None
        else result.get("expected_annual_return", raw_recommended_frontier.get("expected_annual_return")),
        inp=inp,
        goal_output=goal_output,
        kind="annual_return",
        published_point=formal_surface.get("annual_return_point"),
        published_range=formal_surface.get("annual_return_range"),
        disclosure_level_override=formal_surface.get("disclosure_level") or None,
        confidence_level_override=formal_surface.get("confidence_level") or None,
    )
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
            "success_probability": success_probability_point,
            "success_probability_range": success_probability_range,
            "bucket_success_probability": _percent_metric(
                result.get("bucket_success_probability", result.get("success_probability"))
            ),
            "product_independent_success_probability": _percent_metric(
                result.get("product_independent_success_probability")
            ),
            "product_proxy_adjusted_success_probability": _percent_metric(
                _product_proxy_success_value(result)
            ),
            "product_probability_method": canonical_probability_method,
            "implied_required_annual_return": _percent_metric(result.get("implied_required_annual_return")),
            "expected_annual_return": expected_annual_return_point,
            "expected_annual_return_range": expected_annual_return_range,
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
        probability_explanation=probability_explanation,
        frontier_analysis=frontier_analysis,
        product_evidence_panel=product_evidence_panel,
        execution_plan_summary=_execution_plan_summary(inp),
        **_gate1_card_fields(inp),
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
        **_gate1_card_fields(inp),
    )
    return _finalize_card(card)


def _build_quarterly_review_card(inp: DecisionCardBuildInput) -> dict[str, Any]:
    runtime_result = _obj(inp.runtime_result or {})
    goal_output = _obj(inp.goal_solver_output or {})
    ev_report = _obj(runtime_result.get("ev_report", {}))
    result = _obj(goal_output.get("recommended_result", {}))
    formal_surface = _probability_engine_formal_surface(inp)
    formal_result = _obj(formal_surface.get("primary_result") or result)
    canonical_probability_method = formal_surface.get("product_probability_method") or "bucket_only_no_product_proxy_adjustment"
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
    frontier_analysis = _build_frontier_analysis(goal_output, candidate_options)
    probability_explanation = _build_probability_explanation(inp, goal_output, candidate_options)
    product_evidence_panel = _product_evidence_panel(inp)
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
            "new_baseline_success_probability": _percent_metric(_product_layer_success_value(formal_result)),
            "bucket_success_probability": _percent_metric(
                formal_result.get("bucket_success_probability", _product_layer_success_value(formal_result))
            ),
            "product_independent_success_probability": _percent_metric(
                result.get("product_independent_success_probability")
            ),
            "product_proxy_adjusted_success_probability": _percent_metric(
                _product_proxy_success_value(result)
            ),
            "product_probability_method": canonical_probability_method,
            "implied_required_annual_return": _percent_metric(result.get("implied_required_annual_return")),
            "new_baseline_max_drawdown_90pct": _percent_metric(
                risk_summary.get("max_drawdown_90pct")
            ),
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
        probability_explanation=probability_explanation,
        frontier_analysis=frontier_analysis,
        product_evidence_panel=product_evidence_panel,
        execution_plan_summary=_execution_plan_summary(inp),
        **_gate1_card_fields(inp),
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
