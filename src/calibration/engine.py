from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from calibration.types import (
    BehaviorState,
    CalibrationResult,
    ConstraintState,
    DccState,
    DistributionModelState,
    EVParams,
    GarchState,
    JumpOverlayState,
    MarketState,
    ParamVersionMeta,
    RuntimeOptimizerParams,
)
from goal_solver.types import (
    DistributionInput,
    GoalSolverParams,
    MarketAssumptions,
    RankingMode,
    SimulationMode,
)
from snapshot_ingestion.historical import (
    build_bucket_proxy_mapping,
    build_historical_dataset_snapshot,
    build_historical_return_panel,
    build_jump_event_history,
    build_regime_feature_snapshot,
    summarize_historical_dataset,
)
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


def _clip(value: float, low: float, high: float) -> float:
    return float(max(low, min(value, high)))


def _distribution_regime_anchor(
    regime_snapshot: Any | None,
    policy_summary: dict[str, Any],
) -> str | None:
    regime_data = _obj(regime_snapshot or {})
    regime_anchor = _first_text(regime_data.get("inferred_regime"), policy_summary.get("policy_regime"))
    if regime_anchor:
        return regime_anchor
    if str(policy_summary.get("macro_uncertainty") or "").lower() == "high":
        return "uncertain"
    return None


def build_distribution_model_state(
    bundle: SnapshotBundle | dict[str, Any],
    market_state: MarketState,
    market_assumptions: MarketAssumptions,
) -> DistributionModelState:
    bundle_data = _bundle_dict(bundle)
    market_raw = _obj(bundle_data.get("market", {}))
    created_at = _utc(bundle_data.get("created_at"))
    bundle_id = str(bundle_data.get("bundle_id", ""))
    buckets = _bucket_universe(bundle_data)
    policy_summary = _policy_signal_summary(bundle_data)
    historical_panel = build_historical_return_panel(_obj(market_raw.get("historical_return_panel")))
    regime_snapshot = build_regime_feature_snapshot(_obj(market_raw.get("regime_feature_snapshot")))
    jump_history = build_jump_event_history(_obj(market_raw.get("jump_event_history")))
    proxy_mapping = build_bucket_proxy_mapping(_obj(market_raw.get("bucket_proxy_mapping")))
    historical_dataset = build_historical_dataset_snapshot(
        historical_panel
        or _obj(bundle_data.get("historical_dataset_metadata") or market_raw.get("historical_dataset"))
    )

    dataset_volatility: dict[str, float] = {}
    dataset_corr: dict[str, dict[str, float]] = {}
    if historical_dataset is not None:
        _, dataset_volatility, dataset_corr = summarize_historical_dataset(historical_dataset, buckets=buckets)

    stress_multiplier = 1.0
    if market_state.risk_environment == "high":
        stress_multiplier += 0.08
    if str(policy_summary.get("macro_uncertainty") or "").lower() == "high":
        stress_multiplier += 0.07
    if str(policy_summary.get("liquidity_stress") or "").lower() == "high":
        stress_multiplier += 0.05

    garch_notes = [
        "conservative_fallback volatility seeds applied; not fully estimated",
    ]
    annualized_volatility: dict[str, float] = {}
    long_run_variance: dict[str, float] = {}
    persistence: dict[str, float] = {}
    shock_loading: dict[str, float] = {}
    for bucket in buckets:
        base_vol = float(
            dataset_volatility.get(
                bucket,
                market_assumptions.volatility.get(bucket, _default_volatility(bucket)),
            )
        )
        adjusted_vol = _clip(base_vol * stress_multiplier, 0.03, 0.60)
        annualized_volatility[bucket] = adjusted_vol
        long_run_variance[bucket] = _clip((adjusted_vol**2) / 12.0, 0.0001, 1.0)
        persistence[bucket] = 0.90 if "bond" in bucket else 0.94
        shock_loading[bucket] = 0.05 if "bond" in bucket else 0.07
    if historical_dataset is not None:
        garch_notes.append(
            "historical dataset seeded volatility "
            f"source={historical_dataset.source_name or 'unknown'} "
            f"version={historical_dataset.version_id or 'unknown'}"
        )
    else:
        garch_notes.append("market assumptions volatility used as fallback seed")
    garch_state = GarchState(
        version=_version_id("garch_state", created_at),
        annualized_volatility=annualized_volatility,
        long_run_variance=long_run_variance,
        persistence=persistence,
        shock_loading=shock_loading,
        estimation_mode="conservative_fallback",
        is_degraded=True,
        notes=garch_notes,
    )

    regime_anchor = _distribution_regime_anchor(regime_snapshot, policy_summary)
    dcc_notes = [
        "conservative_fallback correlation surface applied; not fully estimated",
    ]
    long_run_correlation: dict[str, dict[str, float]] = {}
    correlation_matrix: dict[str, dict[str, float]] = {}
    stress_shift = 0.12 if market_state.correlation_spike_alert else 0.0
    if str(policy_summary.get("macro_uncertainty") or "").lower() == "high":
        stress_shift += 0.08
    for bucket in buckets:
        baseline_row: dict[str, float] = {}
        stressed_row: dict[str, float] = {}
        for peer in buckets:
            if bucket == peer:
                baseline_row[peer] = 1.0
                stressed_row[peer] = 1.0
                continue
            base_corr = float(
                dataset_corr.get(bucket, {}).get(
                    peer,
                    market_assumptions.correlation_matrix.get(bucket, {}).get(peer, 0.1),
                )
            )
            baseline_row[peer] = _clip(base_corr, -0.95, 0.95)
            stressed_row[peer] = _clip(base_corr + stress_shift, -0.95, 0.95)
        long_run_correlation[bucket] = baseline_row
        correlation_matrix[bucket] = stressed_row
    if regime_anchor:
        dcc_notes.append(f"regime anchor={regime_anchor}")
    dcc_state = DccState(
        version=_version_id("dcc_state", created_at),
        correlation_matrix=correlation_matrix,
        long_run_correlation=long_run_correlation,
        alpha=0.04,
        beta=0.93,
        regime_anchor=regime_anchor,
        estimation_mode="conservative_fallback",
        is_degraded=True,
        notes=dcc_notes,
    )

    jump_notes = [
        "conservative_fallback jump overlay applied; not fully estimated",
    ]
    event_counts: dict[str, int] = {bucket: 0 for bucket in buckets}
    events = list(_obj(jump_history).get("events", []) if jump_history is not None else [])
    for event in events:
        bucket = str(_obj(event).get("bucket") or "").strip()
        if bucket in event_counts:
            event_counts[bucket] += 1
    jump_probability_1m: dict[str, float] = {}
    jump_loss: dict[str, float] = {}
    policy_stress = any(
        [
            bool(policy_summary.get("manual_review_required")),
            str(policy_summary.get("macro_uncertainty") or "").lower() == "high",
            str(policy_summary.get("liquidity_stress") or "").lower() == "high",
        ]
    )
    for bucket in buckets:
        base_prob = 0.01 if "bond" in bucket else 0.02 if "gold" in bucket else 0.08 if "sat" in bucket else 0.05
        probability = base_prob + (0.03 * event_counts.get(bucket, 0))
        if policy_stress and "bond" not in bucket:
            probability += 0.02
        if market_state.risk_environment == "high":
            probability += 0.01
        jump_probability_1m[bucket] = _clip(probability, 0.0, 0.30)
        jump_loss[bucket] = _clip(
            annualized_volatility.get(bucket, _default_volatility(bucket)) * (1.10 + 0.10 * event_counts.get(bucket, 0)),
            0.03,
            0.35,
        )
    if events:
        jump_notes.append(f"jump events absorbed count={len(events)}")
    if policy_stress:
        jump_notes.append(
            "policy signal overlay "
            f"macro_uncertainty={policy_summary.get('macro_uncertainty') or 'unknown'} "
            f"liquidity_stress={policy_summary.get('liquidity_stress') or 'unknown'}"
        )
    jump_overlay_state = JumpOverlayState(
        version=_version_id("jump_overlay_state", created_at),
        event_count=len(events),
        jump_probability_1m=jump_probability_1m,
        jump_loss=jump_loss,
        stress_source=_first_text(policy_summary.get("policy_regime"), regime_anchor, "market_state"),
        estimation_mode="conservative_fallback",
        is_degraded=True,
        notes=jump_notes,
    )

    notes = [
        "distribution model state uses conservative_fallback parameters; not fully estimated",
        "wave 1 contract scaffold only; component states are conservative seeds until full estimation lands",
    ]
    if historical_dataset is not None:
        notes.append(
            "historical dataset attached "
            f"source={historical_dataset.source_name or 'unknown'} "
            f"version={historical_dataset.version_id or 'unknown'}"
        )
    if regime_anchor:
        notes.append(f"regime anchor={regime_anchor}")
    if proxy_mapping is not None:
        notes.append(f"bucket proxy mapping attached buckets={len(proxy_mapping.bucket_to_proxy)}")
    if policy_summary:
        notes.append(
            "policy signal absorbed "
            f"confidence={float(policy_summary.get('confidence', 0.0) or 0.0):.2f}"
        )
    return DistributionModelState(
        as_of=created_at.isoformat().replace("+00:00", "Z"),
        source_bundle_id=bundle_id,
        version=_version_id("distribution_model_state", created_at),
        garch_state=garch_state,
        dcc_state=dcc_state,
        jump_overlay_state=jump_overlay_state,
        historical_dataset_version=_first_text(
            _obj(historical_dataset).get("version_id") if historical_dataset is not None else None,
            market_state.historical_dataset_version,
            historical_panel.version_id if historical_panel is not None else None,
        ),
        regime_anchor=regime_anchor,
        policy_signal_ids=list(market_state.policy_signal_ids),
        bucket_proxy_map=dict(proxy_mapping.bucket_to_proxy) if proxy_mapping is not None else {},
        estimation_mode="conservative_fallback",
        is_degraded=True,
        notes=notes,
    )


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
    historical_panel = build_historical_return_panel(_obj(market_raw.get("historical_return_panel")))
    historical_dataset = build_historical_dataset_snapshot(
        _obj(bundle_data.get("historical_dataset_metadata") or market_raw.get("historical_dataset"))
        or historical_panel
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


def update_goal_solver_params(
    market_assumptions: MarketAssumptions,
    distribution_model_state: DistributionModelState,
    prior_params: GoalSolverParams | dict[str, Any] | None,
    created_at: Any,
) -> GoalSolverParams:
    params = _coerce_goal_solver_params(prior_params, market_assumptions)
    params.version = _version_id("goal_solver_params", created_at)
    params.market_assumptions = market_assumptions
    params.distribution_input = _distribution_input_from_model_state(distribution_model_state)
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
    distribution_model_state: DistributionModelState,
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
        distribution_model_state_version=distribution_model_state.version,
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
        auto_select_simulation_mode=bool(data.get("auto_select_simulation_mode", True)),
        distribution_input=distribution_input,
    )


def _distribution_input_from_model_state(
    distribution_model_state: DistributionModelState,
) -> DistributionInput:
    garch_state = distribution_model_state.garch_state
    dcc_state = distribution_model_state.dcc_state
    jump_overlay_state = distribution_model_state.jump_overlay_state
    historical_ready = bool(str(distribution_model_state.historical_dataset_version or "").strip())

    garch_input: dict[str, dict[str, float]] = {}
    if historical_ready:
        jump_probability = jump_overlay_state.jump_probability_1m
        garch_input = {
            bucket: {
                "annualized_volatility": float(garch_state.annualized_volatility.get(bucket, 0.0) or 0.0),
                "long_run_variance": float(garch_state.long_run_variance.get(bucket, 0.0) or 0.0),
                "alpha": float(garch_state.shock_loading.get(bucket, 0.0) or 0.0),
                "beta": float(garch_state.persistence.get(bucket, 0.0) or 0.0),
                "nu": float(
                    _clip(
                        10.5
                        - 16.0 * float(garch_state.annualized_volatility.get(bucket, 0.0) or 0.0)
                        - 18.0 * float(jump_probability.get(bucket, 0.0) or 0.0),
                        3.5,
                        10.0,
                    )
                ),
            }
            for bucket in garch_state.annualized_volatility
        }
    jump_drag = 0.0
    if jump_overlay_state.jump_probability_1m and jump_overlay_state.jump_loss:
        jump_drag = sum(
            float(jump_overlay_state.jump_probability_1m.get(bucket, 0.0) or 0.0)
            * float(jump_overlay_state.jump_loss.get(bucket, 0.0) or 0.0)
            for bucket in jump_overlay_state.jump_probability_1m
        ) / max(len(jump_overlay_state.jump_probability_1m), 1)
    jump_vol_multiplier = 1.0 + min(
        sum(float(value or 0.0) for value in jump_overlay_state.jump_probability_1m.values()),
        1.0,
    )
    dcc_input: dict[str, Any] = {}
    if historical_ready and dcc_state.correlation_matrix:
        dcc_input = {
            "correlation_matrix": {
                bucket: {peer: float(value) for peer, value in row.items()}
                for bucket, row in dcc_state.correlation_matrix.items()
            },
            "long_run_correlation": {
                bucket: {peer: float(value) for peer, value in row.items()}
                for bucket, row in dcc_state.long_run_correlation.items()
            },
            "alpha": float(dcc_state.alpha),
            "beta": float(dcc_state.beta),
            "regime_anchor": dcc_state.regime_anchor,
        }
    jump_input: dict[str, Any] = {}
    if historical_ready and jump_overlay_state.event_count > 0:
        bucket_jump_probability = {
            bucket: float(value) for bucket, value in jump_overlay_state.jump_probability_1m.items()
        }
        bucket_jump_loss = {
            bucket: float(value) for bucket, value in jump_overlay_state.jump_loss.items()
        }
        max_bucket_probability = max(bucket_jump_probability.values(), default=0.0)
        max_bucket_loss = max(bucket_jump_loss.values(), default=0.0)
        stress_source = str(jump_overlay_state.stress_source or "").lower()
        systemic_probability = max_bucket_probability * 0.5
        if stress_source in {"tightening", "high_volatility", "liquidity_stress"}:
            systemic_probability += 0.02
        systemic_scale = max_bucket_loss * (2.0 if stress_source in {"tightening", "high_volatility"} else 1.5)
        jump_input = {
            "expected_jump_drag": float(jump_drag),
            "jump_vol_multiplier": float(jump_vol_multiplier),
            "event_count": float(jump_overlay_state.event_count),
            "bucket_jump_probability_1m": bucket_jump_probability,
            "bucket_jump_loss": bucket_jump_loss,
            "systemic_jump_probability_1m": float(_clip(systemic_probability, 0.0, 0.20)),
            "systemic_jump_scale": float(_clip(systemic_scale, 0.25, 1.25)),
            "stress_source": jump_overlay_state.stress_source,
        }
    return DistributionInput(
        garch_t_state=garch_input,
        dcc_state=dcc_input,
        jump_state=jump_input,
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
    distribution_model_state = build_distribution_model_state(
        bundle_data,
        market_state,
        market_assumptions,
    )

    goal_solver_params = update_goal_solver_params(
        market_assumptions,
        distribution_model_state,
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
        distribution_model_state=distribution_model_state,
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
        distribution_model_state=distribution_model_state,
        calibration_quality=calibration_quality,
        degraded_domains=degraded_domains,
        notes=notes,
        param_version_meta=param_version_meta,
    )
