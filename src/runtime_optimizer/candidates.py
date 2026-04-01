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
        amount=None,
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
            amount_pct = params_dict.get("new_cash_use_pct", 1.0) / max(float(params_dict.get("new_cash_split_buckets", 1)), 1.0)
            action_type = ActionType.ADD_CASH_TO_CORE if bucket == "equity_cn" else ActionType.ADD_CASH_TO_DEF if bucket == "bond_cn" else ActionType.ADD_CASH_TO_SAT
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
    if max_dev >= hard and (mode != RuntimeOptimizerMode.MONTHLY or full_allowed_monthly) and not behavior_event:
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
        candidates.append(
            _build_action(
                ActionType.ADD_DEFENSE,
                target_bucket="bond_cn",
                amount_pct=float(params_dict.get("defense_add_pct", 0.05)),
                from_bucket=None,
                to_bucket="bond_cn",
                cash_source="new_cash",
                requires_sell=False,
                expected_turnover=0.05,
                policy_tag="risk_reduce",
                rationale="增加防御仓位",
                facts=["defensive_bias"],
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
