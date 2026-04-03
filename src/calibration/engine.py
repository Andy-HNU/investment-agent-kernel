from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from calibration.types import (
    BehaviorState,
    CalibrationResult,
    ConstraintState,
    EVParams,
    MarketState,
    ParamVersionMeta,
    RuntimeOptimizerParams,
)
from goal_solver.types import GoalSolverParams, MarketAssumptions, RankingMode
from snapshot_ingestion.historical import build_historical_dataset_snapshot, summarize_historical_dataset
from snapshot_ingestion.types import CompletenessLevel, SnapshotBundle


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
    liquidity_status: dict[str, str] = {}
    valuation_positions: dict[str, str] = {}
    quality_flags: list[str] = []
    policy_summary = _policy_signal_summary(bundle_data) or {}
    historical_metadata = _obj(
        bundle_data.get("historical_dataset_metadata") or _obj(market_raw.get("historical_dataset")) or {}
    )

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

        valuation = valuation_z_scores.get(bucket)
        if valuation is None:
            valuation_positions[bucket] = "fair"
            if "market_valuation_z_scores_missing" not in quality_flags:
                quality_flags.append("market_valuation_z_scores_missing")
        elif valuation > 2.5:
            valuation_positions[bucket] = "extreme"
        elif valuation > 1.5:
            valuation_positions[bucket] = "rich"
        elif valuation < -1.5:
            valuation_positions[bucket] = "cheap"
        else:
            valuation_positions[bucket] = "fair"

    if not raw_volatility:
        quality_flags.append("market_volatility_missing")
    if bool(policy_summary.get("manual_review_required")):
        quality_flags.append("policy_signal_manual_review_required")
    if str(policy_summary.get("macro_uncertainty") or "").lower() == "high":
        quality_flags.append("policy_signal_macro_uncertainty_high")
        risk_environment = "high"
        volatility_regime = "high"
    if historical_metadata:
        quality_flags.append("historical_dataset_attached")
    coverage_status = _first_text(historical_metadata.get("coverage_status"))
    cycle_reasons = [str(item) for item in list(historical_metadata.get("cycle_reasons") or []) if str(item).strip()]
    if coverage_status == "cycle_insufficient":
        quality_flags.append("historical_dataset_cycle_insufficient")
    if int(historical_metadata.get("inferred_history_days") or 0) > 0:
        quality_flags.append("historical_dataset_inferred_history_attached")
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
        valuation_percentile={
            bucket: 0.5 if valuation_positions[bucket] == "fair" else 0.8
            for bucket in buckets
        },
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
        historical_frequency=_first_text(historical_metadata.get("frequency")),
        historical_coverage_status=coverage_status,
        historical_cycle_reasons=cycle_reasons,
        observed_history_days=int(historical_metadata.get("observed_history_days") or 0),
        inferred_history_days=int(historical_metadata.get("inferred_history_days") or 0),
        lookback_days=int(historical_metadata.get("lookback_days") or 0),
        historical_inference_method=_first_text(historical_metadata.get("inference_method")),
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
            coverage_status = historical_dataset.coverage_status
            cycle_penalty = 1.0 if coverage_status == "verified" else 0.90
            vol_penalty = 1.0 if coverage_status == "verified" else 1.10
            expected_returns = {
                bucket: float(
                    max(
                        min(dataset_returns.get(bucket, _default_expected_return(bucket)) * 0.95 * cycle_penalty, 0.30),
                        -0.30,
                    )
                )
                for bucket in buckets
            }
            volatility = {
                bucket: float(max(dataset_volatility.get(bucket, _default_volatility(bucket)) * vol_penalty, 0.03))
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
                frequency=historical_dataset.frequency,
                lookback_months=historical_dataset.lookback_months or None,
                lookback_days=historical_dataset.lookback_days or None,
                historical_backtest_used=True,
                coverage_status=historical_dataset.coverage_status,
                cycle_reasons=list(historical_dataset.cycle_reasons),
                observed_history_days=int(historical_dataset.observed_history_days or 0),
                inferred_history_days=int(historical_dataset.inferred_history_days or 0),
                inference_method=historical_dataset.inference_method,
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
        frequency=None,
        lookback_months=None,
        lookback_days=None,
        historical_backtest_used=False,
        coverage_status=None,
        cycle_reasons=[],
        observed_history_days=0,
        inferred_history_days=0,
        inference_method=None,
    )


def _normalize_weight_vector(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(float(value), 0.0) for value in weights.values())
    if total <= 0:
        return weights
    return {key: max(float(value), 0.0) / total for key, value in weights.items()}


def _param_meta_from_prior(prior_calibration: CalibrationResult | dict[str, Any] | None) -> dict[str, Any]:
    return _obj(_obj(prior_calibration or {}).get("param_version_meta", {}))


def update_goal_solver_params(
    market_assumptions: MarketAssumptions,
    prior_params: GoalSolverParams | dict[str, Any] | None,
    created_at: Any,
) -> GoalSolverParams:
    params = _coerce_goal_solver_params(prior_params, market_assumptions)
    params.version = _version_id("goal_solver_params", created_at)
    params.market_assumptions = market_assumptions
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
    return GoalSolverParams(
        version=str(data.get("version", "v4.0.0")),
        n_paths=int(data.get("n_paths", 5000) or 5000),
        n_paths_lightweight=int(data.get("n_paths_lightweight", 1000) or 1000),
        seed=int(data.get("seed", 42) or 42),
        market_assumptions=market_assumptions,
        shrinkage_factor=float(data.get("shrinkage_factor", 0.85) or 0.85),
        ranking_mode_default=RankingMode(data.get("ranking_mode_default", "sufficiency_first")),
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

    goal_solver_params = update_goal_solver_params(
        market_assumptions,
        default_goal_solver_params or prior_data.get("goal_solver_params"),
        created_at=created_at,
    )
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
        notes.append(
            "historical_dataset_cycle "
            f"coverage_status={market_assumptions.coverage_status or 'unknown'} "
            f"observed_history_days={market_assumptions.observed_history_days} "
            f"inferred_history_days={market_assumptions.inferred_history_days} "
            f"inference_method={market_assumptions.inference_method or 'none'} "
            f"cycle_reasons={','.join(market_assumptions.cycle_reasons) or 'none'}"
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
        calibration_quality=calibration_quality,
        degraded_domains=degraded_domains,
        notes=notes,
        param_version_meta=param_version_meta,
    )
