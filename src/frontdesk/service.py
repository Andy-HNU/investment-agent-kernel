from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from orchestrator.engine import run_orchestrator
from shared.audit import (
    AuditRecord,
    AuditWindow,
    DataStatus,
    ExecutionPolicy,
    FormalPathStatus,
    FormalPathVisibility,
    EvidenceBundle,
    coerce_data_status,
    build_evidence_invariance_report,
)
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
from shared.providers.tinyshare import has_token as tinyshare_has_token

from frontdesk.adapter import FrontdeskExternalSnapshotAdapter
from frontdesk.external_data import (
    ExternalSnapshotAdapterError,
    apply_external_snapshot_overrides,
    fetch_external_snapshot,
    merge_external_input_provenance,
    profile_patch_from_external_snapshot,
)
from frontdesk.reconciliation import reconcile_observed_portfolio
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
    "allowed_wrappers",
    "forbidden_wrappers",
    "allowed_regions",
    "forbidden_regions",
    "preferred_themes",
    "forbidden_themes",
    "forbidden_risk_labels",
    "qdii_allowed",
    "profile_parse_notes",
    "profile_parse_warnings",
    "requires_confirmation",
    "goal_semantics",
    "profile_dimensions",
}

_AUTO_RUNTIME_MARKET_HISTORY_CONFIG = {
    "adapter": "market_history",
    "provider_name": "runtime_market_history",
    "provider": "tinyshare",
    "fallback_provider": "yfinance",
    "coverage_asset_class": "etf",
    "lookback_months": 36,
    "fail_open": True,
}
_FORMAL_PATH_REQUIRED_FIELDS = {"market_raw", "account_raw", "behavior_raw", "live_portfolio"}
_FORMAL_PATH_SOURCE_STATUS = {
    "user_provided": DataStatus.OBSERVED,
    "system_inferred": DataStatus.INFERRED,
    "default_assumed": DataStatus.PRIOR_DEFAULT,
    "externally_fetched": DataStatus.OBSERVED,
}
_AUDIT_SOURCE_PRIORITY = {
    "externally_fetched": 5,
    "user_provided": 4,
    "system_inferred": 3,
    "default_assumed": 2,
    "synthetic_demo": 1,
}
_AUDIT_DATA_STATUS_PRIORITY = {
    DataStatus.OBSERVED: 5,
    DataStatus.COMPUTED_FROM_OBSERVED: 4,
    DataStatus.INFERRED: 3,
    DataStatus.PRIOR_DEFAULT: 2,
    DataStatus.MANUAL_ANNOTATION: 1,
    DataStatus.SYNTHETIC_DEMO: 0,
}
_REUSE_VOLATILE_KEYS = {
    "run_id",
    "snapshot_id",
    "created_at",
    "updated_at",
    "generated_at",
    "approved_at",
    "executed_at",
    "source_run_id",
}


def _reuse_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _reuse_value(item)
            for key, item in value.items()
            if str(key) not in _REUSE_VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_reuse_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_reuse_value(item) for item in value)
    if hasattr(value, "to_dict"):
        return _reuse_value(value.to_dict())
    if hasattr(value, "__dict__"):
        return _reuse_value(dict(value.__dict__))
    return value


def _reuse_signature_basis(
    *,
    workflow_type: str,
    account_profile_id: str,
    goal_solver_input: dict[str, Any] | None,
    raw_inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_goal_solver_input = _reuse_value(dict(goal_solver_input or {}))
    if isinstance(normalized_goal_solver_input, dict):
        normalized_goal_solver_input.pop("snapshot_id", None)
    payload = {
        "workflow_type": str(workflow_type or ""),
        "account_profile_id": str(account_profile_id or ""),
        "goal_solver_input": normalized_goal_solver_input,
        "goal_semantics": _reuse_value(dict((raw_inputs or {}).get("goal_semantics") or {})),
        "profile_dimensions": _reuse_value(dict((raw_inputs or {}).get("profile_dimensions") or {})),
        "market_raw": _reuse_value(dict((raw_inputs or {}).get("market_raw") or {})),
        "account_raw": _reuse_value(dict((raw_inputs or {}).get("account_raw") or {})),
        "behavior_raw": _reuse_value(dict((raw_inputs or {}).get("behavior_raw") or {})),
        "live_portfolio": _reuse_value(dict((raw_inputs or {}).get("live_portfolio") or {})),
        "formal_path_required": bool((raw_inputs or {}).get("formal_path_required")),
        "execution_policy": str((raw_inputs or {}).get("execution_policy") or ""),
    }
    return payload


def _reuse_signature(
    *,
    workflow_type: str,
    account_profile_id: str,
    goal_solver_input: dict[str, Any] | None,
    raw_inputs: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    basis = _reuse_signature_basis(
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        goal_solver_input=goal_solver_input,
        raw_inputs=raw_inputs,
    )
    digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest, basis


def _baseline_evidence_bundle(baseline: Any | None) -> EvidenceBundle | None:
    if not baseline:
        return None
    payload = _as_dict(baseline)
    result_payload = dict(payload.get("result_payload") or {})
    return EvidenceBundle.from_any(result_payload.get("evidence_bundle"))


def _baseline_reuse_context(baseline: Any | None) -> dict[str, Any]:
    if not baseline:
        return {}
    payload = _as_dict(baseline)
    result_payload = dict(payload.get("result_payload") or {})
    reuse_context = dict(result_payload.get("reuse_context") or {})
    if reuse_context:
        return reuse_context
    return {}


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


def _mapped_probability_result_category(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if normalized == "formal_strict_result":
        return "formal_independent_result"
    if normalized in {"formal_estimated_result", "degraded_formal_result"}:
        return normalized
    return None


def _canonical_probability_method(
    *,
    resolved_result_category: str | None,
    probability_engine_result_payload: dict[str, Any],
) -> str:
    normalized = str(resolved_result_category or "").strip()
    if normalized == "formal_independent_result":
        return "product_independent_path"
    if normalized in {"formal_estimated_result", "degraded_formal_result"}:
        return "product_estimated_path"
    internal = str(probability_engine_result_payload.get("resolved_result_category") or "").strip()
    if internal == "formal_strict_result":
        return "product_independent_path"
    if internal in {"formal_estimated_result", "degraded_formal_result"}:
        return "product_estimated_path"
    return ""


def _probability_engine_scenario_ladder(probability_output: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_ladder = [
        dict(item)
        for item in list(probability_output.get("scenario_ladder") or [])
        if isinstance(item, dict)
    ]
    if explicit_ladder:
        return explicit_ladder

    scenario_comparison = [
        dict(item)
        for item in list(probability_output.get("scenario_comparison") or [])
        if isinstance(item, dict)
    ]
    ladder: list[dict[str, Any]] = []
    for item in scenario_comparison:
        pressure = dict(item.get("pressure") or {})
        recipe_result = dict(item.get("recipe_result") or {})
        path_stats = dict(recipe_result.get("path_stats") or {})
        ladder.append(
            {
                "scenario_kind": item.get("scenario_kind"),
                "label": item.get("label"),
                "pressure_level": pressure.get("market_pressure_level"),
                "pressure_score": pressure.get("market_pressure_score"),
                "success_probability": recipe_result.get("success_probability"),
                "cagr_p50": path_stats.get("cagr_p50"),
                "terminal_value_p50": path_stats.get("terminal_value_p50"),
            }
        )
    return ladder


def _canonical_probability_truth_view(
    *,
    result_payload: dict[str, Any],
    probability_engine_result_payload: dict[str, Any],
) -> dict[str, Any]:
    evidence_bundle = _as_dict(result_payload.get("evidence_bundle"))
    degradation_reasons = " ".join(str(item) for item in list(evidence_bundle.get("degradation_reasons") or []))
    static_gaussian_guard = "static_gaussian" in degradation_reasons
    probability_status = str(probability_engine_result_payload.get("run_outcome_status") or "").strip()
    internal_category = probability_engine_result_payload.get("resolved_result_category")
    mapped_category = _mapped_probability_result_category(internal_category)
    if probability_status in {"success", "degraded"}:
        if mapped_category is None:
            return {}
        normalized_status = "completed" if probability_status == "success" else "degraded"
        if static_gaussian_guard and normalized_status == "degraded":
            mapped_category = "degraded_formal_result"
        probability_output = _as_dict(probability_engine_result_payload.get("output"))
        disclosure_payload = _as_dict(probability_output.get("probability_disclosure_payload"))
        return {
            "run_outcome_status": normalized_status,
            "resolved_result_category": mapped_category,
            "product_probability_method": _canonical_probability_method(
                resolved_result_category=mapped_category,
                probability_engine_result_payload=probability_engine_result_payload,
            ),
            "disclosure_decision": {
                "result_category": mapped_category,
                "disclosure_level": disclosure_payload.get("disclosure_level"),
                "confidence_level": disclosure_payload.get("confidence_level"),
            },
            "formal_path_visibility": {
                "status": normalized_status,
                "fallback_used": False,
                "monthly_fallback_used": False,
                "bucket_fallback_used": False,
            },
        }
    explicit = dict(result_payload.get("probability_truth_view") or {})
    if explicit:
        if static_gaussian_guard and str(explicit.get("run_outcome_status") or "").strip() == "degraded":
            explicit["resolved_result_category"] = "degraded_formal_result"
            disclosure_decision = dict(explicit.get("disclosure_decision") or {})
            if disclosure_decision:
                disclosure_decision["result_category"] = "degraded_formal_result"
                explicit["disclosure_decision"] = disclosure_decision
        return explicit
    top_level_status = str(result_payload.get("run_outcome_status") or "").strip()
    top_level_category = result_payload.get("resolved_result_category")
    if top_level_status or top_level_category:
        if static_gaussian_guard and top_level_status == "degraded":
            top_level_category = "degraded_formal_result"
        return {
            "run_outcome_status": top_level_status,
            "resolved_result_category": top_level_category,
            "product_probability_method": _canonical_probability_method(
                resolved_result_category=str(top_level_category or "").strip() or None,
                probability_engine_result_payload=probability_engine_result_payload,
            ),
            "disclosure_decision": dict(result_payload.get("disclosure_decision") or {}),
            "formal_path_visibility": dict(result_payload.get("formal_path_visibility") or {}),
        }
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
            for key in (
                "detail",
                "source_ref",
                "as_of",
                "fetched_at",
                "freshness",
                "freshness_status",
                "freshness_state",
                "data_status",
                "audit_window",
            ):
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
                if domain_meta.get("source_ref") is not None:
                    rendered["source_ref"] = deepcopy(domain_meta.get("source_ref"))
                if domain_meta.get("as_of") is not None:
                    rendered["as_of"] = deepcopy(domain_meta.get("as_of"))
                if domain_meta.get("fetched_at") is not None:
                    rendered["fetched_at"] = deepcopy(domain_meta.get("fetched_at"))
                if domain_meta.get("status") is not None:
                    rendered["freshness_status"] = deepcopy(domain_meta.get("status"))
                if domain_meta.get("audit_window") is not None:
                    rendered["audit_window"] = deepcopy(domain_meta.get("audit_window"))
                if domain_meta.get("data_status") is not None:
                    rendered["data_status"] = deepcopy(domain_meta.get("data_status"))
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


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        rendered = str(item).strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        ordered.append(rendered)
    return ordered


def _coerce_audit_window(value: Any) -> AuditWindow | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if "audit_window" in value and isinstance(value.get("audit_window"), dict):
            return AuditWindow.from_any(value.get("audit_window"))
        return AuditWindow.from_any(value)
    return AuditWindow.from_any(value)


def _normalize_audit_records(
    input_provenance: dict[str, Any] | None,
    refresh_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    provenance = input_provenance or {}
    refresh = refresh_summary or {}
    domain_lookup = {
        str(item.get("domain") or ""): dict(item)
        for item in list(refresh.get("domain_details") or [])
        if str(item.get("domain") or "").strip()
    }
    items = list(provenance.get("items") or [])
    if not items:
        for source_type in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
            for item in list(provenance.get(source_type) or []):
                rendered = dict(item)
                rendered.setdefault("source_type", source_type)
                items.append(rendered)

    records: list[dict[str, Any]] = []
    for item in items:
        payload = dict(item)
        source_type = str(payload.get("source_type") or "default_assumed")
        field = str(payload.get("field") or "unknown")
        domain_meta = domain_lookup.get(field, {})
        source_ref = str(
            payload.get("source_ref")
            or (payload.get("value") if isinstance(payload.get("value"), str) else "")
            or domain_meta.get("source_ref")
            or (refresh.get("source_ref") if source_type == "externally_fetched" else "")
            or ""
        )
        as_of = str(payload.get("as_of") or domain_meta.get("as_of") or refresh.get("as_of") or "")
        record = AuditRecord.from_any(
            {
                "field": field,
                "label": payload.get("label"),
                "source_type": source_type,
                "source_label": payload.get("source_label"),
                "source_ref": source_ref,
                "as_of": as_of,
                "detail": payload.get("detail") or payload.get("note") or domain_meta.get("detail"),
                "fetched_at": payload.get("fetched_at") or domain_meta.get("fetched_at") or refresh.get("fetched_at"),
                "freshness_state": payload.get("freshness_state")
                or payload.get("freshness_status")
                or domain_meta.get("freshness_state"),
                "data_status": payload.get("data_status") or _FORMAL_PATH_SOURCE_STATUS.get(source_type, DataStatus.INFERRED),
                "audit_window": _coerce_audit_window(payload.get("audit_window"))
                or _coerce_audit_window(domain_meta.get("audit_window")),
            }
        )
        records.append(record.to_dict())
    preferred_by_field: dict[str, dict[str, Any]] = {}
    for record in records:
        field = str(record.get("field") or "").strip()
        if not field:
            continue
        current = preferred_by_field.get(field)
        if current is None or _audit_record_priority(record) > _audit_record_priority(current):
            preferred_by_field[field] = record
    ordered_fields: list[str] = []
    for record in records:
        field = str(record.get("field") or "").strip()
        if field and field not in ordered_fields:
            ordered_fields.append(field)
    return [preferred_by_field[field] for field in ordered_fields if field in preferred_by_field]


def _audit_record_priority(record: dict[str, Any]) -> tuple[int, int, int, int]:
    data_status = coerce_data_status(record.get("data_status"))
    audit_window = _coerce_audit_window(record.get("audit_window"))
    return (
        _AUDIT_SOURCE_PRIORITY.get(str(record.get("source_type") or "").strip(), 0),
        _AUDIT_DATA_STATUS_PRIORITY.get(data_status, 0),
        1 if str(record.get("source_ref") or "").strip() else 0,
        1 if audit_window is not None and audit_window.has_required_window() else 0,
    )


def _classify_formal_path_visibility(
    decision_card: dict[str, Any] | None,
    refresh_summary: dict[str, Any] | None,
    audit_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    card = decision_card or {}
    refresh = refresh_summary or {}
    records = [AuditRecord.from_any(item) for item in list(audit_records or [])]
    degraded_scope: list[str] = []
    fallback_scope: list[str] = []
    reasons: list[str] = []
    missing_audit_fields: list[str] = []

    for item in list(card.get("guardrails") or []) + list(card.get("execution_notes") or []):
        text = str(item).strip()
        if text.startswith("bundle_quality="):
            degraded_scope.append("bundle")
        elif text.startswith("calibration_quality="):
            degraded_scope.append("calibration")
        elif text.startswith("candidate_poverty="):
            degraded_scope.append("runtime_candidates")
        elif text.startswith("cooldown_active=") or text.startswith("high_risk_request="):
            degraded_scope.append("runtime_controls")

    if str(card.get("status_badge") or "").strip().lower() == "degraded" or bool(card.get("low_confidence")):
        degraded_scope.append("decision_card")
        reasons.append("decision_card flagged degraded/low_confidence")

    refresh_state = str(refresh.get("freshness_state") or "").strip().lower()
    external_status = str(refresh.get("external_status") or "").strip().lower()
    if refresh_state in {"fallback", "degraded", "stale"} or external_status == "fallback":
        fallback_scope.append("external_snapshot")
        reasons.append("external snapshot refresh is fallback/degraded")

    for detail in list(refresh.get("domain_details") or []):
        domain = str((detail or {}).get("domain") or "").strip()
        state = str((detail or {}).get("freshness_state") or "").strip().lower()
        if not domain:
            continue
        if state in {"fallback", "degraded", "stale"}:
            degraded_scope.append(domain)
            if state == "fallback":
                fallback_scope.append(domain)

    combined_text = " ".join(
        [
            str(card.get("summary") or "").strip(),
            *[str(item).strip() for item in card.get("recommendation_reason") or []],
        ]
    )
    if "synthetic_fallback_used" in combined_text or any(
        marker in combined_text for marker in ("临时参考", "候选方案不足", "不存在满足")
    ):
        fallback_scope.append("goal_solver")
        reasons.append("goal solver emitted fallback-style candidate output")

    for record in records:
        if record.field in _FORMAL_PATH_REQUIRED_FIELDS:
            if record.source_type == "externally_fetched":
                if not record.source_ref:
                    missing_audit_fields.append(f"{record.field}.source_ref")
                if not record.as_of:
                    missing_audit_fields.append(f"{record.field}.as_of")
                if record.audit_window is None or not record.audit_window.has_required_window():
                    missing_audit_fields.append(f"{record.field}.audit_window")
            if record.data_status in {DataStatus.PRIOR_DEFAULT, DataStatus.SYNTHETIC_DEMO, DataStatus.MANUAL_ANNOTATION}:
                degraded_scope.append(record.field)
                reasons.append(f"{record.field} is backed by non-formal data_status={record.data_status.value}")

    degraded_scope = _unique_strings(degraded_scope)
    fallback_scope = _unique_strings(fallback_scope)
    reasons = _unique_strings(reasons)
    missing_audit_fields = _unique_strings(missing_audit_fields)

    if str(card.get("card_type") or "") == "blocked":
        status = FormalPathStatus.BLOCKED
    elif fallback_scope:
        status = FormalPathStatus.DEGRADED
    elif degraded_scope or missing_audit_fields:
        status = FormalPathStatus.DEGRADED
    else:
        status = FormalPathStatus.COMPLETED

    recommended_action = str(card.get("recommended_action") or "").strip()
    execution_eligible = True
    execution_reason = "eligible"
    if status is not FormalPathStatus.COMPLETED:
        execution_eligible = False
        execution_reason = status.value
    elif any(item == "manual_review_required" for item in card.get("execution_notes") or []):
        execution_eligible = False
        execution_reason = "manual_review_required"
    elif recommended_action in {"", "blocked", "review", "observe", "freeze"}:
        execution_eligible = False
        execution_reason = "non_executable_recommendation"

    return FormalPathVisibility(
        status=status,
        execution_eligible=execution_eligible,
        execution_eligibility_reason=execution_reason,
        degraded_scope=degraded_scope,
        fallback_used=bool(fallback_scope),
        fallback_scope=fallback_scope,
        reasons=reasons,
        missing_audit_fields=missing_audit_fields,
    ).to_dict()


def _apply_formal_path_metadata(
    payload: dict[str, Any],
    *,
    input_provenance: dict[str, Any] | None,
    refresh_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    enriched = dict(payload)
    decision_card = dict(enriched.get("decision_card") or {})
    audit_records = _normalize_audit_records(input_provenance, refresh_summary)
    visibility = _classify_formal_path_visibility(decision_card, refresh_summary, audit_records)
    decision_card["audit_records"] = audit_records
    decision_card["formal_path_visibility"] = visibility
    enriched["decision_card"] = decision_card
    enriched["audit_records"] = audit_records
    enriched["formal_path_visibility"] = visibility
    return enriched


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
    historical_dataset_meta = _as_dict(_as_dict(raw_inputs.get("market_raw")).get("historical_dataset"))
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
        detail = {
            "domain": key,
            "label": _EXT_SOURCE_LABELS.get(key, key),
            "source_type": domain_source,
            "source_label": (input_provenance or {}).get("source_labels", {}).get(domain_source or "", domain_source),
            "source_ref": domain_meta.get("source_ref") or (source_ref if domain_source == "externally_fetched" else None),
            "data_status": domain_meta.get("data_status")
            or (_FORMAL_PATH_SOURCE_STATUS.get(domain_source or "", DataStatus.INFERRED).value if domain_source else None),
            "freshness_state": domain_state,
            "freshness_label": freshness_label_map.get(domain_state, domain_state),
            "fetched_at": domain_meta.get("fetched_at") or (fetched_at if domain_source == "externally_fetched" else None),
            "as_of": domain_meta.get("as_of") or meta.get("as_of") or as_of or None,
            "audit_window": _coerce_audit_window(domain_meta).to_dict() if _coerce_audit_window(domain_meta) else None,
            "detail": domain_meta.get("detail"),
        }
        if key == "market_raw" and historical_dataset_meta:
            detail["historical_dataset"] = {
                "dataset_id": historical_dataset_meta.get("dataset_id"),
                "version_id": historical_dataset_meta.get("version_id"),
                "source_name": historical_dataset_meta.get("source_name"),
                "source_ref": historical_dataset_meta.get("source_ref"),
                "coverage_status": historical_dataset_meta.get("coverage_status"),
                "frequency": historical_dataset_meta.get("frequency"),
                "notes": list(historical_dataset_meta.get("notes") or []),
                "audit_window": _coerce_audit_window(historical_dataset_meta).to_dict()
                if _coerce_audit_window(historical_dataset_meta)
                else None,
            }
        domain_details.append(detail)
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
        execution_as_of_date = str(merged_raw_inputs.get("as_of", _now_iso())).split("T", 1)[0]
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
        # External snapshot account/live data can carry a stale file timestamp, but once it is
        # accepted as the current followup snapshot, runtime decisions must evaluate it against
        # the current workflow execution date rather than the fixture file's embedded default.
        live_portfolio["as_of_date"] = execution_as_of_date
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
    for key in ("external_snapshot_meta", "external_metadata"):
        if external_payload.get(key) is not None:
            merged_raw_inputs[key] = deepcopy(external_payload[key])
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
        external_payload["external_snapshot_meta"] = {
            "source": fetched_snapshot.source_ref,
            "provider_name": fetched_snapshot.provider_name,
            "source_kind": "provider_config",
            "as_of": fetched_snapshot.freshness.get("as_of"),
            "fetched_at": fetched_snapshot.fetched_at,
            "domains": dict(fetched_snapshot.freshness.get("domains") or {}),
        }
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


def _maybe_apply_runtime_market_history(
    *,
    raw_inputs: dict[str, Any],
    input_provenance: dict[str, Any],
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
    external_snapshot_source: str | None,
    external_data_config: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None, str | None, str | None]:
    if external_snapshot_source is not None or external_data_config is not None:
        return raw_inputs, input_provenance, None, None, None, None
    historical_dataset = _as_dict(_as_dict(raw_inputs.get("market_raw")).get("historical_dataset"))
    if historical_dataset or not tinyshare_has_token():
        return raw_inputs, input_provenance, None, None, None, None
    return _apply_external_provider_config(
        raw_inputs=raw_inputs,
        input_provenance=input_provenance,
        external_data_config=dict(_AUTO_RUNTIME_MARKET_HISTORY_CONFIG),
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        as_of=as_of,
    )


def _mark_snapshot_primary_formal_path(
    raw_inputs: dict[str, Any],
    *,
    external_source_ref: str | None,
    external_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not external_source_ref and not external_payload:
        return raw_inputs
    enriched = deepcopy(raw_inputs)
    enriched["snapshot_primary_formal_path"] = True
    if external_source_ref:
        enriched["snapshot_primary_formal_source"] = external_source_ref
    for key in ("external_snapshot_meta", "external_metadata"):
        if external_payload is not None and external_payload.get(key) is not None:
            enriched[key] = deepcopy(external_payload[key])
    return enriched


def _normalize_observed_portfolio_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(payload or {})
    merged_portfolio = normalized.pop("merged_portfolio", None)
    observed_portfolio = normalized.pop("observed_portfolio", None)
    if isinstance(merged_portfolio, dict):
        normalized = _deep_merge(merged_portfolio, normalized)
        nested_observed = merged_portfolio.get("observed_portfolio")
        if isinstance(nested_observed, dict):
            normalized = _deep_merge(normalized, nested_observed)
    elif isinstance(observed_portfolio, dict):
        normalized = _deep_merge(normalized, observed_portfolio)

    if not isinstance(normalized.get("weights"), dict):
        normalized["weights"] = {}
    if not isinstance(normalized.get("holdings"), list):
        normalized["holdings"] = []
    if not isinstance(normalized.get("missing_fields"), list):
        normalized["missing_fields"] = list(normalized.get("missing_fields") or [])
    if normalized.get("snapshot_id") is None:
        normalized["snapshot_id"] = str(
            normalized.get("observed_snapshot_id")
            or normalized.get("snapshot_ref")
            or normalized.get("source_ref")
            or ""
        ).strip()
    if not str(normalized.get("source_kind") or "").strip():
        normalized["source_kind"] = "ocr_snapshot" if isinstance(merged_portfolio, dict) else "manual_json"
    if normalized.get("data_status") is None:
        normalized["data_status"] = "observed"
    if normalized.get("completeness_status") is None:
        normalized["completeness_status"] = "partial" if normalized["missing_fields"] else "complete"
    if normalized.get("as_of") is None and normalized.get("as_of_date") is not None:
        normalized["as_of"] = str(normalized["as_of_date"])
    if normalized.get("total_value") is not None:
        normalized["total_value"] = float(normalized["total_value"])
    if normalized.get("available_cash") is not None:
        normalized["available_cash"] = float(normalized["available_cash"])
    if normalized.get("snapshot_id"):
        normalized["snapshot_id"] = str(normalized["snapshot_id"])
    normalized["source_kind"] = str(normalized.get("source_kind") or "manual_json")
    normalized["data_status"] = str(normalized.get("data_status") or "observed")
    normalized["completeness_status"] = str(normalized.get("completeness_status") or "partial")
    normalized["missing_fields"] = [str(item) for item in normalized.get("missing_fields") or [] if str(item).strip()]
    normalized["holdings"] = [dict(item) for item in normalized.get("holdings") or [] if isinstance(item, dict)]
    normalized["weights"] = {
        str(bucket): float(weight)
        for bucket, weight in dict(normalized.get("weights") or {}).items()
        if str(bucket).strip() and weight is not None
    }
    if not normalized["weights"] and normalized["holdings"]:
        derived_weights: dict[str, float] = {}
        for holding in normalized["holdings"]:
            bucket = str(holding.get("asset_bucket") or "").strip()
            weight = holding.get("weight")
            if bucket and weight is not None:
                try:
                    derived_weights[bucket] = float(weight)
                except (TypeError, ValueError):
                    continue
        normalized["weights"] = derived_weights
    if not normalized["snapshot_id"]:
        normalized["snapshot_id"] = f"observed_{uuid4().hex[:12]}"
    if normalized.get("source_ref") is not None:
        normalized["source_ref"] = str(normalized["source_ref"])
    audit_window = normalized.get("audit_window")
    if isinstance(audit_window, dict):
        normalized["audit_window"] = deepcopy(audit_window)
    else:
        normalized["audit_window"] = None
    return normalized


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
    normalized["allowed_wrappers"] = list(parsed.allowed_wrappers)
    normalized["forbidden_wrappers"] = list(parsed.forbidden_wrappers)
    normalized["allowed_regions"] = list(parsed.allowed_regions)
    normalized["forbidden_regions"] = list(parsed.forbidden_regions)
    normalized["preferred_themes"] = list(parsed.preferred_themes)
    normalized["forbidden_themes"] = list(parsed.forbidden_themes)
    normalized["forbidden_risk_labels"] = list(parsed.forbidden_risk_labels)
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
    probability_truth_view = _canonical_probability_truth_view(
        result_payload=result_payload,
        probability_engine_result_payload=_as_dict(result_payload.get("probability_engine_result")),
    )
    classified_formal_path_visibility = dict(
        result_payload.get("formal_path_visibility")
        or _classify_formal_path_visibility(
            decision_card,
            refresh_summary,
            list(result_payload.get("audit_records") or decision_card.get("audit_records") or []),
        )
    )
    truth_formal_path_visibility = dict(probability_truth_view.get("formal_path_visibility") or {})
    formal_path_visibility = dict(classified_formal_path_visibility)
    formal_path_visibility.update(
        {
            key: value
            for key, value in truth_formal_path_visibility.items()
            if value is not None and value != ""
        }
    )
    audit_records = list(
        result_payload.get("audit_records")
        or decision_card.get("audit_records")
        or _normalize_audit_records(decision_card.get("input_provenance", {}) or {}, refresh_summary)
    )
    profile_payload = _as_dict(user_state.get("profile"))
    if isinstance(profile_payload.get("profile"), dict):
        profile_payload = _as_dict(profile_payload.get("profile"))
    evidence_bundle = dict(result_payload.get("evidence_bundle") or decision_card.get("evidence_bundle") or {})
    probability_engine_result = result_payload.get("probability_engine_result")
    probability_engine_result_payload = _as_dict(probability_engine_result)
    probability_output = _as_dict(probability_engine_result_payload.get("output"))
    probability_disclosure_payload = dict(probability_output.get("probability_disclosure_payload") or {})
    current_market_pressure = dict(probability_output.get("current_market_pressure") or {})
    scenario_comparison = list(probability_output.get("scenario_comparison") or [])
    scenario_ladder = _probability_engine_scenario_ladder(probability_output)
    goal_solver_output = _as_dict(result_payload.get("goal_solver_output"))
    if probability_engine_result_payload:
        product_probability_method = (
            probability_truth_view.get("product_probability_method")
            or _as_dict(result_payload).get("product_probability_method")
            or _as_dict(decision_card.get("probability_explanation")).get("product_probability_method")
            or _as_dict(decision_card.get("key_metrics")).get("product_probability_method")
            or _canonical_probability_method(
                resolved_result_category=resolved_result_category,
                probability_engine_result_payload=probability_engine_result_payload,
            )
        )
    else:
        product_probability_method = (
            probability_truth_view.get("product_probability_method")
            or _as_dict(result_payload).get("product_probability_method")
            or _as_dict(decision_card.get("probability_explanation")).get("product_probability_method")
            or _as_dict(decision_card.get("key_metrics")).get("product_probability_method")
            or _as_dict(goal_solver_output.get("recommended_result") or {}).get("product_probability_method")
        )
    monthly_fallback_used = evidence_bundle.get("monthly_fallback_used")
    bucket_fallback_used = evidence_bundle.get("bucket_fallback_used")
    if probability_engine_result is not None:
        if monthly_fallback_used is None:
            monthly_fallback_used = False
        if bucket_fallback_used is None:
            bucket_fallback_used = False
    run_outcome_status = (
        probability_truth_view.get("run_outcome_status")
        or result_payload.get("run_outcome_status")
        or probability_engine_result_payload.get("run_outcome_status")
    )
    resolved_result_category = (
        probability_truth_view.get("resolved_result_category")
        or result_payload.get("resolved_result_category")
        or probability_engine_result_payload.get("resolved_result_category")
    )
    disclosure_decision = dict(
        probability_truth_view.get("disclosure_decision")
        or result_payload.get("disclosure_decision")
        or (
            {
                "result_category": resolved_result_category,
                "disclosure_level": probability_disclosure_payload.get("disclosure_level"),
                "confidence_level": probability_disclosure_payload.get("confidence_level"),
            }
            if probability_engine_result_payload
            else decision_card.get("disclosure_decision")
            or {}
        )
    )
    if disclosure_decision.get("result_category") is None and resolved_result_category is not None:
        disclosure_decision["result_category"] = resolved_result_category
    summary = {
        "account_profile_id": account_profile_id,
        "display_name": display_name,
        "db_path": str(db_path),
        "run_id": result_payload.get("run_id"),
        "workflow_type": result_payload.get("workflow_type"),
        "status": result_payload.get("status"),
        "run_outcome_status": run_outcome_status or decision_card.get("run_outcome_status"),
        "resolved_result_category": resolved_result_category or decision_card.get("resolved_result_category"),
        "disclosure_decision": disclosure_decision or dict(decision_card.get("disclosure_decision") or {}),
        "evidence_bundle": evidence_bundle,
        "probability_truth_view": probability_truth_view,
        "probability_engine_result": probability_engine_result,
        "probability_disclosure_payload": probability_disclosure_payload,
        "current_market_pressure": current_market_pressure or None,
        "scenario_comparison": scenario_comparison,
        "scenario_ladder": scenario_ladder,
        "runtime_telemetry": dict(result_payload.get("runtime_telemetry") or {}),
        "product_probability_method": product_probability_method,
        "monthly_fallback_used": monthly_fallback_used,
        "bucket_fallback_used": bucket_fallback_used,
        "evidence_invariance_report": dict(result_payload.get("evidence_invariance_report") or {}),
        "reuse_context": dict(result_payload.get("reuse_context") or decision_card.get("reuse_context") or {}),
        "decision_card": decision_card,
        "key_metrics": decision_card.get("key_metrics", {}),
        "input_provenance": decision_card.get("input_provenance", {}),
        "input_source_summary": input_source_summary,
        "candidate_options": decision_card.get("candidate_options", []),
        "goal_alternatives": decision_card.get("goal_alternatives", []),
        "audit_records": audit_records,
        "formal_path_visibility": formal_path_visibility,
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


def _prepare_reuse_context(
    *,
    workflow_type: str,
    account_profile_id: str,
    goal_solver_input: dict[str, Any] | None,
    raw_inputs: dict[str, Any] | None,
    baseline: Any | None,
) -> dict[str, Any]:
    reuse_signature, signature_basis = _reuse_signature(
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        goal_solver_input=goal_solver_input,
        raw_inputs=raw_inputs,
    )
    context = {
        "reuse_signature": reuse_signature,
        "signature_basis": signature_basis,
        "reused": False,
        "source_run_id": None,
        "source_workflow_type": None,
    }
    if baseline is None:
        return context
    baseline_payload = _as_dict(baseline)
    baseline_run_id = str(baseline_payload.get("run_id") or "").strip()
    baseline_workflow_type = str(baseline_payload.get("workflow_type") or "").strip()
    baseline_result_payload = dict(baseline_payload.get("result_payload") or {})
    baseline_reuse_context = dict(baseline_result_payload.get("reuse_context") or {})
    baseline_signature = str(baseline_reuse_context.get("reuse_signature") or "").strip()
    if not baseline_signature:
        return context
    if baseline_signature != reuse_signature:
        return context
    if baseline_run_id:
        context["reused"] = True
        context["source_run_id"] = baseline_run_id
        context["source_workflow_type"] = baseline_workflow_type or workflow_type
        baseline_bundle = _baseline_evidence_bundle(baseline)
        if baseline_bundle is not None:
            context["baseline_evidence_bundle"] = baseline_bundle.to_dict()
        baseline_report = dict(baseline_result_payload.get("evidence_invariance_report") or {})
        if baseline_report:
            context["baseline_evidence_invariance_report"] = baseline_report
    return context


def _reuse_context_for_payload(
    *,
    reuse_context: dict[str, Any] | None,
    current_result_payload: dict[str, Any],
) -> dict[str, Any]:
    if not reuse_context:
        return {}
    payload = dict(reuse_context)
    baseline_bundle = payload.get("baseline_evidence_bundle")
    current_bundle = EvidenceBundle.from_any(current_result_payload.get("evidence_bundle"))
    if baseline_bundle is not None and current_bundle is not None:
        report = build_evidence_invariance_report(
            baseline=baseline_bundle,
            optimized=current_bundle,
            baseline_run_ref=str(payload.get("source_run_id") or ""),
            optimized_run_ref=str(current_result_payload.get("run_id") or ""),
            artifact_refs={
                "bundle_id": str(current_result_payload.get("bundle_id") or ""),
                "workflow_type": str(current_result_payload.get("workflow_type") or ""),
            },
        ).to_dict()
        payload["evidence_invariance_report"] = report
    payload.pop("baseline_evidence_bundle", None)
    payload.pop("baseline_evidence_invariance_report", None)
    return payload


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
    else:
        (
            raw_inputs,
            input_provenance,
            external_payload,
            external_source_ref,
            external_status,
            external_error,
        ) = _maybe_apply_runtime_market_history(
            raw_inputs=raw_inputs,
            input_provenance=input_provenance,
            workflow_type="onboarding",
            account_profile_id=profile.account_profile_id,
            as_of=str(raw_inputs.get("as_of") or _now_iso()),
            external_snapshot_source=external_source_ref,
            external_data_config=None,
        )
    account_profile = _normalize_profile_payload(
        _merge_profile_override(
            _profile_to_dict(onboarding.profile),
            profile_patch_from_external_snapshot(raw_inputs, external_payload=external_payload),
            account_profile_id=onboarding.profile.account_profile_id,
        )
    )
    if (
        (external_snapshot_source is not None or external_data_config is not None)
        and external_status == "fetched"
        and isinstance(external_payload, dict)
        and bool(external_payload)
    ):
        raw_inputs = _mark_snapshot_primary_formal_path(
            raw_inputs,
            external_source_ref=external_source_ref,
            external_payload=external_payload,
    )
    raw_inputs.setdefault("formal_path_required", True)
    raw_inputs.setdefault("execution_policy", ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED.value)
    reuse_signature, _ = _reuse_signature(
        workflow_type="onboarding",
        account_profile_id=onboarding.profile.account_profile_id,
        goal_solver_input=raw_inputs.get("goal_solver_input"),
        raw_inputs=raw_inputs,
    )
    reusable_baseline = store.get_reusable_baseline(
        onboarding.profile.account_profile_id,
        reuse_signature=reuse_signature,
        workflow_type="onboarding",
    )
    reuse_context = _prepare_reuse_context(
        workflow_type="onboarding",
        account_profile_id=onboarding.profile.account_profile_id,
        goal_solver_input=raw_inputs.get("goal_solver_input"),
        raw_inputs=raw_inputs,
        baseline=reusable_baseline,
    )
    if reuse_context.get("reused") and reuse_context.get("baseline_evidence_bundle") is not None:
        raw_inputs["baseline_evidence_bundle"] = reuse_context["baseline_evidence_bundle"]
        raw_inputs["evidence_invariance_baseline"] = reuse_context["baseline_evidence_bundle"]
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
    payload = _apply_formal_path_metadata(
        payload,
        input_provenance=input_provenance,
        refresh_summary=payload.get("refresh_summary"),
    )
    reuse_context_payload = _reuse_context_for_payload(
        reuse_context=reuse_context,
        current_result_payload=payload,
    )
    if reuse_context_payload:
        payload["reuse_context"] = reuse_context_payload
        if reuse_context_payload.get("evidence_invariance_report"):
            payload["evidence_invariance_report"] = reuse_context_payload["evidence_invariance_report"]
        decision_card = dict(payload.get("decision_card") or {})
        decision_card["reuse_context"] = reuse_context_payload
        if reuse_context_payload.get("evidence_invariance_report"):
            decision_card["evidence_invariance_report"] = reuse_context_payload["evidence_invariance_report"]
        payload["decision_card"] = decision_card
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
    if summary.get("formal_path_visibility") is not None and isinstance(summary["user_state"], dict):
        summary["user_state"]["formal_path_visibility"] = summary["formal_path_visibility"]
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

    # Provide execution plan lifecycle context for orchestrator guidance
    try:
        active_record = store.get_latest_active_execution_plan(account_profile_id)
        pending_record = store.get_latest_pending_execution_plan(account_profile_id)
        raw_inputs["frontdesk_execution_plan_context"] = {
            "active": None if active_record is None else dict(active_record.payload or {}),
            "pending": None if pending_record is None else dict(pending_record.payload or {}),
            "comparison": (snapshot or {}).get("execution_plan_comparison"),
        }
    except Exception:
        # Defensive: do not block workflow if store lookup fails
        pass
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
    else:
        (
            raw_inputs,
            input_provenance,
            external_payload,
            external_source_ref,
            external_status,
            external_error,
        ) = _maybe_apply_runtime_market_history(
            raw_inputs=raw_inputs,
            input_provenance=input_provenance,
            workflow_type=workflow_type,
            account_profile_id=account_profile_id,
            as_of=str(raw_inputs.get("as_of") or as_of),
            external_snapshot_source=external_source_ref,
            external_data_config=None,
        )
    active_profile = _merge_profile_override(
        active_profile,
        profile_patch_from_external_snapshot(raw_inputs, external_payload=external_payload),
        account_profile_id=account_profile_id,
    )
    active_profile = _normalize_profile_payload(active_profile)
    if (
        (external_snapshot_source is not None or external_data_config is not None)
        and external_status == "fetched"
        and isinstance(external_payload, dict)
        and bool(external_payload)
    ):
        raw_inputs = _mark_snapshot_primary_formal_path(
            raw_inputs,
            external_source_ref=external_source_ref,
            external_payload=external_payload,
        )
    raw_inputs.setdefault("formal_path_required", True)
    raw_inputs.setdefault("execution_policy", ExecutionPolicy.FORMAL_ESTIMATION_ALLOWED.value)
    reuse_signature, _ = _reuse_signature(
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        goal_solver_input=goal_solver_input,
        raw_inputs=raw_inputs,
    )
    reusable_baseline = store.get_reusable_baseline(
        account_profile_id,
        reuse_signature=reuse_signature,
        workflow_type=workflow_type,
    )
    reuse_context = _prepare_reuse_context(
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        goal_solver_input=goal_solver_input,
        raw_inputs=raw_inputs,
        baseline=reusable_baseline,
    )
    if reuse_context.get("reused") and reuse_context.get("baseline_evidence_bundle") is not None:
        raw_inputs["baseline_evidence_bundle"] = reuse_context["baseline_evidence_bundle"]
        raw_inputs["evidence_invariance_baseline"] = reuse_context["baseline_evidence_bundle"]
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
    payload = _apply_formal_path_metadata(
        payload,
        input_provenance=input_provenance,
        refresh_summary=payload.get("refresh_summary"),
    )
    reuse_context_payload = _reuse_context_for_payload(
        reuse_context=reuse_context,
        current_result_payload=payload,
    )
    if reuse_context_payload:
        payload["reuse_context"] = reuse_context_payload
        if reuse_context_payload.get("evidence_invariance_report"):
            payload["evidence_invariance_report"] = reuse_context_payload["evidence_invariance_report"]
        decision_card = dict(payload.get("decision_card") or {})
        decision_card["reuse_context"] = reuse_context_payload
        if reuse_context_payload.get("evidence_invariance_report"):
            decision_card["evidence_invariance_report"] = reuse_context_payload["evidence_invariance_report"]
        payload["decision_card"] = decision_card
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
    summary = _frontdesk_summary(
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
    if summary.get("formal_path_visibility") is not None and isinstance(user_state, dict):
        user_state["formal_path_visibility"] = summary["formal_path_visibility"]
        summary["user_state"] = user_state
    return summary


def sync_observed_portfolio(
    *,
    account_profile_id: str,
    observed_portfolio: str | Path | dict[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
    created_at: str | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path)
    store = FrontdeskStore(db_path)
    store.init_schema()

    snapshot = store.get_frontdesk_snapshot(account_profile_id)
    if snapshot is None or snapshot.get("profile") is None:
        raise ValueError(f"no saved frontdesk state for {account_profile_id}")
    if observed_portfolio is None:
        raise ValueError("observed_portfolio payload is required")

    source_payload = _mapping_from_source(observed_portfolio, option_name="observed-portfolio-json")
    if source_payload is None or not source_payload:
        raise ValueError("observed_portfolio payload is required")
    normalized = _normalize_observed_portfolio_payload(source_payload)
    timestamp = created_at or _now_iso()
    reconciliation_state = reconcile_observed_portfolio(
        account_profile_id=account_profile_id,
        observed_portfolio=dict(normalized),
        active_execution_plan=_as_dict(snapshot.get("active_execution_plan")),
        pending_execution_plan=_as_dict(snapshot.get("pending_execution_plan")),
    ).to_dict()
    observed_record = store.save_observed_portfolio_record(
        account_profile_id=account_profile_id,
        snapshot_id=str(normalized["snapshot_id"]),
        source_kind=str(normalized["source_kind"]),
        data_status=str(normalized["data_status"]),
        completeness_status=str(normalized["completeness_status"]),
        as_of=normalized.get("as_of"),
        total_value=normalized.get("total_value"),
        available_cash=normalized.get("available_cash"),
        weights=dict(normalized.get("weights") or {}),
        holdings=[dict(item) for item in normalized.get("holdings") or []],
        missing_fields=[str(item) for item in normalized.get("missing_fields") or []],
        audit_window=normalized.get("audit_window"),
        source_ref=normalized.get("source_ref"),
        payload=normalized,
        created_at=timestamp,
        updated_at=timestamp,
    )
    reconciliation_state["snapshot_id"] = observed_record.snapshot_id
    reconciliation_state["observed_snapshot_id"] = observed_record.snapshot_id
    reconciliation_state["observed_source_kind"] = normalized.get("source_kind")
    reconciliation_state["observed_completeness_status"] = normalized.get("completeness_status")
    reconciliation_state["observed_as_of"] = normalized.get("as_of")
    reconciliation_state["observed_total_value"] = normalized.get("total_value")
    reconciliation_state["observed_available_cash"] = normalized.get("available_cash")
    reconciliation_state["observed_weights"] = dict(normalized.get("weights") or {})
    reconciliation_state["summary"] = (
        f"plan coverage against {reconciliation_state.get('compared_against')} plan; "
        f"status={reconciliation_state.get('status')}; snapshot={observed_record.snapshot_id}"
    )
    reconciliation_state["created_at"] = timestamp
    reconciliation_state["updated_at"] = timestamp
    reconciliation_record = store.save_reconciliation_state_record(
        account_profile_id=account_profile_id,
        snapshot_id=observed_record.snapshot_id,
        status=str(reconciliation_state["status"]),
        compared_against=str(reconciliation_state["compared_against"]),
        observed_snapshot_id=observed_record.snapshot_id,
        payload=reconciliation_state,
        created_at=timestamp,
        updated_at=timestamp,
    )
    user_state = load_user_state(account_profile_id, db_path=db_path)
    snapshot_after_sync = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    return {
        "workflow": "sync_portfolio",
        "workflow_type": "sync_portfolio",
        "status": "synced",
        "account_profile_id": account_profile_id,
        "display_name": str((snapshot or {}).get("profile", {}).get("display_name") or account_profile_id),
        "db_path": str(db_path),
        "observed_portfolio": (snapshot_after_sync or {}).get("observed_portfolio") or _observed_portfolio_record_summary(observed_record),
        "reconciliation_state": (snapshot_after_sync or {}).get("reconciliation_state") or dict(reconciliation_record.payload or {}),
        "refresh_summary": (snapshot_after_sync or {}).get("refresh_summary"),
        "user_state": user_state,
    }


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
    snapshot["formal_path_visibility"] = dict(
        result_payload.get("formal_path_visibility")
        or decision_card.get("formal_path_visibility")
        or _classify_formal_path_visibility(
            decision_card,
            snapshot.get("refresh_summary"),
            list(result_payload.get("audit_records") or decision_card.get("audit_records") or []),
        )
    )
    snapshot["audit_records"] = list(
        result_payload.get("audit_records")
        or decision_card.get("audit_records")
        or _normalize_audit_records(decision_card.get("input_provenance", {}) or {}, snapshot.get("refresh_summary"))
    )
    snapshot["reuse_context"] = dict(result_payload.get("reuse_context") or decision_card.get("reuse_context") or {})
    snapshot["evidence_invariance_report"] = dict(
        result_payload.get("evidence_invariance_report") or decision_card.get("evidence_invariance_report") or {}
    )
    if decision_card:
        decision_card["formal_path_visibility"] = snapshot["formal_path_visibility"]
        decision_card["audit_records"] = snapshot["audit_records"]
        decision_card["reuse_context"] = snapshot["reuse_context"]
        decision_card["evidence_invariance_report"] = snapshot["evidence_invariance_report"]
        latest_run["decision_card"] = decision_card
        latest_run["reuse_context"] = snapshot["reuse_context"]
        latest_run["evidence_invariance_report"] = snapshot["evidence_invariance_report"]
        snapshot["latest_run"] = latest_run
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
        user_state["formal_path_visibility"] = snapshot.get("formal_path_visibility")
        user_state["audit_records"] = snapshot.get("audit_records")
        user_state["reuse_context"] = snapshot.get("reuse_context")
        user_state["evidence_invariance_report"] = snapshot.get("evidence_invariance_report")
    return user_state


def explain_frontdesk_probability(
    *,
    account_profile_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    user_state = load_user_state(account_profile_id, db_path=db_path)
    if snapshot is None or user_state is None:
        raise ValueError(f"no saved frontdesk state for {account_profile_id}")
    decision_card = dict(user_state.get("decision_card") or {})
    return {
        "workflow": "explain_probability",
        "status": "explained",
        "account_profile_id": account_profile_id,
        "probability_explanation": dict(decision_card.get("probability_explanation") or {}),
        "frontier_analysis": dict(decision_card.get("frontier_analysis") or {}),
        "key_metrics": dict(decision_card.get("key_metrics") or {}),
        "formal_path_visibility": snapshot.get("formal_path_visibility"),
        "refresh_summary": snapshot.get("refresh_summary"),
        "user_state": user_state,
    }


def explain_frontdesk_plan_change(
    *,
    account_profile_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    user_state = load_user_state(account_profile_id, db_path=db_path)
    if snapshot is None or user_state is None:
        raise ValueError(f"no saved frontdesk state for {account_profile_id}")
    decision_card = dict(user_state.get("decision_card") or {})
    return {
        "workflow": "explain_plan_change",
        "status": "explained",
        "account_profile_id": account_profile_id,
        "active_execution_plan": snapshot.get("active_execution_plan"),
        "pending_execution_plan": snapshot.get("pending_execution_plan"),
        "execution_plan_comparison": snapshot.get("execution_plan_comparison"),
        "execution_plan_guidance": dict(decision_card.get("execution_plan_guidance") or {}),
        "formal_path_visibility": snapshot.get("formal_path_visibility"),
        "refresh_summary": snapshot.get("refresh_summary"),
        "user_state": user_state,
    }


def run_frontdesk_daily_monitor(
    *,
    account_profile_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    snapshot = load_frontdesk_snapshot(account_profile_id, db_path=db_path)
    user_state = load_user_state(account_profile_id, db_path=db_path)
    if snapshot is None or user_state is None:
        raise ValueError(f"no saved frontdesk state for {account_profile_id}")
    plan = snapshot.get("pending_execution_plan") or snapshot.get("active_execution_plan") or {}
    maintenance_policy = dict(plan.get("maintenance_policy_summary") or {})
    monitoring_actions: list[dict[str, Any]] = []
    for item in list(plan.get("items") or []):
        payload = dict(item or {})
        monitoring_actions.append(
            {
                "asset_bucket": payload.get("asset_bucket"),
                "primary_product_id": payload.get("primary_product_id"),
                "trade_direction": payload.get("trade_direction"),
                "initial_trade_amount": payload.get("initial_trade_amount"),
                "deferred_trade_amount": payload.get("deferred_trade_amount"),
                "trigger_conditions": list(payload.get("trigger_conditions") or []),
            }
        )
    monitoring_status = "monitoring_ready" if monitoring_actions else "no_monitorable_actions"
    return {
        "workflow": "daily_monitor",
        "status": monitoring_status,
        "account_profile_id": account_profile_id,
        "monitoring_actions": monitoring_actions,
        "maintenance_policy_summary": maintenance_policy,
        "observed_portfolio": snapshot.get("observed_portfolio"),
        "reconciliation_state": snapshot.get("reconciliation_state"),
        "formal_path_visibility": snapshot.get("formal_path_visibility"),
        "refresh_summary": snapshot.get("refresh_summary"),
        "user_state": user_state,
    }


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
