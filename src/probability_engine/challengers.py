from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from probability_engine.contracts import PathStatsSummary, RecipeSimulationResult, SuccessEventSpec
from probability_engine.recipes import SimulationRecipe


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _annualized_cagr(initial_value: float, terminal_value: float, horizon_days: int) -> float:
    if initial_value <= 0.0 or terminal_value <= 0.0 or horizon_days <= 0:
        return -1.0
    return float((terminal_value / initial_value) ** (252.0 / horizon_days) - 1.0)


def _wilson_interval(success_count: int, total_count: int, z_score: float = 1.96) -> tuple[float, float]:
    if total_count <= 0:
        return (0.0, 0.0)
    probability = float(success_count) / float(total_count)
    z_squared = float(z_score**2)
    denominator = 1.0 + (z_squared / float(total_count))
    center = (probability + (z_squared / (2.0 * float(total_count)))) / denominator
    margin = (
        z_score
        * np.sqrt((probability * (1.0 - probability) + (z_squared / (4.0 * float(total_count)))) / float(total_count))
        / denominator
    )
    return (_clamp_probability(center - margin), _clamp_probability(center + margin))


def _quantile(values: np.ndarray, level: float) -> float:
    return float(np.quantile(values, level))


def _normalized_rows(history_matrix: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(history_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("history_matrix must be a 2D matrix")
    if matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("history_matrix must not be empty")
    return matrix


def _eligible_block_starts(regime_labels: list[str], current_regime: str, block_size: int) -> list[int]:
    labels = [str(label).strip() for label in list(regime_labels)]
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if len(labels) < block_size:
        return []
    current = str(current_regime).strip()
    starts: list[int] = []
    for start in range(0, len(labels) - block_size + 1):
        block = labels[start : start + block_size]
        if all(label == current for label in block):
            starts.append(start)
    return starts


def _simulate_path(
    sampled_returns: np.ndarray,
    *,
    initial_value: float,
    success_event_spec: SuccessEventSpec,
) -> tuple[float, float, float, bool]:
    net_value = float(initial_value)
    peak_value = float(initial_value)
    max_drawdown = 0.0
    for daily_return in sampled_returns.tolist():
        net_value *= max(0.0, 1.0 + float(daily_return))
        peak_value = max(peak_value, net_value)
        if peak_value > 0.0:
            max_drawdown = max(max_drawdown, 1.0 - (net_value / peak_value))
    success = net_value >= float(success_event_spec.target_value)
    if success_event_spec.drawdown_constraint is not None:
        success = success and max_drawdown <= float(success_event_spec.drawdown_constraint)
    cagr = _annualized_cagr(initial_value, net_value, max(len(sampled_returns), 1))
    return net_value, cagr, max_drawdown, success


def _summarize_paths(
    *,
    recipe: SimulationRecipe,
    path_results: list[tuple[float, float, float, bool]],
    calibration_link_ref: str | None,
) -> RecipeSimulationResult:
    terminal_values = np.asarray([item[0] for item in path_results], dtype=float)
    cagrs = np.asarray([item[1] for item in path_results], dtype=float)
    drawdowns = np.asarray([item[2] for item in path_results], dtype=float)
    successes = np.asarray([1.0 if item[3] else 0.0 for item in path_results], dtype=float)
    success_count = int(np.sum(successes))
    success_probability = float(success_count / max(len(path_results), 1))
    success_range = _wilson_interval(success_count, len(path_results))
    return RecipeSimulationResult(
        recipe_name=recipe.recipe_name,
        role=recipe.role,
        success_probability=success_probability,
        success_probability_range=success_range,
        cagr_range=(_quantile(cagrs, 0.05), _quantile(cagrs, 0.95)),
        drawdown_range=(_quantile(drawdowns, 0.05), _quantile(drawdowns, 0.95)),
        sample_count=len(path_results),
        path_stats=PathStatsSummary(
            terminal_value_mean=float(np.mean(terminal_values)),
            terminal_value_p05=_quantile(terminal_values, 0.05),
            terminal_value_p50=_quantile(terminal_values, 0.50),
            terminal_value_p95=_quantile(terminal_values, 0.95),
            cagr_p05=_quantile(cagrs, 0.05),
            cagr_p50=_quantile(cagrs, 0.50),
            cagr_p95=_quantile(cagrs, 0.95),
            max_drawdown_p05=_quantile(drawdowns, 0.05),
            max_drawdown_p50=_quantile(drawdowns, 0.50),
            max_drawdown_p95=_quantile(drawdowns, 0.95),
            success_count=success_count,
            path_count=len(path_results),
        ),
        calibration_link_ref=calibration_link_ref,
    )


CHALLENGER_RECIPE_V14 = SimulationRecipe(
    recipe_name="challenger_regime_conditioned_block_bootstrap_v1",
    role="challenger",
    innovation_layer="regime_conditioned_empirical",
    volatility_layer="bootstrap_reconstructed",
    dependency_layer="shared_time_slice",
    jump_layer="history_carry_forward",
    regime_layer="filtered_block_bootstrap",
    estimation_basis="regime_conditioned_block_bootstrap",
    dependency_scope="product_aligned",
    path_count=2000,
)

STRESS_RECIPE_V14 = SimulationRecipe(
    recipe_name="stress_downside_tail_v1",
    role="stress",
    innovation_layer="student_t",
    volatility_layer="stress_amplified",
    dependency_layer="factor_level_dcc",
    jump_layer="systemic_plus_idio_stressed",
    regime_layer="markov_regime_stressed",
    estimation_basis="stress_tail_overlay",
    dependency_scope="factor",
    path_count=2000,
)


@dataclass(frozen=True)
class ChallengerBootstrapResult:
    recipe: SimulationRecipe
    success_probability: float
    path_stats: PathStatsSummary
    block_size: int
    current_regime: str
    candidate_block_count: int

    def to_recipe_result(self) -> RecipeSimulationResult:
        return RecipeSimulationResult(
            recipe_name=self.recipe.recipe_name,
            role=self.recipe.role,
            success_probability=self.success_probability,
            success_probability_range=_wilson_interval(
                self.path_stats.success_count,
                self.path_stats.path_count,
            ),
            cagr_range=(self.path_stats.cagr_p05, self.path_stats.cagr_p95),
            drawdown_range=(self.path_stats.max_drawdown_p05, self.path_stats.max_drawdown_p95),
            sample_count=self.path_stats.path_count,
            path_stats=self.path_stats,
            calibration_link_ref=f"challenger://{self.recipe.recipe_name}",
        )


def run_challenger_bootstrap(
    *,
    history_matrix: list[list[float]],
    regime_labels: list[str],
    current_regime: str,
    block_size: int = 20,
    path_count: int = 2000,
    horizon_days: int = 20,
    success_event_spec: SuccessEventSpec,
    random_seed: int = 17,
    recipe: SimulationRecipe | None = None,
) -> RecipeSimulationResult:
    candidate_recipe = recipe or CHALLENGER_RECIPE_V14
    if candidate_recipe.role != "challenger":
        raise ValueError("challenger bootstrap requires a challenger recipe")
    matrix = _normalized_rows(history_matrix)
    labels = [str(label).strip() for label in list(regime_labels)]
    if matrix.shape[1] != len(labels):
        raise ValueError("regime_labels must align with the history_matrix columns")
    if int(block_size) <= 0:
        raise ValueError("block_size must be positive")
    if int(path_count) <= 0:
        raise ValueError("path_count must be positive")
    if int(horizon_days) <= 0:
        raise ValueError("horizon_days must be positive")
    if matrix.shape[1] < 2 * int(block_size):
        raise ValueError("history is too short for challenger bootstrap")

    candidate_starts = _eligible_block_starts(labels, current_regime, int(block_size))
    if not candidate_starts:
        raise ValueError("no regime-conditioned challenger blocks are available")

    rng = np.random.default_rng(int(random_seed))
    path_results: list[tuple[float, float, float, bool]] = []
    for _ in range(int(path_count)):
        sampled_returns: list[np.ndarray] = []
        while sum(block.shape[1] for block in sampled_returns) < int(horizon_days):
            start = int(rng.choice(candidate_starts))
            sampled_returns.append(matrix[:, start : start + int(block_size)])
        sampled_matrix = np.concatenate(sampled_returns, axis=1)[:, : int(horizon_days)]
        aggregated_returns = sampled_matrix.mean(axis=0)
        path_results.append(
            _simulate_path(
                aggregated_returns,
                initial_value=1.0,
                success_event_spec=success_event_spec,
            )
        )

    summary = _summarize_paths(
        recipe=candidate_recipe,
        path_results=path_results,
        calibration_link_ref=f"challenger://{candidate_recipe.recipe_name}",
    )
    return ChallengerBootstrapResult(
        recipe=candidate_recipe,
        success_probability=summary.success_probability,
        path_stats=summary.path_stats,
        block_size=int(block_size),
        current_regime=str(current_regime).strip(),
        candidate_block_count=len(candidate_starts),
    ).to_recipe_result()


@dataclass(frozen=True)
class StressRecipeResult:
    recipe: SimulationRecipe
    source_recipe_name: str
    stress_factor: float
    success_probability: float
    path_stats: PathStatsSummary

    def to_recipe_result(self) -> RecipeSimulationResult:
        return RecipeSimulationResult(
            recipe_name=self.recipe.recipe_name,
            role=self.recipe.role,
            success_probability=self.success_probability,
            success_probability_range=_wilson_interval(
                self.path_stats.success_count,
                self.path_stats.path_count,
            ),
            cagr_range=(self.path_stats.cagr_p05, self.path_stats.cagr_p95),
            drawdown_range=(self.path_stats.max_drawdown_p05, self.path_stats.max_drawdown_p95),
            sample_count=self.path_stats.path_count,
            path_stats=self.path_stats,
            calibration_link_ref=f"stress://{self.source_recipe_name}",
        )


def build_stress_recipe_result(
    primary_result: RecipeSimulationResult,
    *,
    recipe: SimulationRecipe | None = None,
    stress_factor: float = 0.92,
) -> RecipeSimulationResult:
    candidate_recipe = recipe or STRESS_RECIPE_V14
    if candidate_recipe.role != "stress":
        raise ValueError("stress recipe result requires a stress recipe")
    stress_factor = float(stress_factor)
    if not 0.0 < stress_factor < 1.0:
        raise ValueError("stress_factor must be between 0 and 1")

    source_range = tuple(primary_result.success_probability_range)
    probability_drop = max(0.04, (source_range[1] - source_range[0]) * 0.5)
    stressed_probability = _clamp_probability(primary_result.success_probability - probability_drop)
    stressed_range = (
        _clamp_probability(source_range[0] * stress_factor),
        _clamp_probability(max(source_range[0] * stress_factor, source_range[1] - probability_drop)),
    )

    stressed_path_stats = PathStatsSummary(
        terminal_value_mean=float(primary_result.path_stats.terminal_value_mean * stress_factor),
        terminal_value_p05=float(primary_result.path_stats.terminal_value_p05 * (stress_factor - 0.02)),
        terminal_value_p50=float(primary_result.path_stats.terminal_value_p50 * stress_factor),
        terminal_value_p95=float(primary_result.path_stats.terminal_value_p95 * (stress_factor + 0.01)),
        cagr_p05=float(primary_result.path_stats.cagr_p05 - 0.03),
        cagr_p50=float(primary_result.path_stats.cagr_p50 - 0.02),
        cagr_p95=float(primary_result.path_stats.cagr_p95 - 0.01),
        max_drawdown_p05=_clamp_probability(primary_result.path_stats.max_drawdown_p05 * 1.10),
        max_drawdown_p50=_clamp_probability(primary_result.path_stats.max_drawdown_p50 * 1.15),
        max_drawdown_p95=_clamp_probability(primary_result.path_stats.max_drawdown_p95 * 1.20),
        success_count=int(round(stressed_probability * primary_result.sample_count)),
        path_count=primary_result.sample_count,
    )
    stressed_summary = StressRecipeResult(
        recipe=candidate_recipe,
        source_recipe_name=primary_result.recipe_name,
        stress_factor=stress_factor,
        success_probability=stressed_probability,
        path_stats=stressed_path_stats,
    )
    stressed_result = stressed_summary.to_recipe_result()
    return RecipeSimulationResult(
        recipe_name=stressed_result.recipe_name,
        role=stressed_result.role,
        success_probability=stressed_probability,
        success_probability_range=stressed_range,
        cagr_range=(stressed_path_stats.cagr_p05, stressed_path_stats.cagr_p95),
        drawdown_range=(stressed_path_stats.max_drawdown_p05, stressed_path_stats.max_drawdown_p95),
        sample_count=stressed_result.sample_count,
        path_stats=stressed_path_stats,
        calibration_link_ref=stressed_result.calibration_link_ref,
    )
