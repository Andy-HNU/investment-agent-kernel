from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("%"):
            raw = raw[:-1].strip()
            try:
                return float(raw) / 100.0
            except ValueError:
                return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _goal_output(snapshot: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(snapshot.get("latest_baseline") or {})
    return dict(baseline.get("goal_solver_output") or {})


def _latest_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_run = dict(snapshot.get("latest_run") or {})
    return dict(latest_run.get("result_payload") or {})


def _goal_solver_input(snapshot: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(snapshot.get("latest_baseline") or {})
    return dict(baseline.get("goal_solver_input") or {})


def _recommended_result(goal_output: dict[str, Any]) -> dict[str, Any]:
    return dict(goal_output.get("recommended_result") or {})


def _highest_probability_result(goal_output: dict[str, Any]) -> dict[str, Any]:
    all_results = list(goal_output.get("all_results") or [])
    if not all_results:
        return {}
    return max(
        (dict(item or {}) for item in all_results),
        key=lambda item: float(
            item.get("product_adjusted_success_probability", item.get("success_probability", 0.0)) or 0.0
        ),
    )


def _frontier_analysis(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _latest_payload(snapshot)
    explicit = dict(payload.get("frontier_analysis") or snapshot.get("frontier_analysis") or {})
    if explicit:
        return explicit
    return dict(_goal_output(snapshot).get("frontier_analysis") or {})


def _frontier_scenario(snapshot: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    frontier = _frontier_analysis(snapshot)
    scenario = dict(frontier.get(scenario_key) or frontier.get(f"{scenario_key}_plan") or {})
    status = dict(frontier.get("scenario_status") or {}).get(scenario_key) or {}
    if not scenario and not status:
        return {}
    if not scenario:
        scenario = {
            "allocation_name": None,
            "label": None,
            "success_probability": None,
            "product_adjusted_success_probability": None,
            "expected_annual_return": None,
            "max_drawdown_90pct": None,
        }
    if status:
        scenario = dict(scenario)
        scenario["constraint_met"] = status.get("constraint_met")
        scenario["availability_reason"] = status.get("reason")
    return scenario


def _candidate_pool(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _latest_payload(snapshot)
    decision_card = dict(payload.get("decision_card") or {})
    options = list(decision_card.get("candidate_options") or [])
    if options:
        normalized: list[dict[str, Any]] = []
        for option in options:
            item = dict(option or {})
            metrics = dict(item.get("metrics") or {})
            normalized.append(
                {
                    "allocation_name": item.get("allocation_name"),
                    "label": item.get("label"),
                    "success_probability": _to_float(item.get("success_probability") or metrics.get("success_probability")),
                    "product_adjusted_success_probability": _to_float(
                        item.get("product_adjusted_success_probability")
                        or metrics.get("product_adjusted_success_probability")
                    ),
                    "implied_required_annual_return": _to_float(
                        item.get("implied_required_annual_return") or metrics.get("implied_required_annual_return")
                    ),
                    "expected_annual_return": _to_float(
                        item.get("expected_annual_return")
                        or item.get("scenario_expected_annual_return")
                        or metrics.get("expected_annual_return")
                        or metrics.get("scenario_expected_annual_return")
                    ),
                    "risk_summary": {
                        "max_drawdown_90pct": _to_float(
                            item.get("max_drawdown_90pct") or metrics.get("max_drawdown_90pct")
                        )
                    },
                }
            )
        return normalized
    goal_output = _goal_output(snapshot)
    all_results = list(goal_output.get("all_results") or [])
    if all_results:
        return [dict(item or {}) for item in all_results]
    candidate_menu = list(goal_output.get("candidate_menu") or [])
    if candidate_menu:
        return [dict(item or {}) for item in candidate_menu]
    recommended = _recommended_result(goal_output)
    return [recommended] if recommended else []


def _scenario_return_metric(snapshot: dict[str, Any], item: dict[str, Any]) -> float | None:
    direct = _to_float(item.get("expected_annual_return") or item.get("scenario_expected_annual_return"))
    if direct is not None:
        return direct
    goal_solver_input = _goal_solver_input(snapshot)
    if not goal_solver_input:
        return None
    expected_terminal_value = _to_float(item.get("expected_terminal_value"))
    current_portfolio_value = _to_float(goal_solver_input.get("current_portfolio_value"))
    goal = dict(goal_solver_input.get("goal") or {})
    cashflow_plan = dict(goal_solver_input.get("cashflow_plan") or {})
    horizon_months = int(goal.get("horizon_months") or 0)
    monthly_contribution = _to_float(cashflow_plan.get("monthly_contribution"))
    if None in {expected_terminal_value, current_portfolio_value, monthly_contribution} or horizon_months <= 0:
        return None
    from goal_solver.engine import _build_cashflow_schedule, _solve_implied_required_annual_return

    return _solve_implied_required_annual_return(
        initial_value=float(current_portfolio_value),
        cashflow_schedule=_build_cashflow_schedule(cashflow_plan, horizon_months),
        goal_amount=float(expected_terminal_value),
    )


def _select_for_target_return(
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    requested_annual_return: float,
) -> dict[str, Any]:
    frontier_selected = _frontier_scenario(snapshot, "target_return_priority")
    if frontier_selected:
        return {
            "requested_annual_return": requested_annual_return,
            "selected_allocation_name": frontier_selected.get("allocation_name"),
            "selected_allocation_label": frontier_selected.get("label"),
            "achievable_probability": _to_float(
                frontier_selected.get("product_adjusted_success_probability", frontier_selected.get("success_probability"))
            ),
            "expected_max_drawdown_90pct": _to_float(frontier_selected.get("max_drawdown_90pct")),
            "achievable_expected_annual_return": _to_float(
                frontier_selected.get("expected_annual_return")
            ),
            "constraint_met": frontier_selected.get("constraint_met"),
            "selection_basis": "frontier_analysis",
            "availability_reason": frontier_selected.get("availability_reason"),
        }
    eligible = [
        item
        for item in candidates
        if (_scenario_return_metric(snapshot, item) or 0.0) >= requested_annual_return
    ]
    pool = eligible or candidates
    selected = max(
        pool,
        key=lambda item: (
            _to_float(item.get("product_adjusted_success_probability"))
            or _to_float(item.get("success_probability"))
            or 0.0,
            -(_to_float(dict(item.get("risk_summary") or {}).get("max_drawdown_90pct")) or 0.0),
        ),
        default={},
    )
    return {
        "requested_annual_return": requested_annual_return,
        "selected_allocation_name": selected.get("allocation_name"),
        "selected_allocation_label": selected.get("label"),
        "achievable_probability": _to_float(
            selected.get("product_adjusted_success_probability", selected.get("success_probability"))
        ),
        "expected_max_drawdown_90pct": _to_float(dict(selected.get("risk_summary") or {}).get("max_drawdown_90pct")),
        "achievable_expected_annual_return": _to_float(
            _scenario_return_metric(snapshot, selected)
        ),
        "constraint_met": bool(eligible),
        "selection_basis": "candidate_pool",
    }


def _select_for_drawdown_limit(
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    requested_max_drawdown: float,
) -> dict[str, Any]:
    frontier_selected = _frontier_scenario(snapshot, "drawdown_priority")
    if frontier_selected:
        return {
            "requested_max_drawdown": requested_max_drawdown,
            "selected_allocation_name": frontier_selected.get("allocation_name"),
            "selected_allocation_label": frontier_selected.get("label"),
            "achievable_expected_annual_return": _to_float(frontier_selected.get("expected_annual_return")),
            "achievable_probability": _to_float(
                frontier_selected.get("product_adjusted_success_probability", frontier_selected.get("success_probability"))
            ),
            "constraint_met": frontier_selected.get("constraint_met"),
            "selection_basis": "frontier_analysis",
            "availability_reason": frontier_selected.get("availability_reason"),
        }
    eligible = [
        item
        for item in candidates
        if (_to_float(dict(item.get("risk_summary") or {}).get("max_drawdown_90pct")) or 1.0) <= requested_max_drawdown
    ]
    pool = eligible or candidates
    selected = max(
        pool,
        key=lambda item: (
            _scenario_return_metric(snapshot, item) or 0.0,
            _to_float(item.get("product_adjusted_success_probability"))
            or _to_float(item.get("success_probability"))
            or 0.0,
        ),
        default={},
    )
    return {
        "requested_max_drawdown": requested_max_drawdown,
        "selected_allocation_name": selected.get("allocation_name"),
        "selected_allocation_label": selected.get("label"),
        "achievable_expected_annual_return": _scenario_return_metric(snapshot, selected),
        "achievable_probability": _to_float(
            selected.get("product_adjusted_success_probability", selected.get("success_probability"))
        ),
        "constraint_met": bool(eligible),
        "selection_basis": "candidate_pool",
    }


def build_probability_explanation(
    snapshot: dict[str, Any],
    *,
    requested_annual_return: float | None = None,
    requested_max_drawdown: float | None = None,
) -> dict[str, Any]:
    goal_output = _goal_output(snapshot)
    recommended = _recommended_result(goal_output)
    highest = _highest_probability_result(goal_output)
    explanation = {
        "simulation_mode_requested": goal_output.get("simulation_mode_requested"),
        "simulation_mode_used": goal_output.get("simulation_mode_used"),
        "recommended_success_probability": recommended.get(
            "product_adjusted_success_probability",
            recommended.get("success_probability"),
        ),
        "recommended_product_adjusted_success_probability": recommended.get("product_adjusted_success_probability"),
        "implied_required_annual_return": recommended.get("implied_required_annual_return"),
        "recommended_allocation_name": recommended.get("allocation_name"),
        "highest_probability_allocation_name": highest.get("allocation_name"),
        "highest_probability": highest.get(
            "product_adjusted_success_probability",
            highest.get("success_probability"),
        ),
        "different_from_recommended": bool(highest) and highest.get("allocation_name") != recommended.get("allocation_name"),
        "solver_notes": list(goal_output.get("solver_notes") or []),
    }
    candidates = _candidate_pool(snapshot)
    if requested_annual_return is not None:
        explanation["target_return_tradeoff"] = _select_for_target_return(snapshot, candidates, requested_annual_return)
    if requested_max_drawdown is not None:
        explanation["drawdown_limit_tradeoff"] = _select_for_drawdown_limit(snapshot, candidates, requested_max_drawdown)
    return explanation


def build_data_basis_explanation(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _latest_payload(snapshot)
    calibration_result = dict(payload.get("calibration_result") or {})
    market_state = dict(calibration_result.get("market_state") or {})
    market_assumptions = dict(calibration_result.get("market_assumptions") or {})
    return {
        "simulation_mode_used": _goal_output(snapshot).get("simulation_mode_used"),
        "dataset_version": market_assumptions.get("dataset_version") or market_state.get("historical_dataset_version"),
        "historical_dataset_source": market_state.get("historical_dataset_source"),
        "historical_frequency": market_state.get("historical_frequency"),
        "observed_history_days": market_state.get("observed_history_days", market_assumptions.get("observed_history_days")),
        "inferred_history_days": market_state.get("inferred_history_days", market_assumptions.get("inferred_history_days")),
        "historical_coverage_status": market_state.get("historical_coverage_status"),
        "historical_cycle_reasons": list(market_state.get("historical_cycle_reasons") or []),
        "risk_environment": market_state.get("risk_environment"),
        "volatility_regime": market_state.get("volatility_regime"),
    }


def build_plan_change_explanation(user_state: dict[str, Any]) -> dict[str, Any]:
    comparison = dict(user_state.get("execution_plan_comparison") or {})
    return {
        "recommendation": comparison.get("recommendation"),
        "change_level": comparison.get("change_level"),
        "changed_bucket_count": comparison.get("changed_bucket_count"),
        "product_switch_count": comparison.get("product_switch_count"),
        "max_weight_delta": comparison.get("max_weight_delta"),
        "summary": list(comparison.get("summary") or []),
    }


def build_execution_policy_explanation(snapshot: dict[str, Any]) -> dict[str, Any]:
    active_plan = dict(snapshot.get("active_execution_plan") or {})
    pending_plan = dict(snapshot.get("pending_execution_plan") or {})
    policy = (
        dict(active_plan.get("quarterly_execution_policy") or {})
        or dict(pending_plan.get("quarterly_execution_policy") or {})
    )
    return {
        "plan_id": policy.get("plan_id") or active_plan.get("plan_id") or pending_plan.get("plan_id"),
        "cash_reserve_target": policy.get("cash_reserve_target"),
        "review_date": policy.get("review_date"),
        "budget_structure": dict(policy.get("budget_structure") or {}),
        "initial_actions": list(policy.get("initial_actions") or []),
        "trigger_rules": list(policy.get("trigger_rules") or []),
    }


def build_daily_monitor_summary(snapshot: dict[str, Any], user_state: dict[str, Any]) -> dict[str, Any]:
    reconciliation = dict(user_state.get("reconciliation_state") or {})
    execution_policy = build_execution_policy_explanation(snapshot)
    alerts: list[dict[str, Any]] = []
    for product_id in list(reconciliation.get("unexpected_products") or []):
        alerts.append(
            {
                "severity": "review",
                "type": "unexpected_product",
                "product_id": product_id,
                "message": f"观测持仓里出现未在目标计划中的产品 {product_id}，需要先对账再决定动作。",
            }
        )
    for bucket, drift in dict(reconciliation.get("drift_by_bucket") or {}).items():
        weight_delta = float(dict(drift or {}).get("weight_delta") or 0.0)
        if abs(weight_delta) >= 0.05:
            alerts.append(
                {
                    "severity": "rebalance",
                    "type": "bucket_drift",
                    "asset_bucket": bucket,
                    "weight_delta": weight_delta,
                    "message": f"{bucket} 偏离目标权重 {weight_delta:.2%}，接近再平衡带。",
                }
            )
    for rule in list(execution_policy.get("trigger_rules") or []):
        payload = dict(rule or {})
        alerts.append(
            {
                "severity": "watch",
                "type": "policy_rule",
                "rule_id": payload.get("rule_id"),
                "scope": payload.get("scope"),
                "trigger_type": payload.get("trigger_type"),
                "message": payload.get("note"),
            }
        )
    return {
        "planned_action_status": reconciliation.get("planned_action_status"),
        "alerts": alerts,
        "execution_policy": execution_policy,
    }
