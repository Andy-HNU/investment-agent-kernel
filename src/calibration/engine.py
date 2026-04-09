from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from calibration.types import (
    BehaviorState,
    CalibrationResult,
    ConstraintState,
    CalibrationSummary,
    EVParams,
    DistributionModelState,
    MarketState,
    ParamVersionMeta,
    ModeResolutionDecision,
    SimulationModeEligibility,
    RuntimeOptimizerParams,
)
from goal_solver.types import (
    DistributionInput,
    GoalSolverParams,
    MarketAssumptions,
    RankingMode,
    SimulationMode,
)
from probability_engine.jumps import JumpStateSpec
from probability_engine.regime import RegimeStateSpec
from probability_engine.volatility import FactorDynamicsSpec
from snapshot_ingestion.historical import build_historical_dataset_snapshot, summarize_historical_dataset
from snapshot_ingestion.types import CompletenessLevel, SnapshotBundle
from snapshot_ingestion.valuation import build_valuation_percentile_results


def _obj(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _stamp(value: Any) -> str:
    return _utc(value).strftime("%Y%m%dT%H%M%SZ")


def _first_text(*values: Any) -> str | None:
    for value in values:
        rendered = str(value or "").strip()
        if rendered:
            return rendered
    return None


def _bundle_dict(bundle: SnapshotBundle | dict[str, Any]) -> dict[str, Any]:
    return _obj(bundle)


def _version_id(prefix: str, created_at: Any) -> str:
    return f"{prefix}_{_stamp(created_at)}"


def _quality_text(value: Any) -> str:
    if isinstance(value, CompletenessLevel):
        return value.value
    if value is None:
        return "full"
    return str(getattr(value, "value", value))


def _severity_domains(bundle_data: dict[str, Any], severity: str) -> list[str]:
    domains: list[str] = []
    for flag in bundle_data.get("quality_summary", []):
        flag_data = _obj(flag)
        if flag_data.get("severity") == severity:
            domain = str(flag_data.get("domain", "")).strip()
            if domain and domain not in domains:
                domains.append(domain)
    return domains


def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _bucket_universe(bundle_data: dict[str, Any]) -> list[str]:
    constraint = _obj(bundle_data.get("constraint", {}))
    boundaries = constraint.get("ips_bucket_boundaries", {})
    if boundaries:
        return list(boundaries.keys())
    account = _obj(bundle_data.get("account", {}))
    weights = account.get("weights", {})
    return list(weights.keys())


def _policy_signal_summary(bundle_data: dict[str, Any]) -> dict[str, Any]:
    signals = list(bundle_data.get("policy_news_signals") or [])
    if not signals:
        return {}
    ordered = sorted(
        (_obj(signal) for signal in signals),
        key=lambda item: (float(item.get("confidence", 0.0) or 0.0), str(item.get("as_of") or "")),
        reverse=True,
    )
    chosen = ordered[0]
    return {
        "policy_regime": chosen.get("policy_regime"),
        "macro_uncertainty": chosen.get("macro_uncertainty"),
        "sentiment_stress": chosen.get("sentiment_stress"),
        "liquidity_stress": chosen.get("liquidity_stress"),
        "manual_review_required": any(bool(_obj(item).get("manual_review_required")) for item in signals),
        "confidence": float(chosen.get("confidence", 0.0) or 0.0),
        "signal_ids": [str(_obj(item).get("signal_id") or "") for item in signals if str(_obj(item).get("signal_id") or "").strip()],
    }


def _historical_dataset_from_bundle(bundle_data: dict[str, Any]):
    market_raw = _obj(bundle_data.get("market", {}))
    historical_seed = market_raw.get("historical_dataset")
    if not historical_seed:
        historical_seed = bundle_data.get("historical_dataset_metadata") or market_raw.get("historical_dataset_metadata")
    if not historical_seed:
        return None
    return build_historical_dataset_snapshot(_obj(historical_seed))


def _aligned_historical_series(dataset: Any, buckets: list[str]) -> tuple[dict[str, list[float]], int]:
    selected = {
        bucket: [float(value) for value in list(dataset.return_series.get(bucket) or [])]
        for bucket in buckets
        if list(dataset.return_series.get(bucket) or [])
    }
    if not selected:
        return {}, 0
    min_len = min(len(series) for series in selected.values())
    if min_len <= 0:
        return {}, 0
    return {bucket: series[-min_len:] for bucket, series in selected.items()}, min_len


def _historical_regime_series(sample_returns: list[float]) -> list[str]:
    if not sample_returns:
        return []
    center = float(np.median(np.asarray(sample_returns, dtype=float)))
    return ["stress" if value <= center else "normal" for value in sample_returns]


def _build_reliability_buckets(
    predicted_probabilities: np.ndarray,
    observed_hits: np.ndarray,
) -> list[dict[str, Any]]:
    bucket_edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    results: list[dict[str, Any]] = []
    for low, high in zip(bucket_edges[:-1], bucket_edges[1:], strict=True):
        if high >= 1.0:
            mask = (predicted_probabilities >= low) & (predicted_probabilities <= 1.0)
            label = f"{low:.1f}-1.0"
        else:
            mask = (predicted_probabilities >= low) & (predicted_probabilities < high)
            label = f"{low:.1f}-{high:.1f}"
        if not np.any(mask):
            continue
        results.append(
            {
                "bucket": label,
                "sample_count": int(np.sum(mask)),
                "predicted_mean": float(np.mean(predicted_probabilities[mask])),
                "observed_hit_rate": float(np.mean(observed_hits[mask])),
            }
        )
    return results


def _build_regime_breakdown(
    sample_returns: list[float],
    predicted_probabilities: np.ndarray,
    observed_hits: np.ndarray,
) -> list[dict[str, Any]]:
    regimes = _historical_regime_series(sample_returns)
    if not regimes:
        return []
    results: list[dict[str, Any]] = []
    for regime in ("normal", "stress"):
        mask = np.asarray([item == regime for item in regimes], dtype=bool)
        if not np.any(mask):
            continue
        results.append(
            {
                "regime": regime,
                "sample_count": int(np.sum(mask)),
                "predicted_mean": float(np.mean(predicted_probabilities[mask])),
                "observed_hit_rate": float(np.mean(observed_hits[mask])),
                "brier_score": float(np.mean((predicted_probabilities[mask] - observed_hits[mask]) ** 2)),
            }
        )
    return results


def _build_distribution_input_from_dataset(dataset: Any | None) -> DistributionInput | None:
    if dataset is None:
        return None
    aligned_series, _sample_count = _aligned_historical_series(dataset, sorted(dataset.return_series))
    if not aligned_series:
        return None
    sample_returns = [
        float(np.mean([series[idx] for series in aligned_series.values()]))
        for idx in range(len(next(iter(aligned_series.values()))))
    ]
    return DistributionInput(
        frequency=str(dataset.frequency or "monthly"),
        historical_return_series=aligned_series,
        regime_series=_historical_regime_series(sample_returns),
        tail_df=7.0 if len(sample_returns) >= 24 else 5.0,
        block_size=max(2, min(6, len(sample_returns) // 12 or 3)),
        source_ref=str(dataset.source_ref or dataset.version_id or dataset.dataset_id),
        audit_window=None if dataset.audit_window is None else dataset.audit_window.to_dict(),
    )


def _current_regime_name(market_state: MarketState) -> str:
    if market_state.risk_environment == "high":
        return "stress"
    if market_state.risk_environment == "elevated":
        return "risk_off"
    return "normal"


def _build_factor_dynamics_spec(
    *,
    bundle_id: str,
    distribution_input: DistributionInput | None,
    market_assumptions: MarketAssumptions,
    historical_dataset: Any | None,
    created_at: Any,
    calibration_quality: str,
) -> FactorDynamicsSpec:
    factor_names = list(market_assumptions.correlation_matrix.keys()) or list(
        (distribution_input.historical_return_series if distribution_input is not None else {}).keys()
    )
    if not factor_names and historical_dataset is not None:
        factor_names = list(dict(getattr(historical_dataset, "return_series", {}) or {}).keys())
    if not factor_names:
        factor_names = [f"factor_{idx + 1}" for idx in range(3)]

    if distribution_input is not None and distribution_input.garch_t_state:
        garch_params_by_factor = {
            factor: {
                "omega": float(
                    state.get("long_run_variance", 1e-4)
                    * max(1.0 - float(state.get("alpha", 0.06)) - float(state.get("beta", 0.90)), 0.01)
                ),
                "alpha": float(state.get("alpha", 0.06)),
                "beta": float(state.get("beta", 0.90)),
                "nu": float(state.get("nu", 7.0)),
                "long_run_variance": float(state.get("long_run_variance", 1e-4)),
            }
            for factor, state in distribution_input.garch_t_state.items()
            if factor in factor_names
        }
    else:
        garch_params_by_factor = {
            factor: {
                "omega": 0.00002,
                "alpha": 0.06,
                "beta": 0.90,
                "nu": 7.0,
                "long_run_variance": float(max(market_assumptions.volatility.get(factor, 0.15) ** 2 / 252.0, 1e-6)),
            }
            for factor in factor_names
        }

    summary_returns: dict[str, float] = {}
    summary_volatility: dict[str, float] = {}
    summary_corr: dict[str, dict[str, float]] = {}
    if historical_dataset is not None:
        summary_returns, summary_volatility, summary_corr = summarize_historical_dataset(historical_dataset, buckets=factor_names)
    if not summary_corr:
        for factor in factor_names:
            summary_corr[factor] = {peer: (1.0 if peer == factor else 0.15) for peer in factor_names}

    long_run_covariance: dict[str, dict[str, float]] = {}
    for factor in factor_names:
        row: dict[str, float] = {}
        for peer in factor_names:
            corr = float(summary_corr.get(factor, {}).get(peer, 1.0 if factor == peer else 0.15))
            vol_a = float(summary_volatility.get(factor, market_assumptions.volatility.get(factor, 0.15)))
            vol_b = float(summary_volatility.get(peer, market_assumptions.volatility.get(peer, 0.15)))
            row[peer] = corr * vol_a * vol_b
        long_run_covariance[factor] = row

    dcc_state = distribution_input.dcc_state if distribution_input is not None else {}
    dcc_params = {
        "alpha": float(dcc_state.get("alpha", 0.04) or 0.04),
        "beta": float(dcc_state.get("beta", 0.93) or 0.93),
    }
    if calibration_quality in {"weak", "insufficient_sample"}:
        covariance_shrinkage = 0.30
    elif calibration_quality == "acceptable":
        covariance_shrinkage = 0.20
    else:
        covariance_shrinkage = 0.12

    if distribution_input is not None and distribution_input.tail_df is not None:
        tail_df = float(distribution_input.tail_df)
    else:
        tail_df = 7.0 if len(factor_names) >= 3 else 5.0
    calibration_window_days = 0
    if distribution_input is not None and distribution_input.historical_return_series:
        calibration_window_days = len(next(iter(distribution_input.historical_return_series.values())))
    elif summary_returns:
        calibration_window_days = len(summary_returns)

    return FactorDynamicsSpec(
        factor_names=factor_names,
        factor_series_ref=f"{bundle_id or 'unknown'}::{_stamp(created_at)}::factor_series",
        innovation_family="student_t" if tail_df < 30 else "gaussian",
        tail_df=tail_df,
        garch_params_by_factor=garch_params_by_factor,
        dcc_params=dcc_params,
        long_run_covariance=long_run_covariance,
        covariance_shrinkage=covariance_shrinkage,
        calibration_window_days=calibration_window_days,
    )


def _build_regime_state_spec(
    *,
    market_state: MarketState,
    calibration_quality: str,
    historical_dataset: Any | None,
) -> RegimeStateSpec:
    current_regime = _current_regime_name(market_state)
    transition_matrix = [
        [0.86, 0.11, 0.03],
        [0.14, 0.72, 0.14],
        [0.06, 0.18, 0.76],
    ]
    if calibration_quality in {"weak", "insufficient_sample"}:
        transition_matrix = [
            [0.82, 0.13, 0.05],
            [0.15, 0.68, 0.17],
            [0.06, 0.24, 0.70],
        ]
    if historical_dataset is not None and len(_portfolio_return_series_from_dataset(historical_dataset)) >= 60:
        transition_matrix[0] = [0.88, 0.09, 0.03]

    return RegimeStateSpec(
        regime_names=["normal", "risk_off", "stress"],
        current_regime=current_regime,
        transition_matrix=transition_matrix,
        regime_mean_adjustments={
            "normal": {"mean_shift": 0.0},
            "risk_off": {"mean_shift": -0.0005},
            "stress": {"mean_shift": -0.0012},
        },
        regime_vol_adjustments={
            "normal": {"volatility_multiplier": 1.0},
            "risk_off": {"volatility_multiplier": 1.15},
            "stress": {"volatility_multiplier": 1.35},
        },
        regime_jump_adjustments={
            "normal": {
                "systemic_jump_probability_multiplier": 1.0,
                "idio_jump_probability_multiplier": 1.0,
                "systemic_jump_dispersion_multiplier": 1.0,
            },
            "risk_off": {
                "systemic_jump_probability_multiplier": 1.3,
                "idio_jump_probability_multiplier": 1.15,
                "systemic_jump_dispersion_multiplier": 1.05,
            },
            "stress": {
                "systemic_jump_probability_multiplier": 1.8,
                "idio_jump_probability_multiplier": 1.30,
                "systemic_jump_dispersion_multiplier": 1.15,
            },
        },
    )


def _build_jump_state_spec(
    *,
    market_state: MarketState,
    factor_dynamics: FactorDynamicsSpec,
    regime_state: RegimeStateSpec,
    historical_dataset: Any | None,
) -> JumpStateSpec:
    diagonal_covariances = [
        float(factor_dynamics.long_run_covariance.get(factor, {}).get(factor, 0.0))
        for factor in factor_dynamics.factor_names
        if factor in factor_dynamics.long_run_covariance
    ]
    avg_factor_variance = sum(max(value, 0.0) for value in diagonal_covariances) / len(diagonal_covariances) if diagonal_covariances else 0.0004
    systemic_jump_probability_1d = 0.012
    if market_state.risk_environment == "elevated":
        systemic_jump_probability_1d = 0.016
    elif market_state.risk_environment == "high":
        systemic_jump_probability_1d = 0.024
    if historical_dataset is not None:
        portfolio_returns = _portfolio_return_series_from_dataset(historical_dataset)
        tail_hits = [abs(value) for value in portfolio_returns if value < -0.02]
        if portfolio_returns:
            systemic_jump_probability_1d = min(
                max(systemic_jump_probability_1d, len(tail_hits) / len(portfolio_returns) * 0.5 + 0.008),
                0.08,
            )
    current_regime_adjustments = regime_state.regime_jump_adjustments.get(regime_state.current_regime, {})
    systemic_jump_probability_1d /= float(current_regime_adjustments.get("systemic_jump_probability_multiplier", 1.0))
    systemic_jump_dispersion = float(
        max(
            0.01,
            min(
                0.08,
                0.5 * np.sqrt(max(avg_factor_variance, 1e-8))
                * float(current_regime_adjustments.get("systemic_jump_dispersion_multiplier", 1.0)),
            ),
        )
    )
    systemic_jump_impact_by_factor = {
        factor: float(-0.35 * np.sqrt(max(factor_dynamics.long_run_covariance.get(factor, {}).get(factor, 0.0), 1e-8)))
        for factor in factor_dynamics.factor_names
    }
    if market_state.risk_environment == "high":
        systemic_jump_impact_by_factor = {factor: value * 1.25 for factor, value in systemic_jump_impact_by_factor.items()}
    idio_jump_profile_by_product = {
        factor: {
            "probability_1d": float(min(0.25, systemic_jump_probability_1d * 1.15)),
            "loss_mean": float(-0.9 * np.sqrt(max(factor_dynamics.long_run_covariance.get(factor, {}).get(factor, 0.0), 1e-8))),
            "loss_std": float(max(0.001, systemic_jump_dispersion * 0.6)),
        }
        for factor in factor_dynamics.factor_names
    }
    return JumpStateSpec(
        systemic_jump_probability_1d=systemic_jump_probability_1d,
        systemic_jump_impact_by_factor=systemic_jump_impact_by_factor,
        systemic_jump_dispersion=systemic_jump_dispersion,
        idio_jump_profile_by_product=idio_jump_profile_by_product,
    )


def _build_probability_engine_state_artifacts(
    *,
    bundle_data: dict[str, Any],
    market_state: MarketState,
    market_assumptions: MarketAssumptions,
    distribution_input: DistributionInput | None,
    historical_dataset: Any | None,
    created_at: Any,
    calibration_quality: str,
    prior_calibration: CalibrationResult | dict[str, Any] | None,
) -> tuple[FactorDynamicsSpec, RegimeStateSpec, JumpStateSpec]:
    prior_data = _obj(prior_calibration or {})
    v14_artifacts = _obj(bundle_data.get("probability_engine_v14") or bundle_data.get("v14_probability_engine") or {})

    factor_dynamics = FactorDynamicsSpec.from_any(prior_data.get("factor_dynamics") or v14_artifacts.get("factor_dynamics"))
    regime_state = RegimeStateSpec.from_any(prior_data.get("regime_state") or v14_artifacts.get("regime_state"))
    jump_state = JumpStateSpec.from_any(prior_data.get("jump_state") or v14_artifacts.get("jump_state"))

    if factor_dynamics is None:
        factor_dynamics = _build_factor_dynamics_spec(
            bundle_id=str(bundle_data.get("bundle_id", "")),
            distribution_input=distribution_input,
            market_assumptions=market_assumptions,
            historical_dataset=historical_dataset,
            created_at=created_at,
            calibration_quality=calibration_quality,
        )
    if regime_state is None:
        regime_state = _build_regime_state_spec(
            market_state=market_state,
            calibration_quality=calibration_quality,
            historical_dataset=historical_dataset,
        )
    if jump_state is None:
        jump_state = _build_jump_state_spec(
            market_state=market_state,
            factor_dynamics=factor_dynamics,
            regime_state=regime_state,
            historical_dataset=historical_dataset,
        )
    return factor_dynamics, regime_state, jump_state


def _default_expected_return(bucket: str) -> float:
    if "bond" in bucket:
        return 0.03
    if "gold" in bucket:
        return 0.025
    if "sat" in bucket:
        return 0.10
    return 0.08


def _default_volatility(bucket: str) -> float:
    if "bond" in bucket:
        return 0.04
    if "gold" in bucket:
        return 0.12
    if "sat" in bucket:
        return 0.22
    return 0.18


def interpret_market_state(bundle: SnapshotBundle | dict[str, Any]) -> MarketState:
    bundle_data = _bundle_dict(bundle)
    market_raw = _obj(bundle_data.get("market", {}))
    created_at = _utc(bundle_data.get("created_at"))
    bundle_id = str(bundle_data.get("bundle_id", ""))
    buckets = _bucket_universe(bundle_data)

    raw_volatility = market_raw.get("raw_volatility", {}) or {}
    avg_vol = 0.0
    if raw_volatility:
        avg_vol = sum(float(value) for value in raw_volatility.values()) / len(raw_volatility)

    if avg_vol >= 0.22:
        risk_environment = "high"
        volatility_regime = "high"
    elif avg_vol >= 0.16:
        risk_environment = "elevated"
        volatility_regime = "high"
    elif avg_vol >= 0.08:
        risk_environment = "moderate"
        volatility_regime = "normal"
    else:
        risk_environment = "low"
        volatility_regime = "low"

    liquidity_scores = market_raw.get("liquidity_scores", {}) or {}
    valuation_z_scores = market_raw.get("valuation_z_scores", {}) or {}
    observed_valuation_inputs = market_raw.get("observed_valuation_inputs") or {}
    liquidity_status: dict[str, str] = {}
    quality_flags: list[str] = []
    policy_summary = _policy_signal_summary(bundle_data) or {}
    historical_metadata = _obj(
        bundle_data.get("historical_dataset_metadata") or _obj(market_raw.get("historical_dataset")) or {}
    )
    valuation_percentile_results = build_valuation_percentile_results(
        buckets=buckets,
        observed_inputs=observed_valuation_inputs,
        valuation_z_scores=valuation_z_scores,
        as_of=created_at.isoformat().replace("+00:00", "Z"),
    )
    valuation_positions: dict[str, str] = {
        bucket: valuation_percentile_results[bucket].valuation_position for bucket in buckets
    }

    for bucket in buckets:
        liq = liquidity_scores.get(bucket)
        if liq is None:
            liquidity_status[bucket] = "normal"
            if "market_liquidity_scores_missing" not in quality_flags:
                quality_flags.append("market_liquidity_scores_missing")
        elif liq <= 0.3:
            liquidity_status[bucket] = "stressed"
        elif liq <= 0.6:
            liquidity_status[bucket] = "tight"
        else:
            liquidity_status[bucket] = "normal"

    if not raw_volatility:
        quality_flags.append("market_volatility_missing")
    if not observed_valuation_inputs:
        quality_flags.append("market_observed_valuation_inputs_missing")
    if not valuation_z_scores:
        quality_flags.append("market_valuation_z_scores_missing")
    if bool(policy_summary.get("manual_review_required")):
        quality_flags.append("policy_signal_manual_review_required")
    if str(policy_summary.get("macro_uncertainty") or "").lower() == "high":
        quality_flags.append("policy_signal_macro_uncertainty_high")
        risk_environment = "high"
        volatility_regime = "high"
    if historical_metadata:
        quality_flags.append("historical_dataset_attached")
    if str(policy_summary.get("liquidity_stress") or "").lower() == "high":
        quality_flags.append("policy_signal_liquidity_stress_high")
        for bucket in buckets:
            liquidity_status[bucket] = "stressed"
    if str(policy_summary.get("sentiment_stress") or "").lower() == "high":
        quality_flags.append("policy_signal_sentiment_stress_high")

    return MarketState(
        as_of=created_at.isoformat().replace("+00:00", "Z"),
        source_bundle_id=bundle_id,
        version=f"market_state_{_stamp(created_at)}",
        risk_environment=risk_environment,
        volatility_regime=volatility_regime,
        liquidity_status=liquidity_status,
        valuation_positions=valuation_positions,
        correlation_spike_alert=bool(
            market_raw.get("correlation_spike_alert", False)
            or str(policy_summary.get("sentiment_stress") or "").lower() == "high"
        ),
        quality_flags=quality_flags,
        is_degraded=not raw_volatility,
        valuation_percentile={bucket: valuation_percentile_results[bucket].percentile for bucket in buckets},
        valuation_percentile_results=valuation_percentile_results,
        liquidity_flag={
            bucket: liquidity_status[bucket] != "normal"
            for bucket in buckets
        },
        policy_regime=policy_summary.get("policy_regime"),
        macro_uncertainty=policy_summary.get("macro_uncertainty"),
        sentiment_stress=policy_summary.get("sentiment_stress"),
        liquidity_stress=policy_summary.get("liquidity_stress"),
        manual_review_required=bool(policy_summary.get("manual_review_required")),
        policy_signal_confidence=float(policy_summary.get("confidence", 0.0) or 0.0),
        policy_signal_ids=list(policy_summary.get("signal_ids") or []),
        historical_dataset_version=_first_text(historical_metadata.get("version_id"), historical_metadata.get("dataset_version")),
        historical_dataset_source=_first_text(historical_metadata.get("source_name"), historical_metadata.get("source_ref")),
    )


def _behavior_penalty(chase_risk: str, panic_risk: str) -> float:
    levels = {"none": 0.0, "low": 0.2, "moderate": 0.5, "high": 1.0}
    return max(levels.get(chase_risk, 0.0), levels.get(panic_risk, 0.0))


def _behavior_state_from_prior(
    prior_behavior: BehaviorState | dict[str, Any],
    created_at: datetime,
    bundle_id: str,
) -> BehaviorState:
    data = _obj(prior_behavior)
    return BehaviorState(
        as_of=created_at.isoformat().replace("+00:00", "Z"),
        source_bundle_id=bundle_id,
        version=f"behavior_state_{_stamp(created_at)}",
        recent_chase_risk=str(data.get("recent_chase_risk", "none")),
        recent_panic_risk=str(data.get("recent_panic_risk", "none")),
        trade_frequency_30d=float(data.get("trade_frequency_30d", 0.0) or 0.0),
        override_count_90d=int(data.get("override_count_90d", 0) or 0),
        cooldown_active=bool(data.get("cooldown_active", False)),
        cooldown_until=data.get("cooldown_until"),
        behavior_penalty_coeff=float(data.get("behavior_penalty_coeff", 0.0) or 0.0),
        recent_chasing_flag=bool(data.get("recent_chasing_flag", False)),
        high_emotion_flag=bool(data.get("high_emotion_flag", False)),
        panic_flag=bool(data.get("panic_flag", False)),
        action_frequency_30d=int(data.get("action_frequency_30d", 0) or 0),
        emotion_score=float(data.get("emotion_score", 0.0) or 0.0),
    )


def interpret_behavior_state(
    bundle: SnapshotBundle | dict[str, Any],
    prior_behavior: BehaviorState | dict[str, Any] | None = None,
) -> tuple[BehaviorState, list[str]]:
    bundle_data = _bundle_dict(bundle)
    behavior_raw = _obj(bundle_data.get("behavior"))
    created_at = _utc(bundle_data.get("created_at"))
    bundle_id = str(bundle_data.get("bundle_id", ""))
    notes: list[str] = []

    if behavior_raw in (None, {}):
        if prior_behavior is not None:
            notes.append("behavior domain missing; prior behavior state reused")
            return _behavior_state_from_prior(prior_behavior, created_at, bundle_id), notes
        notes.append("behavior domain missing; default behavior state applied")
        return (
            BehaviorState(
                as_of=created_at.isoformat().replace("+00:00", "Z"),
                source_bundle_id=bundle_id,
                version=f"behavior_state_{_stamp(created_at)}",
                recent_chase_risk="none",
                recent_panic_risk="none",
                trade_frequency_30d=0.0,
                override_count_90d=0,
                cooldown_active=False,
                cooldown_until=None,
                behavior_penalty_coeff=0.0,
                recent_chasing_flag=False,
                high_emotion_flag=False,
                panic_flag=False,
                action_frequency_30d=0,
                emotion_score=0.0,
            ),
            notes,
        )

    chase_risk = str(behavior_raw.get("recent_chase_risk", "low"))
    panic_risk = str(behavior_raw.get("recent_panic_risk", "none"))
    coeff = _behavior_penalty(chase_risk, panic_risk)
    cooldown_until = behavior_raw.get("cooldown_until")
    return (
        BehaviorState(
            as_of=created_at.isoformat().replace("+00:00", "Z"),
            source_bundle_id=bundle_id,
            version=f"behavior_state_{_stamp(created_at)}",
            recent_chase_risk=chase_risk,
            recent_panic_risk=panic_risk,
            trade_frequency_30d=float(behavior_raw.get("trade_frequency_30d", 0.0)),
            override_count_90d=int(behavior_raw.get("override_count_90d", 0) or 0),
            cooldown_active=bool(behavior_raw.get("cooldown_active", False)),
            cooldown_until=cooldown_until,
            behavior_penalty_coeff=coeff,
            recent_chasing_flag=chase_risk in {"moderate", "high"},
            high_emotion_flag=bool(behavior_raw.get("high_emotion_flag", False)),
            panic_flag=panic_risk in {"moderate", "high"},
            action_frequency_30d=int(behavior_raw.get("action_frequency_30d", 0) or 0),
            emotion_score=float(behavior_raw.get("emotion_score", 0.0) or 0.0),
        ),
        notes,
    )


def interpret_constraint_state(
    bundle: SnapshotBundle | dict[str, Any],
    market_state: MarketState,
    behavior_state: BehaviorState,
) -> ConstraintState:
    bundle_data = _bundle_dict(bundle)
    constraint_raw = _obj(bundle_data.get("constraint", {}))
    created_at = _utc(bundle_data.get("created_at"))
    bundle_id = str(bundle_data.get("bundle_id", ""))
    max_drawdown = float(constraint_raw.get("max_drawdown_tolerance", 0.2))
    effective_drawdown = max_drawdown * 0.85 if market_state.risk_environment == "high" else max_drawdown
    soft_preferences = dict(constraint_raw.get("soft_preferences", {}))
    if market_state.manual_review_required:
        soft_preferences["policy_manual_review_required"] = True
    return ConstraintState(
        as_of=created_at.isoformat().replace("+00:00", "Z"),
        source_bundle_id=bundle_id,
        version=f"constraint_state_{_stamp(created_at)}",
        ips_bucket_boundaries=dict(constraint_raw.get("ips_bucket_boundaries", {})),
        satellite_cap=float(constraint_raw.get("satellite_cap", 0.15)),
        theme_caps=dict(constraint_raw.get("theme_caps", {})),
        qdii_cap=float(constraint_raw.get("qdii_cap", 0.2)),
        liquidity_reserve_min=float(constraint_raw.get("liquidity_reserve_min", 0.05)),
        max_drawdown_tolerance=max_drawdown,
        rebalancing_band=float(constraint_raw.get("rebalancing_band", 0.1)),
        forbidden_actions=list(constraint_raw.get("forbidden_actions", [])),
        cooling_period_days=int(constraint_raw.get("cooling_period_days", 0) or 0),
        soft_preferences=soft_preferences,
        effective_drawdown_threshold=effective_drawdown,
        cooldown_currently_active=behavior_state.cooldown_active,
        bucket_category=dict(constraint_raw.get("bucket_category", {})),
        bucket_to_theme=dict(constraint_raw.get("bucket_to_theme", {})),
        qdii_available=float(constraint_raw.get("qdii_available", 0.0) or 0.0),
        premium_discount=dict(constraint_raw.get("premium_discount", {})),
        transaction_fee_rate=dict(constraint_raw.get("transaction_fee_rate", {})),
    )


def _constraint_conflicts(constraint_state: ConstraintState) -> list[str]:
    conflicts: list[str] = []
    for bucket, bounds in constraint_state.ips_bucket_boundaries.items():
        low, high = bounds
        if low > high:
            conflicts.append(f"CONSTRAINT_BOUNDS_CONFLICT:{bucket}")
        if low < 0 or high > 1:
            conflicts.append(f"CONSTRAINT_BOUNDS_OUT_OF_RANGE:{bucket}")
    return conflicts


def calibrate_market_assumptions(
    bundle: SnapshotBundle | dict[str, Any],
    prior_calibration: CalibrationResult | dict[str, Any] | None,
) -> MarketAssumptions:
    bundle_data = _bundle_dict(bundle)
    market_raw = _obj(bundle_data.get("market", {}))
    buckets = _bucket_universe(bundle_data)

    prior_market_assumptions = {}
    if prior_calibration is not None:
        prior_market_assumptions = _obj(_obj(prior_calibration).get("market_assumptions", {}))

    bundle_quality = _quality_text(bundle_data.get("bundle_quality"))
    raw_returns = dict(market_raw.get("expected_returns", {}))
    raw_volatility = dict(market_raw.get("raw_volatility", {}))
    historical_dataset = build_historical_dataset_snapshot(
        _obj(bundle_data.get("historical_dataset_metadata") or market_raw.get("historical_dataset"))
    )
    if historical_dataset is not None:
        dataset_returns, dataset_volatility, dataset_corr = summarize_historical_dataset(
            historical_dataset,
            buckets=buckets,
        )
        if dataset_returns and dataset_volatility:
            expected_returns = {
                bucket: float(
                    max(
                        min(dataset_returns.get(bucket, _default_expected_return(bucket)) * 0.95, 0.30),
                        -0.30,
                    )
                )
                for bucket in buckets
            }
            volatility = {
                bucket: float(max(dataset_volatility.get(bucket, _default_volatility(bucket)), 0.03))
                for bucket in buckets
            }
            correlation_matrix: dict[str, dict[str, float]] = {}
            for bucket in buckets:
                row: dict[str, float] = {}
                for peer in buckets:
                    if bucket == peer:
                        row[peer] = 1.0
                    else:
                        row[peer] = float(
                            dataset_corr.get(bucket, {}).get(
                                peer,
                                prior_market_assumptions.get("correlation_matrix", {}).get(bucket, {}).get(peer, 0.1),
                            )
                        )
                correlation_matrix[bucket] = row
            return MarketAssumptions(
                expected_returns=expected_returns,
                volatility=volatility,
                correlation_matrix=correlation_matrix,
                source_name=historical_dataset.source_name,
                dataset_version=historical_dataset.version_id,
                lookback_months=historical_dataset.lookback_months or None,
                historical_backtest_used=True,
            )
    if (bundle_quality == "degraded" or not raw_volatility) and prior_market_assumptions:
        return MarketAssumptions(**prior_market_assumptions)

    expected_returns = {
        bucket: float(
            raw_returns.get(
                bucket,
                prior_market_assumptions.get("expected_returns", {}).get(bucket, _default_expected_return(bucket)),
            )
        )
        for bucket in buckets
    }
    volatility = {
        bucket: float(
            raw_volatility.get(
                bucket,
                prior_market_assumptions.get("volatility", {}).get(bucket, _default_volatility(bucket)),
            )
        )
        for bucket in buckets
    }
    prior_corr = prior_market_assumptions.get("correlation_matrix", {})
    correlation_matrix: dict[str, dict[str, float]] = {}
    for bucket in buckets:
        row: dict[str, float] = {}
        for peer in buckets:
            if bucket == peer:
                row[peer] = 1.0
            else:
                row[peer] = float(prior_corr.get(bucket, {}).get(peer, 0.1))
        correlation_matrix[bucket] = row

    return MarketAssumptions(
        expected_returns=expected_returns,
        volatility=volatility,
        correlation_matrix=correlation_matrix,
        source_name=str(market_raw.get("provider_name") or "snapshot_market"),
        dataset_version=None,
        lookback_months=None,
        historical_backtest_used=False,
    )


def _normalize_weight_vector(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(float(value), 0.0) for value in weights.values())
    if total <= 0:
        return weights
    return {key: max(float(value), 0.0) / total for key, value in weights.items()}


def _param_meta_from_prior(prior_calibration: CalibrationResult | dict[str, Any] | None) -> dict[str, Any]:
    return _obj(_obj(prior_calibration or {}).get("param_version_meta", {}))


def _portfolio_return_series_from_dataset(dataset: Any | None) -> list[float]:
    if dataset is None:
        return []
    series_map = {
        str(bucket): [float(value) for value in list(series or [])]
        for bucket, series in dict(getattr(dataset, "return_series", {}) or {}).items()
        if list(series or [])
    }
    if not series_map:
        return []
    min_len = min(len(series) for series in series_map.values())
    if min_len <= 0:
        return []
    ordered_buckets = sorted(series_map)
    weight = 1.0 / len(ordered_buckets)
    portfolio_returns: list[float] = []
    for idx in range(-min_len, 0):
        portfolio_returns.append(
            sum(weight * float(series_map[bucket][idx]) for bucket in ordered_buckets)
        )
    return portfolio_returns


def _derive_regime_series(dataset: Any | None) -> list[str]:
    portfolio_returns = _portfolio_return_series_from_dataset(dataset)
    if not portfolio_returns:
        return []
    regimes: list[str] = []
    for value in portfolio_returns:
        if value <= -0.01:
            regimes.append("stress")
        elif value < 0.0:
            regimes.append("drawdown")
        elif value >= 0.01:
            regimes.append("expansion")
        else:
            regimes.append("normal")
    return regimes


def _bucketed_calibration_summary(portfolio_returns: list[float]) -> tuple[float | None, list[dict[str, Any]]]:
    if not portfolio_returns:
        return None, []
    window = min(6, max(len(portfolio_returns) - 1, 1))
    predictions: list[float] = []
    actuals: list[float] = []
    for idx in range(window, len(portfolio_returns)):
        history = portfolio_returns[max(0, idx - window):idx]
        if not history:
            continue
        predicted = sum(1.0 for value in history if value > 0.0) / len(history)
        actual = 1.0 if portfolio_returns[idx] > 0.0 else 0.0
        predictions.append(predicted)
        actuals.append(actual)
    if not predictions:
        base_rate = sum(1.0 for value in portfolio_returns if value > 0.0) / len(portfolio_returns)
        predictions = [base_rate for _ in portfolio_returns]
        actuals = [1.0 if value > 0.0 else 0.0 for value in portfolio_returns]
    brier_score = sum((pred - actual) ** 2 for pred, actual in zip(predictions, actuals, strict=True)) / max(
        len(predictions),
        1,
    )
    bucket_edges = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    buckets: list[dict[str, Any]] = []
    for lower, upper in bucket_edges:
        members = [
            (pred, actual)
            for pred, actual in zip(predictions, actuals, strict=True)
            if (pred >= lower and pred < upper) or (upper == 1.0 and pred <= upper)
        ]
        buckets.append(
            {
                "bucket_label": f"{int(lower * 100)}-{int(upper * 100)}",
                "predicted_probability_mean": (
                    sum(pred for pred, _ in members) / len(members) if members else None
                ),
                "realized_hit_rate": (
                    sum(actual for _, actual in members) / len(members) if members else None
                ),
                "sample_count": len(members),
                "status": "insufficient_sample" if len(members) < 3 else "ready",
            }
        )
    return float(brier_score), buckets


def _regime_breakdown(dataset: Any | None) -> list[dict[str, Any]]:
    portfolio_returns = _portfolio_return_series_from_dataset(dataset)
    regimes = _derive_regime_series(dataset)
    if not portfolio_returns or not regimes:
        return []
    breakdown: dict[str, list[float]] = {}
    for regime, value in zip(regimes, portfolio_returns, strict=True):
        breakdown.setdefault(regime, []).append(float(value))
    rows: list[dict[str, Any]] = []
    for regime, values in sorted(breakdown.items()):
        rows.append(
            {
                "regime": regime,
                "sample_count": len(values),
                "mean_return": sum(values) / len(values),
                "hit_rate": sum(1.0 for value in values if value > 0.0) / len(values),
            }
        )
    return rows


def _calibration_quality_from_sample_count(sample_count: int) -> str:
    if sample_count >= 60:
        return "strong"
    if sample_count >= 24:
        return "acceptable"
    if sample_count >= 12:
        return "weak"
    return "insufficient_sample"


def _distribution_input_from_historical_dataset(dataset: Any | None) -> DistributionInput | None:
    if dataset is None:
        return None
    return_series = {
        str(bucket): [float(value) for value in list(series or [])]
        for bucket, series in dict(getattr(dataset, "return_series", {}) or {}).items()
        if list(series or [])
    }
    if not return_series:
        return None
    summary_returns, summary_volatility, summary_corr = summarize_historical_dataset(
        dataset,
        buckets=sorted(return_series),
    )
    garch_t_state = {
        bucket: {
            "annualized_volatility": float(summary_volatility.get(bucket, 0.15) or 0.15),
            "long_run_variance": float(max((summary_volatility.get(bucket, 0.15) or 0.15) ** 2 / 12.0, 1e-6)),
            "alpha": 0.06,
            "beta": 0.90,
            "nu": 7.0,
        }
        for bucket in return_series
    }
    bucket_jump_probability: dict[str, float] = {}
    bucket_jump_loss: dict[str, float] = {}
    for bucket, series in return_series.items():
        negatives = [abs(value) for value in series if value < -0.02]
        bucket_jump_probability[bucket] = min(len(negatives) / max(len(series), 1), 0.25)
        bucket_jump_loss[bucket] = max(sum(negatives) / len(negatives), 0.03) if negatives else 0.03
    return DistributionInput(
        frequency=str(getattr(dataset, "frequency", "monthly") or "monthly"),
        historical_return_series=return_series,
        regime_series=_derive_regime_series(dataset),
        tail_df=7.0,
        block_size=3,
        source_ref=str(getattr(dataset, "source_ref", "") or ""),
        audit_window=None if getattr(dataset, "audit_window", None) is None else dataset.audit_window.to_dict(),
        garch_t_state=garch_t_state,
        dcc_state={
            "correlation_matrix": summary_corr,
            "long_run_correlation": summary_corr,
            "alpha": 0.04,
            "beta": 0.93,
        },
        jump_state={
            "bucket_jump_probability_1m": bucket_jump_probability,
            "bucket_jump_loss": bucket_jump_loss,
            "systemic_jump_probability_1m": min(sum(bucket_jump_probability.values()) / max(len(bucket_jump_probability), 1), 0.15),
            "systemic_jump_scale": 0.75,
        },
    )


def update_goal_solver_params(
    market_assumptions: MarketAssumptions,
    distribution_model_state: DistributionModelState,
    distribution_input: DistributionInput | None,
    prior_params: GoalSolverParams | dict[str, Any] | None,
    created_at: Any,
) -> GoalSolverParams:
    params = _coerce_goal_solver_params(prior_params, market_assumptions)
    params.version = _version_id("goal_solver_params", created_at)
    params.market_assumptions = market_assumptions
    params.simulation_mode = SimulationMode(distribution_model_state.selected_mode)
    params.distribution_input = distribution_input
    return params


def update_runtime_optimizer_params(
    market_state: MarketState,
    constraint_state: ConstraintState,
    prior_params: RuntimeOptimizerParams | dict[str, Any] | None,
    created_at: Any,
) -> RuntimeOptimizerParams:
    params = _coerce_runtime_params(prior_params)
    if market_state.risk_environment == "high":
        params.deviation_soft_threshold = max(0.01, params.deviation_soft_threshold * 0.8)
        params.deviation_hard_threshold = max(
            params.deviation_soft_threshold + 0.01,
            params.deviation_hard_threshold * 0.85,
        )
        params.drawdown_event_threshold = min(
            params.drawdown_event_threshold,
            constraint_state.effective_drawdown_threshold,
        )
    if market_state.policy_signal_confidence >= 0.6:
        if market_state.macro_uncertainty == "high":
            params.deviation_soft_threshold = max(0.01, params.deviation_soft_threshold * 0.9)
            params.deviation_hard_threshold = max(
                params.deviation_soft_threshold + 0.01,
                params.deviation_hard_threshold * 0.95,
            )
        if market_state.liquidity_stress == "high":
            params.new_cash_use_pct = min(params.new_cash_use_pct, 0.70)
            params.min_cash_for_action = max(params.min_cash_for_action, 2000.0)
    params.version = _version_id("runtime_params", created_at)
    return params


def update_ev_params(
    market_state: MarketState,
    behavior_state: BehaviorState,
    prior_params: EVParams | dict[str, Any] | None,
    created_at: Any,
) -> EVParams:
    params = _coerce_ev_params(prior_params)
    weights = {
        "goal_impact_weight": params.goal_impact_weight,
        "risk_penalty_weight": params.risk_penalty_weight,
        "soft_constraint_weight": params.soft_constraint_weight,
        "behavior_penalty_weight": params.behavior_penalty_weight,
        "execution_penalty_weight": params.execution_penalty_weight,
    }
    behavior_risk = max(
        behavior_state.behavior_penalty_coeff,
        1.0 if behavior_state.high_emotion_flag or behavior_state.panic_flag else 0.0,
    )
    if behavior_risk >= 0.5:
        target_behavior = min(0.20, max(weights["behavior_penalty_weight"], 0.15 + 0.05 * behavior_risk))
        remaining_target = 1.0 - target_behavior
        other_keys = [key for key in weights if key != "behavior_penalty_weight"]
        other_total = sum(weights[key] for key in other_keys) or 1.0
        for key in other_keys:
            weights[key] = remaining_target * weights[key] / other_total
        weights["behavior_penalty_weight"] = target_behavior
    if market_state.correlation_spike_alert:
        weights["risk_penalty_weight"] = min(0.35, weights["risk_penalty_weight"] + 0.03)
        normalized = _normalize_weight_vector(weights)
        weights.update(normalized)
    if market_state.policy_signal_confidence >= 0.6 and (
        market_state.sentiment_stress == "high" or market_state.liquidity_stress == "high"
    ):
        weights["risk_penalty_weight"] = min(0.40, weights["risk_penalty_weight"] + 0.03)
        weights["goal_impact_weight"] = max(0.20, weights["goal_impact_weight"] - 0.02)
        normalized = _normalize_weight_vector(weights)
        weights.update(normalized)

    params.goal_impact_weight = weights["goal_impact_weight"]
    params.risk_penalty_weight = weights["risk_penalty_weight"]
    params.soft_constraint_weight = weights["soft_constraint_weight"]
    params.behavior_penalty_weight = weights["behavior_penalty_weight"]
    params.execution_penalty_weight = weights["execution_penalty_weight"]
    params.version = _version_id("ev_params", created_at)
    return params


def _derive_updated_reason(
    calibration_quality: str,
    *,
    updated_reason: str | None,
    manual_override: bool,
    replay_mode: bool,
    has_prior: bool,
) -> str:
    if updated_reason:
        return updated_reason
    if manual_override:
        return "manual_review"
    if replay_mode:
        return "replay_calibration"
    if calibration_quality == "full":
        return "monthly_calibration"
    if calibration_quality == "partial":
        return "partial_calibration"
    if has_prior:
        return "degraded_replay"
    return "degraded_fallback"


def _param_meta_quality(calibration_quality: str, manual_override: bool) -> str:
    if manual_override:
        return "manual"
    if calibration_quality == "full":
        return "full"
    return "degraded"


def _build_param_version_meta(
    *,
    created_at: Any,
    bundle_id: str,
    calibration_quality: str,
    updated_reason: str,
    manual_override: bool,
    prior_calibration: CalibrationResult | dict[str, Any] | None,
    goal_solver_params: GoalSolverParams,
    runtime_optimizer_params: RuntimeOptimizerParams,
    ev_params: EVParams,
) -> ParamVersionMeta:
    quality = _param_meta_quality(calibration_quality, manual_override)
    is_temporary = quality == "degraded"
    prior_meta = _param_meta_from_prior(prior_calibration)
    return ParamVersionMeta(
        version_id=_version_id("calibration", created_at),
        source_bundle_id=bundle_id,
        created_at=_utc(created_at).isoformat().replace("+00:00", "Z"),
        updated_reason=updated_reason,
        quality=quality,
        is_temporary=is_temporary,
        can_be_replayed=not is_temporary,
        previous_version_id=prior_meta.get("version_id"),
        market_assumptions_version=_version_id("market_assumptions", created_at),
        goal_solver_params_version=goal_solver_params.version,
        runtime_optimizer_params_version=runtime_optimizer_params.version,
        ev_params_version=ev_params.version,
    )


def _coerce_goal_solver_params(
    params: Any | None,
    market_assumptions: MarketAssumptions,
) -> GoalSolverParams:
    data = _obj(params or {})
    ranking_mode_default = data.get("ranking_mode_default", "sufficiency_first")
    simulation_mode = data.get("simulation_mode", SimulationMode.STATIC_GAUSSIAN.value)
    distribution_input_raw = data.get("distribution_input")
    distribution_input = None
    if distribution_input_raw is not None:
        distribution_input = DistributionInput(**_obj(distribution_input_raw))
    return GoalSolverParams(
        version=str(data.get("version", "v4.0.0")),
        n_paths=int(data.get("n_paths", 5000) or 5000),
        n_paths_lightweight=int(data.get("n_paths_lightweight", 1000) or 1000),
        seed=int(data.get("seed", 42) or 42),
        market_assumptions=market_assumptions,
        shrinkage_factor=float(data.get("shrinkage_factor", 0.85) or 0.85),
        ranking_mode_default=RankingMode(str(getattr(ranking_mode_default, "value", ranking_mode_default))),
        simulation_mode=SimulationMode(str(getattr(simulation_mode, "value", simulation_mode))),
        distribution_input=distribution_input,
    )


def _coerce_runtime_params(params: Any | None) -> RuntimeOptimizerParams:
    data = _obj(params or {})
    return RuntimeOptimizerParams(
        version=str(data.get("version", "v1.0.0")),
        deviation_soft_threshold=float(data.get("deviation_soft_threshold", 0.03)),
        deviation_hard_threshold=float(data.get("deviation_hard_threshold", 0.10)),
        satellite_overweight_threshold=float(data.get("satellite_overweight_threshold", 0.02)),
        drawdown_event_threshold=float(data.get("drawdown_event_threshold", 0.10)),
        min_candidates=int(data.get("min_candidates", 2) or 2),
        max_candidates=int(data.get("max_candidates", 8) or 8),
        min_cash_for_action=float(data.get("min_cash_for_action", 1000.0)),
        new_cash_split_buckets=int(data.get("new_cash_split_buckets", 2) or 2),
        new_cash_use_pct=float(data.get("new_cash_use_pct", 0.8)),
        defense_add_pct=float(data.get("defense_add_pct", 0.05)),
        rebalance_full_allowed_monthly=bool(data.get("rebalance_full_allowed_monthly", False)),
        cooldown_trade_frequency_limit=float(data.get("cooldown_trade_frequency_limit", 4.0)),
        amount_pct_min=float(data.get("amount_pct_min", 0.02)),
        amount_pct_max=float(data.get("amount_pct_max", 0.30)),
        max_portfolio_snapshot_age_days=int(data.get("max_portfolio_snapshot_age_days", 3) or 3),
    )


def _coerce_ev_params(params: Any | None) -> EVParams:
    data = _obj(params or {})
    return EVParams(
        version=str(data.get("version", "v1.0.0")),
        goal_impact_weight=float(data.get("goal_impact_weight", 0.40)),
        risk_penalty_weight=float(data.get("risk_penalty_weight", 0.25)),
        soft_constraint_weight=float(data.get("soft_constraint_weight", 0.15)),
        behavior_penalty_weight=float(data.get("behavior_penalty_weight", 0.10)),
        execution_penalty_weight=float(data.get("execution_penalty_weight", 0.10)),
        goal_solver_seed=int(data.get("goal_solver_seed", 42) or 42),
        goal_solver_min_delta=float(data.get("goal_solver_min_delta", 0.003)),
        high_confidence_min_diff=float(data.get("high_confidence_min_diff", 0.020)),
        medium_confidence_min_diff=float(data.get("medium_confidence_min_diff", 0.005)),
        volatility_penalty_coeff=float(data.get("volatility_penalty_coeff", 0.0)),
        drawdown_penalty_coeff=float(data.get("drawdown_penalty_coeff", 0.0)),
        qdii_premium_cost_rate=float(data.get("qdii_premium_cost_rate", 0.0)),
        transaction_cost_rate=float(data.get("transaction_cost_rate", 0.0)),
        ips_headroom_warning_threshold=float(data.get("ips_headroom_warning_threshold", 0.0)),
        theme_budget_warning_pct=float(data.get("theme_budget_warning_pct", 0.0)),
        concentration_headroom_threshold=float(data.get("concentration_headroom_threshold", 0.0)),
        emotion_score_threshold=float(data.get("emotion_score_threshold", 0.0)),
        action_frequency_threshold=float(data.get("action_frequency_threshold", 0.0)),
        momentum_lookback_days=int(data.get("momentum_lookback_days", 0) or 0),
        momentum_threshold_pct=float(data.get("momentum_threshold_pct", 0.0)),
    )


def _build_calibration_summary(bundle_id: str, calibration_quality: str, historical_dataset: Any | None) -> CalibrationSummary:
    portfolio_returns = _portfolio_return_series_from_dataset(historical_dataset)
    brier_score, reliability_buckets = _bucketed_calibration_summary(portfolio_returns)
    regime_breakdown = _regime_breakdown(historical_dataset)
    sample_count = len(portfolio_returns)
    return CalibrationSummary(
        sample_count=sample_count,
        brier_score=brier_score,
        reliability_buckets=reliability_buckets,
        regime_breakdown=regime_breakdown,
        calibration_quality=_calibration_quality_from_sample_count(sample_count),
        source_ref=(
            f"{getattr(historical_dataset, 'source_ref', '') or bundle_id or 'unknown'}::calibration"
        ),
    )


def _build_distribution_model_state(
    *,
    bundle_id: str,
    created_at: Any,
    calibration_summary: CalibrationSummary,
    requested_mode: SimulationMode,
    distribution_input: DistributionInput | None,
) -> DistributionModelState:
    sample_count = int(calibration_summary.sample_count)
    regime_sensitive = bool(distribution_input and distribution_input.regime_series)
    eligible_modes_in_order: list[str] = [SimulationMode.STATIC_GAUSSIAN.value]
    if sample_count >= 12:
        eligible_modes_in_order.append(SimulationMode.STUDENT_T.value)
    if distribution_input is not None and distribution_input.historical_return_series and sample_count >= 12:
        eligible_modes_in_order.append(SimulationMode.HISTORICAL_BLOCK_BOOTSTRAP.value)
    if regime_sensitive and sample_count >= 24:
        eligible_modes_in_order.append(SimulationMode.REGIME_SWITCHING_BOOTSTRAP.value)
    if distribution_input is not None and distribution_input.garch_t_state and sample_count >= 24:
        eligible_modes_in_order.append(SimulationMode.GARCH_T.value)
    if distribution_input is not None and distribution_input.dcc_state and sample_count >= 24:
        eligible_modes_in_order.append(SimulationMode.GARCH_T_DCC.value)
    if distribution_input is not None and distribution_input.jump_state and sample_count >= 24:
        eligible_modes_in_order.append(SimulationMode.GARCH_T_DCC_JUMP.value)
    requested_mode_value = requested_mode.value
    selected_mode = requested_mode_value if requested_mode_value in eligible_modes_in_order else eligible_modes_in_order[-1]
    downgrade_reason = None if selected_mode == requested_mode_value else f"requested_mode {requested_mode_value} not eligible"
    eligibility = SimulationModeEligibility(
        simulation_mode=selected_mode,
        minimum_sample_months=24 if selected_mode != SimulationMode.STATIC_GAUSSIAN.value else 0,
        minimum_weight_adjusted_coverage=0.6 if selected_mode != SimulationMode.STATIC_GAUSSIAN.value else 0.0,
        requires_regime_stability=selected_mode == SimulationMode.REGIME_SWITCHING_BOOTSTRAP.value,
        requires_jump_calibration=selected_mode == SimulationMode.GARCH_T_DCC_JUMP.value,
        allowed_result_categories=[
            "formal_independent_result",
            "formal_estimated_result",
            "degraded_formal_result",
        ],
        downgrade_target=None if selected_mode == requested_mode_value else "degraded_formal_result",
        ineligibility_action="degrade_result" if selected_mode != requested_mode_value else "mark_unavailable",
    )
    mode_resolution = ModeResolutionDecision(
        requested_mode=requested_mode_value,
        selected_mode=selected_mode,
        eligible_modes_in_order=eligible_modes_in_order,
        ineligibility_action="degrade_result" if selected_mode != requested_mode_value else "mark_unavailable",
        downgraded=selected_mode != requested_mode_value,
        downgrade_reason=downgrade_reason,
    )
    return DistributionModelState(
        simulation_mode=requested_mode_value,
        selected_mode=selected_mode,
        tail_model=(
            "student_t"
            if selected_mode in {SimulationMode.STUDENT_T.value, SimulationMode.GARCH_T.value, SimulationMode.GARCH_T_DCC.value, SimulationMode.GARCH_T_DCC_JUMP.value}
            else "historical_empirical"
        ),
        regime_sensitive=regime_sensitive,
        jump_overlay_enabled=selected_mode == SimulationMode.GARCH_T_DCC_JUMP.value,
        eligibility_decision=eligibility,
        mode_resolution_decision=mode_resolution,
        calibration_summary=calibration_summary,
        source_ref=f"{bundle_id or 'unknown'}::{selected_mode}",
        as_of=_utc(created_at).isoformat().replace("+00:00", "Z"),
        data_status="observed",
    )


def run_calibration(
    bundle: SnapshotBundle | dict[str, Any],
    prior_calibration: CalibrationResult | dict[str, Any] | None,
    default_goal_solver_params: GoalSolverParams | dict[str, Any] | None = None,
    default_runtime_params: RuntimeOptimizerParams | dict[str, Any] | None = None,
    default_ev_params: EVParams | dict[str, Any] | None = None,
    updated_reason: str | None = None,
    manual_override: bool = False,
    replay_mode: bool = False,
) -> CalibrationResult:
    bundle_data = _bundle_dict(bundle)
    bundle_id = str(bundle_data.get("bundle_id", ""))
    created_at = _utc(bundle_data.get("created_at"))
    account_profile_id = str(bundle_data.get("account_profile_id", ""))

    market_state = interpret_market_state(bundle_data)
    prior_data = _obj(prior_calibration or {})
    historical_dataset = build_historical_dataset_snapshot(
        _obj(bundle_data.get("historical_dataset_metadata") or _obj(bundle_data.get("market", {})).get("historical_dataset"))
    )
    behavior_state, notes = interpret_behavior_state(
        bundle_data,
        prior_behavior=prior_data.get("behavior_state"),
    )
    constraint_state = interpret_constraint_state(bundle_data, market_state, behavior_state)
    market_assumptions = calibrate_market_assumptions(bundle_data, prior_calibration)
    if (
        (_quality_text(bundle_data.get("bundle_quality")) == "degraded" or market_state.is_degraded)
        and prior_data.get("market_assumptions")
    ):
        notes.append("market assumptions reused from prior due degraded market input")

    runtime_optimizer_params = update_runtime_optimizer_params(
        market_state,
        constraint_state,
        default_runtime_params or prior_data.get("runtime_optimizer_params"),
        created_at=created_at,
    )
    ev_params = update_ev_params(
        market_state,
        behavior_state,
        default_ev_params or prior_data.get("ev_params"),
        created_at=created_at,
    )

    degraded_domains: list[str] = []
    bundle_quality = _quality_text(bundle_data.get("bundle_quality"))
    if bundle_quality == "degraded" or market_state.is_degraded:
        degraded_domains.extend(_severity_domains(bundle_data, "error"))
        if "market" not in degraded_domains and market_state.is_degraded:
            degraded_domains.append("market")
        calibration_quality = "degraded"
    else:
        if bundle_quality == "partial":
            degraded_domains.extend(_severity_domains(bundle_data, "warn"))
            degraded_domains.extend(_severity_domains(bundle_data, "info"))
        if bundle_data.get("behavior") in (None, {}):
            if "behavior" not in degraded_domains:
                degraded_domains.append("behavior")
        calibration_quality = "partial" if degraded_domains else "full"

    constraint_conflicts = _constraint_conflicts(constraint_state)
    if constraint_conflicts:
        degraded_domains.append("constraint")
        notes.extend(constraint_conflicts)
        notes.append("manual review required: constraint bounds conflict")
        calibration_quality = "degraded"
    degraded_domains = _unique_items(degraded_domains)

    if market_state.risk_environment == "high":
        notes.append("risk_environment=high tightened drawdown threshold")
    if market_state.manual_review_required:
        notes.append("policy_news manual review required")
        notes.append("policy_signal manual_review_required=true")
    if market_state.policy_signal_confidence >= 0.6:
        notes.append(
            "policy_signal "
            f"macro_uncertainty={market_state.macro_uncertainty or 'unknown'} "
            f"manual_review_required={'true' if market_state.manual_review_required else 'false'}"
        )
        notes.append(
            "policy_signal "
            f"policy_regime={market_state.policy_regime or 'unclear'} "
            f"macro_uncertainty={market_state.macro_uncertainty or 'unknown'} "
            f"sentiment_stress={market_state.sentiment_stress or 'unknown'} "
            f"liquidity_stress={market_state.liquidity_stress or 'unknown'} "
            f"confidence={market_state.policy_signal_confidence:.2f}"
        )
        notes.append(
            "policy_signal_absorption "
            f"runtime_soft_threshold={runtime_optimizer_params.deviation_soft_threshold:.4f} "
            f"new_cash_use_pct={runtime_optimizer_params.new_cash_use_pct:.4f} "
            f"risk_penalty_weight={ev_params.risk_penalty_weight:.4f}"
        )
    if market_assumptions.historical_backtest_used:
        notes.append(
            "historical_dataset "
            f"source={market_assumptions.source_name or 'unknown'} "
            f"version={market_assumptions.dataset_version or 'unknown'} "
            f"lookback_months={market_assumptions.lookback_months or 0}"
        )

    requested_mode = SimulationMode.HISTORICAL_BLOCK_BOOTSTRAP
    requested_params = _obj(default_goal_solver_params or prior_data.get("goal_solver_params") or {})
    if requested_params.get("simulation_mode"):
        requested_mode = SimulationMode(str(getattr(requested_params.get("simulation_mode"), "value", requested_params.get("simulation_mode"))))
    distribution_input = _distribution_input_from_historical_dataset(historical_dataset)
    factor_dynamics, regime_state_artifact, jump_state_artifact = _build_probability_engine_state_artifacts(
        bundle_data=bundle_data,
        market_state=market_state,
        market_assumptions=market_assumptions,
        distribution_input=distribution_input,
        historical_dataset=historical_dataset,
        created_at=created_at,
        calibration_quality=calibration_quality,
        prior_calibration=prior_calibration,
    )
    calibration_summary = _build_calibration_summary(bundle_id, calibration_quality, historical_dataset)
    distribution_model_state = _build_distribution_model_state(
        bundle_id=bundle_id,
        created_at=created_at,
        calibration_summary=calibration_summary,
        requested_mode=requested_mode,
        distribution_input=distribution_input,
    )
    calibration_summary.source_ref = (
        f"{getattr(historical_dataset, 'source_ref', '') or bundle_id or 'unknown'}::{distribution_model_state.selected_mode}"
    )
    distribution_model_state.calibration_summary = calibration_summary
    goal_solver_params = update_goal_solver_params(
        market_assumptions,
        distribution_model_state,
        distribution_input,
        default_goal_solver_params or prior_data.get("goal_solver_params"),
        created_at=created_at,
    )

    reason = _derive_updated_reason(
        calibration_quality,
        updated_reason=updated_reason,
        manual_override=manual_override,
        replay_mode=replay_mode,
        has_prior=bool(prior_data),
    )
    if manual_override:
        notes.append("manual override applied to calibration metadata")
    if replay_mode:
        notes.append("replay mode calibration metadata applied")
    param_version_meta = _build_param_version_meta(
        created_at=created_at,
        bundle_id=bundle_id,
        calibration_quality=calibration_quality,
        updated_reason=reason,
        manual_override=manual_override,
        prior_calibration=prior_calibration,
        goal_solver_params=goal_solver_params,
        runtime_optimizer_params=runtime_optimizer_params,
        ev_params=ev_params,
    )

    return CalibrationResult(
        calibration_id=f"{account_profile_id}_{_stamp(created_at)}",
        source_bundle_id=bundle_id,
        created_at=created_at.isoformat().replace("+00:00", "Z"),
        account_profile_id=account_profile_id,
        market_state=market_state,
        constraint_state=constraint_state,
        behavior_state=behavior_state,
        market_assumptions=market_assumptions,
        goal_solver_params=goal_solver_params,
        runtime_optimizer_params=runtime_optimizer_params,
        ev_params=ev_params,
        factor_dynamics=factor_dynamics,
        regime_state=regime_state_artifact,
        jump_state=jump_state_artifact,
        distribution_model_state=distribution_model_state,
        calibration_summary=calibration_summary,
        calibration_quality=calibration_quality,
        degraded_domains=degraded_domains,
        notes=notes,
        param_version_meta=param_version_meta,
    )
