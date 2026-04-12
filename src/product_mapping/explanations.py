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
    annualized_range: tuple[float, float]
    terminal_value_range: tuple[float, float]
    pressure_score: float | None
    pressure_level: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_kind", str(self.scenario_kind).strip())
        object.__setattr__(self, "annualized_range", _pair(self.annualized_range))
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
    success_delta_if_removed: float
    terminal_mean_delta_if_removed: float
    drawdown_delta_if_removed: float
    median_return_delta_if_removed: float
    highest_overlap_product_ids: list[str] = field(default_factory=list)
    highest_diversification_product_ids: list[str] = field(default_factory=list)
    quality_labels: list[str] = field(default_factory=list)
    suggested_action: str = "keep"

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
        object.__setattr__(self, "suggested_action", str(self.suggested_action).strip())
        object.__setattr__(self, "success_delta_if_removed", float(self.success_delta_if_removed))
        object.__setattr__(self, "terminal_mean_delta_if_removed", float(self.terminal_mean_delta_if_removed))
        object.__setattr__(self, "drawdown_delta_if_removed", float(self.drawdown_delta_if_removed))
        object.__setattr__(self, "median_return_delta_if_removed", float(self.median_return_delta_if_removed))

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class ProductGroupExplanation:
    group_id: str
    group_name: str
    member_product_ids: list[str]
    scenario_metrics: list[ProductScenarioMetrics]
    quality_labels: list[str] = field(default_factory=list)
    suggested_action: str = "keep"
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", str(self.group_id).strip())
        object.__setattr__(self, "group_name", str(self.group_name).strip())
        object.__setattr__(self, "member_product_ids", [str(item).strip() for item in self.member_product_ids])
        object.__setattr__(self, "scenario_metrics", validate_product_scenario_metrics(self.scenario_metrics))
        object.__setattr__(self, "quality_labels", [str(item).strip() for item in self.quality_labels])
        object.__setattr__(self, "suggested_action", str(self.suggested_action).strip())
        object.__setattr__(self, "notes", [str(item).strip() for item in self.notes])

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BucketConstructionExplanation:
    bucket: str
    requested_count: int | None
    resolved_count: int
    source: Literal["explicit_user", "persisted_user", "auto_policy"]
    fully_satisfied: bool
    unmet_reasons: list[str] = field(default_factory=list)
    alternative_counts_considered: list[int] = field(default_factory=list)
    selected_product_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket", str(self.bucket).strip())
        if self.requested_count is not None:
            object.__setattr__(self, "requested_count", int(self.requested_count))
        object.__setattr__(self, "resolved_count", int(self.resolved_count))
        object.__setattr__(self, "source", str(self.source).strip().lower())
        object.__setattr__(self, "fully_satisfied", bool(self.fully_satisfied))
        object.__setattr__(self, "unmet_reasons", [str(item).strip() for item in self.unmet_reasons if str(item).strip()])
        object.__setattr__(
            self,
            "alternative_counts_considered",
            [int(item) for item in list(self.alternative_counts_considered or [])],
        )
        object.__setattr__(self, "selected_product_ids", [str(item).strip() for item in self.selected_product_ids])
        object.__setattr__(self, "notes", [str(item).strip() for item in self.notes])

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

