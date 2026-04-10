from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from probability_engine.contracts import PathStatsSummary, RecipeSimulationResult, SuccessEventSpec
from probability_engine.portfolio_policy import CurrentPosition, PortfolioState, initialize_portfolio_state
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
        if block and block[0] == current:
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


def _portfolio_state_from_positions(
    *,
    num_products: int,
    portfolio_weights: list[float] | None,
    current_positions: list[CurrentPosition | dict[str, Any]] | None,
    initial_portfolio_value: float | None,
) -> tuple[PortfolioState, list[str], list[float], float]:
    if current_positions is not None:
        if len(current_positions) != num_products:
            raise ValueError("current_positions must align with the history_matrix rows")
        normalized_positions = [CurrentPosition.from_any(position) for position in current_positions]
        state = initialize_portfolio_state(normalized_positions)
        effective_initial_value = float(state.net_value)
        if initial_portfolio_value is not None and not np.isclose(
            float(initial_portfolio_value),
            effective_initial_value,
            rtol=1e-9,
            atol=1e-9,
        ):
            raise ValueError("initial_portfolio_value must match the net value implied by current_positions")
        product_ids = [position.product_id for position in normalized_positions]
        weights = [float(state.current_weights().get(product_id, 0.0)) for product_id in product_ids]
        return state, product_ids, weights, effective_initial_value

    effective_initial_value = 1.0 if initial_portfolio_value is None else float(initial_portfolio_value)
    if portfolio_weights is None:
        weights = [1.0 / float(num_products)] * num_products
    else:
        weights = [max(0.0, float(value)) for value in list(portfolio_weights)]
        if len(weights) != num_products:
            raise ValueError("portfolio_weights must align with the history_matrix rows")
        total = sum(weights)
        if total <= 0.0:
            weights = [1.0 / float(num_products)] * num_products
        else:
            weights = [weight / total for weight in weights]

    product_ids = [f"product_{index}" for index in range(num_products)]
    synthetic_positions = [
        CurrentPosition(
            product_id=product_id,
            units=0.0,
            market_value=effective_initial_value * float(weight),
            weight=float(weight),
            cost_basis=None,
            tradable=True,
        )
        for product_id, weight in zip(product_ids, weights, strict=True)
    ]
    state = initialize_portfolio_state(synthetic_positions)
    normalized_weights = [float(state.current_weights().get(product_id, 0.0)) for product_id in product_ids]
    return state, product_ids, normalized_weights, effective_initial_value


def _portfolio_daily_returns(
    *,
    block: np.ndarray,
    portfolio_state: PortfolioState,
    product_ids: list[str],
) -> tuple[PortfolioState, list[float]]:
    daily_returns: list[float] = []
    for day_index in range(block.shape[1]):
        product_returns = {product_ids[row_index]: float(block[row_index, day_index]) for row_index in range(block.shape[0])}
        previous_value = portfolio_state.net_value
        portfolio_state = portfolio_state.after_returns(product_returns)
        if previous_value <= 0.0:
            daily_returns.append(0.0)
        else:
            daily_returns.append(float(portfolio_state.net_value / previous_value - 1.0))
    return portfolio_state, daily_returns


def _build_path_returns(
    *,
    matrix: np.ndarray,
    labels: list[str],
    current_regime: str,
    block_size: int,
    horizon_days: int,
    rng: np.random.Generator,
    portfolio_state: PortfolioState,
    product_ids: list[str],
) -> tuple[list[float], list[int], list[str]]:
    selected_block_starts: list[int] = []
    selected_block_regimes: list[str] = []
    path_returns: list[float] = []
    regime_cursor = str(current_regime).strip()

    while len(path_returns) < horizon_days:
        candidate_starts = _eligible_block_starts(labels, regime_cursor, block_size)
        if not candidate_starts:
            raise ValueError(f"no regime-conditioned challenger blocks are available for regime '{regime_cursor}'")
        start = int(rng.choice(candidate_starts))
        selected_block_starts.append(start)
        selected_block_regimes.append(regime_cursor)
        block = matrix[:, start : start + block_size]
        portfolio_state, block_returns = _portfolio_daily_returns(
            block=block,
            portfolio_state=portfolio_state,
            product_ids=product_ids,
        )
        path_returns.extend(block_returns)
        regime_cursor = labels[start + block_size - 1]

    return path_returns[:horizon_days], selected_block_starts, selected_block_regimes


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
class ChallengerBootstrapDiagnostics:
    result: RecipeSimulationResult
    block_size: int
    current_regime: str
    candidate_block_count: int
    portfolio_weights: tuple[float, ...]
    selected_block_starts_by_path: list[list[int]]
    selected_block_regimes_by_path: list[list[str]]


def run_challenger_bootstrap(
    *,
    history_matrix: list[list[float]],
    regime_labels: list[str],
    current_regime: str,
    block_size: int = 20,
    path_count: int = 2000,
    horizon_days: int = 20,
    success_event_spec: SuccessEventSpec,
    portfolio_weights: list[float] | None = None,
    current_positions: list[CurrentPosition | dict[str, Any]] | None = None,
    initial_portfolio_value: float | None = None,
    random_seed: int = 17,
    recipe: SimulationRecipe | None = None,
) -> ChallengerBootstrapDiagnostics:
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

    initial_state, product_ids, normalized_weights, effective_initial_value = _portfolio_state_from_positions(
        num_products=matrix.shape[0],
        portfolio_weights=portfolio_weights,
        current_positions=current_positions,
        initial_portfolio_value=None if initial_portfolio_value is None else float(initial_portfolio_value),
    )
    candidate_starts = _eligible_block_starts(labels, current_regime, int(block_size))
    if not candidate_starts:
        raise ValueError("no regime-conditioned challenger blocks are available")

    rng = np.random.default_rng(int(random_seed))
    path_results: list[tuple[float, float, float, bool]] = []
    selected_block_starts_by_path: list[list[int]] = []
    selected_block_regimes_by_path: list[list[str]] = []
    for path_index in range(int(path_count)):
        portfolio_state = initial_state
        path_returns, selected_block_starts, selected_block_regimes = _build_path_returns(
            matrix=matrix,
            labels=labels,
            current_regime=current_regime,
            block_size=int(block_size),
            horizon_days=int(horizon_days),
            rng=rng,
            portfolio_state=portfolio_state,
            product_ids=product_ids,
        )
        selected_block_starts_by_path.append(selected_block_starts)
        selected_block_regimes_by_path.append(selected_block_regimes)
        path_results.append(
            _simulate_path(
                np.asarray(path_returns, dtype=float),
                initial_value=effective_initial_value,
                success_event_spec=success_event_spec,
            )
        )

    summary = _summarize_paths(
        recipe=candidate_recipe,
        path_results=path_results,
        calibration_link_ref=f"challenger://{candidate_recipe.recipe_name}",
    )
    return ChallengerBootstrapDiagnostics(
        result=summary,
        block_size=int(block_size),
        current_regime=str(current_regime).strip(),
        candidate_block_count=len(candidate_starts),
        portfolio_weights=tuple(normalized_weights),
        selected_block_starts_by_path=selected_block_starts_by_path,
        selected_block_regimes_by_path=selected_block_regimes_by_path,
    )


def build_stress_recipe_result(
    *,
    stressed_path_returns: list[list[float]],
    success_event_spec: SuccessEventSpec,
    initial_portfolio_value: float | None = None,
    recipe: SimulationRecipe | None = None,
) -> RecipeSimulationResult:
    candidate_recipe = recipe or STRESS_RECIPE_V14
    if candidate_recipe.role != "stress":
        raise ValueError("stress recipe result requires a stress recipe")
    if not stressed_path_returns:
        raise ValueError("stressed_path_returns must not be empty")
    if initial_portfolio_value is None:
        if float(success_event_spec.target_value) > 2.0:
            raise ValueError("initial_portfolio_value is required for non-normalized stress targets")
        effective_initial_value = 1.0
    else:
        effective_initial_value = float(initial_portfolio_value)

    path_results = [
        _simulate_path(
            np.asarray(path_returns, dtype=float),
            initial_value=effective_initial_value,
            success_event_spec=success_event_spec,
        )
        for path_returns in stressed_path_returns
    ]
    summary = _summarize_paths(
        recipe=candidate_recipe,
        path_results=path_results,
        calibration_link_ref="stress://explicit_stress_paths",
    )
    return summary
