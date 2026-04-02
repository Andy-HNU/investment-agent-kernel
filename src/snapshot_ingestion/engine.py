from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from snapshot_ingestion.historical import (
    build_bucket_proxy_mapping,
    build_historical_dataset_snapshot,
    build_historical_return_panel,
    build_jump_event_history,
    build_regime_feature_snapshot,
)
from snapshot_ingestion.types import CompletenessLevel, PolicyNewsSignal, QualityFlag, SnapshotBundle


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bundle_timestamp(as_of: datetime) -> str:
    return _as_utc(as_of).strftime("%Y%m%dT%H%M%SZ")


def _generate_bundle_id(account_profile_id: str, as_of: datetime) -> str:
    return f"{account_profile_id}_{_bundle_timestamp(as_of)}"


def _quality_flag(code: str, severity: str, domain: str, message: str) -> QualityFlag:
    return QualityFlag(code=code, severity=severity, domain=domain, message=message)


def validate_market_snapshot(snap: dict[str, Any]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if not snap.get("raw_volatility"):
        flags.append(
            _quality_flag(
                "MARKET_VOLATILITY_MISSING",
                "error",
                "market",
                "raw_volatility is required",
            )
        )
    if not snap.get("liquidity_scores"):
        flags.append(
            _quality_flag(
                "MARKET_LIQUIDITY_SCORES_MISSING",
                "warn",
                "market",
                "liquidity_scores missing; downstream will use defaults",
            )
        )
    if not snap.get("valuation_z_scores"):
        flags.append(
            _quality_flag(
                "MARKET_VALUATION_ZSCORES_MISSING",
                "warn",
                "market",
                "valuation_z_scores missing; downstream will use defaults",
            )
        )
    return flags


def validate_account_snapshot(snap: dict[str, Any]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    weights = snap.get("weights") or {}
    if not weights:
        total_value = snap.get("total_value")
        available_cash = snap.get("available_cash")
        try:
            if total_value is not None and available_cash is not None and float(available_cash) >= float(total_value):
                return flags
        except (TypeError, ValueError):
            pass
        flags.append(
            _quality_flag(
                "ACCOUNT_WEIGHTS_MISSING",
                "error",
                "account",
                "weights are required",
            )
        )
    return flags


def validate_goal_snapshot(snap: dict[str, Any]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if snap.get("goal_amount") is None:
        flags.append(
            _quality_flag(
                "GOAL_AMOUNT_MISSING",
                "error",
                "goal",
                "goal_amount is required",
            )
        )
    if snap.get("horizon_months") is None:
        flags.append(
            _quality_flag(
                "GOAL_HORIZON_MISSING",
                "error",
                "goal",
                "horizon_months is required",
            )
        )
    return flags


def validate_constraint_snapshot(snap: dict[str, Any]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if not snap.get("ips_bucket_boundaries"):
        flags.append(
            _quality_flag(
                "CONSTRAINT_BUCKET_BOUNDARIES_MISSING",
                "error",
                "constraint",
                "ips_bucket_boundaries are required",
            )
        )
    return flags


def validate_behavior_snapshot(snap: dict[str, Any]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if (snap.get("override_count_90d") or 0) < 0:
        flags.append(
            _quality_flag(
                "BEHAVIOR_OVERRIDE_COUNT_INVALID",
                "warn",
                "behavior",
                "override_count_90d should not be negative",
            )
        )
    return flags


def validate_policy_news_signals(signals: list[PolicyNewsSignal]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    for signal in signals:
        if not signal.source_refs:
            flags.append(
                _quality_flag(
                    "POLICY_SIGNAL_SOURCE_REFS_MISSING",
                    "warn",
                    "market",
                    f"policy/news signal {signal.signal_id} missing source_refs",
                )
            )
        if not 0.0 <= float(signal.confidence) <= 1.0:
            flags.append(
                _quality_flag(
                    "POLICY_SIGNAL_CONFIDENCE_INVALID",
                    "warn",
                    "market",
                    f"policy/news signal {signal.signal_id} confidence out of range",
                )
            )
    return flags


def validate_bundle(bundle: SnapshotBundle) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    constraint_buckets = set((bundle.constraint or {}).get("ips_bucket_boundaries", {}).keys())
    account_buckets = set((bundle.account or {}).get("weights", {}).keys())
    is_all_cash_snapshot = False
    if not account_buckets:
        total_value = (bundle.account or {}).get("total_value")
        available_cash = (bundle.account or {}).get("available_cash")
        try:
            is_all_cash_snapshot = (
                total_value is not None
                and available_cash is not None
                and float(available_cash) >= float(total_value)
            )
        except (TypeError, ValueError):
            is_all_cash_snapshot = False
    if constraint_buckets and not constraint_buckets.issubset(account_buckets) and not is_all_cash_snapshot:
        flags.append(
            _quality_flag(
                "PARTIAL_BUCKET_COVERAGE",
                "warn",
                "bundle",
                "account weights do not fully cover constraint bucket universe",
            )
        )
    account_horizon = bundle.account.get("remaining_horizon_months")
    goal_horizon = bundle.goal.get("horizon_months")
    if (
        isinstance(account_horizon, int)
        and isinstance(goal_horizon, int)
        and abs(account_horizon - goal_horizon) > 3
    ):
        flags.append(
            _quality_flag(
                "HORIZON_MISMATCH",
                "warn",
                "bundle",
                "goal/account horizon mismatch exceeds 3 months",
            )
        )
    if bundle.behavior is None and (bundle.constraint or {}).get("cooling_period_days", 0) > 0:
        flags.append(
            _quality_flag(
                "BEHAVIOR_DOMAIN_MISSING_WITH_COOLDOWN",
                "info",
                "bundle",
                "behavior domain missing while cooling period is configured",
            )
        )
    flags.extend(validate_policy_news_signals(bundle.policy_news_signals))
    return flags


def _derive_bundle_quality(
    *,
    flags: list[QualityFlag],
    missing_domains: list[str],
) -> CompletenessLevel:
    error_domains = {
        flag.domain
        for flag in flags
        if flag.severity == "error" and flag.domain in {"market", "account", "goal", "constraint"}
    }
    if error_domains or any(domain in {"market", "account", "goal", "constraint"} for domain in missing_domains):
        return CompletenessLevel.DEGRADED
    if missing_domains or flags:
        return CompletenessLevel.PARTIAL
    return CompletenessLevel.FULL


def build_snapshot_bundle(
    account_profile_id: str,
    as_of: datetime,
    market_raw: dict,
    account_raw: dict,
    goal_raw: dict,
    constraint_raw: dict,
    behavior_raw: dict | None,
    remaining_horizon_months: int,
    policy_news_signals: list[dict[str, Any]] | list[PolicyNewsSignal] | None = None,
    historical_dataset_metadata: dict[str, Any] | None = None,
    schema_version: str = "v1.0",
) -> SnapshotBundle:
    created_at = _as_utc(as_of)
    market = dict(market_raw or {})
    account = dict(account_raw or {})
    goal = dict(goal_raw or {})
    constraint = dict(constraint_raw or {})
    behavior = None if behavior_raw is None else dict(behavior_raw)
    signal_payloads = policy_news_signals
    if signal_payloads is None:
        signal_payloads = list(market.get("policy_news_signals") or [])
    rendered_signals: list[PolicyNewsSignal] = []
    for signal in signal_payloads or []:
        if isinstance(signal, PolicyNewsSignal):
            rendered_signals.append(signal)
            continue
        signal_data = dict(signal or {})
        rendered_signals.append(
            PolicyNewsSignal(
                signal_id=str(signal_data.get("signal_id") or signal_data.get("id") or "policy_signal"),
                as_of=str(signal_data.get("as_of") or created_at.isoformat().replace("+00:00", "Z")),
                source_type=str(signal_data.get("source_type") or "analysis"),
                source_refs=[str(item) for item in list(signal_data.get("source_refs") or []) if str(item).strip()],
                policy_regime=signal_data.get("policy_regime"),
                macro_uncertainty=signal_data.get("macro_uncertainty"),
                sentiment_stress=signal_data.get("sentiment_stress"),
                liquidity_stress=signal_data.get("liquidity_stress"),
                manual_review_required=bool(signal_data.get("manual_review_required", False)),
                confidence=float(signal_data.get("confidence", 0.0) or 0.0),
                notes=[str(item) for item in list(signal_data.get("notes") or []) if str(item).strip()],
            )
        )
    historical_seed = dict(historical_dataset_metadata or market.get("historical_dataset") or {})
    historical_dataset = build_historical_dataset_snapshot(historical_seed)
    historical_dataset_metadata = historical_dataset.to_dict() if historical_dataset is not None else {}
    if historical_dataset is not None:
        market["historical_dataset"] = historical_dataset_metadata
    historical_return_panel = build_historical_return_panel(market.get("historical_return_panel"))
    regime_feature_snapshot = build_regime_feature_snapshot(market.get("regime_feature_snapshot"))
    jump_event_history = build_jump_event_history(market.get("jump_event_history"))
    bucket_proxy_mapping = build_bucket_proxy_mapping(market.get("bucket_proxy_mapping"))

    account.setdefault("remaining_horizon_months", remaining_horizon_months)
    goal.setdefault("horizon_months", remaining_horizon_months)
    missing_domains = [
        domain
        for domain, payload in (
            ("market", market),
            ("account", account),
            ("goal", goal),
            ("constraint", constraint),
            ("behavior", behavior),
        )
        if payload in (None, {})
    ]

    flags: list[QualityFlag] = []
    flags.extend(validate_market_snapshot(market))
    flags.extend(validate_account_snapshot(account))
    flags.extend(validate_goal_snapshot(goal))
    flags.extend(validate_constraint_snapshot(constraint))
    if behavior is None:
        flags.append(
            _quality_flag(
                "BEHAVIOR_DOMAIN_MISSING",
                "warn",
                "behavior",
                "behavior domain missing; downstream may use defaults",
            )
        )
    else:
        flags.extend(validate_behavior_snapshot(behavior))

    bundle = SnapshotBundle(
        bundle_id=_generate_bundle_id(account_profile_id, created_at),
        account_profile_id=account_profile_id,
        created_at=created_at,
        market=market,
        account=account,
        goal=goal,
        constraint=constraint,
        behavior=behavior,
        bundle_quality=CompletenessLevel.FULL,
        missing_domains=missing_domains,
        quality_summary=[],
        policy_news_signals=rendered_signals,
        historical_dataset_metadata=historical_dataset_metadata,
        historical_return_panel=historical_return_panel.to_dict() if historical_return_panel is not None else None,
        regime_feature_snapshot=regime_feature_snapshot.to_dict() if regime_feature_snapshot is not None else None,
        jump_event_history=jump_event_history.to_dict() if jump_event_history is not None else None,
        bucket_proxy_mapping=bucket_proxy_mapping.to_dict() if bucket_proxy_mapping is not None else None,
        schema_version=schema_version,
    )

    flags.extend(validate_bundle(bundle))
    bundle.bundle_quality = _derive_bundle_quality(flags=flags, missing_domains=missing_domains)
    bundle.quality_summary = flags
    return bundle
