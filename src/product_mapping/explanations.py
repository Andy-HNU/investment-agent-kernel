from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

from probability_engine.engine import run_probability_engine


PRODUCT_SCENARIO_LADDER: tuple[str, ...] = (
    "historical_replay",
    "current_market",
    "deteriorated_mild",
    "deteriorated_moderate",
    "deteriorated_severe",
)

_EXPLANATION_RECIPE_PATH_COUNT_BUDGET = 1
_EXPLANATION_CHALLENGER_PATH_COUNT_BUDGET = 1
_EXPLANATION_STRESS_PATH_COUNT_BUDGET = 1


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


def _text(value: Any) -> str | None:
    if value is None:
        return None
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


def _scenario_result_summary(result: dict[str, Any], pressure: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _obj(result) or {}
    path_stats = _obj(payload.get("path_stats")) or {}
    cagr_range = _pair(payload.get("cagr_range")) if payload.get("cagr_range") is not None else None
    terminal_range = None
    cagr_p05 = _float(path_stats.get("cagr_p05"))
    cagr_p95 = _float(path_stats.get("cagr_p95"))
    if cagr_range is None:
        if cagr_p05 is not None and cagr_p95 is not None:
            cagr_range = (cagr_p05, cagr_p95)
        else:
            cagr_p50 = _float(path_stats.get("cagr_p50"))
            cagr_range = None if cagr_p50 is None else (cagr_p50, cagr_p50)
    terminal_p05 = _float(path_stats.get("terminal_value_p05"))
    terminal_p95 = _float(path_stats.get("terminal_value_p95"))
    if terminal_p05 is not None and terminal_p95 is not None:
        terminal_range = (terminal_p05, terminal_p95)
    else:
        terminal_p50 = _float(path_stats.get("terminal_value_p50"))
        terminal_range = None if terminal_p50 is None else (terminal_p50, terminal_p50)
    return {
        "success_probability": _float(payload.get("success_probability")),
        "terminal_value_mean": _float(path_stats.get("terminal_value_mean")),
        "terminal_value_range": terminal_range,
        "cagr_range": cagr_range,
        "cagr_p50": _float(path_stats.get("cagr_p50")),
        "max_drawdown_p95": _float(path_stats.get("max_drawdown_p95")),
        "pressure_score": _float((pressure or {}).get("market_pressure_score")),
        "pressure_level": _text((pressure or {}).get("market_pressure_level")) or None,
    }


def _scenario_summaries_from_probability_output(probability_output: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    output = dict(probability_output or {})
    primary = _obj(output.get("primary_result")) or {}
    current_pressure = _obj(output.get("current_market_pressure")) or {}
    summary_by_kind: dict[str, dict[str, Any]] = {}
    if primary:
        summary_by_kind["current_market"] = _scenario_result_summary(primary, current_pressure)
    comparison = [_obj(item) for item in list(output.get("scenario_comparison") or []) if _obj(item)]
    for item in comparison:
        scenario_kind = _text(item.get("scenario_kind"))
        if not scenario_kind:
            continue
        recipe_result = _obj(item.get("recipe_result")) or primary
        summary_by_kind[scenario_kind] = _scenario_result_summary(recipe_result, _obj(item.get("pressure")))
    for scenario_kind in PRODUCT_SCENARIO_LADDER:
        summary_by_kind.setdefault(scenario_kind, summary_by_kind.get("current_market") or _scenario_result_summary(primary, current_pressure))
    return summary_by_kind


def _scenario_metrics_from_probability_output(probability_output: dict[str, Any] | None) -> list[ProductScenarioMetrics]:
    summaries = _scenario_summaries_from_probability_output(probability_output)
    scenario_metrics: list[ProductScenarioMetrics] = []
    for scenario_kind in PRODUCT_SCENARIO_LADDER:
        summary = summaries.get(scenario_kind) or {}
        scenario_metrics.append(
            ProductScenarioMetrics(
                scenario_kind=scenario_kind,
                annualized_range=summary.get("cagr_range"),
                terminal_value_range=summary.get("terminal_value_range"),
                pressure_score=summary.get("pressure_score"),
                pressure_level=summary.get("pressure_level"),
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


def _portfolio_weight_map(items: list[dict[str, Any]]) -> dict[str, float]:
    weight_map: dict[str, float] = {}
    for item in items:
        product_id = _text(item.get("primary_product_id"))
        if not product_id:
            continue
        weight_map[product_id] = max(_float(item.get("target_weight")) or 0.0, 0.0)
    total = sum(weight_map.values())
    if total <= 0.0:
        return {product_id: 1.0 / max(len(weight_map), 1) for product_id in weight_map}
    return {product_id: weight / total for product_id, weight in weight_map.items()}


def _counterfactual_probability_input(
    *,
    probability_engine_input: Any | None,
    removed_product_ids: set[str],
) -> dict[str, Any] | None:
    payload = _obj(probability_engine_input)
    if not payload:
        return None
    counterfactual = deepcopy(payload)
    current_positions = [dict(item) for item in list(counterfactual.get("current_positions") or [])]
    products = [dict(item) for item in list(counterfactual.get("products") or [])]
    if not current_positions or not products:
        return None
    original_total_value = sum(max(_float(item.get("market_value")) or _float(item.get("units")) or 0.0, 0.0) for item in current_positions)
    remaining_positions = [item for item in current_positions if _text(item.get("product_id")) not in removed_product_ids]
    remaining_products = [item for item in products if _text(item.get("product_id")) not in removed_product_ids]
    if not remaining_positions or not remaining_products:
        return None
    remaining_weights = {str(item.get("product_id")): max(_float(item.get("weight")) or 0.0, 0.0) for item in remaining_positions}
    remaining_total_weight = sum(remaining_weights.values())
    if remaining_total_weight <= 0.0:
        equal_weight = 1.0 / float(len(remaining_positions))
        redistributed_weights = {str(item.get("product_id")): equal_weight for item in remaining_positions}
    else:
        redistributed_weights = {
            product_id: weight / remaining_total_weight
            for product_id, weight in remaining_weights.items()
        }
    for position in remaining_positions:
        product_id = str(position.get("product_id"))
        new_weight = float(redistributed_weights.get(product_id, 0.0))
        position["weight"] = new_weight
        position["market_value"] = round(original_total_value * new_weight, 2)
        position["units"] = round(original_total_value * new_weight, 2)
    counterfactual["current_positions"] = remaining_positions
    counterfactual["products"] = remaining_products
    contribution_schedule = []
    for item in list(counterfactual.get("contribution_schedule") or []):
        entry = dict(item)
        if "target_weights" in entry:
            entry["target_weights"] = dict(redistributed_weights)
        contribution_schedule.append(entry)
    counterfactual["contribution_schedule"] = contribution_schedule

    recipes = []
    for recipe in list(counterfactual.get("recipes") or []):
        recipe_payload = dict(_obj(recipe) or {})
        path_count = recipe_payload.get("path_count")
        if path_count is not None:
            try:
                recipe_payload["path_count"] = max(
                    1,
                    min(int(path_count), _EXPLANATION_RECIPE_PATH_COUNT_BUDGET),
                )
            except (TypeError, ValueError):
                recipe_payload["path_count"] = _EXPLANATION_RECIPE_PATH_COUNT_BUDGET
        recipes.append(recipe_payload)
    if recipes:
        counterfactual["recipes"] = recipes

    if counterfactual.get("challenger_path_count") is not None:
        try:
            counterfactual["challenger_path_count"] = max(
                1,
                min(int(counterfactual["challenger_path_count"]), _EXPLANATION_CHALLENGER_PATH_COUNT_BUDGET),
            )
        except (TypeError, ValueError):
            counterfactual["challenger_path_count"] = _EXPLANATION_CHALLENGER_PATH_COUNT_BUDGET

    if counterfactual.get("stress_path_count") is not None:
        try:
            counterfactual["stress_path_count"] = max(
                1,
                min(int(counterfactual["stress_path_count"]), _EXPLANATION_STRESS_PATH_COUNT_BUDGET),
            )
        except (TypeError, ValueError):
            counterfactual["stress_path_count"] = _EXPLANATION_STRESS_PATH_COUNT_BUDGET

    return counterfactual


def _run_counterfactual_probability_result(
    *,
    probability_engine_input: Any | None,
    removed_product_ids: set[str],
) -> dict[str, Any] | None:
    counterfactual_input = _counterfactual_probability_input(
        probability_engine_input=probability_engine_input,
        removed_product_ids=removed_product_ids,
    )
    if counterfactual_input is None:
        return None
    try:
        return _obj(run_probability_engine(counterfactual_input))
    except Exception:
        return None


def _aggregate_counterfactual_deltas(
    *,
    baseline_summaries: dict[str, dict[str, Any]],
    counterfactual_summaries: dict[str, dict[str, Any]] | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    if not counterfactual_summaries:
        return None, None, None, None
    scenario_keys = [
        scenario_kind
        for scenario_kind in PRODUCT_SCENARIO_LADDER
        if baseline_summaries.get(scenario_kind) and counterfactual_summaries.get(scenario_kind)
    ]
    if not scenario_keys:
        return None, None, None, None
    success_deltas: list[float] = []
    terminal_deltas: list[float] = []
    drawdown_deltas: list[float] = []
    return_deltas: list[float] = []
    for scenario_kind in scenario_keys:
        baseline = baseline_summaries[scenario_kind]
        counterfactual = counterfactual_summaries[scenario_kind]
        baseline_success = _float(baseline.get("success_probability"))
        counterfactual_success = _float(counterfactual.get("success_probability"))
        baseline_terminal = _float(baseline.get("terminal_value_mean"))
        counterfactual_terminal = _float(counterfactual.get("terminal_value_mean"))
        baseline_drawdown = _float(baseline.get("max_drawdown_p95"))
        counterfactual_drawdown = _float(counterfactual.get("max_drawdown_p95"))
        baseline_return = _float(baseline.get("cagr_p50"))
        counterfactual_return = _float(counterfactual.get("cagr_p50"))
        if baseline_success is not None and counterfactual_success is not None:
            success_deltas.append(round(baseline_success - counterfactual_success, 4))
        if baseline_terminal is not None and counterfactual_terminal is not None:
            terminal_deltas.append(round(baseline_terminal - counterfactual_terminal, 2))
        if baseline_drawdown is not None and counterfactual_drawdown is not None:
            drawdown_deltas.append(round(counterfactual_drawdown - baseline_drawdown, 4))
        if baseline_return is not None and counterfactual_return is not None:
            return_deltas.append(round(baseline_return - counterfactual_return, 4))
    if not success_deltas:
        return None, None, None, None
    return (
        round(sum(success_deltas) / len(success_deltas), 4),
        round(sum(terminal_deltas) / len(terminal_deltas), 2) if terminal_deltas else None,
        round(sum(drawdown_deltas) / len(drawdown_deltas), 4) if drawdown_deltas else None,
        round(sum(return_deltas) / len(return_deltas), 4) if return_deltas else None,
    )


def _group_explanation(
    *,
    group_type: str,
    product_ids: list[str],
    success_delta_if_removed: float | None,
    terminal_mean_delta_if_removed: float | None,
    drawdown_delta_if_removed: float | None,
    median_return_delta_if_removed: float | None,
    rationale: str,
) -> ProductGroupExplanation:
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
    probability_engine_input: Any | None = None,
) -> dict[str, Any]:
    items = [_obj(item) for item in _execution_plan_items(execution_plan)]
    probability_payload = _obj(probability_engine_result) or {}
    probability_output = _obj(probability_payload.get("output")) or {}
    primary_result = _obj(probability_output.get("primary_result")) or {}
    baseline_summaries = _scenario_summaries_from_probability_output(probability_output)
    scenario_metrics = _scenario_metrics_from_probability_output(probability_output)
    weight_map = _portfolio_weight_map(items)

    product_explanations: dict[str, ProductExplanation] = {}
    for item in items:
        product_id = _text(item.get("primary_product_id"))
        if not product_id:
            continue
        role_in_portfolio = _infer_product_role(item)
        counterfactual_result = _run_counterfactual_probability_result(
            probability_engine_input=probability_engine_input,
            removed_product_ids={product_id},
        )
        counterfactual_summaries = _scenario_summaries_from_probability_output(
            _obj(counterfactual_result.get("output")) if counterfactual_result else None
        )
        success_delta_if_removed, terminal_mean_delta_if_removed, drawdown_delta_if_removed, median_return_delta_if_removed = _aggregate_counterfactual_deltas(
            baseline_summaries=baseline_summaries,
            counterfactual_summaries=counterfactual_summaries,
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
            weight_share=weight_map.get(product_id, 0.0),
            success_delta_if_removed=0.0 if success_delta_if_removed is None else success_delta_if_removed,
            drawdown_delta_if_removed=0.0 if drawdown_delta_if_removed is None else drawdown_delta_if_removed,
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
        group_ids = {product_id for product_id in product_ids if product_id}
        counterfactual_result = _run_counterfactual_probability_result(
            probability_engine_input=probability_engine_input,
            removed_product_ids=group_ids,
        )
        counterfactual_summaries = _scenario_summaries_from_probability_output(
            _obj(counterfactual_result.get("output")) if counterfactual_result else None
        )
        success_delta_if_removed, terminal_mean_delta_if_removed, drawdown_delta_if_removed, median_return_delta_if_removed = _aggregate_counterfactual_deltas(
            baseline_summaries=baseline_summaries,
            counterfactual_summaries=counterfactual_summaries,
        )
        group_explanations["duplicate_exposure_group"] = _group_explanation(
            group_type="duplicate_exposure_group",
            product_ids=product_ids,
            success_delta_if_removed=success_delta_if_removed,
            terminal_mean_delta_if_removed=terminal_mean_delta_if_removed,
            drawdown_delta_if_removed=drawdown_delta_if_removed,
            median_return_delta_if_removed=median_return_delta_if_removed,
            rationale="shared bucket and wrapper exposure creates duplicate exposure",
        )
    low_contribution_members = [
        item
        for item in items
        if weight_map.get(_text(item.get("primary_product_id")), 0.0) <= 0.15
    ]
    if low_contribution_members:
        product_ids = [_text(item.get("primary_product_id")) for item in low_contribution_members if _text(item.get("primary_product_id"))]
        group_ids = {product_id for product_id in product_ids if product_id}
        counterfactual_result = _run_counterfactual_probability_result(
            probability_engine_input=probability_engine_input,
            removed_product_ids=group_ids,
        )
        counterfactual_summaries = _scenario_summaries_from_probability_output(
            _obj(counterfactual_result.get("output")) if counterfactual_result else None
        )
        success_delta_if_removed, terminal_mean_delta_if_removed, drawdown_delta_if_removed, median_return_delta_if_removed = _aggregate_counterfactual_deltas(
            baseline_summaries=baseline_summaries,
            counterfactual_summaries=counterfactual_summaries,
        )
        group_explanations["limited_contribution_group"] = _group_explanation(
            group_type="limited_contribution_group",
            product_ids=product_ids,
            success_delta_if_removed=success_delta_if_removed,
            terminal_mean_delta_if_removed=terminal_mean_delta_if_removed,
            drawdown_delta_if_removed=drawdown_delta_if_removed,
            median_return_delta_if_removed=median_return_delta_if_removed,
            rationale="products with small weight shares contribute limited standalone portfolio impact",
        )

    return {
        "bucket_construction_explanations": _execution_plan_bucket_explanations(execution_plan),
        "product_explanations": product_explanations,
        "product_group_explanations": group_explanations,
    }
