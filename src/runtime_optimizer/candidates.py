from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any

from runtime_optimizer.types import RuntimeOptimizerMode


class ActionType(str, Enum):
    FREEZE = "freeze"
    OBSERVE = "observe"
    ADD_CASH_TO_CORE = "add_cash_core"
    ADD_CASH_TO_DEF = "add_cash_defense"
    ADD_CASH_TO_SAT = "add_cash_satellite"
    REBALANCE_LIGHT = "rebalance_light"
    REBALANCE_FULL = "rebalance_full"
    REDUCE_SATELLITE = "reduce_satellite"
    ADD_DEFENSE = "add_defense"


@dataclass
class Action:
    type: ActionType
    target_bucket: str | None
    amount: float | None
    amount_pct: float | None
    from_bucket: str | None
    to_bucket: str | None
    cash_source: str
    requires_sell: bool
    expected_turnover: float
    policy_tag: str
    cooldown_applicable: bool
    rationale: str
    explanation_facts: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        return data


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _build_action(
    action_type: ActionType,
    target_bucket: str | None = None,
    amount: float | None = None,
    amount_pct: float = 0.0,
    from_bucket: str | None = None,
    to_bucket: str | None = None,
    cash_source: str = "new_cash",
    requires_sell: bool = False,
    expected_turnover: float = 0.0,
    policy_tag: str = "observe",
    cooldown_applicable: bool = False,
    rationale: str = "",
    facts: list[str] | None = None,
) -> Action:
    return Action(
        type=action_type,
        target_bucket=target_bucket,
        amount=amount,
        amount_pct=_clamp(amount_pct, 0.0, 1.0),
        from_bucket=from_bucket,
        to_bucket=to_bucket,
        cash_source=cash_source,
        requires_sell=requires_sell,
        expected_turnover=expected_turnover,
        policy_tag=policy_tag,
        cooldown_applicable=cooldown_applicable,
        rationale=rationale or action_type.value,
        explanation_facts=facts or [],
    )


def _get_bucket_deviation(state: dict[str, Any]) -> dict[str, float]:
    account = state.get("account", {})
    current = account.get("current_weights", {})
    target = account.get("target_weights", {})
    buckets = set(current) | set(target)
    return {bucket: current.get(bucket, 0.0) - target.get(bucket, 0.0) for bucket in buckets}


def _select_defense_target_bucket(
    deviation: dict[str, float],
    constraints: dict[str, Any],
    market: dict[str, Any],
) -> str | None:
    bucket_category = constraints.get("bucket_category", {}) or {}
    liquidity_flag = market.get("liquidity_flag", {}) or {}
    transaction_fee_rate = constraints.get("transaction_fee_rate", {}) or {}
    defense_buckets = [
        bucket for bucket, category in bucket_category.items() if category == "defense"
    ]
    if not defense_buckets:
        return None
    defense_buckets.sort(
        key=lambda bucket: (
            deviation.get(bucket, 0.0),
            1 if liquidity_flag.get(bucket, False) else 0,
            float(transaction_fee_rate.get(bucket, 0.0) or 0.0),
            bucket,
        )
    )
    return defense_buckets[0]


def _find_most_overweight_bucket(
    deviation: dict[str, float],
    constraints: dict[str, Any],
    *,
    exclude_category: str | None = None,
) -> str | None:
    bucket_category = constraints.get("bucket_category", {}) or {}
    eligible = [
        bucket
        for bucket, value in deviation.items()
        if value > 0 and (exclude_category is None or bucket_category.get(bucket) != exclude_category)
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda bucket: (-deviation.get(bucket, 0.0), bucket))
    return eligible[0]


def _clip_amount_pct(
    raw_pct: float,
    params: dict[str, Any],
    *,
    upper_bound: float = 1.0,
) -> float:
    capped_upper = min(float(params.get("amount_pct_max", 1.0) or 1.0), upper_bound)
    clipped = _clamp(raw_pct, 0.0, max(0.0, capped_upper))
    minimum = float(params.get("amount_pct_min", 0.0) or 0.0)
    if clipped < minimum:
        return 0.0
    return clipped


def generate_candidates(
    state: Any,
    params: Any,
    mode: RuntimeOptimizerMode,
    structural_event: bool = False,
    behavior_event: bool = False,
    drawdown_event: bool = False,
    satellite_event: bool = False,
) -> list[Action]:
    state_dict = _as_dict(state)
    params_dict = _as_dict(params)
    account = state_dict.get("account", {})
    market = state_dict.get("market", {})
    constraints = state_dict.get("constraints", {})
    behavior = state_dict.get("behavior", {})
    current_weights = account.get("current_weights", {})
    target_weights = account.get("target_weights", {})
    deviation = _get_bucket_deviation(state_dict)
    candidates: list[Action] = []

    candidates.append(_build_action(ActionType.FREEZE, policy_tag="observe", rationale="维持现状"))
    candidates.append(_build_action(ActionType.OBSERVE, policy_tag="observe", rationale="观察并复核"))
    behavior_cooldown = behavior_event or behavior.get("high_emotion_flag") or behavior.get("panic_flag")

    available_cash = float(account.get("available_cash", 0.0))
    min_cash = float(params_dict.get("min_cash_for_action", 0.0))
    if available_cash >= min_cash:
        underweight = sorted(
            target_weights,
            key=lambda bucket: deviation.get(bucket, 0.0),
        )
        if underweight:
            bucket = underweight[0]
            total_value = float(account.get("total_portfolio_value", 0.0) or 0.0)
            bucket_deficit_pct = max(0.0, -float(deviation.get(bucket, 0.0) or 0.0))
            cash_budget_value = available_cash * float(params_dict.get("new_cash_use_pct", 1.0) or 1.0)
            deficit_value = bucket_deficit_pct * total_value
            raw_amount_pct = 0.0
            if total_value > 0.0:
                raw_amount_pct = min(cash_budget_value, deficit_value) / total_value
            upper_bound = 1.0
            if bucket == "satellite":
                upper_bound = max(
                    0.0,
                    float(constraints.get("satellite_cap", 1.0) or 1.0)
                    - float(current_weights.get("satellite", 0.0) or 0.0),
                )
            amount_pct = _clip_amount_pct(raw_amount_pct, params_dict, upper_bound=upper_bound)
            action_type = ActionType.ADD_CASH_TO_CORE if bucket == "equity_cn" else ActionType.ADD_CASH_TO_DEF if bucket == "bond_cn" else ActionType.ADD_CASH_TO_SAT
            if amount_pct > 0.0:
                candidates.append(
                    _build_action(
                        action_type,
                        target_bucket=bucket,
                        amount_pct=amount_pct,
                        cash_source="new_cash",
                        policy_tag="monthly_fix",
                        rationale=f"新增资金补{bucket}",
                        facts=["new_cash_available"],
                    )
                )

    hard = float(params_dict.get("deviation_hard_threshold", 0.1))
    soft = float(params_dict.get("deviation_soft_threshold", 0.03))
    max_dev = max((abs(v) for v in deviation.values()), default=0.0)
    if max_dev >= soft:
        candidates.append(
            _build_action(
                ActionType.REBALANCE_LIGHT,
                amount_pct=min(float(params_dict.get("amount_pct_max", 0.3)), max_dev),
                from_bucket=max(deviation, key=deviation.get) if deviation else None,
                to_bucket=min(deviation, key=deviation.get) if deviation else None,
                cash_source="sell_rebalance",
                requires_sell=True,
                expected_turnover=max_dev,
                policy_tag="rebalance",
                rationale="轻量再平衡",
                facts=["deviation_soft_trigger"],
            )
        )
    full_allowed_monthly = bool(params_dict.get("rebalance_full_allowed_monthly", False))
    full_rebalance_allowed = False
    if not behavior_event:
        if structural_event and max_dev >= soft:
            full_rebalance_allowed = True
        elif max_dev >= hard and (mode != RuntimeOptimizerMode.MONTHLY or full_allowed_monthly):
            full_rebalance_allowed = True
    if full_rebalance_allowed:
        candidates.append(
            _build_action(
                ActionType.REBALANCE_FULL,
                amount_pct=min(1.0, max_dev),
                from_bucket=max(deviation, key=deviation.get) if deviation else None,
                to_bucket=min(deviation, key=deviation.get) if deviation else None,
                cash_source="sell_rebalance",
                requires_sell=True,
                expected_turnover=max_dev * 1.5,
                policy_tag="rebalance",
                rationale="完整再平衡",
                facts=["deviation_hard_trigger"],
            )
        )

    satellite_cap = float(constraints.get("satellite_cap", 1.0))
    satellite_weight = float(current_weights.get("satellite", 0.0))
    if satellite_event or satellite_weight > satellite_cap:
        candidates.append(
            _build_action(
                ActionType.REDUCE_SATELLITE,
                target_bucket="satellite",
                amount_pct=min(0.15, satellite_weight),
                from_bucket="satellite",
                to_bucket="bond_cn",
                cash_source="sell_rebalance",
                requires_sell=True,
                expected_turnover=0.15,
                policy_tag="risk_reduce",
                rationale="降低卫星仓位",
                facts=["satellite_overweight"],
            )
        )

    if drawdown_event and mode == RuntimeOptimizerMode.EVENT:
        target_bucket = _select_defense_target_bucket(deviation, constraints, market)
        if target_bucket is not None:
            bucket_deficit = max(0.0, -deviation.get(target_bucket, 0.0))
            amount_pct = _clip_amount_pct(
                min(float(params_dict.get("defense_add_pct", 0.05)), bucket_deficit),
                params_dict,
            )
            if amount_pct > 0.0:
                defense_amount = amount_pct * float(account.get("total_portfolio_value", 0.0) or 0.0)
                available_cash = float(account.get("available_cash", 0.0) or 0.0)
                from_bucket = None
                cash_source = "new_cash"
                requires_sell = False
                if available_cash < defense_amount:
                    from_bucket = _find_most_overweight_bucket(
                        deviation,
                        constraints,
                        exclude_category="defense",
                    )
                    if from_bucket is not None:
                        cash_source = "sell_rebalance"
                        requires_sell = True
                    else:
                        amount_pct = 0.0
                if amount_pct > 0.0:
                    candidates.append(
                        _build_action(
                            ActionType.ADD_DEFENSE,
                            target_bucket=target_bucket,
                            amount=defense_amount,
                            amount_pct=amount_pct,
                            from_bucket=from_bucket,
                            to_bucket=target_bucket,
                            cash_source=cash_source,
                            requires_sell=requires_sell,
                            expected_turnover=amount_pct,
                            policy_tag="risk_reduce",
                            rationale=f"回撤触发防御补仓：{target_bucket}",
                            facts=[
                                "defensive_bias",
                                f"target_bucket={target_bucket}",
                                f"bucket_deficit={bucket_deficit:.4f}",
                            ],
                        )
                    )

    if behavior_cooldown:
        for item in candidates:
            if item.type not in {ActionType.FREEZE, ActionType.OBSERVE}:
                item.cooldown_applicable = True

    # recent_chasing_flag only affects scoring, not candidate construction
    unique: list[Action] = []
    seen: set[tuple[Any, ...]] = set()
    for item in candidates:
        key = (item.type, item.target_bucket, item.from_bucket, item.to_bucket)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[: max(2, int(params_dict.get("max_candidates", len(unique) or 2)))]
