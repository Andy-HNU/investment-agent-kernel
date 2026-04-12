from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from probability_engine.contracts import (
    FailureArtifact,
    ProbabilityDisclosurePayload,
    ProbabilityEngineOutput,
    ProbabilityEngineRunResult,
    ScenarioComparisonResult,
)
from probability_engine.challengers import (
    run_challenger_bootstrap,
)
from probability_engine.disclosure_bridge import DisclosureEvidenceSpec, assemble_probability_run_result
from probability_engine.path_generator import (
    DailyEngineRuntimeInput,
    probability_engine_confidence_level,
    simulate_primary_paths,
)
from probability_engine.pressure import build_deteriorated_runtime_input, compute_market_pressure_snapshot
from probability_engine.recipes import primary_recipe, resolve_recipes


_SCENARIO_LABELS = {
    "historical_replay": "历史回测",
    "current_market": "当前市场延续",
    "deteriorated_mild": "若市场轻度恶化",
    "deteriorated_moderate": "若市场中度恶化",
    "deteriorated_severe": "若市场重度恶化",
}


def _calendar_month_distance(start_date: str, end_date: str) -> int:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    start_year, start_month = start.year, start.month
    end_year, end_month = end.year, end.month
    return (end_year - start_year) * 12 + (end_month - start_month)


def _compatible_horizon_months(runtime_input: DailyEngineRuntimeInput) -> set[int]:
    step_dates = runtime_input.trading_step_dates()
    base_month_distance = 0 if not step_dates else _calendar_month_distance(runtime_input.as_of, step_dates[-1])
    compatible = {base_month_distance}
    if step_dates:
        compatible.add(base_month_distance + 1)
    return compatible


def _validate_task4_formal_success_event(runtime_input: DailyEngineRuntimeInput) -> None:
    success_event = runtime_input.success_event_spec
    failures: list[str] = []
    if int(runtime_input.path_horizon_days) <= 0:
        failures.append("path_horizon_days must be positive for formal Task 4 runs")
    required_values = {
        "target_type": "goal_amount",
        "success_logic": "joint_target_and_drawdown",
        "return_basis": "nominal",
        "fee_basis": "net",
    }
    for field_name, expected in required_values.items():
        actual = getattr(success_event, field_name)
        if actual != expected:
            failures.append(f"success_event_spec.{field_name} must be '{expected}'")
    if success_event.benchmark_ref is not None:
        failures.append("success_event_spec.benchmark_ref must be null")
    if int(success_event.horizon_days) != int(runtime_input.path_horizon_days):
        failures.append("success_event_spec.horizon_days must match path_horizon_days")
    if int(success_event.horizon_months) not in _compatible_horizon_months(runtime_input):
        failures.append(
            "success_event_spec.horizon_months conflicts with the realized trading calendar horizon"
        )
    if failures:
        raise ValueError("; ".join(failures))


def _published_disclosure_level(run_outcome_status: str) -> str:
    return "point_and_range" if run_outcome_status == "success" else "range_only"


def _published_point(run_outcome_status: str, success_probability: float) -> float | None:
    if run_outcome_status != "success":
        return None
    return float(success_probability)


def _resolve_outcome(runtime_input: DailyEngineRuntimeInput) -> tuple[str, str]:
    confidence_level = probability_engine_confidence_level(runtime_input)
    if confidence_level == "low":
        return "degraded", "degraded_formal_result"
    return "success", "formal_strict_result"


def _base_disclosure_payload(
    primary_result: Any,
    *,
    run_outcome_status: str,
    confidence_level: str,
) -> ProbabilityDisclosurePayload:
    return ProbabilityDisclosurePayload(
        published_point=_published_point(run_outcome_status, primary_result.success_probability),
        published_range=tuple(primary_result.success_probability_range),
        disclosure_level=_published_disclosure_level(run_outcome_status),
        confidence_level=confidence_level,
        challenger_gap=None,
        stress_gap=None,
        gap_total=0.0,
        widening_method="wilson_plus_gap_total",
    )


def _aligned_observed_history(runtime_input: DailyEngineRuntimeInput) -> tuple[list[list[float]], list[str], str]:
    matrix = runtime_input.observed_history_matrix()
    if matrix is None:
        raise ValueError("observed_daily_returns are required for live challenger bootstrap")
    labels = [str(item).strip() for item in list(runtime_input.observed_regime_labels) if str(item).strip()]
    if not labels:
        raise ValueError("observed_regime_labels are required for live challenger bootstrap")
    if len(labels) != len(matrix[0]):
        raise ValueError("observed_regime_labels must align with observed_daily_returns")
    product_ids = [position.product_id for position in runtime_input.current_positions]
    matrix_by_product = {product.product_id: list(product.observed_daily_returns) for product in runtime_input.products}
    aligned_matrix: list[list[float]] = []
    for product_id in product_ids:
        series = matrix_by_product.get(product_id)
        if not series:
            raise ValueError(f"missing observed_daily_returns for product '{product_id}'")
        if len(series) != len(labels):
            raise ValueError("observed_daily_returns must align across products")
        aligned_matrix.append([float(value) for value in series])
    current_regime = str(runtime_input.observed_current_regime or labels[-1]).strip() or labels[-1]
    return aligned_matrix, labels, current_regime


def _observed_weight_adjusted_coverage(runtime_input: DailyEngineRuntimeInput, history_matrix: list[list[float]]) -> float:
    if not history_matrix or not runtime_input.current_positions:
        return 0.0
    weights_by_product = {
        position.product_id: max(float(position.weight), 0.0)
        for position in runtime_input.current_positions
    }
    total_weight = sum(weights_by_product.values())
    if total_weight <= 0.0:
        total_weight = float(len(runtime_input.current_positions))
    if total_weight <= 0.0:
        return 0.0
    coverage = 0.0
    for index, product in enumerate(runtime_input.products):
        row = history_matrix[index] if index < len(history_matrix) else []
        weight = weights_by_product.get(product.product_id, 0.0)
        has_observed_history = 1.0 if row else 0.0
        coverage += weight * has_observed_history
    return max(0.0, min(1.0, coverage / total_weight))


def _minimum_observed_history_days(history_matrix: list[list[float]]) -> int:
    positive_lengths = [len(row) for row in history_matrix if row]
    if not positive_lengths:
        return 0
    return min(positive_lengths)


def _distribution_readiness_from_runtime(
    *,
    primary_result: Any,
    observed_coverage: float,
    product_count: int,
    minimum_observed_history_days: int,
) -> str:
    sample_count = int(getattr(primary_result, "sample_count", 0))
    ready_threshold = max(32, int(product_count) * 8)
    partial_threshold = max(8, int(product_count) * 2)
    if (
        observed_coverage >= 0.95
        and minimum_observed_history_days >= 126
        and sample_count >= ready_threshold
    ):
        return "ready"
    if (
        observed_coverage >= 0.60
        and minimum_observed_history_days >= 40
        and sample_count >= partial_threshold
    ):
        return "partial"
    return "not_ready"


def _calibration_quality_from_primary_result(primary_result: Any) -> str:
    sample_count = int(getattr(primary_result, "sample_count", 0))
    if sample_count >= 256:
        return "strong"
    if sample_count >= 32:
        return "acceptable"
    return "weak"


def _execution_policy_from_runtime(
    *,
    factor_mapping_confidence: str,
    distribution_readiness: str,
    calibration_quality: str,
) -> str:
    if (
        factor_mapping_confidence == "high"
        and distribution_readiness == "ready"
        and calibration_quality in {"acceptable", "strong"}
    ):
        return "FORMAL_STRICT"
    return "FORMAL_ESTIMATION_ALLOWED"


def _challenger_bootstrap_available(labels: list[str], current_regime: str, block_size: int) -> bool:
    normalized_current = str(current_regime).strip()
    if not normalized_current or len(labels) < 2 * int(block_size):
        return False
    last_start = len(labels) - int(block_size) + 1
    return any(labels[start] == normalized_current for start in range(0, max(last_start, 0)))


def _run_live_challenger(
    runtime_input: DailyEngineRuntimeInput,
    *,
    history_matrix: list[list[float]],
    labels: list[str],
    current_regime: str,
    block_size: int,
    path_count: int,
):
    if not _challenger_bootstrap_available(labels, current_regime, block_size):
        return None
    try:
        return run_challenger_bootstrap(
            history_matrix=history_matrix,
            regime_labels=labels,
            current_regime=current_regime,
            block_size=block_size,
            path_count=path_count,
            horizon_days=int(runtime_input.path_horizon_days),
            success_event_spec=runtime_input.success_event_spec,
            current_positions=runtime_input.current_positions,
            initial_portfolio_value=sum(float(position.market_value) for position in runtime_input.current_positions),
            contribution_schedule=runtime_input.contribution_schedule,
            withdrawal_schedule=runtime_input.withdrawal_schedule,
            rebalancing_policy=runtime_input.rebalancing_policy,
            step_dates=runtime_input.trading_step_dates(),
            random_seed=int(runtime_input.random_seed),
        ).result
    except ValueError as exc:
        if "no regime-conditioned challenger blocks are available" in str(exc):
            return None
        raise


def _stress_recipe_for_level(primary_recipe: Any, *, level: str, path_count: int):
    return replace(
        primary_recipe,
        recipe_name=f"stress_deteriorated_{level}_v1",
        role="stress",
        path_count=path_count,
    )


def _run_deteriorated_stress_ladder(
    runtime_input: DailyEngineRuntimeInput,
    *,
    primary_recipe: Any,
    path_count: int,
):
    stress_results: list[Any] = []
    scenario_entries: list[tuple[str, Any, Any]] = []
    for level, scenario_kind in (
        ("mild", "deteriorated_mild"),
        ("moderate", "deteriorated_moderate"),
        ("severe", "deteriorated_severe"),
    ):
        deteriorated_runtime = build_deteriorated_runtime_input(runtime_input, level=level)
        stress_recipe = _stress_recipe_for_level(primary_recipe, level=level, path_count=path_count)
        stress_result = simulate_primary_paths(deteriorated_runtime, stress_recipe)
        pressure = compute_market_pressure_snapshot(deteriorated_runtime, scenario_kind=scenario_kind)
        stress_results.append(stress_result)
        scenario_entries.append((scenario_kind, pressure, stress_result))
    return stress_results, scenario_entries


def _portfolio_return_series(runtime_input: DailyEngineRuntimeInput, history_matrix: list[list[float]]) -> list[float]:
    weights_by_product = {
        position.product_id: float(position.weight)
        for position in runtime_input.current_positions
    }
    product_ids = [position.product_id for position in runtime_input.current_positions]
    total_weight = sum(max(weight, 0.0) for weight in weights_by_product.values())
    if total_weight <= 0.0:
        normalized_weights = {product_id: 1.0 / max(len(product_ids), 1) for product_id in product_ids}
    else:
        normalized_weights = {
            product_id: max(weights_by_product.get(product_id, 0.0), 0.0) / total_weight
            for product_id in product_ids
        }
    series_length = len(history_matrix[0]) if history_matrix else 0
    portfolio_returns: list[float] = []
    for day_index in range(series_length):
        portfolio_returns.append(
            sum(
                float(history_matrix[row_index][day_index]) * float(normalized_weights.get(product_id, 0.0))
                for row_index, product_id in enumerate(product_ids)
            )
        )
    return portfolio_returns


def run_probability_engine(sim_input: Any) -> ProbabilityEngineRunResult:
    evidence_ref = None
    if isinstance(sim_input, dict):
        evidence_ref = sim_input.get("evidence_bundle_ref")
    try:
        runtime_input = DailyEngineRuntimeInput.from_any(sim_input)
        recipes = resolve_recipes(runtime_input.recipes)
        selected_recipe = primary_recipe(recipes)
        _validate_task4_formal_success_event(runtime_input)
        primary_result = simulate_primary_paths(runtime_input, selected_recipe)
        confidence_level = probability_engine_confidence_level(runtime_input)
        history_matrix, labels, current_regime = _aligned_observed_history(runtime_input)
        challenger_block_size = 20
        challenger_result = _run_live_challenger(
            runtime_input,
            history_matrix=history_matrix,
            labels=labels,
            current_regime=current_regime,
            block_size=challenger_block_size,
            path_count=int(runtime_input.challenger_path_count or 32),
        )
        current_market_pressure = compute_market_pressure_snapshot(runtime_input, scenario_kind="current_market")
        stress_results, stress_scenarios = _run_deteriorated_stress_ladder(
            runtime_input,
            primary_recipe=selected_recipe,
            path_count=int(runtime_input.stress_path_count or 16),
        )
        observed_coverage = _observed_weight_adjusted_coverage(runtime_input, history_matrix)
        minimum_observed_history_days = _minimum_observed_history_days(history_matrix)
        distribution_readiness = _distribution_readiness_from_runtime(
            primary_result=primary_result,
            observed_coverage=observed_coverage,
            product_count=len(runtime_input.current_positions),
            minimum_observed_history_days=minimum_observed_history_days,
        )
        calibration_quality = _calibration_quality_from_primary_result(primary_result)
        execution_policy = _execution_policy_from_runtime(
            factor_mapping_confidence=confidence_level,
            distribution_readiness=distribution_readiness,
            calibration_quality=calibration_quality,
        )
        evidence = DisclosureEvidenceSpec(
            daily_product_path_available=observed_coverage > 0.0,
            monthly_fallback_used=False,
            bucket_fallback_used=False,
            independent_weight_adjusted_coverage=observed_coverage,
            observed_weight_adjusted_coverage=observed_coverage,
            estimated_weight_adjusted_coverage=max(0.0, 1.0 - observed_coverage),
            factor_mapping_confidence=confidence_level,
            distribution_readiness=distribution_readiness,
            calibration_quality=calibration_quality,
            challenger_available=bool(challenger_result),
            stress_available=bool(stress_results),
            execution_policy=execution_policy,
        )
        scenario_comparison: list[ScenarioComparisonResult] = []
        if challenger_result is not None:
            scenario_comparison.append(
                ScenarioComparisonResult(
                    scenario_kind="historical_replay",
                    label=_SCENARIO_LABELS["historical_replay"],
                    pressure=None,
                    recipe_result=challenger_result,
                )
            )
        scenario_comparison.append(
            ScenarioComparisonResult(
                scenario_kind="current_market",
                label=_SCENARIO_LABELS["current_market"],
                pressure=current_market_pressure,
                recipe_result=primary_result,
            )
        )
        for scenario_kind, pressure, recipe_result in stress_scenarios:
            scenario_comparison.append(
                ScenarioComparisonResult(
                    scenario_kind=scenario_kind,
                    label=_SCENARIO_LABELS[scenario_kind],
                    pressure=pressure,
                    recipe_result=recipe_result,
                )
            )
        assembled = assemble_probability_run_result(
            primary=primary_result,
            challengers=[challenger_result] if challenger_result is not None else [],
            stresses=stress_results,
            evidence=evidence,
            current_market_pressure=current_market_pressure,
            scenario_comparison=scenario_comparison,
        )
        if assembled.output is None:
            return assembled
        assembled_output = assembled.output
        evidence_refs = list(assembled_output.evidence_refs)
        if runtime_input.evidence_bundle_ref:
            evidence_refs.append(runtime_input.evidence_bundle_ref)
        assembled_output = ProbabilityEngineOutput(
            primary_result=assembled_output.primary_result,
            challenger_results=assembled_output.challenger_results,
            stress_results=assembled_output.stress_results,
            model_disagreement=assembled_output.model_disagreement,
            probability_disclosure_payload=assembled_output.probability_disclosure_payload,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            current_market_pressure=assembled_output.current_market_pressure,
            scenario_comparison=assembled_output.scenario_comparison,
        )
        return ProbabilityEngineRunResult(
            run_outcome_status=assembled.run_outcome_status,
            resolved_result_category=assembled.resolved_result_category,
            output=assembled_output,
            failure_artifact=None,
        )
    except Exception as exc:
        return ProbabilityEngineRunResult(
            run_outcome_status="failure",
            resolved_result_category="null",
            output=None,
            failure_artifact=FailureArtifact(
                failure_stage="probability_engine",
                failure_code="primary_daily_engine_failed",
                message=str(exc),
                diagnostic_refs=[str(evidence_ref)] if evidence_ref else [],
                trustworthy_partial_diagnostics=False,
            ),
        )
