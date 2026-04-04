from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SOURCE_LABELS = {
    "user_provided": "用户提供",
    "system_inferred": "系统推断",
    "default_assumed": "默认假设",
    "externally_fetched": "外部抓取",
}
_ACTIVE_EXECUTION_PLAN_STATUSES = {"approved"}
_PENDING_EXECUTION_PLAN_STATUSES = {"draft", "user_review"}


def _empty_input_provenance() -> dict[str, Any]:
    return {
        "items": [],
        "counts": {source_type: 0 for source_type in _SOURCE_LABELS},
        "source_labels": dict(_SOURCE_LABELS),
        "user_provided": [],
        "system_inferred": [],
        "default_assumed": [],
        "externally_fetched": [],
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _normalize_input_provenance(input_provenance: dict[str, Any] | None) -> dict[str, Any]:
    if not input_provenance:
        return _empty_input_provenance()
    has_group_entries = any(input_provenance.get(source_type) for source_type in _SOURCE_LABELS)
    if "items" in input_provenance and "counts" in input_provenance:
        if not has_group_entries:
            normalized = _empty_input_provenance()
            normalized.update(dict(input_provenance))
            normalized["source_labels"] = {
                **dict(_SOURCE_LABELS),
                **dict(input_provenance.get("source_labels") or {}),
            }
            return normalized
    normalized = _empty_input_provenance()
    items = None if has_group_entries else input_provenance.get("items")
    if isinstance(items, list):
        for item in items:
            payload = dict(item)
            source_type = str(payload.get("source_type") or "default_assumed")
            if source_type == "external_data":
                source_type = "externally_fetched"
            if source_type not in _SOURCE_LABELS:
                source_type = "default_assumed"
            rendered = {
                "field": payload.get("field", "unknown"),
                "label": payload.get("label", payload.get("field", "unknown")),
                "value": payload.get("value"),
                "note": payload.get("note") or payload.get("detail"),
                "source_type": source_type,
                "source_label": _SOURCE_LABELS[source_type],
            }
            for key in ("detail", "source_ref", "as_of", "fetched_at", "freshness_state", "data_status", "audit_window"):
                if payload.get(key) is not None:
                    rendered[key] = payload.get(key)
            normalized[source_type].append(rendered)
            normalized["items"].append(rendered)
        for source_type in _SOURCE_LABELS:
            normalized["counts"][source_type] = len(normalized[source_type])
        return normalized
    for source_type in _SOURCE_LABELS:
        for item in input_provenance.get(source_type, []):
            payload = dict(item)
            rendered = {
                "field": payload.get("field", "unknown"),
                "label": payload.get("label", payload.get("field", "unknown")),
                "value": payload.get("value"),
                "note": payload.get("note") or payload.get("detail"),
                "source_type": source_type,
                "source_label": _SOURCE_LABELS[source_type],
            }
            for key in ("detail", "source_ref", "as_of", "fetched_at", "freshness_state", "data_status", "audit_window"):
                if payload.get(key) is not None:
                    rendered[key] = payload.get(key)
            normalized[source_type].append(rendered)
            normalized["items"].append(rendered)
        normalized["counts"][source_type] = len(normalized[source_type])
    return normalized


def _persist_input_provenance_records(
    conn: sqlite3.Connection,
    *,
    account_profile_id: str,
    run_id: str,
    input_provenance: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_input_provenance(input_provenance)
    conn.execute("DELETE FROM input_provenance_records WHERE run_id = ?", (run_id,))
    for source_type in _SOURCE_LABELS:
        for item in normalized.get(source_type, []):
            conn.execute(
                """
                INSERT INTO input_provenance_records(
                    account_profile_id,
                    run_id,
                    source_type,
                    field_name,
                    label,
                    value_json,
                    note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_profile_id,
                    run_id,
                    source_type,
                    str(item.get("field", "unknown")),
                    str(item.get("label", item.get("field", "unknown"))),
                    _json_dumps(item.get("value")),
                    None if item.get("note") is None else str(item.get("note")),
                ),
            )
    return normalized


@dataclass
class FrontdeskBaselineRecord:
    account_profile_id: str
    run_id: str
    workflow_type: str
    goal_solver_input: dict[str, Any]
    goal_solver_output: dict[str, Any]
    decision_card: dict[str, Any]
    input_provenance: dict[str, Any]
    result_payload: dict[str, Any]
    created_at: str


@dataclass
class FrontdeskExecutionFeedbackRecord:
    account_profile_id: str
    source_run_id: str
    workflow_type: str
    recommended_action: str
    user_executed: bool | None
    actual_action: str | None
    executed_at: str | None
    note: str | None
    feedback_status: str
    feedback_source: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class FrontdeskExecutionPlanRecord:
    account_profile_id: str
    plan_id: str
    plan_version: int
    source_run_id: str
    source_allocation_id: str
    status: str
    confirmation_required: bool
    payload: dict[str, Any]
    approved_at: str | None
    superseded_by_plan_id: str | None
    created_at: str
    updated_at: str


def _bool_from_db(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _feedback_status(user_executed: bool | None) -> str:
    if user_executed is True:
        return "executed"
    if user_executed is False:
        return "skipped"
    return "pending"


def _execution_feedback_payload(
    *,
    workflow_type: str,
    recommended_action: str,
    user_executed: bool | None,
    actual_action: str | None,
    executed_at: str | None,
    note: str | None,
    feedback_source: str,
    persistence_execution_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "workflow_type": workflow_type,
        "recommended_action": recommended_action,
        "user_executed": user_executed,
        "actual_action": actual_action,
        "executed_at": executed_at,
        "note": note,
        "feedback_status": _feedback_status(user_executed),
        "feedback_source": feedback_source,
    }
    if persistence_execution_record:
        payload["persistence_execution_record"] = dict(persistence_execution_record)
    return payload


def _execution_plan_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    items = list(payload.get("items") or [])
    breakdown = dict(payload.get("candidate_filter_breakdown") or {})
    return {
        "plan_id": payload.get("plan_id"),
        "plan_version": payload.get("plan_version"),
        "source_run_id": payload.get("source_run_id"),
        "source_allocation_id": payload.get("source_allocation_id"),
        "status": payload.get("status"),
        "item_count": len(items),
        "confirmation_required": bool(payload.get("confirmation_required", True)),
        "warning_count": len(list(payload.get("warnings") or [])),
        "approved_at": payload.get("approved_at"),
        "superseded_by_plan_id": payload.get("superseded_by_plan_id"),
        "registry_candidate_count": payload.get("registry_candidate_count"),
        "runtime_candidate_count": payload.get("runtime_candidate_count"),
        "product_proxy_specs": list(payload.get("product_proxy_specs") or []),
        "proxy_universe_summary": dict(payload.get("proxy_universe_summary") or {}),
        "execution_realism_summary": dict(payload.get("execution_realism_summary") or {}),
        "candidate_filter_dropped_reasons": dict(breakdown.get("dropped_reasons") or {}),
        "candidate_filter_stages": list(breakdown.get("stages") or []),
        "valuation_audit_summary": dict(
            payload.get("valuation_audit_summary") or breakdown.get("valuation_audit_summary") or {}
        ),
        "policy_news_audit_summary": dict(
            payload.get("policy_news_audit_summary") or breakdown.get("policy_news_audit_summary") or {}
        ),
    }


def _execution_plan_record_summary(record: FrontdeskExecutionPlanRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    payload_summary = _execution_plan_summary(record.payload) or {}
    return {
        **payload_summary,
        "plan_id": record.plan_id,
        "plan_version": record.plan_version,
        "source_run_id": record.source_run_id,
        "source_allocation_id": record.source_allocation_id,
        "status": record.status,
        "confirmation_required": record.confirmation_required,
        "approved_at": record.approved_at,
        "superseded_by_plan_id": record.superseded_by_plan_id,
    }


def _execution_plan_record_from_row(row: sqlite3.Row | None) -> FrontdeskExecutionPlanRecord | None:
    if row is None:
        return None
    return FrontdeskExecutionPlanRecord(
        account_profile_id=row["account_profile_id"],
        plan_id=row["plan_id"],
        plan_version=int(row["plan_version"]),
        source_run_id=row["source_run_id"],
        source_allocation_id=row["source_allocation_id"],
        status=row["status"],
        confirmation_required=bool(row["confirmation_required"]),
        payload=_json_loads(row["payload_json"]) or {},
        approved_at=row["approved_at"],
        superseded_by_plan_id=row["superseded_by_plan_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _execution_plan_item_index(record: FrontdeskExecutionPlanRecord | None) -> dict[str, dict[str, Any]]:
    if record is None:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in list((record.payload or {}).get("items") or []):
        payload = dict(item or {})
        bucket = str(payload.get("asset_bucket") or "").strip()
        if bucket:
            index[bucket] = payload
    return index


def _primary_product_id(item: dict[str, Any]) -> str | None:
    direct = str(item.get("primary_product_id") or "").strip()
    if direct:
        return direct
    product = dict(item.get("primary_product") or {})
    nested = str(product.get("product_id") or "").strip()
    return nested or None


def _compare_execution_plans(
    active: FrontdeskExecutionPlanRecord | None,
    pending: FrontdeskExecutionPlanRecord | None,
) -> dict[str, Any] | None:
    if active is not None and pending is None:
        return {
            "active_plan_id": active.plan_id,
            "active_plan_version": active.plan_version,
            "pending_plan_id": None,
            "pending_plan_version": None,
            "change_level": "none",
            "recommendation": "keep_active",
            "changed_bucket_count": 0,
            "product_switch_count": 0,
            "max_weight_delta": 0.0,
            "bucket_changes": [],
            "product_switches": [],
            "summary": ["no new pending execution plan generated; keep current active plan"],
        }
    if active is None or pending is None:
        return None

    active_items = _execution_plan_item_index(active)
    pending_items = _execution_plan_item_index(pending)
    bucket_changes: list[dict[str, Any]] = []
    product_switches: list[dict[str, Any]] = []
    max_weight_delta = 0.0

    for bucket in sorted(set(active_items) | set(pending_items)):
        active_item = active_items.get(bucket, {})
        pending_item = pending_items.get(bucket, {})
        active_weight = round(float(active_item.get("target_weight", 0.0) or 0.0), 4)
        pending_weight = round(float(pending_item.get("target_weight", 0.0) or 0.0), 4)
        weight_delta = round(pending_weight - active_weight, 4)
        active_product_id = _primary_product_id(active_item)
        pending_product_id = _primary_product_id(pending_item)
        product_changed = active_product_id != pending_product_id and bool(active_product_id or pending_product_id)
        if abs(weight_delta) <= 1e-6 and not product_changed:
            continue
        max_weight_delta = max(max_weight_delta, abs(weight_delta))
        change_payload = {
            "asset_bucket": bucket,
            "active_target_weight": active_weight,
            "pending_target_weight": pending_weight,
            "weight_delta": weight_delta,
            "active_primary_product_id": active_product_id,
            "pending_primary_product_id": pending_product_id,
            "product_changed": product_changed,
        }
        bucket_changes.append(change_payload)
        if product_changed:
            product_switches.append(
                {
                    "asset_bucket": bucket,
                    "active_primary_product_id": active_product_id,
                    "pending_primary_product_id": pending_product_id,
                }
            )

    bucket_set_changed = any(
        (item["active_target_weight"] <= 1e-6) != (item["pending_target_weight"] <= 1e-6)
        for item in bucket_changes
    )
    changed_bucket_count = len(bucket_changes)
    product_switch_count = len(product_switches)

    if changed_bucket_count == 0 and product_switch_count == 0:
        change_level = "none"
        recommendation = "keep_active"
        summary = ["pending plan matches current active plan"]
    else:
        if bucket_set_changed or max_weight_delta >= 0.10 or changed_bucket_count >= 3:
            change_level = "major"
            recommendation = "replace_active"
        else:
            change_level = "minor"
            recommendation = "review_replace"
        summary = [f"{changed_bucket_count} bucket changes detected"]
        if product_switch_count:
            summary.append(f"{product_switch_count} primary product switches detected")
        if max_weight_delta > 0.0:
            summary.append(f"largest weight delta={max_weight_delta:.2%}")

    return {
        "active_plan_id": active.plan_id,
        "active_plan_version": active.plan_version,
        "pending_plan_id": pending.plan_id,
        "pending_plan_version": pending.plan_version,
        "change_level": change_level,
        "recommendation": recommendation,
        "changed_bucket_count": changed_bucket_count,
        "product_switch_count": product_switch_count,
        "max_weight_delta": round(max_weight_delta, 4),
        "bucket_changes": bucket_changes,
        "product_switches": product_switches,
        "summary": summary,
    }


def _plan_comparison_guidance(comparison: dict[str, Any] | None) -> dict[str, list[str] | str | bool]:
    if not comparison:
        return {
            "review_conditions": [],
            "next_steps": [],
            "execution_notes": [],
            "reason_lines": [],
            "summary_prefix": "",
            "low_confidence": False,
        }

    recommendation = str(comparison.get("recommendation") or "")
    change_level = str(comparison.get("change_level") or "")
    changed_bucket_count = int(comparison.get("changed_bucket_count") or 0)
    product_switch_count = int(comparison.get("product_switch_count") or 0)
    max_weight_delta = float(comparison.get("max_weight_delta") or 0.0)

    summary_bits = [
        f"{changed_bucket_count} 个资金桶变化",
        f"{product_switch_count} 个主产品切换" if product_switch_count else None,
        f"最大权重变化 {max_weight_delta:.2%}" if max_weight_delta > 0.0 else None,
    ]
    summary_line = "；".join(bit for bit in summary_bits if bit)
    if recommendation == "replace_active":
        return {
            "review_conditions": ["pending_plan_major_change"],
            "next_steps": ["approve_pending_plan_replacement", "review_plan_differences"],
            "execution_notes": [f"新计划相对当前已确认计划属于重大变化：{summary_line}。"],
            "reason_lines": [f"相对当前已执行方案，本次建议涉及重大变更：{summary_line}。"],
            "summary_prefix": "待确认的新计划相对当前已执行方案变化较大，建议优先复核并决定是否替换。",
            "low_confidence": False,
        }
    if recommendation == "review_replace":
        return {
            "review_conditions": ["pending_plan_minor_change_review"],
            "next_steps": ["review_plan_differences", "confirm_keep_or_replace_active_plan"],
            "execution_notes": [f"新计划相对当前已确认计划存在中小幅变化：{summary_line}。"],
            "reason_lines": [f"相对当前已执行方案，本次建议存在中小幅调整：{summary_line}。"],
            "summary_prefix": "待确认的新计划和当前已执行方案有差异，建议先核对变化后再决定是否替换。",
            "low_confidence": change_level != "major",
        }
    if comparison.get("pending_plan_id") is None:
        return {
            "review_conditions": ["no_new_plan_generated"],
            "next_steps": ["keep_active_plan", "recheck_after_next_cycle"],
            "execution_notes": ["本轮没有生成新的待确认执行计划，可继续沿用当前 active plan。"],
            "reason_lines": ["本轮没有生成新的待确认执行计划，继续沿用当前已执行方案。"],
            "summary_prefix": "本轮没有生成新的待确认计划，建议继续沿用当前 active plan。",
            "low_confidence": False,
        }
    return {
        "review_conditions": ["pending_plan_matches_active"],
        "next_steps": ["keep_active_plan", "approve_pending_plan_only_if_manual_override_needed"],
        "execution_notes": ["待确认的新计划与当前已执行方案基本一致，可继续沿用当前 active plan。"],
        "reason_lines": ["待确认的新计划与当前已执行方案基本一致。"],
        "summary_prefix": "当前 active plan 仍可继续沿用，新 pending plan 仅作记录。",
        "low_confidence": False,
    }


def _decorate_decision_card_with_plan_comparison(
    decision_card: dict[str, Any],
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    if not decision_card or not comparison:
        return decision_card
    payload = dict(decision_card)
    guidance = _plan_comparison_guidance(comparison)
    payload["execution_plan_comparison"] = comparison
    payload["review_conditions"] = list(
        dict.fromkeys(list(payload.get("review_conditions") or []) + list(guidance["review_conditions"]))
    )
    payload["next_steps"] = list(
        dict.fromkeys(list(guidance["next_steps"]) + list(payload.get("next_steps") or []))
    )
    payload["execution_notes"] = list(
        dict.fromkeys(list(payload.get("execution_notes") or []) + list(guidance["execution_notes"]))
    )
    payload["recommendation_reason"] = list(
        dict.fromkeys(list(payload.get("recommendation_reason") or []) + list(guidance["reason_lines"]))
    )
    payload["reasons"] = list(
        dict.fromkeys(list(payload.get("reasons") or []) + list(guidance["reason_lines"]))
    )
    summary_prefix = str(guidance["summary_prefix"] or "").strip()
    if summary_prefix:
        current_summary = str(payload.get("summary") or "").strip()
        if current_summary:
            payload["summary"] = f"{summary_prefix} {current_summary}"
        else:
            payload["summary"] = summary_prefix
    payload["low_confidence"] = bool(payload.get("low_confidence")) or bool(guidance["low_confidence"])
    execution_plan_summary = dict(payload.get("execution_plan_summary") or {})
    execution_plan_summary["comparison_recommendation"] = comparison.get("recommendation")
    execution_plan_summary["comparison_change_level"] = comparison.get("change_level")
    payload["execution_plan_summary"] = execution_plan_summary
    return payload


class FrontdeskStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    account_profile_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS onboarding_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    input_provenance_json TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS frontdesk_baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    workflow_type TEXT NOT NULL,
                    goal_solver_input_json TEXT NOT NULL,
                    goal_solver_output_json TEXT NOT NULL,
                    decision_card_json TEXT NOT NULL,
                    input_provenance_json TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    workflow_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision_card_json TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    card_id TEXT NOT NULL,
                    card_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_plan_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    source_run_id TEXT NOT NULL,
                    source_allocation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmation_required INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    approved_at TEXT,
                    superseded_by_plan_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(plan_id, plan_version)
                );

                CREATE TABLE IF NOT EXISTS input_provenance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    label TEXT,
                    value_json TEXT,
                    note TEXT
                );

                CREATE TABLE IF NOT EXISTS execution_feedback_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_profile_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL UNIQUE,
                    workflow_type TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    user_executed INTEGER,
                    actual_action TEXT,
                    executed_at TEXT,
                    note TEXT,
                    feedback_status TEXT NOT NULL,
                    feedback_source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_frontdesk_baselines_account_created
                ON frontdesk_baselines(account_profile_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_workflow_runs_account_created
                ON workflow_runs(account_profile_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_execution_plan_records_account_updated
                ON execution_plan_records(account_profile_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_input_provenance_records_run
                ON input_provenance_records(run_id, source_type);

                CREATE INDEX IF NOT EXISTS idx_execution_feedback_records_account_updated
                ON execution_feedback_records(account_profile_id, updated_at DESC);
                """
            )

    def initialize(self) -> None:
        self.init_schema()

    def upsert_user_profile(
        self,
        *,
        account_profile_id: str,
        display_name: str,
        profile: dict[str, Any],
        created_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    account_profile_id,
                    display_name,
                    profile_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_profile_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (
                    account_profile_id,
                    display_name,
                    _json_dumps(profile),
                    created_at,
                    created_at,
                ),
            )

    def save_workflow_run(
        self,
        *,
        account_profile_id: str,
        run_id: str,
        workflow_type: str,
        status: str,
        decision_card: dict[str, Any],
        result_payload: dict[str, Any],
        created_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    account_profile_id,
                    run_id,
                    workflow_type,
                    status,
                    decision_card_json,
                    result_payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_profile_id,
                    run_id,
                    workflow_type,
                    status,
                    _json_dumps(decision_card),
                    _json_dumps(result_payload),
                    created_at,
                ),
            )

    def save_baseline(
        self,
        *,
        account_profile_id: str,
        run_id: str,
        workflow_type: str,
        goal_solver_input: dict[str, Any],
        goal_solver_output: dict[str, Any],
        decision_card: dict[str, Any],
        input_provenance: dict[str, Any],
        result_payload: dict[str, Any],
        created_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO frontdesk_baselines (
                    account_profile_id,
                    run_id,
                    workflow_type,
                    goal_solver_input_json,
                    goal_solver_output_json,
                    decision_card_json,
                    input_provenance_json,
                    result_payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_profile_id,
                    run_id,
                    workflow_type,
                    _json_dumps(goal_solver_input),
                    _json_dumps(goal_solver_output),
                    _json_dumps(decision_card),
                    _json_dumps(input_provenance),
                    _json_dumps(result_payload),
                    created_at,
                ),
            )

    def save_decision_card(
        self,
        *,
        account_profile_id: str,
        run_id: str,
        decision_card: dict[str, Any],
        created_at: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_cards(
                    account_profile_id,
                    run_id,
                    card_id,
                    card_type,
                    summary,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_profile_id,
                    run_id,
                    str(decision_card.get("card_id") or run_id),
                    str(decision_card.get("card_type") or ""),
                    str(decision_card.get("summary") or ""),
                    _json_dumps(decision_card),
                    created_at,
                ),
            )

    def save_execution_plan_record(
        self,
        *,
        account_profile_id: str,
        plan_id: str,
        plan_version: int,
        source_run_id: str,
        source_allocation_id: str,
        status: str,
        confirmation_required: bool,
        payload: dict[str, Any],
        created_at: str,
        updated_at: str,
        approved_at: str | None = None,
        superseded_by_plan_id: str | None = None,
    ) -> FrontdeskExecutionPlanRecord:
        payload_data = dict(payload or {})
        resolved_approved_at = approved_at if approved_at is not None else payload_data.get("approved_at")
        resolved_superseded_by_plan_id = (
            superseded_by_plan_id
            if superseded_by_plan_id is not None
            else payload_data.get("superseded_by_plan_id")
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_plan_records(
                    account_profile_id,
                    plan_id,
                    plan_version,
                    source_run_id,
                    source_allocation_id,
                    status,
                    confirmation_required,
                    payload_json,
                    approved_at,
                    superseded_by_plan_id,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id, plan_version) DO UPDATE SET
                    account_profile_id=excluded.account_profile_id,
                    source_run_id=excluded.source_run_id,
                    source_allocation_id=excluded.source_allocation_id,
                    status=excluded.status,
                    confirmation_required=excluded.confirmation_required,
                    payload_json=excluded.payload_json,
                    approved_at=excluded.approved_at,
                    superseded_by_plan_id=excluded.superseded_by_plan_id,
                    updated_at=excluded.updated_at
                """,
                (
                    account_profile_id,
                    plan_id,
                    int(plan_version),
                    source_run_id,
                    source_allocation_id,
                    status,
                    int(bool(confirmation_required)),
                    _json_dumps(payload_data),
                    resolved_approved_at,
                    resolved_superseded_by_plan_id,
                    created_at,
                    updated_at,
                ),
            )
        return FrontdeskExecutionPlanRecord(
            account_profile_id=account_profile_id,
            plan_id=plan_id,
            plan_version=int(plan_version),
            source_run_id=source_run_id,
            source_allocation_id=source_allocation_id,
            status=status,
            confirmation_required=bool(confirmation_required),
            payload=payload_data,
            approved_at=resolved_approved_at,
            superseded_by_plan_id=resolved_superseded_by_plan_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    def save_execution_feedback_record(
        self,
        *,
        account_profile_id: str,
        source_run_id: str,
        workflow_type: str,
        recommended_action: str,
        user_executed: bool | None,
        actual_action: str | None,
        executed_at: str | None,
        note: str | None,
        feedback_source: str,
        created_at: str,
        updated_at: str,
        persistence_execution_record: dict[str, Any] | None = None,
    ) -> FrontdeskExecutionFeedbackRecord:
        payload = _execution_feedback_payload(
            workflow_type=workflow_type,
            recommended_action=recommended_action,
            user_executed=user_executed,
            actual_action=actual_action,
            executed_at=executed_at,
            note=note,
            feedback_source=feedback_source,
            persistence_execution_record=persistence_execution_record,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_feedback_records(
                    account_profile_id,
                    source_run_id,
                    workflow_type,
                    recommended_action,
                    user_executed,
                    actual_action,
                    executed_at,
                    note,
                    feedback_status,
                    feedback_source,
                    payload_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_run_id) DO UPDATE SET
                    account_profile_id=excluded.account_profile_id,
                    workflow_type=excluded.workflow_type,
                    recommended_action=excluded.recommended_action,
                    user_executed=excluded.user_executed,
                    actual_action=excluded.actual_action,
                    executed_at=excluded.executed_at,
                    note=excluded.note,
                    feedback_status=excluded.feedback_status,
                    feedback_source=excluded.feedback_source,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    account_profile_id,
                    source_run_id,
                    workflow_type,
                    recommended_action,
                    None if user_executed is None else int(user_executed),
                    actual_action,
                    executed_at,
                    note,
                    payload["feedback_status"],
                    feedback_source,
                    _json_dumps(payload),
                    created_at,
                    updated_at,
                ),
            )
        return FrontdeskExecutionFeedbackRecord(
            account_profile_id=account_profile_id,
            source_run_id=source_run_id,
            workflow_type=workflow_type,
            recommended_action=recommended_action,
            user_executed=user_executed,
            actual_action=actual_action,
            executed_at=executed_at,
            note=note,
            feedback_status=payload["feedback_status"],
            feedback_source=feedback_source,
            payload=payload,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _seed_execution_feedback_record(
        self,
        *,
        account_profile_id: str,
        run_id: str,
        workflow_type: str,
        decision_card: dict[str, Any],
        result_payload: dict[str, Any],
        created_at: str,
    ) -> FrontdeskExecutionFeedbackRecord | None:
        recommended_action = str(decision_card.get("recommended_action") or "").strip()
        if not recommended_action:
            return None
        persistence_plan = dict(result_payload.get("persistence_plan") or {})
        execution_record = dict(persistence_plan.get("execution_record") or {})
        return self.save_execution_feedback_record(
            account_profile_id=account_profile_id,
            source_run_id=run_id,
            workflow_type=workflow_type,
            recommended_action=recommended_action,
            user_executed=execution_record.get("user_executed"),
            actual_action=None,
            executed_at=None,
            note=execution_record.get("override_reason"),
            feedback_source="system_seed",
            created_at=created_at,
            updated_at=created_at,
            persistence_execution_record=execution_record,
        )

    def save_run_artifacts(
        self,
        *,
        account_profile_id: str,
        run_id: str,
        workflow_type: str,
        status: str,
        decision_card: dict[str, Any],
        result_payload: dict[str, Any],
        input_provenance: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        normalized = _normalize_input_provenance(input_provenance)
        decision_card_payload = dict(decision_card)
        decision_card_payload["input_provenance"] = normalized
        result_payload_with_provenance = dict(result_payload)
        result_payload_with_provenance["decision_card"] = decision_card_payload
        card_build_input = dict(result_payload_with_provenance.get("card_build_input") or {})
        card_build_input["input_provenance"] = normalized
        result_payload_with_provenance["card_build_input"] = card_build_input
        self._seed_execution_plan_record(
            account_profile_id=account_profile_id,
            result_payload=result_payload_with_provenance,
            created_at=created_at,
        )
        comparison = _compare_execution_plans(
            self.get_latest_active_execution_plan(account_profile_id),
            self.get_latest_pending_execution_plan(account_profile_id),
        )
        if comparison is not None:
            decision_card_payload = _decorate_decision_card_with_plan_comparison(decision_card_payload, comparison)
            result_payload_with_provenance["decision_card"] = decision_card_payload
            result_payload_with_provenance["execution_plan_comparison"] = comparison
            card_build_input = dict(result_payload_with_provenance.get("card_build_input") or {})
            execution_plan_summary = dict(card_build_input.get("execution_plan_summary") or {})
            execution_plan_summary["comparison_recommendation"] = comparison.get("recommendation")
            execution_plan_summary["comparison_change_level"] = comparison.get("change_level")
            card_build_input["execution_plan_summary"] = execution_plan_summary
            result_payload_with_provenance["card_build_input"] = card_build_input
        decision_card.clear()
        decision_card.update(decision_card_payload)
        result_payload.clear()
        result_payload.update(result_payload_with_provenance)
        self.save_workflow_run(
            account_profile_id=account_profile_id,
            run_id=run_id,
            workflow_type=workflow_type,
            status=status,
            decision_card=decision_card_payload,
            result_payload=result_payload_with_provenance,
            created_at=created_at,
        )
        self.save_decision_card(
            account_profile_id=account_profile_id,
            run_id=run_id,
            decision_card=decision_card_payload,
            created_at=created_at,
        )
        self._seed_execution_feedback_record(
            account_profile_id=account_profile_id,
            run_id=run_id,
            workflow_type=workflow_type,
            decision_card=decision_card_payload,
            result_payload=result_payload_with_provenance,
            created_at=created_at,
        )
        with self.connect() as conn:
            _persist_input_provenance_records(
                conn,
                account_profile_id=account_profile_id,
                run_id=run_id,
                input_provenance=normalized,
            )
        return normalized

    def save_onboarding_result(
        self,
        *,
        account_profile: dict[str, Any],
        onboarding_result: dict[str, Any],
        input_provenance: dict[str, Any],
        created_at: str | None = None,
    ) -> None:
        self.init_schema()
        account_profile_id = str(account_profile["account_profile_id"])
        display_name = str(account_profile["display_name"])
        normalized_provenance = _normalize_input_provenance(input_provenance)
        result_payload = dict(onboarding_result)
        created_at = str(
            created_at
            or result_payload.get("goal_solver_output", {}).get("generated_at")
            or result_payload.get("created_at")
            or result_payload.get("run_id")
        )
        decision_card = dict(result_payload.get("decision_card") or {})
        decision_card["input_provenance"] = normalized_provenance
        result_payload["decision_card"] = decision_card
        card_build_input = dict(result_payload.get("card_build_input") or {})
        card_build_input["input_provenance"] = normalized_provenance
        result_payload["card_build_input"] = card_build_input

        self.upsert_user_profile(
            account_profile_id=account_profile_id,
            display_name=display_name,
            profile=account_profile,
            created_at=created_at,
        )
        self.save_run_artifacts(
            account_profile_id=account_profile_id,
            run_id=str(result_payload["run_id"]),
            workflow_type=str(result_payload["workflow_type"]),
            status=str(result_payload["status"]),
            decision_card=decision_card,
            result_payload=result_payload,
            input_provenance=normalized_provenance,
            created_at=created_at,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_sessions(
                    account_profile_id,
                    run_id,
                    input_provenance_json,
                    result_payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    account_profile_id,
                    result_payload["run_id"],
                    _json_dumps(normalized_provenance),
                    _json_dumps(result_payload),
                    created_at,
                ),
            )
        if (
            str(result_payload.get("workflow_type")) in {"onboarding", "quarterly"}
            and str(decision_card.get("card_type") or "") != "blocked"
            and result_payload.get("goal_solver_output")
        ):
            self.save_baseline(
                account_profile_id=account_profile_id,
                run_id=str(result_payload["run_id"]),
                workflow_type=str(result_payload["workflow_type"]),
                goal_solver_input=(card_build_input.get("goal_solver_input") or {}),
                goal_solver_output=result_payload.get("goal_solver_output") or {},
                decision_card=decision_card,
                input_provenance=normalized_provenance,
                result_payload=result_payload,
                created_at=created_at,
            )

    def get_execution_feedback(self, source_run_id: str) -> FrontdeskExecutionFeedbackRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM execution_feedback_records
                WHERE source_run_id = ?
                LIMIT 1
                """,
                (source_run_id,),
            ).fetchone()
        if row is None:
            return None
        return FrontdeskExecutionFeedbackRecord(
            account_profile_id=row["account_profile_id"],
            source_run_id=row["source_run_id"],
            workflow_type=row["workflow_type"],
            recommended_action=row["recommended_action"],
            user_executed=_bool_from_db(row["user_executed"]),
            actual_action=row["actual_action"],
            executed_at=row["executed_at"],
            note=row["note"],
            feedback_status=row["feedback_status"],
            feedback_source=row["feedback_source"],
            payload=_json_loads(row["payload_json"]) or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def record_execution_feedback(
        self,
        *,
        account_profile_id: str,
        source_run_id: str,
        user_executed: bool | None,
        actual_action: str | None = None,
        executed_at: str | None = None,
        note: str | None = None,
        feedback_source: str = "user",
        recorded_at: str,
    ) -> FrontdeskExecutionFeedbackRecord:
        existing = self.get_execution_feedback(source_run_id)
        if existing is None:
            raise ValueError(f"no execution feedback seed for run_id={source_run_id}")
        if existing.account_profile_id != account_profile_id:
            raise ValueError("account_profile_id does not match seeded execution record")
        return self.save_execution_feedback_record(
            account_profile_id=account_profile_id,
            source_run_id=source_run_id,
            workflow_type=existing.workflow_type,
            recommended_action=existing.recommended_action,
            user_executed=user_executed,
            actual_action=actual_action,
            executed_at=executed_at,
            note=note,
            feedback_source=feedback_source,
            created_at=existing.created_at,
            updated_at=recorded_at,
            persistence_execution_record=dict(existing.payload.get("persistence_execution_record") or {}),
        )

    def _seed_execution_plan_record(
        self,
        *,
        account_profile_id: str,
        result_payload: dict[str, Any],
        created_at: str,
    ) -> FrontdeskExecutionPlanRecord | None:
        persistence_plan = dict(result_payload.get("persistence_plan") or {})
        execution_plan_record = dict((persistence_plan.get("artifact_records") or {}).get("execution_plan") or {})
        payload = dict(execution_plan_record.get("payload") or {})
        plan_id = str(execution_plan_record.get("plan_id") or payload.get("plan_id") or "").strip()
        if not plan_id:
            return None
        return self.save_execution_plan_record(
            account_profile_id=account_profile_id,
            plan_id=plan_id,
            plan_version=int(execution_plan_record.get("plan_version") or payload.get("plan_version") or 1),
            source_run_id=str(
                execution_plan_record.get("source_run_id") or payload.get("source_run_id") or ""
            ),
            source_allocation_id=str(
                execution_plan_record.get("source_allocation_id")
                or payload.get("source_allocation_id")
                or ""
            ),
            status=str(execution_plan_record.get("status") or payload.get("status") or "draft"),
            confirmation_required=bool(payload.get("confirmation_required", True)),
            payload=payload,
            approved_at=execution_plan_record.get("approved_at") or payload.get("approved_at"),
            superseded_by_plan_id=execution_plan_record.get("superseded_by_plan_id")
            or payload.get("superseded_by_plan_id"),
            created_at=created_at,
            updated_at=created_at,
        )

    def list_execution_feedback(
        self,
        account_profile_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM execution_feedback_records
                WHERE account_profile_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (account_profile_id, int(limit)),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "account_profile_id": row["account_profile_id"],
                    "source_run_id": row["source_run_id"],
                    "workflow_type": row["workflow_type"],
                    "recommended_action": row["recommended_action"],
                    "user_executed": _bool_from_db(row["user_executed"]),
                    "actual_action": row["actual_action"],
                    "executed_at": row["executed_at"],
                    "note": row["note"],
                    "feedback_status": row["feedback_status"],
                    "feedback_source": row["feedback_source"],
                    "payload": _json_loads(row["payload_json"]) or {},
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return records

    def get_execution_feedback_summary(self, account_profile_id: str) -> dict[str, Any]:
        feedback_records = self.list_execution_feedback(account_profile_id, limit=100)
        counts = {"pending": 0, "executed": 0, "skipped": 0}
        for item in feedback_records:
            status = str(item.get("feedback_status") or "pending")
            if status in counts:
                counts[status] += 1
        latest_feedback = feedback_records[0] if feedback_records else None
        return {
            "latest_feedback": latest_feedback,
            "counts": counts,
            "history": feedback_records,
        }

    def load_user_state(self, account_profile_id: str) -> dict[str, Any] | None:
        snapshot = self.get_frontdesk_snapshot(account_profile_id)
        if snapshot is None:
            return None
        profile = dict(snapshot["profile"]["profile"])
        latest_run = snapshot.get("latest_run") or {}
        baseline = snapshot.get("latest_baseline") or {}
        decision_card = dict((latest_run.get("decision_card") or baseline.get("decision_card") or {}))
        if "input_provenance" not in decision_card and baseline.get("input_provenance") is not None:
            decision_card["input_provenance"] = baseline["input_provenance"]
        return {
            "profile": profile,
            "latest_result": {
                "run_id": latest_run.get("run_id"),
                "workflow_type": latest_run.get("workflow_type"),
                "status": latest_run.get("status"),
            },
            "decision_card": decision_card,
            "baseline_card": dict(baseline.get("decision_card") or {}),
            "active_execution_plan": snapshot.get("active_execution_plan"),
            "pending_execution_plan": snapshot.get("pending_execution_plan"),
            "execution_plan_comparison": snapshot.get("execution_plan_comparison"),
            "execution_feedback": snapshot.get("execution_feedback"),
            "execution_feedback_summary": snapshot.get("execution_feedback_summary"),
        }

    def get_user_profile(self, account_profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT account_profile_id, display_name, profile_json, created_at, updated_at
                FROM user_profiles
                WHERE account_profile_id = ?
                """,
                (account_profile_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "account_profile_id": row["account_profile_id"],
            "display_name": row["display_name"],
            "profile": _json_loads(row["profile_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_latest_baseline(self, account_profile_id: str) -> FrontdeskBaselineRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM frontdesk_baselines
                WHERE account_profile_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (account_profile_id,),
            ).fetchone()
        if row is None:
            return None
        return FrontdeskBaselineRecord(
            account_profile_id=row["account_profile_id"],
            run_id=row["run_id"],
            workflow_type=row["workflow_type"],
            goal_solver_input=_json_loads(row["goal_solver_input_json"]) or {},
            goal_solver_output=_json_loads(row["goal_solver_output_json"]) or {},
            decision_card=_json_loads(row["decision_card_json"]) or {},
            input_provenance=_json_loads(row["input_provenance_json"]) or {},
            result_payload=_json_loads(row["result_payload_json"]) or {},
            created_at=row["created_at"],
        )

    def get_latest_run(self, account_profile_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM workflow_runs
                WHERE account_profile_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (account_profile_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "account_profile_id": row["account_profile_id"],
            "run_id": row["run_id"],
            "workflow_type": row["workflow_type"],
            "status": row["status"],
            "decision_card": _json_loads(row["decision_card_json"]) or {},
            "result_payload": _json_loads(row["result_payload_json"]) or {},
            "created_at": row["created_at"],
        }

    def get_latest_active_execution_plan(
        self,
        account_profile_id: str,
    ) -> FrontdeskExecutionPlanRecord | None:
        placeholders = ", ".join("?" for _ in _ACTIVE_EXECUTION_PLAN_STATUSES)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM execution_plan_records
                WHERE account_profile_id = ?
                  AND status IN ({placeholders})
                  AND superseded_by_plan_id IS NULL
                ORDER BY approved_at DESC, updated_at DESC, plan_version DESC, id DESC
                LIMIT 1
                """,
                (account_profile_id, *_ACTIVE_EXECUTION_PLAN_STATUSES),
            ).fetchone()
        return _execution_plan_record_from_row(row)

    def get_latest_pending_execution_plan(
        self,
        account_profile_id: str,
    ) -> FrontdeskExecutionPlanRecord | None:
        placeholders = ", ".join("?" for _ in _PENDING_EXECUTION_PLAN_STATUSES)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM execution_plan_records
                WHERE account_profile_id = ?
                  AND status IN ({placeholders})
                  AND superseded_by_plan_id IS NULL
                  AND plan_id NOT IN (
                      SELECT plan_id
                      FROM execution_plan_records
                      WHERE account_profile_id = ?
                        AND status IN ({", ".join("?" for _ in _ACTIVE_EXECUTION_PLAN_STATUSES)})
                        AND superseded_by_plan_id IS NULL
                  )
                ORDER BY updated_at DESC, plan_version DESC, id DESC
                LIMIT 1
                """,
                (
                    account_profile_id,
                    *_PENDING_EXECUTION_PLAN_STATUSES,
                    account_profile_id,
                    *_ACTIVE_EXECUTION_PLAN_STATUSES,
                ),
            ).fetchone()
        return _execution_plan_record_from_row(row)

    def get_execution_plan_record(
        self,
        account_profile_id: str,
        *,
        plan_id: str,
        plan_version: int,
    ) -> FrontdeskExecutionPlanRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM execution_plan_records
                WHERE account_profile_id = ?
                  AND plan_id = ?
                  AND plan_version = ?
                LIMIT 1
                """,
                (account_profile_id, plan_id, int(plan_version)),
            ).fetchone()
        return _execution_plan_record_from_row(row)

    def approve_execution_plan(
        self,
        account_profile_id: str,
        *,
        plan_id: str,
        plan_version: int,
        approved_at: str,
    ) -> FrontdeskExecutionPlanRecord:
        target = self.get_execution_plan_record(
            account_profile_id,
            plan_id=plan_id,
            plan_version=plan_version,
        )
        if target is None:
            raise ValueError(f"no execution plan for {account_profile_id}: {plan_id}@v{plan_version}")
        if target.superseded_by_plan_id:
            raise ValueError(f"execution plan already superseded: {plan_id}@v{plan_version}")

        active = self.get_latest_active_execution_plan(account_profile_id)
        if (
            active is not None
            and (active.plan_id != target.plan_id or active.plan_version != target.plan_version)
        ):
            superseded_payload = dict(active.payload)
            superseded_payload["status"] = "superseded"
            superseded_payload["superseded_by_plan_id"] = target.plan_id
            self.save_execution_plan_record(
                account_profile_id=account_profile_id,
                plan_id=active.plan_id,
                plan_version=active.plan_version,
                source_run_id=active.source_run_id,
                source_allocation_id=active.source_allocation_id,
                status="superseded",
                confirmation_required=active.confirmation_required,
                payload=superseded_payload,
                created_at=active.created_at,
                updated_at=approved_at,
                approved_at=active.approved_at,
                superseded_by_plan_id=target.plan_id,
            )

        approved_payload = dict(target.payload)
        approved_payload["status"] = "approved"
        approved_payload["approved_at"] = approved_at
        approved_payload["superseded_by_plan_id"] = None
        return self.save_execution_plan_record(
            account_profile_id=account_profile_id,
            plan_id=target.plan_id,
            plan_version=target.plan_version,
            source_run_id=target.source_run_id,
            source_allocation_id=target.source_allocation_id,
            status="approved",
            confirmation_required=target.confirmation_required,
            payload=approved_payload,
            created_at=target.created_at,
            updated_at=approved_at,
            approved_at=approved_at,
            superseded_by_plan_id=None,
        )

    def get_latest_execution_feedback(self, account_profile_id: str) -> dict[str, Any] | None:
        records = self.list_execution_feedback(account_profile_id, limit=1)
        if not records:
            return None
        return records[0]

    def get_frontdesk_snapshot(self, account_profile_id: str) -> dict[str, Any] | None:
        profile = self.get_user_profile(account_profile_id)
        if profile is None:
            return None
        baseline = self.get_latest_baseline(account_profile_id)
        latest_run = self.get_latest_run(account_profile_id)
        active_execution_plan = self.get_latest_active_execution_plan(account_profile_id)
        pending_execution_plan = self.get_latest_pending_execution_plan(account_profile_id)
        execution_feedback_summary = self.get_execution_feedback_summary(account_profile_id)
        return {
            "profile": profile,
            "latest_baseline": None if baseline is None else {
                "run_id": baseline.run_id,
                "workflow_type": baseline.workflow_type,
                "goal_solver_input": baseline.goal_solver_input,
                "goal_solver_output": baseline.goal_solver_output,
                "decision_card": baseline.decision_card,
                "input_provenance": baseline.input_provenance,
                "result_payload": baseline.result_payload,
                "created_at": baseline.created_at,
            },
            "latest_run": latest_run,
            "active_execution_plan": _execution_plan_record_summary(active_execution_plan),
            "pending_execution_plan": _execution_plan_record_summary(pending_execution_plan),
            "execution_plan_comparison": _compare_execution_plans(active_execution_plan, pending_execution_plan),
            "execution_feedback": execution_feedback_summary["latest_feedback"],
            "execution_feedback_summary": execution_feedback_summary,
        }
