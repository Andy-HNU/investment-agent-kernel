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


_BUCKET_COUNT_SOURCES = {"explicit_user", "persisted_user", "auto_policy"}


def _require_real_bool(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")
    return value


def _require_count_source(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("count_source must be a string")
    normalized = value.strip()
    if normalized not in _BUCKET_COUNT_SOURCES:
        raise ValueError(f"invalid count_source: {value!r}")
    return normalized


def _obj(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _text(value: Any) -> str:
    return str(value).strip()


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    suggested_action: str | None = None

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
    diagnostic_codes: list[str] = field(default_factory=list)
    why_split: list[str] = field(default_factory=list)
    no_split_counterfactual: list[str] = field(default_factory=list)
    member_roles: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket", str(self.bucket).strip())
        if self.requested_count is not None:
            if type(self.requested_count) is bool or not isinstance(self.requested_count, int):
                raise TypeError("requested_count must be a positive integer")
            if self.requested_count < 1:
                raise ValueError("requested_count must be >= 1")
            object.__setattr__(self, "requested_count", self.requested_count)
        if type(self.actual_count) is bool or not isinstance(self.actual_count, int):
            raise TypeError("actual_count must be a positive integer")
        if self.actual_count < 1:
            raise ValueError("actual_count must be >= 1")
        object.__setattr__(self, "actual_count", self.actual_count)
        object.__setattr__(self, "count_source", _require_count_source(self.count_source))
        object.__setattr__(self, "count_satisfied", _require_real_bool(self.count_satisfied, field_name="count_satisfied"))
        if self.unmet_reason is not None:
            object.__setattr__(self, "unmet_reason", str(self.unmet_reason).strip())
        object.__setattr__(
            self,
            "diagnostic_codes",
            [str(item).strip() for item in self.diagnostic_codes if str(item).strip()],
        )
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


def _execution_plan_items(execution_plan: Any) -> list[Any]:
    payload = _obj(execution_plan)
    if isinstance(payload, dict):
        return list(payload.get("items") or [])
    return list(getattr(execution_plan, "items", []) or [])


def _execution_plan_bucket_explanations(execution_plan: Any) -> dict[str, Any]:
    payload = _obj(execution_plan)
    if isinstance(payload, dict):
        return dict(payload.get("bucket_construction_explanations") or {})
    bucket_explanations = getattr(execution_plan, "bucket_construction_explanations", {})
    return dict(bucket_explanations or {})


def _scenario_metrics_from_probability_output(probability_output: dict[str, Any] | None) -> list[ProductScenarioMetrics]:
    output = dict(probability_output or {})
    primary = _obj(output.get("primary_result")) or {}
    path_stats = _obj(primary.get("path_stats")) or {}
    comparison = [
        _obj(item)
        for item in list(output.get("scenario_comparison") or [])
        if _obj(item)
    ]
    pressure_by_kind = {
        _text(item.get("scenario_kind")): _obj(item.get("pressure"))
        for item in comparison
        if _text(item.get("scenario_kind"))
    }
    annualized_range = None
    terminal_value_range = None
    cagr_p05 = _float(path_stats.get("cagr_p05"))
    cagr_p95 = _float(path_stats.get("cagr_p95"))
    if cagr_p05 is not None and cagr_p95 is not None:
        annualized_range = (cagr_p05, cagr_p95)
    else:
        cagr_p50 = _float(path_stats.get("cagr_p50"))
        annualized_range = None if cagr_p50 is None else (cagr_p50, cagr_p50)
    terminal_p05 = _float(path_stats.get("terminal_value_p05"))
    terminal_p95 = _float(path_stats.get("terminal_value_p95"))
    if terminal_p05 is not None and terminal_p95 is not None:
        terminal_value_range = (terminal_p05, terminal_p95)
    else:
        terminal_p50 = _float(path_stats.get("terminal_value_p50"))
        terminal_value_range = None if terminal_p50 is None else (terminal_p50, terminal_p50)
    scenario_metrics: list[ProductScenarioMetrics] = []
    for scenario_kind in PRODUCT_SCENARIO_LADDER:
        pressure = pressure_by_kind.get(scenario_kind) or {}
        scenario_metrics.append(
            ProductScenarioMetrics(
                scenario_kind=scenario_kind,
                annualized_range=annualized_range,
                terminal_value_range=terminal_value_range,
                pressure_score=_float(pressure.get("market_pressure_score")),
                pressure_level=_text(pressure.get("market_pressure_level")) or None,
            )
        )
    return scenario_metrics


def _infer_product_role(item: dict[str, Any]) -> str:
    bucket = _text(item.get("asset_bucket"))
    risk_labels = {str(label).strip() for label in list(item.get("risk_labels") or []) if str(label).strip()}
    if bucket == "cash_liquidity":
        return "liquidity_management"
    if bucket in {"gold", "bond_cn"}:
        return "defensive_buffer"
    if bucket == "satellite":
        if "主题波动" in risk_labels or "high_beta" in risk_labels:
            return "event_satellite"
        return "style_offset"
    if "style_offset" in risk_labels:
        return "style_offset"
    return "main_growth"


def _product_quality_labels(
    *,
    role_in_portfolio: str,
    weight_share: float,
    success_delta_if_removed: float,
    drawdown_delta_if_removed: float,
) -> list[str]:
    labels: list[str] = []
    if role_in_portfolio in {"defensive_buffer", "liquidity_management"}:
        labels.append("defensive")
    else:
        labels.append("high_expected_return" if success_delta_if_removed >= 0 else "replaceable")
    if weight_share <= 0.15 or abs(success_delta_if_removed) < 0.02:
        labels.append("limited_contribution")
        labels.append("replaceable")
    if drawdown_delta_if_removed > 0.03:
        labels.append("high_beta")
    return list(dict.fromkeys(labels))


def _leave_one_out_deltas(
    *,
    role_in_portfolio: str,
    weight_share: float,
    baseline_success: float,
    baseline_terminal_mean: float,
    baseline_drawdown: float,
    baseline_median_return: float,
) -> tuple[float, float, float, float]:
    role_multipliers = {
        "main_growth": (0.20, 0.18, 0.08, 0.12),
        "style_offset": (0.12, 0.10, 0.05, 0.08),
        "event_satellite": (0.10, 0.08, 0.07, 0.06),
        "defensive_buffer": (-0.08, -0.06, -0.04, -0.05),
        "liquidity_management": (-0.05, -0.04, -0.03, -0.03),
    }
    success_factor, terminal_factor, drawdown_factor, return_factor = role_multipliers.get(
        role_in_portfolio,
        (0.10, 0.08, 0.04, 0.06),
    )
    return (
        round(baseline_success * weight_share * success_factor, 4),
        round(baseline_terminal_mean * weight_share * terminal_factor, 2),
        round(baseline_drawdown * weight_share * drawdown_factor, 4),
        round(baseline_median_return * weight_share * return_factor, 4),
    )


def _group_explanation(
    *,
    group_type: str,
    product_ids: list[str],
    group_weight_share: float,
    baseline_success: float,
    baseline_terminal_mean: float,
    baseline_drawdown: float,
    baseline_median_return: float,
    rationale: str,
) -> ProductGroupExplanation:
    success_delta_if_removed = round(baseline_success * group_weight_share * 0.16, 4)
    terminal_mean_delta_if_removed = round(baseline_terminal_mean * group_weight_share * 0.12, 2)
    drawdown_delta_if_removed = round(baseline_drawdown * group_weight_share * 0.06, 4)
    median_return_delta_if_removed = round(baseline_median_return * group_weight_share * 0.08, 4)
    return ProductGroupExplanation(
        group_type=group_type,
        product_ids=product_ids,
        rationale=rationale,
        success_delta_if_removed=success_delta_if_removed,
        terminal_mean_delta_if_removed=terminal_mean_delta_if_removed,
        drawdown_delta_if_removed=drawdown_delta_if_removed,
        median_return_delta_if_removed=median_return_delta_if_removed,
    )


def build_portfolio_explanation_surfaces(
    *,
    execution_plan: Any,
    probability_engine_result: Any | None = None,
) -> dict[str, Any]:
    items = [_obj(item) for item in _execution_plan_items(execution_plan)]
    probability_payload = _obj(probability_engine_result)
    probability_output = _obj(probability_payload.get("output")) or {}
    primary_result = _obj(probability_output.get("primary_result")) or {}
    path_stats = _obj(primary_result.get("path_stats")) or {}
    baseline_success = _float(primary_result.get("success_probability")) or 0.0
    baseline_terminal_mean = _float(path_stats.get("terminal_value_mean")) or 0.0
    baseline_drawdown = _float(path_stats.get("max_drawdown_p95")) or 0.0
    baseline_median_return = _float(path_stats.get("cagr_p50")) or 0.0
    scenario_metrics = _scenario_metrics_from_probability_output(probability_output)
    total_weight = sum(max(_float(item.get("target_weight")) or 0.0, 0.0) for item in items) or 1.0

    product_explanations: dict[str, ProductExplanation] = {}
    for item in items:
        product_id = _text(item.get("primary_product_id"))
        if not product_id:
            continue
        weight = max(_float(item.get("target_weight")) or 0.0, 0.0)
        weight_share = weight / total_weight
        role_in_portfolio = _infer_product_role(item)
        success_delta_if_removed, terminal_mean_delta_if_removed, drawdown_delta_if_removed, median_return_delta_if_removed = _leave_one_out_deltas(
            role_in_portfolio=role_in_portfolio,
            weight_share=weight_share,
            baseline_success=baseline_success,
            baseline_terminal_mean=baseline_terminal_mean,
            baseline_drawdown=baseline_drawdown,
            baseline_median_return=baseline_median_return,
        )
        overlap_candidates: list[tuple[float, str]] = []
        diversification_candidates: list[tuple[float, str]] = []
        primary_product = _obj(item.get("primary_product"))
        primary_bucket = _text(item.get("asset_bucket"))
        primary_wrapper = _text(primary_product.get("wrapper_type"))
        primary_family = _text(primary_product.get("product_family"))
        for peer in items:
            peer_product_id = _text(peer.get("primary_product_id"))
            if not peer_product_id or peer_product_id == product_id:
                continue
            peer_product = _obj(peer.get("primary_product"))
            peer_bucket = _text(peer.get("asset_bucket"))
            peer_wrapper = _text(peer_product.get("wrapper_type"))
            peer_family = _text(peer_product.get("product_family"))
            peer_weight = max(_float(peer.get("target_weight")) or 0.0, 0.0)
            overlap_score = 0.0
            if primary_bucket and primary_bucket == peer_bucket:
                overlap_score += 0.4
            if primary_wrapper and primary_wrapper == peer_wrapper:
                overlap_score += 0.4
            if primary_family and primary_family == peer_family:
                overlap_score += 0.2
            if overlap_score > 0.0:
                overlap_candidates.append((overlap_score + peer_weight, peer_product_id))
            else:
                diversification_candidates.append((peer_weight, peer_product_id))
        highest_overlap_product_ids = [
            peer_product_id
            for _, peer_product_id in sorted(overlap_candidates, key=lambda item: (-item[0], item[1]))[:2]
        ]
        highest_diversification_product_ids = [
            peer_product_id
            for _, peer_product_id in sorted(diversification_candidates, key=lambda item: (-item[0], item[1]))[:2]
        ]
        quality_labels = _product_quality_labels(
            role_in_portfolio=role_in_portfolio,
            weight_share=weight_share,
            success_delta_if_removed=success_delta_if_removed,
            drawdown_delta_if_removed=drawdown_delta_if_removed,
        )
        suggested_action = "keep"
        if role_in_portfolio in {"defensive_buffer", "liquidity_management"}:
            suggested_action = "keep_as_hedge_leg"
        elif "limited_contribution" in quality_labels:
            suggested_action = "reduce"
        elif highest_overlap_product_ids:
            suggested_action = "replace"
        product_explanations[product_id] = ProductExplanation(
            product_id=product_id,
            role_in_portfolio=role_in_portfolio,
            scenario_metrics=scenario_metrics,
            success_delta_if_removed=success_delta_if_removed,
            terminal_mean_delta_if_removed=terminal_mean_delta_if_removed,
            drawdown_delta_if_removed=drawdown_delta_if_removed,
            median_return_delta_if_removed=median_return_delta_if_removed,
            highest_overlap_product_ids=highest_overlap_product_ids,
            highest_diversification_product_ids=highest_diversification_product_ids,
            quality_labels=quality_labels,
            suggested_action=suggested_action,
        )

    group_explanations: dict[str, ProductGroupExplanation] = {}
    duplicate_groups: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
    for item in items:
        primary = _obj(item.get("primary_product"))
        key = (_text(item.get("asset_bucket")) or None, _text(primary.get("wrapper_type")) or None)
        duplicate_groups.setdefault(key, []).append(item)
    duplicate_members = [
        member
        for group in duplicate_groups.values()
        if len(group) >= 2
        for member in group
    ]
    if duplicate_members:
        duplicate_members = sorted(
            duplicate_members,
            key=lambda member: (-max(_float(member.get("target_weight")) or 0.0, 0.0), _text(member.get("primary_product_id"))),
        )
        product_ids = [_text(item.get("primary_product_id")) for item in duplicate_members if _text(item.get("primary_product_id"))]
        group_weight_share = sum(max(_float(item.get("target_weight")) or 0.0, 0.0) for item in duplicate_members) / total_weight
        group_explanations["duplicate_exposure_group"] = _group_explanation(
            group_type="duplicate_exposure_group",
            product_ids=product_ids,
            group_weight_share=group_weight_share,
            baseline_success=baseline_success,
            baseline_terminal_mean=baseline_terminal_mean,
            baseline_drawdown=baseline_drawdown,
            baseline_median_return=baseline_median_return,
            rationale="shared bucket and wrapper exposure creates duplicate exposure",
        )
    low_contribution_members = [
        item
        for item in items
        if (max(_float(item.get("target_weight")) or 0.0, 0.0) / total_weight) <= 0.15
    ]
    if low_contribution_members:
        product_ids = [_text(item.get("primary_product_id")) for item in low_contribution_members if _text(item.get("primary_product_id"))]
        group_weight_share = sum(max(_float(item.get("target_weight")) or 0.0, 0.0) for item in low_contribution_members) / total_weight
        group_explanations["limited_contribution_group"] = _group_explanation(
            group_type="limited_contribution_group",
            product_ids=product_ids,
            group_weight_share=group_weight_share,
            baseline_success=baseline_success,
            baseline_terminal_mean=baseline_terminal_mean,
            baseline_drawdown=baseline_drawdown,
            baseline_median_return=baseline_median_return,
            rationale="products with small weight shares contribute limited standalone portfolio impact",
        )

    return {
        "bucket_construction_explanations": _execution_plan_bucket_explanations(execution_plan),
        "product_explanations": product_explanations,
        "product_group_explanations": group_explanations,
    }
