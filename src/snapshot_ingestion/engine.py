from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from snapshot_ingestion.types import CompletenessLevel, QualityFlag, SnapshotBundle


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
    schema_version: str = "v1.0",
) -> SnapshotBundle:
    created_at = _as_utc(as_of)
    market = dict(market_raw or {})
    account = dict(account_raw or {})
    goal = dict(goal_raw or {})
    constraint = dict(constraint_raw or {})
    behavior = None if behavior_raw is None else dict(behavior_raw)

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
        schema_version=schema_version,
    )

    flags.extend(validate_bundle(bundle))
    bundle.bundle_quality = _derive_bundle_quality(flags=flags, missing_domains=missing_domains)
    bundle.quality_summary = flags
    return bundle
