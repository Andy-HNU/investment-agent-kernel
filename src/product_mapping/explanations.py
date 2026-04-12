from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


PRODUCT_SCENARIO_LADDER: tuple[str, ...] = (
    "historical_replay",
    "current_market",
    "deteriorated_mild",
    "deteriorated_moderate",
    "deteriorated_severe",
)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize(item) for item in value)
    return value


def _pair(value: Any) -> tuple[float, float]:
    pair = tuple(value)
    if len(pair) != 2:
        raise ValueError("expected a pair-like value")
    return float(pair[0]), float(pair[1])


@dataclass(frozen=True)
class ProductScenarioMetrics:
    scenario_kind: str
    annualized_range: tuple[float, float] | None
    terminal_value_range: tuple[float, float] | None
    pressure_score: float | None
    pressure_level: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_kind", str(self.scenario_kind).strip())
        if self.annualized_range is not None:
            object.__setattr__(self, "annualized_range", _pair(self.annualized_range))
        if self.terminal_value_range is not None:
            object.__setattr__(self, "terminal_value_range", _pair(self.terminal_value_range))
        if self.pressure_score is not None:
            object.__setattr__(self, "pressure_score", float(self.pressure_score))
        if self.pressure_level is not None:
            object.__setattr__(self, "pressure_level", str(self.pressure_level).strip())

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def validate_product_scenario_metrics(
    scenario_metrics: list[ProductScenarioMetrics] | tuple[ProductScenarioMetrics, ...],
) -> list[ProductScenarioMetrics]:
    metrics = list(scenario_metrics)
    observed = [item.scenario_kind for item in metrics]
    if tuple(observed) != PRODUCT_SCENARIO_LADDER:
        raise ValueError(
            "product explanation requires full five-scenario ladder: "
            + ", ".join(PRODUCT_SCENARIO_LADDER)
        )
    return metrics


@dataclass(frozen=True)
class ProductExplanation:
    product_id: str
    role_in_portfolio: str
    scenario_metrics: list[ProductScenarioMetrics]
    success_delta_if_removed: float | None
    terminal_mean_delta_if_removed: float | None
    drawdown_delta_if_removed: float | None
    median_return_delta_if_removed: float | None
    highest_overlap_product_ids: list[str] = field(default_factory=list)
    highest_diversification_product_ids: list[str] = field(default_factory=list)
    quality_labels: list[str] = field(default_factory=list)
    suggested_action: str | None = "keep"

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", str(self.product_id).strip())
        object.__setattr__(self, "role_in_portfolio", str(self.role_in_portfolio).strip())
        object.__setattr__(self, "scenario_metrics", validate_product_scenario_metrics(self.scenario_metrics))
        object.__setattr__(self, "highest_overlap_product_ids", [str(item).strip() for item in self.highest_overlap_product_ids])
        object.__setattr__(
            self,
            "highest_diversification_product_ids",
            [str(item).strip() for item in self.highest_diversification_product_ids],
        )
        object.__setattr__(self, "quality_labels", [str(item).strip() for item in self.quality_labels])
        if self.suggested_action is not None:
            object.__setattr__(self, "suggested_action", str(self.suggested_action).strip())
        if self.success_delta_if_removed is not None:
            object.__setattr__(self, "success_delta_if_removed", float(self.success_delta_if_removed))
        if self.terminal_mean_delta_if_removed is not None:
            object.__setattr__(self, "terminal_mean_delta_if_removed", float(self.terminal_mean_delta_if_removed))
        if self.drawdown_delta_if_removed is not None:
            object.__setattr__(self, "drawdown_delta_if_removed", float(self.drawdown_delta_if_removed))
        if self.median_return_delta_if_removed is not None:
            object.__setattr__(self, "median_return_delta_if_removed", float(self.median_return_delta_if_removed))

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductGroupExplanation:
    group_type: str
    product_ids: list[str]
    rationale: str
    success_delta_if_removed: float | None
    terminal_mean_delta_if_removed: float | None
    drawdown_delta_if_removed: float | None
    median_return_delta_if_removed: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_type", str(self.group_type).strip())
        object.__setattr__(self, "product_ids", [str(item).strip() for item in self.product_ids])
        object.__setattr__(self, "rationale", str(self.rationale).strip())
        if self.success_delta_if_removed is not None:
            object.__setattr__(self, "success_delta_if_removed", float(self.success_delta_if_removed))
        if self.terminal_mean_delta_if_removed is not None:
            object.__setattr__(self, "terminal_mean_delta_if_removed", float(self.terminal_mean_delta_if_removed))
        if self.drawdown_delta_if_removed is not None:
            object.__setattr__(self, "drawdown_delta_if_removed", float(self.drawdown_delta_if_removed))
        if self.median_return_delta_if_removed is not None:
            object.__setattr__(self, "median_return_delta_if_removed", float(self.median_return_delta_if_removed))

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BucketConstructionExplanation:
    bucket: str
    requested_count: int | None
    actual_count: int
    count_source: Literal["explicit_user", "persisted_user", "auto_policy"]
    count_satisfied: bool
    unmet_reason: str | None
    why_split: list[str] = field(default_factory=list)
    no_split_counterfactual: list[str] = field(default_factory=list)
    member_roles: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket", str(self.bucket).strip())
        if self.requested_count is not None:
            object.__setattr__(self, "requested_count", int(self.requested_count))
        object.__setattr__(self, "actual_count", int(self.actual_count))
        object.__setattr__(self, "count_source", str(self.count_source).strip().lower())
        object.__setattr__(self, "count_satisfied", bool(self.count_satisfied))
        if self.unmet_reason is not None:
            object.__setattr__(self, "unmet_reason", str(self.unmet_reason).strip())
        object.__setattr__(self, "why_split", [str(item).strip() for item in self.why_split if str(item).strip()])
        object.__setattr__(
            self,
            "no_split_counterfactual",
            [str(item).strip() for item in self.no_split_counterfactual if str(item).strip()],
        )
        object.__setattr__(
            self,
            "member_roles",
            {str(key).strip(): str(value).strip() for key, value in dict(self.member_roles or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))
