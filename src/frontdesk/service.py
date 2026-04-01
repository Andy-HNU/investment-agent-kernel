from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from orchestrator.engine import run_orchestrator
from shared.goal_semantics import build_goal_semantics
from shared.profile_dimensions import build_profile_dimensions, goal_priority_from_dimensions
from shared.product_defaults import (
    build_default_account_raw,
    build_default_allocation_input,
    build_default_behavior_raw,
    build_default_constraint_raw,
    build_default_goal_raw,
    build_default_market_raw,
)
from shared.onboarding import UserOnboardingProfile, build_user_onboarding_inputs
from shared.profile_parser import parse_profile_semantics

from frontdesk.adapter import FrontdeskExternalSnapshotAdapter
from frontdesk.external_data import (
    ExternalSnapshotAdapterError,
    apply_external_snapshot_overrides,
    fetch_external_snapshot,
    merge_external_input_provenance,
    profile_patch_from_external_snapshot,
)
from frontdesk.storage import FrontdeskStore


DEFAULT_DB_PATH = Path("/root/AndyFtp/investment_system_codex_ready_repo/data/investment_frontdesk.sqlite")
_EXT_SOURCE_LABELS = {
    "market_raw": "市场输入",
    "account_raw": "账户输入",
    "behavior_raw": "行为输入",
    "live_portfolio": "账户快照",
}
_MONTHLY_EVENT_PROFILE_FIELDS = {
    "display_name",
    "current_total_assets",
    "current_holdings",
    "current_weights",
    "restrictions",
    "goal_priority",
    "goal_amount_basis",
    "goal_amount_scope",
    "tax_assumption",
    "fee_assumption",
    "contribution_commitment_confidence",
    "monthly_contribution_stability",
    "risk_tolerance_score",
    "risk_capacity_score",
    "loss_limit",
    "liquidity_need_level",
    "account_type",
    "review_frequency",
    "manual_confirmation_threshold",
    "allowed_buckets",
    "forbidden_buckets",
    "preferred_themes",
    "forbidden_themes",
    "qdii_allowed",
    "profile_parse_notes",
    "profile_parse_warnings",
    "requires_confirmation",
    "goal_semantics",
    "profile_dimensions",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _serialize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return dict(result)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _profile_to_dict(profile: UserOnboardingProfile | dict[str, Any]) -> dict[str, Any]:
    if isinstance(profile, UserOnboardingProfile):
        return profile.to_dict()
    return dict(profile)


def _profile_model(profile: dict[str, Any]) -> UserOnboardingProfile:
    return UserOnboardingProfile(**profile)


def _external_snapshot_payload(source: str | Path | None) -> dict[str, Any] | None:
    if source is None:
        return None
    adapter = FrontdeskExternalSnapshotAdapter(source)
    loaded = adapter.load()
    payload = deepcopy(loaded.payload)
    metadata = {
        "source": loaded.source,
        "source_kind": loaded.source_kind,
        "fetched_at": loaded.fetched_at,
        "provider_name": "snapshot_source",
        "domains": {
            key: {
                "status": "fresh",
                "fetched_at": loaded.fetched_at,
            }
            for key in ("market_raw", "account_raw", "behavior_raw", "live_portfolio")
            if isinstance(payload.get(key), dict)
        },
    }
    payload.setdefault(
        "external_snapshot_meta",
        metadata,
    )
    payload.setdefault(
        "external_metadata",
        {
            "provider_name": metadata["provider_name"],
            "fetched_at": metadata["fetched_at"],
            "domains": dict(metadata["domains"]),
        },
    )
    return payload


def _mapping_from_source(source: str | Path | dict[str, Any] | None, *, option_name: str) -> dict[str, Any] | None:
    if source is None:
        return None
    if isinstance(source, dict):
        return deepcopy(source)
    source_text = str(source).strip()
    parsed = urlparse(source_text)
    if parsed.scheme == "file":
        source_path = Path(unquote(parsed.path))
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    elif source_text.startswith("{"):
        payload = json.loads(source_text)
    else:
        source_path = Path(source_text)
        try:
            if source_path.exists():
                payload = json.loads(source_path.read_text(encoding="utf-8"))
            else:
                payload = json.loads(source_text)
        except OSError:
            payload = json.loads(source_text)
    if not isinstance(payload, dict):
        raise ValueError(f"{option_name} must decode to an object")
    return payload


def _stringify_external_snapshot_config(config_source: str | Path | dict[str, Any] | None) -> str | None:
    if config_source is None:
        return None
    if isinstance(config_source, (str, Path)):
        return str(config_source)
    return json.dumps(config_source, ensure_ascii=False, sort_keys=True)


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = deepcopy(base)
        for key, value in patch.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(patch)


def _external_snapshot_items(external_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    provenance = external_payload.get("input_provenance")
    if isinstance(provenance, dict):
        source_items = provenance.get("externally_fetched") or provenance.get("items") or []
        for item in source_items:
            payload = dict(item)
            rendered = {
                "field": str(payload.get("field", "unknown")),
                "label": str(payload.get("label", payload.get("field", "unknown"))),
                "value": payload.get("value"),
                "note": payload.get("note") or payload.get("detail"),
                "source_type": "externally_fetched",
                "source_label": "外部抓取",
            }
            for key in ("detail", "as_of", "fetched_at", "freshness", "freshness_status"):
                if payload.get(key) is not None:
                    rendered[key] = deepcopy(payload.get(key))
            items.append(rendered)
    for field, label in _EXT_SOURCE_LABELS.items():
        if field in external_payload and external_payload[field] is not None:
            rendered = {
                "field": field,
                "label": label,
                "value": deepcopy(external_payload[field]),
                "note": "来自外部快照源",
                "source_type": "externally_fetched",
                "source_label": "外部抓取",
            }
            domain_meta = _as_dict(
                _as_dict(external_payload.get("external_snapshot_meta")).get("domains", {})
            ).get(field)
            if isinstance(domain_meta, dict):
                if domain_meta.get("detail") is not None:
                    rendered["detail"] = deepcopy(domain_meta.get("detail"))
                if domain_meta.get("as_of") is not None:
                    rendered["as_of"] = deepcopy(domain_meta.get("as_of"))
                if domain_meta.get("fetched_at") is not None:
                    rendered["fetched_at"] = deepcopy(domain_meta.get("fetched_at"))
                if domain_meta.get("status") is not None:
                    rendered["freshness_status"] = deepcopy(domain_meta.get("status"))
            items.append(rendered)
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        deduped[str(item["field"])] = item
    return list(deduped.values())


def _parse_iso_datetime(value: Any) -> datetime | None:
    rendered = str(value or "").strip()
    if not rendered:
        return None
    if len(rendered) == 10 and rendered.count("-") == 2:
        rendered = rendered + "T00:00:00Z"
    if rendered.endswith("Z"):
        rendered = rendered[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(rendered)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_state(
    *,
    as_of: str | None,
    fetched_at: str | None,
    fallback_active: bool,
    externally_fetched_count: int,
) -> str:
    if fallback_active:
        return "fallback"
    if externally_fetched_count <= 0:
        return "default_assumed"
    as_of_dt = _parse_iso_datetime(as_of)
    fetched_dt = _parse_iso_datetime(fetched_at)
    if as_of_dt is None or fetched_dt is None:
        return "fresh"
    age_seconds = abs((fetched_dt - as_of_dt).total_seconds())
    if age_seconds <= 6 * 3600:
        return "fresh"
    if age_seconds <= 24 * 3600:
        return "aging"
    return "stale"


def _build_input_source_summary(input_provenance: dict[str, Any]) -> dict[str, Any]:
    counts = dict((input_provenance or {}).get("counts") or {})
    labels = dict((input_provenance or {}).get("source_labels") or {})
    preview: dict[str, list[dict[str, Any]]] = {}
    for source_type in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        preview[source_type] = []
        for item in list((input_provenance or {}).get(source_type, []))[:3]:
            payload = dict(item)
            preview[source_type].append(
                {
                    "field": payload.get("field"),
                    "label": payload.get("label"),
                    "note": payload.get("note"),
                }
            )
    if counts.get("externally_fetched", 0) > 0:
        message = "当前结果混合使用了用户输入、系统推断和外部抓取数据。"
    elif counts.get("default_assumed", 0) > 0:
        message = "当前结果仍包含默认假设数据，适合先体验，不应误解为实时投顾。"
    else:
        message = "当前结果主要基于用户输入和系统推断。"
    return {
        "counts": counts,
        "source_labels": labels,
        "preview": preview,
        "transparency_message": message,
    }


def _build_refresh_summary(
    *,
    workflow_type: str,
    raw_inputs: dict[str, Any] | None,
    input_provenance: dict[str, Any],
    external_snapshot_source: str | None,
    external_snapshot_status: str | None,
    external_snapshot_error: str | None,
    external_payload: dict[str, Any] | None,
    external_snapshot_config: str | None = None,
) -> dict[str, Any]:
    raw_inputs = raw_inputs or {}
    meta = _as_dict((external_payload or {}).get("external_snapshot_meta"))
    provider_meta = _as_dict((external_payload or {}).get("external_metadata"))
    if provider_meta:
        merged_meta = dict(meta)
        merged_meta.setdefault("fetched_at", provider_meta.get("fetched_at"))
        merged_meta.setdefault("provider_name", provider_meta.get("provider_name"))
        merged_meta.setdefault("as_of", provider_meta.get("as_of"))
        domains = dict(meta.get("domains") or {})
        domains.update(dict(provider_meta.get("domains") or {}))
        if domains:
            merged_meta["domains"] = domains
        meta = merged_meta
    counts = dict((input_provenance or {}).get("counts") or {})
    fetched_at_raw = meta.get("fetched_at")
    fetched_at = str(fetched_at_raw) if fetched_at_raw else None
    as_of = str(meta.get("as_of") or raw_inputs.get("as_of") or "")
    source_ref = str(meta.get("source") or external_snapshot_source or external_snapshot_config or "")
    fallback_active = bool(external_snapshot_status == "fallback" or external_snapshot_error)
    freshness = _freshness_state(
        as_of=as_of or None,
        fetched_at=fetched_at if source_ref else None,
        fallback_active=fallback_active,
        externally_fetched_count=int(counts.get("externally_fetched", 0)),
    )
    domains = sorted({str(item.get("field")) for item in (input_provenance or {}).get("externally_fetched", [])})
    if fallback_active:
        next_action = "retry_external_refresh"
        next_action_label = "外部抓取失败，先修复 provider 或重试刷新"
    elif int(counts.get("externally_fetched", 0)) <= 0:
        next_action = "configure_or_enable_provider"
        next_action_label = "当前仍主要依赖默认值，建议接入外部 provider"
    elif workflow_type in {"monthly", "event"}:
        next_action = "refresh_before_next_runtime_decision"
        next_action_label = "下一次运行时决策前先刷新外部数据"
    else:
        next_action = "refresh_before_next_review"
        next_action_label = "下一次复盘前先刷新外部数据"
    freshness_label_map = {
        "fresh": "新鲜",
        "aging": "开始变旧",
        "stale": "已陈旧",
        "fallback": "已降级",
        "default_assumed": "默认假设",
    }
    domain_details: list[dict[str, Any]] = []
    externally_fetched_items = list((input_provenance or {}).get("externally_fetched", []))
    for key in ("market_raw", "account_raw", "behavior_raw", "live_portfolio"):
        domain_meta = _as_dict((meta.get("domains") or {}).get(key))
        domain_source = "externally_fetched" if any(str(item.get("field")) == key for item in externally_fetched_items) else None
        if domain_source is None:
            for source_type in ("user_provided", "system_inferred", "default_assumed"):
                if any(str(item.get("field")) == key or str(item.get("field")).startswith(key.split("_", 1)[0]) for item in (input_provenance or {}).get(source_type, [])):
                    domain_source = source_type
                    break
        domain_state = str(domain_meta.get("status") or freshness)
        if domain_source != "externally_fetched" and not fallback_active and int(counts.get("externally_fetched", 0)) <= 0:
            domain_state = "default_assumed" if domain_source == "default_assumed" else "fresh"
        if fallback_active and domain_source != "externally_fetched":
            domain_state = "fallback"
        domain_details.append(
            {
                "domain": key,
                "label": _EXT_SOURCE_LABELS.get(key, key),
                "source_type": domain_source,
                "source_label": (input_provenance or {}).get("source_labels", {}).get(domain_source or "", domain_source),
                "freshness_state": domain_state,
                "freshness_label": freshness_label_map.get(domain_state, domain_state),
                "fetched_at": domain_meta.get("fetched_at") or (fetched_at if domain_source == "externally_fetched" else None),
                "as_of": domain_meta.get("as_of") or meta.get("as_of") or as_of or None,
                "detail": domain_meta.get("detail"),
            }
        )
    return {
        "workflow_type": workflow_type,
        "as_of": as_of or None,
        "source_ref": source_ref or None,
        "source_kind": meta.get("source_kind") or ("provider_config" if external_snapshot_config else "snapshot_source"),
        "provider_name": meta.get("provider_name"),
        "fetched_at": fetched_at if (source_ref or int(counts.get("externally_fetched", 0)) > 0) and fetched_at else None,
        "external_status": external_snapshot_status or ("fetched" if int(counts.get("externally_fetched", 0)) > 0 else None),
        "fallback_active": fallback_active,
        "freshness_state": freshness,
        "freshness_label": freshness_label_map.get(freshness, freshness),
        "externally_fetched_count": int(counts.get("externally_fetched", 0)),
        "domains": domains,
        "domain_details": domain_details,
        "next_action": next_action,
        "next_action_label": next_action_label,
        "error": external_snapshot_error,
    }


def _merge_external_provenance(
    provenance: dict[str, Any],
    external_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not external_items:
        return provenance
    merged = deepcopy(provenance)
    fetched_fields = {str(item.get("field", "unknown")) for item in external_items}
    for group in ("user_provided", "system_inferred", "default_assumed", "externally_fetched", "items"):
        entries = merged.get(group)
        if isinstance(entries, list):
            merged[group] = [item for item in entries if str(item.get("field", "unknown")) not in fetched_fields]
    merged.setdefault("externally_fetched", [])
    merged.setdefault("items", [])
    merged["externally_fetched"].extend(external_items)
    merged["items"].extend(external_items)
    counts = merged.setdefault("counts", {})
    for group in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        counts[group] = len(merged.get(group, []))
    merged.setdefault("source_labels", {}).update({"externally_fetched": "外部抓取"})
    return merged


def _apply_external_snapshot(
    *,
    raw_inputs: dict[str, Any],
    input_provenance: dict[str, Any],
    external_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not external_payload:
        return raw_inputs, input_provenance, []
    merged_raw_inputs = deepcopy(raw_inputs)
    applied_keys = (
        "market_raw",
        "account_raw",
        "behavior_raw",
        "live_portfolio",
    )
    for key in applied_keys:
        if key in external_payload and external_payload[key] is not None:
            merged_raw_inputs[key] = _deep_merge(merged_raw_inputs.get(key), external_payload[key])
    if isinstance(merged_raw_inputs.get("account_raw"), dict) or isinstance(merged_raw_inputs.get("live_portfolio"), dict):
        account_raw = deepcopy(merged_raw_inputs.get("account_raw") or {})
        live_portfolio = deepcopy(merged_raw_inputs.get("live_portfolio") or {})
        horizon = (
            live_portfolio.get("remaining_horizon_months")
            or account_raw.get("remaining_horizon_months")
            or merged_raw_inputs.get("remaining_horizon_months")
        )
        if external_payload.get("live_portfolio") is not None:
            for field in ("weights", "total_value", "available_cash", "remaining_horizon_months"):
                if field in live_portfolio and live_portfolio[field] is not None:
                    account_raw[field] = deepcopy(live_portfolio[field])
        if external_payload.get("account_raw") is not None or "live_portfolio" not in external_payload:
            for field in ("weights", "total_value", "available_cash", "remaining_horizon_months"):
                if field in account_raw and account_raw[field] is not None:
                    live_portfolio[field] = deepcopy(account_raw[field])
        if horizon is not None:
            account_raw["remaining_horizon_months"] = int(horizon)
            live_portfolio["remaining_horizon_months"] = int(horizon)
        goal_amount = (
            ((merged_raw_inputs.get("goal_solver_input") or {}).get("goal") or {}).get("goal_amount")
            or (merged_raw_inputs.get("goal_raw") or {}).get("goal_amount")
        )
        if goal_amount is not None and live_portfolio.get("total_value") is not None:
            live_portfolio["goal_gap"] = max(float(goal_amount) - float(live_portfolio["total_value"]), 0.0)
        live_portfolio.setdefault("as_of_date", str(merged_raw_inputs.get("as_of", _now_iso())).split("T", 1)[0])
        live_portfolio.setdefault("current_drawdown", 0.0)
        if account_raw:
            merged_raw_inputs["account_raw"] = account_raw
        if live_portfolio:
            merged_raw_inputs["live_portfolio"] = live_portfolio
    if isinstance(merged_raw_inputs.get("goal_solver_input"), dict):
        goal_solver_input = deepcopy(merged_raw_inputs["goal_solver_input"])
        live_portfolio = merged_raw_inputs.get("live_portfolio") or {}
        if isinstance(live_portfolio, dict) and live_portfolio.get("total_value") is not None:
            goal_solver_input["current_portfolio_value"] = live_portfolio["total_value"]
        merged_raw_inputs["goal_solver_input"] = goal_solver_input
    external_items = _external_snapshot_items(external_payload)
    merged_provenance = _merge_external_provenance(input_provenance, external_items)
    merged_raw_inputs["input_provenance"] = merged_provenance
    return merged_raw_inputs, merged_provenance, external_items


def _apply_external_provider_config(
    *,
    raw_inputs: dict[str, Any],
    input_provenance: dict[str, Any],
    external_data_config: dict[str, Any] | None,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None, str | None, str | None]:
    if not external_data_config:
        return raw_inputs, input_provenance, None, None, None, None
    fetched_snapshot = fetch_external_snapshot(
        external_data_config,
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        as_of=as_of,
    )
    merged_raw_inputs = apply_external_snapshot_overrides(
        raw_inputs,
        fetched_snapshot=fetched_snapshot,
        goal_solver_input=(raw_inputs.get("goal_solver_input") if isinstance(raw_inputs.get("goal_solver_input"), dict) else None),
    )
    merged_provenance = merge_external_input_provenance(input_provenance, fetched_snapshot)
    merged_raw_inputs["input_provenance"] = merged_provenance
    warnings = "; ".join(fetched_snapshot.warnings) if fetched_snapshot and fetched_snapshot.warnings else None
    status = "fetched" if fetched_snapshot and fetched_snapshot.provenance_items else "fallback"
    external_payload = None
    if fetched_snapshot is not None:
        external_payload = deepcopy(fetched_snapshot.raw_overrides)
        external_payload["external_metadata"] = {
            "provider_name": fetched_snapshot.provider_name,
            "fetched_at": fetched_snapshot.fetched_at,
            "requested_as_of": fetched_snapshot.requested_as_of,
            "as_of": fetched_snapshot.freshness.get("as_of"),
            "domains": dict(fetched_snapshot.freshness.get("domains") or {}),
        }
    return (
        merged_raw_inputs,
        merged_provenance,
        external_payload,
        fetched_snapshot.source_ref if fetched_snapshot is not None else None,
        status,
        warnings,
    )


def _merge_profile_override(
    base_profile: dict[str, Any],
    override_profile: dict[str, Any],
    *,
    account_profile_id: str,
) -> dict[str, Any]:
    merged = deepcopy(base_profile)
    holdings_changed = (
        "current_holdings" in override_profile
        and override_profile.get("current_holdings") is not None
        and override_profile.get("current_holdings") != base_profile.get("current_holdings")
    )
    weights_explicitly_provided = (
        "current_weights" in override_profile and override_profile.get("current_weights") is not None
    )
    if holdings_changed and not weights_explicitly_provided:
        merged["current_weights"] = None
    for key, value in override_profile.items():
        if value is not None:
            merged[key] = deepcopy(value)
    merged["account_profile_id"] = account_profile_id
    if not merged.get("display_name"):
        merged["display_name"] = str(base_profile.get("display_name") or account_profile_id)
    return merged


def _make_run_id(prefix: str, account_profile_id: str, workflow_type: str) -> str:
    timestamp = _now_iso().replace(":", "").replace("-", "")
    token = uuid4().hex[:8]
    return f"{prefix}_{account_profile_id}_{workflow_type}_{timestamp}_{token}"


def _profile_parse(profile: dict[str, Any]):
    restrictions = profile.get("restrictions") or []
    if not isinstance(restrictions, list):
        restrictions = [str(restrictions)]
    explicit_weights = _effective_explicit_current_weights(profile)
    return parse_profile_semantics(
        current_holdings=str(profile.get("current_holdings", "")),
        restrictions=[str(item) for item in restrictions],
        explicit_current_weights=explicit_weights,
    )


def _effective_explicit_current_weights(profile: dict[str, Any]) -> dict[str, float] | None:
    explicit_weights = profile.get("current_weights")
    if not isinstance(explicit_weights, dict):
        return None
    return dict(explicit_weights)


def _normalize_profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(profile)
    parsed = _profile_parse(profile)
    goal_semantics = build_goal_semantics(normalized, explicit_semantics=normalized.get("goal_semantics"))
    profile_dimensions = build_profile_dimensions(
        normalized,
        parsed_profile={**parsed.to_dict(), "requires_confirmation": bool(parsed.requires_confirmation)},
        goal_semantics=goal_semantics.to_dict(),
    )
    profile_dimensions_data = profile_dimensions.to_dict()
    if parsed.current_weights is not None:
        normalized["current_weights"] = dict(parsed.current_weights)
    elif _effective_explicit_current_weights(profile) is None:
        normalized["current_weights"] = None
    normalized["allowed_buckets"] = list(parsed.allowed_buckets)
    normalized["forbidden_buckets"] = list(parsed.forbidden_buckets)
    normalized["preferred_themes"] = list(parsed.preferred_themes)
    normalized["forbidden_themes"] = list(parsed.forbidden_themes)
    if normalized.get("qdii_allowed") is None and parsed.qdii_allowed is not None:
        normalized["qdii_allowed"] = parsed.qdii_allowed
    elif parsed.qdii_allowed is None:
        normalized["qdii_allowed"] = None
    else:
        normalized["qdii_allowed"] = parsed.qdii_allowed
    normalized["profile_parse_notes"] = list(parsed.notes)
    normalized["profile_parse_warnings"] = list(parsed.warnings)
    normalized["requires_confirmation"] = bool(parsed.requires_confirmation)
    normalized["goal_priority"] = str(normalized.get("goal_priority") or goal_priority_from_dimensions(profile_dimensions))
    normalized["goal_amount_basis"] = goal_semantics.goal_amount_basis
    normalized["goal_amount_scope"] = goal_semantics.goal_amount_scope
    normalized["tax_assumption"] = goal_semantics.tax_assumption
    normalized["fee_assumption"] = goal_semantics.fee_assumption
    normalized["contribution_commitment_confidence"] = goal_semantics.contribution_commitment_confidence
    normalized["monthly_contribution_stability"] = profile_dimensions_data["cashflow"]["monthly_contribution_stability_score"]
    normalized["risk_tolerance_score"] = profile_dimensions_data["risk"]["risk_tolerance_score"]
    normalized["risk_capacity_score"] = profile_dimensions_data["risk"]["risk_capacity_score"]
    normalized["loss_limit"] = profile_dimensions_data["risk"]["loss_limit"]
    normalized["liquidity_need_level"] = profile_dimensions_data["risk"]["liquidity_need_level"]
    normalized["account_type"] = str(normalized.get("account_type") or profile_dimensions_data["account"]["account_type"])
    normalized["review_frequency"] = str(
        normalized.get("review_frequency") or profile_dimensions_data["behavior"]["review_frequency"]
    )
    normalized["manual_confirmation_threshold"] = str(
        normalized.get("manual_confirmation_threshold")
        or profile_dimensions_data["behavior"]["manual_confirmation_threshold"]
    )
    normalized["goal_semantics"] = goal_semantics.to_dict()
    normalized["profile_dimensions"] = profile_dimensions_data
    return normalized


def _current_weights_from_profile(profile: dict[str, Any]) -> dict[str, float]:
    parsed = _profile_parse(profile)
    if parsed.current_weights is not None:
        return dict(parsed.current_weights)
    holdings_text = str(profile.get("current_holdings", "cash")).strip().lower()
    if holdings_text in {"现金", "cash", "all cash", "cash only"} or parsed.available_cash_fraction >= 0.999:
        return {}
    return {}


def _build_live_portfolio(
    profile: dict[str, Any],
    goal_solver_input: dict[str, Any],
    *,
    as_of_date: str,
) -> dict[str, Any]:
    parsed = _profile_parse(profile)
    weights = _current_weights_from_profile(profile)
    total_value = float(profile["current_total_assets"])
    goal_amount = float(_goal(goal_solver_input)["goal_amount"])
    horizon_months = int(_goal(goal_solver_input)["horizon_months"])
    return {
        "weights": weights,
        "total_value": total_value,
        "available_cash": round(total_value * parsed.available_cash_fraction, 2)
        if parsed.available_cash_fraction > 0
        else (total_value if sum(weights.values()) == 0.0 else 0.0),
        "goal_gap": max(goal_amount - total_value, 0.0),
        "remaining_horizon_months": horizon_months,
        "as_of_date": as_of_date,
        "current_drawdown": 0.0,
    }


def _goal(goal_solver_input: dict[str, Any]) -> dict[str, Any]:
    return dict(goal_solver_input.get("goal", {}))


def _workflow_input_provenance(
    *,
    workflow_type: str,
    profile: dict[str, Any],
    goal_solver_input: dict[str, Any],
    live_portfolio: dict[str, Any],
    baseline_run_id: str | None,
    event_request: bool,
    event_context: dict[str, Any] | None,
    profile_confirmed: bool,
) -> dict[str, Any]:
    parsed = _profile_parse(profile)
    goal_semantics = build_goal_semantics(profile, explicit_semantics=profile.get("goal_semantics"))
    profile_dimensions = build_profile_dimensions(
        profile,
        parsed_profile={**parsed.to_dict(), "requires_confirmation": bool(parsed.requires_confirmation)},
        goal_semantics=goal_semantics.to_dict(),
    )
    profile_dimensions_data = profile_dimensions.to_dict()
    user_provided: list[dict[str, Any]] = []
    system_inferred = [
        {
            "field": "baseline.run_id",
            "label": "沿用基线",
            "value": baseline_run_id or "loaded_from_sqlite",
            "note": "月度/事件流程继续沿用最近已保存基线",
        },
        {
            "field": "goal.goal_amount",
            "label": "当前目标期末总资产",
            "value": float(_goal(goal_solver_input)["goal_amount"]),
            "note": "来自最近已保存基线",
        },
        {
            "field": "goal.horizon_months",
            "label": "当前剩余期限（月）",
            "value": int(_goal(goal_solver_input)["horizon_months"]),
            "note": "来自最近已保存基线",
        },
        {
            "field": "goal.goal_gap",
            "label": "目标缺口",
            "value": live_portfolio["goal_gap"],
            "note": "由当前资产和基线目标期末总资产推导",
        },
    ]
    account_items = [
        ("account_profile.display_name", "账户名", profile["display_name"]),
        ("account.total_value", "当前总资产", float(profile["current_total_assets"])),
        ("account.current_holdings", "当前持仓", profile.get("current_holdings", "cash")),
    ]
    for field, label, value in account_items:
        target = user_provided if profile_confirmed else system_inferred
        item = {"field": field, "label": label, "value": value}
        if not profile_confirmed:
            item["note"] = "沿用已保存用户画像"
        target.append(item)
    if profile.get("current_weights") is not None or parsed.current_weights is not None:
        target = user_provided if profile_confirmed else system_inferred
        item = {
            "field": "account.current_weights",
            "label": "当前资产桶权重",
            "value": dict(profile.get("current_weights") or parsed.current_weights or {}),
        }
        if not profile_confirmed:
            item["note"] = "沿用已保存用户画像或根据自然语言重新结构化"
        target.append(item)
    restrictions = profile.get("restrictions") or []
    if restrictions:
        target = user_provided if profile_confirmed else system_inferred
        item = {"field": "account.restrictions", "label": "限制条件", "value": list(restrictions)}
        if not profile_confirmed:
            item["note"] = "沿用已保存用户画像"
        target.append(item)
    semantics_labels = {
        "goal_amount_basis": "目标金额口径",
        "goal_amount_scope": "目标范围",
        "tax_assumption": "税务口径",
        "fee_assumption": "费用口径",
        "contribution_commitment_confidence": "每月投入兑现置信度",
    }
    semantics_notes = {
        "goal_amount_basis": "当前只做透明披露，尚未单独折算通胀",
        "goal_amount_scope": goal_semantics.explanation,
        "tax_assumption": "当前 goal solver 未单独建模税差",
        "fee_assumption": "当前 goal solver 未完整建模综合费率",
        "contribution_commitment_confidence": "当前主要进入解释层和风险分层，不会伪装成已完全进入 solver",
    }
    semantics_values = goal_semantics.to_dict()
    if workflow_type == "event" and event_request:
        requested_action = (event_context or {}).get("requested_action", "rebalance_full")
        user_provided.append(
            {"field": "event.requested_action", "label": "事件请求", "value": requested_action}
        )
        for field, label in (
            ("manual_review_requested", "人工复核请求"),
            ("manual_override_requested", "人工覆盖请求"),
            ("high_risk_request", "高风险请求"),
        ):
            if field in (event_context or {}):
                user_provided.append(
                    {"field": f"event.{field}", "label": label, "value": bool((event_context or {}).get(field))}
                )
    if profile.get("current_weights") is None and parsed.current_weights is None:
        default_assumed_item = {
            "field": "account.weights",
            "label": "当前资产桶权重",
            "value": live_portfolio["weights"],
            "note": "当前持仓描述未能稳定解析，临时按全现金占位，不代表真实持仓",
        }
        default_assumed = [
            {"field": "market_raw", "label": "市场输入", "value": "product_default_market_snapshot"},
            {"field": "behavior_raw", "label": "行为输入", "value": "product_default_behavior_snapshot"},
            default_assumed_item,
        ]
    else:
        default_assumed = [
            {"field": "market_raw", "label": "市场输入", "value": "product_default_market_snapshot"},
            {"field": "behavior_raw", "label": "行为输入", "value": "product_default_behavior_snapshot"},
        ]
    for field_name, source_type in goal_semantics.field_sources.items():
        item = {
            "field": f"goal.{field_name}",
            "label": semantics_labels[field_name],
            "value": semantics_values[field_name],
            "note": semantics_notes[field_name],
        }
        if profile_confirmed and source_type == "user_provided":
            user_provided.append(item)
        elif source_type == "system_inferred":
            system_inferred.append(item)
        else:
            default_assumed.append(item)
    system_inferred.append(
        {
            "field": "profile_dimensions",
            "label": "画像分层模型",
            "value": profile_dimensions_data["model_inputs"],
            "note": "内部按 goal/risk/cashflow/account/behavior 五层建模，前台风险风格仍保留易读标签",
        }
    )
    if parsed.notes:
        system_inferred.append(
            {
                "field": "account.profile_parse_notes",
                "label": "画像解析说明",
                "value": list(parsed.notes),
                "note": "自然语言画像已被结构化处理",
            }
        )
    if parsed.warnings:
        default_assumed.append(
            {
                "field": "account.profile_parse_warnings",
                "label": "画像解析警示",
                "value": list(parsed.warnings),
                "note": "存在未解析字段，本轮结果包含显式默认假设",
            }
        )
    return {
        "user_provided": user_provided,
        "system_inferred": system_inferred,
        "default_assumed": default_assumed,
        "externally_fetched": [],
    }


def _workflow_raw_inputs(
    *,
    workflow_type: str,
    profile: dict[str, Any],
    goal_solver_input: dict[str, Any],
    as_of: str | None = None,
    event_request: bool = False,
    baseline_run_id: str | None = None,
    event_context: dict[str, Any] | None = None,
    profile_confirmed: bool = False,
) -> dict[str, Any]:
    as_of = as_of or _now_iso()
    parsed = _profile_parse(profile)
    goal_semantics = build_goal_semantics(profile, explicit_semantics=profile.get("goal_semantics"))
    profile_dimensions = build_profile_dimensions(
        profile,
        parsed_profile={**parsed.to_dict(), "requires_confirmation": bool(parsed.requires_confirmation)},
        goal_semantics=goal_semantics.to_dict(),
    )
    profile_dimensions_data = profile_dimensions.to_dict()
    live_portfolio = _build_live_portfolio(
        profile,
        goal_solver_input,
        as_of_date=as_of.split("T", 1)[0],
    )
    raw_inputs = {
        "account_profile_id": goal_solver_input["account_profile_id"],
        "as_of": as_of,
        "market_raw": build_default_market_raw(goal_solver_input),
        "account_raw": build_default_account_raw(goal_solver_input, live_portfolio),
        "goal_raw": build_default_goal_raw(goal_solver_input),
        "constraint_raw": build_default_constraint_raw(
            goal_solver_input,
            parsed_profile=parsed.to_dict(),
            profile_dimensions=profile_dimensions_data,
        ),
        "goal_semantics": goal_semantics.to_dict(),
        "profile_dimensions": profile_dimensions_data,
        "behavior_raw": build_default_behavior_raw(
            cooldown_active=workflow_type == "event" and event_request,
            cooldown_until=(as_of.split("T", 1)[0] + "T23:59:59Z") if workflow_type == "event" and event_request else None,
            override_count_90d=1 if workflow_type == "event" and event_request else 0,
        ),
        "remaining_horizon_months": _goal(goal_solver_input)["horizon_months"],
        "live_portfolio": live_portfolio,
        "profile_parse": parsed.to_dict(),
        "input_provenance": _workflow_input_provenance(
            workflow_type=workflow_type,
            profile=profile,
            goal_solver_input=goal_solver_input,
            live_portfolio=live_portfolio,
            baseline_run_id=baseline_run_id,
            event_request=event_request,
            event_context=event_context,
            profile_confirmed=profile_confirmed,
        ),
    }
    if workflow_type == "quarterly":
        raw_inputs["allocation_engine_input"] = build_default_allocation_input(
            goal_solver_input=goal_solver_input,
            parsed_profile=parsed.to_dict(),
            profile_dimensions=profile_dimensions_data,
        )
        raw_inputs["goal_solver_input"] = goal_solver_input
    if workflow_type == "event" and event_request:
        raw_inputs["user_request_context"] = {
            "requested_action": "rebalance_full",
            "manual_review_requested": True,
            "high_risk_request": True,
        }
        if event_context:
            raw_inputs["user_request_context"].update(event_context)
    return raw_inputs


def _quarterly_raw_inputs(
    *,
    profile: dict[str, Any],
    as_of: str,
    baseline_run_id: str | None,
) -> dict[str, Any]:
    bundle = build_user_onboarding_inputs(_profile_model(profile), as_of=as_of)
    raw_inputs = deepcopy(bundle.raw_inputs)
    raw_inputs.setdefault("input_provenance", {}).setdefault("system_inferred", []).append(
        {
            "field": "baseline.run_id",
            "label": "上一版基线",
            "value": baseline_run_id or "loaded_from_sqlite",
            "note": "季度复盘会基于最新画像重新生成基线",
        }
    )
    return raw_inputs


def _frontdesk_summary(
    *,
    account_profile_id: str,
    display_name: str,
    result_payload: dict[str, Any],
    db_path: Path,
    raw_inputs: dict[str, Any] | None = None,
    external_snapshot_source: str | None = None,
    external_snapshot_config: str | None = None,
    external_snapshot_status: str | None = None,
    external_snapshot_error: str | None = None,
    external_payload: dict[str, Any] | None = None,
    user_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_state = user_state or {}
    decision_card = _apply_execution_plan_guidance(
        dict(result_payload.get("decision_card") or {}),
        workflow_type=str(result_payload.get("workflow_type") or ""),
        comparison=_as_dict(user_state.get("execution_plan_comparison")),
    )
    refresh_summary = dict(
        result_payload.get("refresh_summary")
        or _build_refresh_summary(
            workflow_type=str(result_payload.get("workflow_type") or ""),
            raw_inputs=raw_inputs,
            input_provenance=decision_card.get("input_provenance", {}) or {},
            external_snapshot_source=external_snapshot_source,
            external_snapshot_status=external_snapshot_status,
            external_snapshot_error=external_snapshot_error,
            external_payload=external_payload,
            external_snapshot_config=external_snapshot_config,
        )
    )
    input_source_summary = dict(
        result_payload.get("input_source_summary")
        or _build_input_source_summary(decision_card.get("input_provenance", {}) or {})
    )
    profile_payload = _as_dict(user_state.get("profile"))
    if isinstance(profile_payload.get("profile"), dict):
        profile_payload = _as_dict(profile_payload.get("profile"))
    summary = {
        "account_profile_id": account_profile_id,
        "display_name": display_name,
        "db_path": str(db_path),
        "run_id": result_payload.get("run_id"),
        "workflow_type": result_payload.get("workflow_type"),
        "status": result_payload.get("status"),
        "decision_card": decision_card,
        "key_metrics": decision_card.get("key_metrics", {}),
        "input_provenance": decision_card.get("input_provenance", {}),
        "input_source_summary": input_source_summary,
        "candidate_options": decision_card.get("candidate_options", []),
        "goal_alternatives": decision_card.get("goal_alternatives", []),
        "refresh_summary": refresh_summary,
        "active_execution_plan": user_state.get("active_execution_plan"),
        "pending_execution_plan": user_state.get("pending_execution_plan"),
        "execution_plan_comparison": user_state.get("execution_plan_comparison"),
        "execution_feedback": user_state.get("execution_feedback"),
        "execution_feedback_summary": user_state.get("execution_feedback_summary"),
        "goal_semantics": _as_dict(profile_payload.get("goal_semantics")),
        "profile_dimensions": _as_dict(profile_payload.get("profile_dimensions")),
    }
    if external_snapshot_source is not None:
        summary["external_snapshot_source"] = external_snapshot_source
    if external_snapshot_config is not None:
        summary["external_snapshot_config"] = external_snapshot_config
    if external_snapshot_status is not None:
        summary["external_snapshot_status"] = external_snapshot_status
    if external_snapshot_error is not None:
        summary["external_snapshot_error"] = external_snapshot_error
    return summary


def _apply_execution_plan_guidance(
    decision_card: dict[str, Any],
    *,
    workflow_type: str,
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    if not comparison:
        return decision_card
    recommendation = str(comparison.get("recommendation") or "").strip()
    if recommendation not in {"keep_active", "review_replace", "replace_active"}:
        return decision_card

    card = dict(decision_card)
    changed_bucket_count = int(comparison.get("changed_bucket_count") or 0)
    product_switch_count = int(comparison.get("product_switch_count") or 0)
    max_weight_delta = float(comparison.get("max_weight_delta") or 0.0)

    if recommendation == "replace_active":
        headline = "新执行计划与当前已确认计划差异较大，建议替换当前 active plan。"
        next_step = "approve_pending_plan"
        review_condition = "after_reviewing_plan_replacement"
    elif recommendation == "review_replace":
        headline = "新执行计划与当前 active plan 有局部变化，建议人工复核后决定是否替换。"
        next_step = "review_plan_delta"
        review_condition = "after_reviewing_plan_delta"
    else:
        headline = "新执行计划与当前 active plan 基本一致，可继续沿用当前计划。"
        next_step = "keep_active_plan"
        review_condition = "after_next_scheduled_review"

    guidance = {
        "recommendation": recommendation,
        "change_level": comparison.get("change_level"),
        "headline": headline,
        "changed_bucket_count": changed_bucket_count,
        "product_switch_count": product_switch_count,
        "max_weight_delta": round(max_weight_delta, 4),
        "summary": list(comparison.get("summary") or []),
    }

    if workflow_type in {"monthly", "quarterly"}:
        summary = str(card.get("summary") or "").strip()
        if summary and headline not in summary:
            card["summary"] = f"{summary} {headline}"

    recommendation_reason = list(card.get("recommendation_reason") or [])
    if headline not in recommendation_reason:
        recommendation_reason.append(headline)
    evidence_highlights = list(card.get("evidence_highlights") or [])
    evidence_line = (
        "execution_plan_delta "
        f"recommendation={recommendation} "
        f"changed_buckets={changed_bucket_count} "
        f"product_switches={product_switch_count} "
        f"max_weight_delta={max_weight_delta:.4f}"
    )
    if evidence_line not in evidence_highlights:
        evidence_highlights.append(evidence_line)
    next_steps = list(card.get("next_steps") or [])
    if next_step not in next_steps:
        next_steps.insert(0, next_step)
    review_conditions = list(card.get("review_conditions") or [])
    if review_condition not in review_conditions:
        review_conditions.append(review_condition)

    card["recommendation_reason"] = recommendation_reason
    card["evidence_highlights"] = evidence_highlights
    card["next_steps"] = next_steps
    card["review_conditions"] = review_conditions
    card["execution_plan_guidance"] = guidance
    if recommendation == "replace_active" and str(card.get("status_badge") or "") not in {"blocked", "degraded"}:
        card["status_badge"] = "caution"
    return card


def run_frontdesk_onboarding(
    profile: UserOnboardingProfile,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    external_snapshot_source: str | Path | None = None,
    external_snapshot_config: str | Path | dict[str, Any] | None = None,
    external_data_config: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if external_snapshot_config is not None and external_data_config is not None:
        raise ValueError("use either external_snapshot_config or external_data_config, not both")
    if external_snapshot_config is not None:
        external_data_config = external_snapshot_config
    if external_snapshot_source is not None and external_data_config is not None:
        raise ValueError("use either external_snapshot_source or external_snapshot_config, not both")
    db_path = Path(db_path)
    store = FrontdeskStore(db_path)
    store.init_schema()

    onboarding = build_user_onboarding_inputs(profile)
    external_payload = None
    external_error = None
    if external_snapshot_source is not None:
        try:
            external_payload = _external_snapshot_payload(external_snapshot_source)
        except Exception as exc:  # pragma: no cover - defensive fallback
            external_error = str(exc)
    raw_inputs = deepcopy(onboarding.raw_inputs)
    input_provenance = deepcopy(onboarding.input_provenance)
    external_source_ref = str(external_snapshot_source) if external_snapshot_source is not None else None
    external_status = None
    if external_snapshot_source is not None:
        raw_inputs, input_provenance, external_items = _apply_external_snapshot(
            raw_inputs=raw_inputs,
            input_provenance=input_provenance,
            external_payload=external_payload,
        )
        external_status = "fetched" if external_items else "fallback"
    elif external_data_config is not None:
        config_payload = _mapping_from_source(external_data_config, option_name="external-data-config")
        raw_inputs, input_provenance, external_payload, external_source_ref, external_status, external_error = _apply_external_provider_config(
            raw_inputs=raw_inputs,
            input_provenance=input_provenance,
            external_data_config=config_payload,
            workflow_type="onboarding",
            account_profile_id=profile.account_profile_id,
            as_of=str(raw_inputs.get("as_of") or _now_iso()),
        )
    account_profile = _normalize_profile_payload(
        _merge_profile_override(
            _profile_to_dict(onboarding.profile),
            profile_patch_from_external_snapshot(raw_inputs, external_payload=external_payload),
            account_profile_id=onboarding.profile.account_profile_id,
        )
    )
    run_id = _make_run_id("frontdesk", onboarding.profile.account_profile_id, "onboarding")
    result = run_orchestrator(
        trigger={"workflow_type": "onboarding", "run_id": run_id},
        raw_inputs=raw_inputs,
    )
    payload = _serialize_result(result)
    payload["external_snapshot_source"] = external_source_ref
    payload["external_snapshot_config"] = _stringify_external_snapshot_config(external_data_config)
    payload["external_snapshot_status"] = external_status
    payload["external_snapshot_error"] = external_error
    payload["input_source_summary"] = _build_input_source_summary(input_provenance)
    payload["refresh_summary"] = _build_refresh_summary(
        workflow_type="onboarding",
        raw_inputs=raw_inputs,
        input_provenance=input_provenance,
        external_snapshot_source=external_source_ref,
        external_snapshot_status=external_status,
        external_snapshot_error=external_error,
        external_payload=external_payload,
        external_snapshot_config=_stringify_external_snapshot_config(external_data_config),
    )
    created_at = _now_iso()
    store.save_onboarding_result(
        account_profile=account_profile,
        onboarding_result=payload,
        input_provenance=input_provenance,
        created_at=created_at,
    )
    user_state = store.load_user_state(onboarding.profile.account_profile_id)
    persisted_payload = dict(payload)
    if user_state is not None and user_state.get("decision_card"):
        persisted_payload["decision_card"] = user_state["decision_card"]
    summary = _frontdesk_summary(
        account_profile_id=onboarding.profile.account_profile_id,
        display_name=onboarding.profile.display_name,
        result_payload=persisted_payload,
        db_path=db_path,
        raw_inputs=raw_inputs,
        external_snapshot_source=external_source_ref,
        external_snapshot_config=_stringify_external_snapshot_config(external_data_config),
        external_snapshot_status=external_status,
        external_snapshot_error=external_error,
        external_payload=external_payload,
        user_state=user_state,
    )
    summary["workflow"] = "onboard"
    summary["user_state"] = user_state
    return summary


def run_frontdesk_followup(
    *,
    account_profile_id: str,
    workflow_type: str,
    db_path: str | Path = DEFAULT_DB_PATH,
    event_request: bool = False,
    profile: UserOnboardingProfile | dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    external_snapshot_source: str | Path | None = None,
    external_snapshot_config: str | Path | dict[str, Any] | None = None,
    external_data_config: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if workflow_type not in {"monthly", "event", "quarterly"}:
        raise ValueError(f"unsupported workflow_type: {workflow_type}")
    if external_snapshot_config is not None and external_data_config is not None:
        raise ValueError("use either external_snapshot_config or external_data_config, not both")
    if external_snapshot_config is not None:
        external_data_config = external_snapshot_config
    if external_snapshot_source is not None and external_data_config is not None:
        raise ValueError("use either external_snapshot_source or external_snapshot_config, not both")
    db_path = Path(db_path)
    store = FrontdeskStore(db_path)
    store.init_schema()

    snapshot = store.get_frontdesk_snapshot(account_profile_id)
    if snapshot is None or snapshot.get("latest_baseline") is None:
        raise ValueError(f"no saved onboarding baseline for {account_profile_id}")

    saved_profile = snapshot["profile"]["profile"]
    active_profile = dict(saved_profile)
    override_profile = _profile_to_dict(profile) if profile is not None else None
    if override_profile is not None and workflow_type in {"monthly", "event"}:
        disallowed = []
        for field, value in override_profile.items():
            if field not in _MONTHLY_EVENT_PROFILE_FIELDS and saved_profile.get(field) != value:
                disallowed.append(field)
        if disallowed:
            raise ValueError(
                "monthly/event profile updates only support account snapshot fields; "
                "use quarterly or onboarding to change goal settings: "
                + ", ".join(sorted(disallowed))
            )
    if profile is not None:
        active_profile = _merge_profile_override(
            active_profile,
            override_profile or {},
            account_profile_id=account_profile_id,
        )
    active_profile = _normalize_profile_payload(active_profile)
    if str(active_profile.get("account_profile_id", account_profile_id)) != account_profile_id:
        raise ValueError("profile_json account_profile_id does not match requested account_profile_id")

    baseline = snapshot["latest_baseline"]
    goal_solver_input = deepcopy(baseline["goal_solver_input"])
    goal_solver_output = deepcopy(baseline["goal_solver_output"])
    event_flag = workflow_type == "event" and (
        event_request
        or bool(event_context)
    )
    as_of = _now_iso()
    raw_inputs = (
        _quarterly_raw_inputs(
            profile=active_profile,
            as_of=as_of,
            baseline_run_id=baseline["run_id"],
        )
        if workflow_type == "quarterly"
        else _workflow_raw_inputs(
            workflow_type=workflow_type,
            profile=active_profile,
            goal_solver_input=goal_solver_input,
            as_of=as_of,
            event_request=event_flag,
            baseline_run_id=baseline["run_id"],
            event_context=event_context,
            profile_confirmed=profile is not None,
        )
    )
    external_payload = None
    external_error = None
    external_source_ref = str(external_snapshot_source) if external_snapshot_source is not None else None
    external_status = None
    if external_snapshot_source is not None:
        try:
            external_payload = _external_snapshot_payload(external_snapshot_source)
        except Exception as exc:  # pragma: no cover - defensive fallback
            external_error = str(exc)
    input_provenance = raw_inputs.get("input_provenance") or {}
    if external_snapshot_source is not None:
        raw_inputs, input_provenance, external_items = _apply_external_snapshot(
            raw_inputs=raw_inputs,
            input_provenance=input_provenance,
            external_payload=external_payload,
        )
        external_status = "fetched" if external_items else "fallback"
    elif external_data_config is not None:
        config_payload = _mapping_from_source(external_data_config, option_name="external-data-config")
        try:
            raw_inputs, input_provenance, external_payload, external_source_ref, external_status, external_error = _apply_external_provider_config(
                raw_inputs=raw_inputs,
                input_provenance=input_provenance,
                external_data_config=config_payload,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=str(raw_inputs.get("as_of") or as_of),
            )
        except ExternalSnapshotAdapterError:
            raise
    active_profile = _merge_profile_override(
        active_profile,
        profile_patch_from_external_snapshot(raw_inputs, external_payload=external_payload),
        account_profile_id=account_profile_id,
    )
    active_profile = _normalize_profile_payload(active_profile)
    run_id = _make_run_id("frontdesk", account_profile_id, workflow_type)
    result = run_orchestrator(
        trigger={
            "workflow_type": workflow_type,
            "run_id": run_id,
            "manual_review_requested": bool((event_context or {}).get("manual_review_requested", event_flag)),
            "manual_override_requested": bool((event_context or {}).get("manual_override_requested", event_flag)),
            "high_risk_request": bool((event_context or {}).get("high_risk_request", event_flag)),
        },
        raw_inputs=raw_inputs,
        prior_solver_output=goal_solver_output,
        prior_solver_input=goal_solver_input,
    )
    payload = _serialize_result(result)
    payload["external_snapshot_source"] = external_source_ref
    payload["external_snapshot_config"] = _stringify_external_snapshot_config(external_data_config)
    payload["external_snapshot_status"] = external_status
    payload["external_snapshot_error"] = external_error
    payload["input_source_summary"] = _build_input_source_summary(input_provenance)
    payload["refresh_summary"] = _build_refresh_summary(
        workflow_type=workflow_type,
        raw_inputs=raw_inputs,
        input_provenance=input_provenance,
        external_snapshot_source=external_source_ref,
        external_snapshot_status=external_status,
        external_snapshot_error=external_error,
        external_payload=external_payload,
        external_snapshot_config=_stringify_external_snapshot_config(external_data_config),
    )
    created_at = _now_iso()
    normalized_provenance = store.save_run_artifacts(
        account_profile_id=account_profile_id,
        run_id=payload["run_id"],
        workflow_type=payload["workflow_type"],
        status=payload["status"],
        decision_card=payload.get("decision_card") or {},
        result_payload=payload,
        input_provenance=input_provenance,
        created_at=created_at,
    )
    payload.setdefault("decision_card", {})["input_provenance"] = normalized_provenance
    if profile is not None or profile_patch_from_external_snapshot(raw_inputs, external_payload=external_payload):
        store.upsert_user_profile(
            account_profile_id=account_profile_id,
            display_name=str(active_profile.get("display_name", snapshot["profile"]["display_name"])),
            profile=active_profile,
            created_at=created_at,
        )
    if (
        workflow_type == "quarterly"
        and payload.get("goal_solver_output") is not None
        and str((payload.get("decision_card") or {}).get("card_type") or "") != "blocked"
    ):
        store.save_baseline(
            account_profile_id=account_profile_id,
            run_id=payload["run_id"],
            workflow_type=payload["workflow_type"],
            goal_solver_input=(payload.get("card_build_input") or {}).get("goal_solver_input") or raw_inputs.get("goal_solver_input") or goal_solver_input,
            goal_solver_output=payload.get("goal_solver_output") or {},
            decision_card=payload.get("decision_card") or {},
            input_provenance=normalized_provenance,
            result_payload=payload,
            created_at=created_at,
        )
    user_state = store.load_user_state(account_profile_id)
    return _frontdesk_summary(
        account_profile_id=account_profile_id,
        display_name=str(active_profile.get("display_name", snapshot["profile"]["display_name"])),
        result_payload=payload,
        db_path=db_path,
        raw_inputs=raw_inputs,
        external_snapshot_source=external_source_ref,
        external_snapshot_config=_stringify_external_snapshot_config(external_data_config),
        external_snapshot_status=external_status,
        external_snapshot_error=external_error,
        external_payload=external_payload,
        user_state=user_state,
    )


def load_frontdesk_snapshot(
    account_profile_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    store = FrontdeskStore(db_path)
    store.init_schema()
    snapshot = store.get_frontdesk_snapshot(account_profile_id)
    if snapshot is None:
        return None
    latest_run = dict(snapshot.get("latest_run") or {})
    result_payload = dict(latest_run.get("result_payload") or {})
    decision_card = dict(latest_run.get("decision_card") or {})
    snapshot["refresh_summary"] = dict(
        result_payload.get("refresh_summary")
        or _build_refresh_summary(
            workflow_type=str(latest_run.get("workflow_type") or ""),
            raw_inputs=result_payload.get("raw_inputs") if isinstance(result_payload.get("raw_inputs"), dict) else None,
            input_provenance=decision_card.get("input_provenance", {}) or {},
            external_snapshot_source=result_payload.get("external_snapshot_source"),
            external_snapshot_status=result_payload.get("external_snapshot_status"),
            external_snapshot_error=result_payload.get("external_snapshot_error"),
            external_payload=None,
            external_snapshot_config=result_payload.get("external_snapshot_config"),
        )
    )
    snapshot["input_source_summary"] = dict(
        result_payload.get("input_source_summary")
        or _build_input_source_summary(decision_card.get("input_provenance", {}) or {})
    )
    return snapshot


def load_user_state(
    account_profile_id: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    store = FrontdeskStore(db_path)
    store.init_schema()
    user_state = store.load_user_state(account_profile_id)
    if user_state is None:
        return None
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    if snapshot is not None:
        user_state["refresh_summary"] = snapshot.get("refresh_summary")
        user_state["input_source_summary"] = snapshot.get("input_source_summary")
    return user_state


def record_frontdesk_execution_feedback(
    *,
    account_profile_id: str,
    source_run_id: str,
    user_executed: bool | None,
    actual_action: str | None = None,
    executed_at: str | None = None,
    note: str | None = None,
    feedback_source: str = "user",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    db_path = Path(db_path)
    store = FrontdeskStore(db_path)
    store.init_schema()
    recorded_at = _now_iso()
    record = store.record_execution_feedback(
        account_profile_id=account_profile_id,
        source_run_id=source_run_id,
        user_executed=user_executed,
        actual_action=actual_action,
        executed_at=executed_at,
        note=note,
        feedback_source=feedback_source,
        recorded_at=recorded_at,
    )
    user_state = store.load_user_state(account_profile_id)
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    return {
        "workflow": "feedback",
        "status": "recorded",
        "account_profile_id": account_profile_id,
        "source_run_id": source_run_id,
        "db_path": str(db_path),
        "recorded_at": recorded_at,
        "execution_feedback": _as_dict(record),
        "execution_feedback_summary": (snapshot or {}).get("execution_feedback_summary"),
        "refresh_summary": (snapshot or {}).get("refresh_summary"),
        "user_state": user_state,
    }


def approve_frontdesk_execution_plan(
    *,
    account_profile_id: str,
    plan_id: str,
    plan_version: int,
    approved_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    db_path = Path(db_path)
    store = FrontdeskStore(db_path)
    store.init_schema()
    approved_timestamp = approved_at or _now_iso()
    record = store.approve_execution_plan(
        account_profile_id=account_profile_id,
        plan_id=plan_id,
        plan_version=int(plan_version),
        approved_at=approved_timestamp,
    )
    user_state = store.load_user_state(account_profile_id)
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    return {
        "workflow": "approve_plan",
        "status": "approved",
        "account_profile_id": account_profile_id,
        "db_path": str(db_path),
        "approved_at": approved_timestamp,
        "approved_execution_plan": _as_dict(record),
        "active_execution_plan": (snapshot or {}).get("active_execution_plan"),
        "pending_execution_plan": (snapshot or {}).get("pending_execution_plan"),
        "execution_plan_comparison": (snapshot or {}).get("execution_plan_comparison"),
        "refresh_summary": (snapshot or {}).get("refresh_summary"),
        "user_state": user_state,
    }
