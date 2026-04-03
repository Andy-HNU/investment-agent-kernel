from __future__ import annotations

from typing import Any


def _goal_output(snapshot: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(snapshot.get("latest_baseline") or {})
    return dict(baseline.get("goal_solver_output") or {})


def _latest_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_run = dict(snapshot.get("latest_run") or {})
    return dict(latest_run.get("result_payload") or {})


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


def build_probability_explanation(snapshot: dict[str, Any]) -> dict[str, Any]:
    goal_output = _goal_output(snapshot)
    recommended = _recommended_result(goal_output)
    highest = _highest_probability_result(goal_output)
    return {
        "simulation_mode_requested": goal_output.get("simulation_mode_requested"),
        "simulation_mode_used": goal_output.get("simulation_mode_used"),
        "recommended_success_probability": recommended.get("success_probability"),
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
