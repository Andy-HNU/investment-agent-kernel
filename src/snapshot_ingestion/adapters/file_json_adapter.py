from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.audit import DataStatus
from snapshot_ingestion.adapters.http_json_adapter import (
    FetchedSnapshotPayload,
    ExternalSnapshotAdapterError,
)

_ALLOWED_OVERRIDE_KEYS = {
    "market_raw": "市场输入",
    "account_raw": "账户快照",
    "behavior_raw": "行为输入",
    "live_portfolio": "组合快照",
}


@dataclass(frozen=True)
class FileJsonSnapshotAdapterConfig:
    file_path: str | None = None
    inline_json: str | None = None
    fail_open: bool = True

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "FileJsonSnapshotAdapterConfig":
        file_path = payload.get("file_path")
        inline_json = payload.get("inline_json")
        fail_open = bool(payload.get("fail_open", True))
        if not file_path and not inline_json:
            raise ValueError("file_json adapter requires file_path or inline_json")
        return cls(file_path=str(file_path) if file_path else None, inline_json=str(inline_json) if inline_json else None, fail_open=fail_open)


def _coerce_raw_overrides(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    overrides: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for key in _ALLOWED_OVERRIDE_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, dict):
            raise ExternalSnapshotAdapterError(f"{_ALLOWED_OVERRIDE_KEYS[key]} 响应必须是对象")
        overrides[key] = dict(value)
    ignored = sorted(
        key
        for key in payload
        if key not in _ALLOWED_OVERRIDE_KEYS
        and key not in {"warnings", "source_ref", "provider_name", "fetched_at", "as_of", "freshness", "domains"}
    )
    if ignored:
        warnings.append("ignored external snapshot keys: " + ", ".join(ignored))
    for item in payload.get("warnings", []) or []:
        text = str(item).strip()
        if text:
            warnings.append(text)
    return overrides, warnings


def _provenance_items_for_source(
    source_ref: str,
    keys: list[str],
    *,
    provider_name: str | None = None,
    fetched_at: str | None = None,
    freshness: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    note_parts = ["通过 file_json_adapter 加载"]
    if provider_name:
        note_parts.append(f"provider={provider_name}")
    if fetched_at:
        note_parts.append(f"fetched_at={fetched_at}")
    note = "; ".join(note_parts)
    return [
        {
            "field": key,
            "label": _ALLOWED_OVERRIDE_KEYS[key],
            "value": source_ref,
            "source_ref": source_ref,
            "as_of": (freshness or {}).get("as_of"),
            "fetched_at": fetched_at,
            "data_status": DataStatus.OBSERVED.value,
            "audit_window": dict((freshness or {}).get("domains", {}).get(key, {}).get("audit_window") or {}),
            "note": note,
            "freshness": dict((freshness or {}).get("domains", {}).get(key) or {}),
        }
        for key in keys
    ]


def fetch_file_json_snapshot(
    config: FileJsonSnapshotAdapterConfig,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload:
    try:
        if config.file_path:
            raw_text = Path(config.file_path).read_text(encoding="utf-8")
        else:
            raw_text = str(config.inline_json or "{}")
        payload = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        if not config.fail_open:
            raise ExternalSnapshotAdapterError(f"external snapshot load failed: {exc}") from exc
        return FetchedSnapshotPayload(
            raw_overrides={},
            provenance_items=[],
            warnings=[f"external snapshot load failed: {exc}"],
            source_ref=config.file_path or "inline-json",
        )

    if not isinstance(payload, dict):
        if not config.fail_open:
            raise ExternalSnapshotAdapterError("external snapshot must decode to an object")
        return FetchedSnapshotPayload(
            raw_overrides={},
            provenance_items=[],
            warnings=["external snapshot must decode to an object"],
            source_ref=config.file_path or "inline-json",
        )

    source_ref = str(payload.get("source_ref") or config.file_path or "inline-json")
    freshness = {
        "as_of": payload.get("as_of") or as_of,
        "fetched_at": payload.get("fetched_at"),
        "domains": {
            str(key): dict(value)
            for key, value in dict(payload.get("domains") or {}).items()
            if isinstance(value, dict)
        },
    }
    overrides, warnings = _coerce_raw_overrides(payload)
    provider_name = str(payload.get("provider_name") or "file_json_fixture").strip() or None
    fetched_at = payload.get("fetched_at")

    return FetchedSnapshotPayload(
        raw_overrides=overrides,
        provenance_items=_provenance_items_for_source(
            source_ref,
            sorted(overrides),
            provider_name=provider_name,
            fetched_at=fetched_at,
            freshness=freshness,
        ),
        warnings=warnings,
        source_ref=source_ref,
        provider_name=provider_name,
        fetched_at=fetched_at,
        requested_as_of=as_of,
        freshness=freshness,
    )


__all__ = [
    "FileJsonSnapshotAdapterConfig",
    "fetch_file_json_snapshot",
]
