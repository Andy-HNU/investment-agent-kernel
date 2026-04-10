from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar


T = TypeVar("T")


def _normalize_weight_map(values: dict[str, float]) -> dict[str, float]:
    positive = {str(key): max(0.0, float(value)) for key, value in dict(values).items()}
    total = sum(positive.values())
    if total <= 0.0:
        return {}
    return {key: value / total for key, value in positive.items()}


def _instruction_date(value: str) -> str:
    return str(value or "").strip()


def _calendar_rebalance_triggered(
    policy: "RebalancingPolicySpec",
    *,
    current_date: str | None,
    previous_date: str | None,
) -> bool:
    if policy.policy_type not in {"calendar", "hybrid"}:
        return False
    frequency = str(policy.calendar_frequency or "").strip().lower()
    if frequency == "daily":
        return True
    if not current_date or not previous_date:
        return False
    current = date.fromisoformat(current_date)
    previous = date.fromisoformat(previous_date)
    if frequency == "weekly":
        return current.isocalendar()[:2] != previous.isocalendar()[:2]
    if frequency == "monthly":
        return (current.year, current.month) != (previous.year, previous.month)
    if frequency == "quarterly":
        return (current.year, (current.month - 1) // 3) != (previous.year, (previous.month - 1) // 3)
    if frequency == "annual":
        return current.year != previous.year
    return False


@dataclass(frozen=True)
class CurrentPosition:
    product_id: str
    units: float
    market_value: float
    weight: float
    cost_basis: float | None
    tradable: bool

    @classmethod
    def from_any(cls, value: "CurrentPosition | dict[str, Any]") -> "CurrentPosition":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            product_id=str(payload.get("product_id", "")).strip(),
            units=float(payload.get("units", 0.0)),
            market_value=float(payload.get("market_value", 0.0)),
            weight=float(payload.get("weight", 0.0)),
            cost_basis=None if payload.get("cost_basis") is None else float(payload.get("cost_basis")),
            tradable=bool(payload.get("tradable", True)),
        )


@dataclass(frozen=True)
class ContributionInstruction:
    date: str
    amount: float
    allocation_mode: str
    target_weights: dict[str, float] | None

    @classmethod
    def from_any(cls, value: "ContributionInstruction | dict[str, Any]") -> "ContributionInstruction":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        target_weights = payload.get("target_weights")
        return cls(
            date=_instruction_date(payload.get("date")),
            amount=float(payload.get("amount", 0.0)),
            allocation_mode=str(payload.get("allocation_mode", "pro_rata")).strip(),
            target_weights=None if target_weights is None else {str(key): float(item) for key, item in dict(target_weights).items()},
        )


@dataclass(frozen=True)
class WithdrawalInstruction:
    date: str
    amount: float
    execution_rule: str
    target_products: list[str] | None

    @classmethod
    def from_any(cls, value: "WithdrawalInstruction | dict[str, Any]") -> "WithdrawalInstruction":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        target_products = payload.get("target_products")
        return cls(
            date=_instruction_date(payload.get("date")),
            amount=float(payload.get("amount", 0.0)),
            execution_rule=str(payload.get("execution_rule", "cash_first")).strip(),
            target_products=None if target_products is None else [str(item).strip() for item in list(target_products)],
        )


@dataclass(frozen=True)
class RebalancingPolicySpec:
    policy_type: str
    calendar_frequency: str | None
    threshold_band: float | None
    execution_timing: str
    transaction_cost_bps: float
    min_trade_amount: float | None

    @classmethod
    def from_any(cls, value: "RebalancingPolicySpec | dict[str, Any]") -> "RebalancingPolicySpec":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            policy_type=str(payload.get("policy_type", "none")).strip(),
            calendar_frequency=None if payload.get("calendar_frequency") is None else str(payload.get("calendar_frequency")).strip(),
            threshold_band=None if payload.get("threshold_band") is None else float(payload.get("threshold_band")),
            execution_timing=str(payload.get("execution_timing", "")).strip(),
            transaction_cost_bps=float(payload.get("transaction_cost_bps", 0.0)),
            min_trade_amount=None if payload.get("min_trade_amount") is None else float(payload.get("min_trade_amount")),
        )


@dataclass(frozen=True)
class PortfolioState:
    product_values: dict[str, float]
    cash: float
    target_weights: dict[str, float]
    last_contribution: float = 0.0
    last_withdrawal: float = 0.0
    last_turnover: float = 0.0
    last_transaction_cost: float = 0.0

    @property
    def net_value(self) -> float:
        return float(sum(self.product_values.values()) + self.cash)

    def after_returns(self, product_returns: dict[str, float]) -> "PortfolioState":
        updated = {
            product_id: max(0.0, float(value) * (1.0 + float(product_returns.get(product_id, 0.0))))
            for product_id, value in self.product_values.items()
        }
        return PortfolioState(
            product_values=updated,
            cash=self.cash,
            target_weights=dict(self.target_weights),
        )

    def apply_contribution(self, instruction: ContributionInstruction | None) -> "PortfolioState":
        if instruction is None or instruction.amount <= 0.0:
            return self
        allocations = _normalize_weight_map(instruction.target_weights or {}) if instruction.allocation_mode == "target_weights" else {}
        if not allocations:
            allocations = _normalize_weight_map(self.target_weights) or _normalize_weight_map(self.current_weights())
        updated = dict(self.product_values)
        residual_cash = float(instruction.amount)
        for product_id, weight in allocations.items():
            if product_id not in updated:
                continue
            allocated = float(instruction.amount) * weight
            updated[product_id] += allocated
            residual_cash -= allocated
        return PortfolioState(
            product_values=updated,
            cash=self.cash + residual_cash,
            target_weights=dict(self.target_weights),
            last_contribution=float(instruction.amount),
        )

    def apply_withdrawal(self, instruction: WithdrawalInstruction | None) -> "PortfolioState":
        if instruction is None or instruction.amount <= 0.0:
            return self
        remaining = float(instruction.amount)
        cash = self.cash
        updated = dict(self.product_values)
        if instruction.execution_rule in {"cash_first", "custom", "pro_rata_sell"} and cash > 0.0:
            cash_used = min(cash, remaining)
            cash -= cash_used
            remaining -= cash_used
        if remaining > 0.0:
            target_ids = [product_id for product_id in (instruction.target_products or list(updated)) if product_id in updated]
            sale_base = sum(updated[product_id] for product_id in target_ids)
            if sale_base > 0.0:
                for product_id in target_ids:
                    available = updated[product_id]
                    sale_amount = min(available, remaining * (available / sale_base))
                    updated[product_id] = max(0.0, available - sale_amount)
                sold_total = sum(self.product_values[product_id] - updated[product_id] for product_id in target_ids)
                remaining = max(0.0, remaining - sold_total)
        if remaining > 0.0:
            updated = {product_id: 0.0 for product_id in updated}
            cash = 0.0
        return PortfolioState(
            product_values=updated,
            cash=cash,
            target_weights=dict(self.target_weights),
            last_withdrawal=float(instruction.amount),
        )

    def rebalance(
        self,
        policy: RebalancingPolicySpec | None,
        *,
        current_date: str | None = None,
        previous_date: str | None = None,
    ) -> "PortfolioState":
        if policy is None:
            return self
        if policy.policy_type == "none":
            return self
        if policy.execution_timing != "end_of_day_after_return":
            return self
        current_weights = self.current_weights()
        threshold_triggered = False
        if policy.threshold_band is not None and self.target_weights:
            threshold_triggered = any(
                abs(current_weights.get(product_id, 0.0) - self.target_weights.get(product_id, 0.0)) >= float(policy.threshold_band)
                for product_id in self.target_weights
            )
        calendar_triggered = _calendar_rebalance_triggered(
            policy,
            current_date=current_date,
            previous_date=previous_date,
        )
        if policy.policy_type == "threshold" and not threshold_triggered:
            return self
        if policy.policy_type == "calendar" and not calendar_triggered:
            return self
        if policy.policy_type == "hybrid" and not (threshold_triggered or calendar_triggered):
            return self
        if not self.target_weights:
            return self
        total_before = self.net_value
        desired = {product_id: total_before * weight for product_id, weight in self.target_weights.items()}
        turnover = 0.5 * sum(abs(desired.get(product_id, 0.0) - self.product_values.get(product_id, 0.0)) for product_id in desired)
        if policy.min_trade_amount is not None and turnover < float(policy.min_trade_amount):
            return self
        transaction_cost = turnover * float(policy.transaction_cost_bps) / 10000.0
        investable = max(0.0, total_before - transaction_cost)
        updated = {product_id: investable * weight for product_id, weight in self.target_weights.items()}
        return PortfolioState(
            product_values=updated,
            cash=0.0,
            target_weights=dict(self.target_weights),
            last_turnover=turnover,
            last_transaction_cost=transaction_cost,
        )

    def current_weights(self) -> dict[str, float]:
        total = self.net_value
        if total <= 0.0:
            return {product_id: 0.0 for product_id in self.product_values}
        return {product_id: value / total for product_id, value in self.product_values.items()}


def initialize_portfolio_state(current_positions: list[CurrentPosition]) -> PortfolioState:
    product_values = {position.product_id: max(0.0, float(position.market_value)) for position in current_positions}
    target_weights = _normalize_weight_map({position.product_id: float(position.weight) for position in current_positions})
    if not target_weights:
        target_weights = _normalize_weight_map(product_values)
    return PortfolioState(product_values=product_values, cash=0.0, target_weights=target_weights)


def instructions_for_date(schedule: list[T], target_date: str) -> list[T]:
    return [instruction for instruction in schedule if getattr(instruction, "date", None) == target_date]


def apply_daily_cashflows_and_rebalance(
    portfolio_state: PortfolioState,
    product_returns: dict[str, float],
    contributions: list[ContributionInstruction],
    withdrawals: list[WithdrawalInstruction],
    policy: RebalancingPolicySpec,
    *,
    current_date: str | None = None,
    previous_date: str | None = None,
) -> PortfolioState:
    post_return = portfolio_state.after_returns(product_returns)
    post_contribution = post_return
    for contribution in contributions:
        post_contribution = post_contribution.apply_contribution(contribution)
    post_withdrawal = post_contribution
    for withdrawal in withdrawals:
        post_withdrawal = post_withdrawal.apply_withdrawal(withdrawal)
    return post_withdrawal.rebalance(
        policy,
        current_date=current_date,
        previous_date=previous_date,
    )
