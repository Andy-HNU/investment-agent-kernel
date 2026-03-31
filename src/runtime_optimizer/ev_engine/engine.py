from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from goal_solver.engine import run_goal_solver_lightweight
from runtime_optimizer.candidates import Action, ActionType
from runtime_optimizer.ev_engine.scorer import score_action
from runtime_optimizer.ev_engine.types import EVComponentScore, EVReport, EVResult, EVState, FeasibilityResult


def _obj(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _action_from_any(item: Any) -> Action:
    if isinstance(item, Action):
        return item
    data = _obj(item)
    action_type = data.get("type")
    if isinstance(action_type, ActionType):
        atype = action_type
    else:
        atype = ActionType(str(getattr(action_type, "value", action_type)))
    return Action(
        type=atype,
        target_bucket=data.get("target_bucket"),
        amount=data.get("amount"),
        amount_pct=data.get("amount_pct"),
        from_bucket=data.get("from_bucket"),
        to_bucket=data.get("to_bucket"),
        cash_source=data.get("cash_source", "new_cash"),
        requires_sell=bool(data.get("requires_sell", False)),
        expected_turnover=float(data.get("expected_turnover", 0.0)),
        policy_tag=data.get("policy_tag", "observe"),
        cooldown_applicable=bool(data.get("cooldown_applicable", False)),
        rationale=data.get("rationale", ""),
        explanation_facts=list(data.get("explanation_facts", [])),
    )


def _weights_after_action(action: Action, account: dict[str, Any]) -> dict[str, float]:
    current = dict(account.get("current_weights", {}))
    target = account.get("target_weights", {}) or {}
    if action.type in {ActionType.FREEZE, ActionType.OBSERVE}:
        return current

    delta = float(action.amount_pct or 0.0)
    new_weights = dict(current)
    if action.type in {
        ActionType.ADD_CASH_TO_CORE,
        ActionType.ADD_CASH_TO_DEF,
        ActionType.ADD_CASH_TO_SAT,
        ActionType.ADD_DEFENSE,
    }:
        bucket = action.target_bucket or action.to_bucket or "equity_cn"
        new_weights[bucket] = new_weights.get(bucket, 0.0) + delta
    elif action.type == ActionType.REDUCE_SATELLITE:
        bucket = action.target_bucket or "satellite"
        new_weights[bucket] = max(0.0, new_weights.get(bucket, 0.0) - delta)
    elif action.type in {ActionType.REBALANCE_LIGHT, ActionType.REBALANCE_FULL}:
        from_bucket = action.from_bucket or max(current, key=current.get)
        to_bucket = action.to_bucket or (min(target, key=target.get) if target else from_bucket)
        new_weights[from_bucket] = max(0.0, new_weights.get(from_bucket, 0.0) - delta)
        new_weights[to_bucket] = new_weights.get(to_bucket, 0.0) + delta

    total = sum(new_weights.values()) or 1.0
    return {key: value / total for key, value in new_weights.items()}


def _market_assumptions(state: EVState | dict[str, Any]) -> dict[str, Any]:
    state_dict = _obj(state)
    baseline = _obj(state_dict.get("goal_solver_baseline_inp", {}))
    solver_params = _obj(baseline.get("solver_params", {}))
    return _obj(solver_params.get("market_assumptions", {}))


def _is_qdii_bucket(bucket: str | None, constraints: dict[str, Any]) -> bool:
    if not bucket:
        return False
    normalized = bucket.lower()
    if "qdii" in normalized:
        return True
    return constraints.get("bucket_category", {}).get(bucket) == "qdii"


def _estimate_qdii_usage(
    account: dict[str, Any],
    constraints: dict[str, Any],
    new_weights: dict[str, float],
) -> float:
    current_weights = account.get("current_weights", {}) or {}
    total_value = float(account.get("total_portfolio_value", 0.0) or 0.0)
    current_qdii = sum(
        float(weight)
        for bucket, weight in current_weights.items()
        if _is_qdii_bucket(bucket, constraints)
    )
    after_qdii = sum(
        float(weight)
        for bucket, weight in new_weights.items()
        if _is_qdii_bucket(bucket, constraints)
    )
    return max(0.0, after_qdii - current_qdii) * total_value


def _validate_state(state: EVState) -> None:
    account = _obj(state.account)
    behavior = _obj(state.behavior)

    current_total = sum(float(value) for value in account["current_weights"].values())
    all_cash_snapshot = (
        current_total <= 1e-9
        and float(account.get("total_portfolio_value", 0.0) or 0.0) > 0.0
        and float(account.get("available_cash", 0.0) or 0.0) >= float(account.get("total_portfolio_value", 0.0) or 0.0) - 1e-6
    )
    assert abs(current_total - 1.0) < 1e-3 or all_cash_snapshot, "current_weights 合计必须为 1"
    target_total = sum(float(value) for value in account["target_weights"].values())
    assert abs(target_total - 1.0) < 1e-3, "target_weights 合计必须为 1"
    assert 0.0 <= float(account["success_prob_baseline"]) <= 1.0, "success_prob_baseline 必须在 [0, 1]"
    assert 0.0 <= float(behavior.get("emotion_score", 0.0) or 0.0) <= 1.0, "emotion_score 必须在 [0, 1]"

    corr = _obj(_market_assumptions(state)).get("correlation_matrix", {}) or {}
    for bucket, row in corr.items():
        assert abs(float(_obj(row).get(bucket, 0.0)) - 1.0) < 1e-4, (
            f"correlation_matrix 对角元素必须为 1，违反桶：{bucket}"
        )
    for bucket_a, row in corr.items():
        row_data = _obj(row)
        for bucket_b, value in row_data.items():
            peer = float(_obj(corr.get(bucket_b, {})).get(bucket_a, value))
            assert abs(float(value) - peer) < 1e-4, (
                f"correlation_matrix 必须对称，违反桶对：{bucket_a}, {bucket_b}"
            )


def _validate_action(action: Action) -> None:
    assert not (action.amount is None and action.amount_pct is None), "amount 和 amount_pct 不能同时为空"
    assert action.amount_pct is not None, "进入 EV scorer 前，amount_pct 必须由调用方预先换算填入"
    assert 0.0 <= float(action.amount_pct) <= 1.0, "amount_pct 必须在 [0, 1]"


def _check_feasibility(action: Action, state: EVState | dict[str, Any]) -> FeasibilityResult:
    state_dict = _obj(state)
    account = _obj(state_dict["account"])
    constraints = _obj(state_dict["constraints"])
    behavior = _obj(state_dict["behavior"])
    reasons: list[str] = []
    if action.type in {ActionType.FREEZE, ActionType.OBSERVE}:
        return FeasibilityResult(True, [])
    if action.cooldown_applicable and (behavior.get("high_emotion_flag") or behavior.get("panic_flag")) and action.type not in {ActionType.FREEZE, ActionType.OBSERVE}:
        reasons.append("当前处于高情绪冷静期，非观察/冻结动作不可执行")
    if action.amount_pct is None:
        reasons.append("amount_pct 不能为空")
    if action.amount_pct <= 0:
        reasons.append("amount_pct 必须大于 0")
    if action.requires_sell and action.cash_source == "new_cash":
        reasons.append("卖出型动作不能使用 new_cash")
    if reasons:
        return FeasibilityResult(False, reasons)

    new_weights = _weights_after_action(action, account)
    for bucket, (lo, hi) in constraints.get("ips_boundaries", constraints.get("ips_bucket_boundaries", {})).items():
        weight = float(new_weights.get(bucket, 0.0))
        if weight < lo - 1e-4 or weight > hi + 1e-4:
            reasons.append(f"{bucket} 仓位 {weight:.1%} 超出 IPS 边界 [{lo:.1%}, {hi:.1%}]")

    qdii_usage = _estimate_qdii_usage(account, constraints, new_weights)
    qdii_available = float(constraints.get("qdii_available", float("inf")) or 0.0)
    if qdii_usage > qdii_available + 1e-6:
        reasons.append(
            f"QDII 配额不足，需要 {qdii_usage:.0f} 元，剩余 {qdii_available:.0f} 元"
        )

    sat_weight = sum(value for bucket, value in new_weights.items() if constraints.get("bucket_category", {}).get(bucket) == "satellite")
    if sat_weight > float(constraints.get("satellite_cap", 1.0)) + 1e-4:
        reasons.append(
            f"卫星总仓 {sat_weight:.1%} 超过上限 {float(constraints.get('satellite_cap', 1.0)):.1%}"
        )
    if action.amount and action.cash_source == "new_cash" and action.amount > float(account.get("available_cash", 0.0)):
        reasons.append(
            f"资金不足：需要 {float(action.amount):.0f} 元，可用 {float(account.get('available_cash', 0.0)):.0f} 元"
        )
    return FeasibilityResult(len(reasons) == 0, reasons)


def _action_priority(action_type: ActionType) -> int:
    priority = {
        ActionType.ADD_DEFENSE: 0,
        ActionType.ADD_CASH_TO_CORE: 1,
        ActionType.ADD_CASH_TO_DEF: 2,
        ActionType.REDUCE_SATELLITE: 3,
        ActionType.REBALANCE_LIGHT: 4,
        ActionType.REBALANCE_FULL: 5,
        ActionType.OBSERVE: 6,
        ActionType.FREEZE: 7,
        ActionType.ADD_CASH_TO_SAT: 8,
    }
    return priority.get(action_type, 99)


def _generate_reason(
    action: Action,
    score: EVComponentScore,
    rank: int,
    goal_solver_min_delta: float,
) -> str:
    if (
        score.goal_impact > goal_solver_min_delta
        and score.goal_impact >= max(
            score.risk_penalty,
            score.soft_constraint_penalty,
            score.behavior_penalty,
            score.execution_penalty,
        )
    ):
        reason = "该动作在提升目标成功概率方面最优，风险与成本可控"
    elif (
        abs(score.goal_impact) <= goal_solver_min_delta
        and score.risk_penalty <= max(goal_solver_min_delta, 0.002)
    ):
        reason = "该动作主要通过降低风险暴露提升整体配置稳健性"
    elif action.type in {ActionType.FREEZE, ActionType.OBSERVE} and score.total >= -goal_solver_min_delta:
        reason = "当前可执行动作改善空间有限，维持现状或观察更优"
    elif score.behavior_penalty >= max(score.risk_penalty, score.soft_constraint_penalty, score.execution_penalty) and score.behavior_penalty > 0:
        reason = "该动作在行为约束下优先级受限，但仍优于其他候选"
    else:
        execution_text = "执行成本较低" if score.execution_penalty <= max(goal_solver_min_delta, 0.002) else f"执行成本 -{score.execution_penalty:.2%}"
        reason = (
            f"目标影响 {score.goal_impact:+.2%}，风险成本 -{score.risk_penalty:.2%}，"
            f"{execution_text}"
        )
    if rank == 0:
        return reason
    return f"备选方案：{reason}"


def _build_confidence(
    results: list[EVResult],
    eliminated: list[tuple[Action, FeasibilityResult]],
    state: EVState,
    total_actions: int,
) -> tuple[str, str]:
    behavior = _obj(state.behavior)
    params = _obj(state.ev_params)
    goal_min_delta = float(params.get("goal_solver_min_delta", 0.0) or 0.0)

    if not results:
        return "low", "没有通过硬约束过滤的候选动作"

    if behavior.get("high_emotion_flag") or behavior.get("panic_flag"):
        return "low", "情绪标志触发，推荐稳定性下降"

    if len(results) == 1:
        return "low", "通过过滤动作仅 1 个"

    if total_actions > 0 and len(eliminated) > total_actions / 2:
        return "low", "大多数候选动作因硬约束被淘汰"

    max_goal_impact = max(abs(item.score.goal_impact) for item in results)
    if max_goal_impact <= goal_min_delta:
        return "low", "GoalImpact 近似为 0，动作改善空间有限"

    diff = results[0].score.total - results[1].score.total
    high_diff = float(params.get("high_confidence_min_diff", 0.0) or 0.0)
    medium_diff = float(params.get("medium_confidence_min_diff", 0.0) or 0.0)
    if len(results) >= 3 and diff > high_diff:
        return "high", f"top1-top2 分差 {diff:.4f} 高于 high 阈值"
    if len(results) >= 2 and diff >= medium_diff:
        return "medium", f"top1-top2 分差 {diff:.4f} 达到 medium 阈值"
    return "low", f"top1-top2 分差 {diff:.4f} 低于 medium 阈值"


def _goal_probability_after_action(action: Action, state: EVState) -> float:
    weights = _weights_after_action(action, _obj(state.account))
    after, _risk_after = run_goal_solver_lightweight(
        weights=weights,
        baseline_inp=state.goal_solver_baseline_inp,
    )
    return after


def run_ev_engine(
    state: EVState | dict[str, Any],
    candidate_actions: list[Action | dict[str, Any]],
    trigger_type: str,
) -> EVReport:
    ev_state = EVState.from_any(state)
    _validate_state(ev_state)
    state_dict = ev_state.to_dict()
    actions = [_action_from_any(item) for item in candidate_actions]
    for action in actions:
        _validate_action(action)
    baseline, _risk = run_goal_solver_lightweight(
        weights=state_dict["account"]["current_weights"],
        baseline_inp=ev_state.goal_solver_baseline_inp,
    )
    passed: list[tuple[Action, Any, int]] = []
    eliminated: list[tuple[Action, FeasibilityResult]] = []
    for index, action in enumerate(actions):
        feasibility = _check_feasibility(action, state_dict)
        if not feasibility.is_feasible:
            eliminated.append((action, feasibility))
            continue
        score = score_action(action, ev_state)
        passed.append((action, score, index))

    goal_solver_min_delta = float(_obj(state_dict["ev_params"]).get("goal_solver_min_delta", 0.0) or 0.0)
    passed.sort(key=lambda item: (-item[1].total, _action_priority(item[0].type), item[2]))
    results: list[EVResult] = []
    for rank, (action, score, _index) in enumerate(passed):
        results.append(
            EVResult(
                action=action,
                score=score,
                rank=rank + 1,
                is_recommended=rank == 0,
                recommendation_reason=_generate_reason(action, score, rank, goal_solver_min_delta),
            )
        )

    if results:
        recommended = results[0].action
        recommended_score = results[0].score
        after = _goal_probability_after_action(recommended, ev_state)
    else:
        recommended = None
        recommended_score = None
        after = None

    confidence_flag, confidence_reason = _build_confidence(
        results=results,
        eliminated=eliminated,
        state=ev_state,
        total_actions=len(actions),
    )

    report = EVReport(
        trigger_type=trigger_type,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        state_snapshot_id=str(state_dict.get("goal_solver_baseline_inp", {}).get("snapshot_id", "")),
        ranked_actions=results,
        eliminated_actions=eliminated,
        recommended_action=recommended,
        recommended_score=recommended_score,
        confidence_flag=confidence_flag,
        confidence_reason=confidence_reason,
        goal_solver_baseline=baseline,
        goal_solver_after_recommended=after,
        params_version=str(_obj(state_dict["ev_params"]).get("version", "")),
    )
    return report
