from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from snapshot_ingestion.adapters import (
    ExternalSnapshotAdapterError,
    FetchedSnapshotPayload,
    HttpJsonSnapshotAdapterConfig,
    fetch_http_json_snapshot,
)
from snapshot_ingestion.provider_matrix import find_provider_coverage, provider_capability_matrix_dicts

_ALLOWED_INLINE_KEYS = {
    "market_raw",
    "account_raw",
    "behavior_raw",
    "live_portfolio",
}


def _source_ref(config: dict[str, Any], default: str) -> str:
    return str(config.get("source_ref") or default)


def _payload_warning_list(payload: dict[str, Any]) -> list[str]:
    return [str(item) for item in list(payload.get("warnings") or []) if str(item).strip()]


def _coerce_inline_snapshot(config: dict[str, Any]) -> FetchedSnapshotPayload:
    payload = dict(config.get("payload") or {})
    raw_overrides = {
        key: dict(value)
        for key, value in payload.items()
        if key in _ALLOWED_INLINE_KEYS and isinstance(value, dict)
    }
    ignored = [key for key in payload if key not in raw_overrides and key not in {"warnings"}]
    warnings = _payload_warning_list(payload)
    if ignored:
        warnings.append("ignored inline snapshot keys: " + ", ".join(sorted(ignored)))
    provider_name = str(config.get("provider_name") or "inline_snapshot").strip()
    source_ref = _source_ref(config, f"inline://{provider_name}")
    freshness = {
        "as_of": config.get("as_of"),
        "fetched_at": config.get("fetched_at"),
        "domains": {
            key: {
                "status": "fresh",
                "as_of": config.get("as_of"),
                "fetched_at": config.get("fetched_at"),
            }
            for key in raw_overrides
        },
    }
    provenance_items = [
        {
            "field": key,
            "label": key,
            "value": source_ref,
            "note": f"provider={provider_name}; inline_snapshot",
            "freshness": dict(freshness["domains"].get(key) or {}),
        }
        for key in sorted(raw_overrides)
    ]
    return FetchedSnapshotPayload(
        raw_overrides=raw_overrides,
        provenance_items=provenance_items,
        warnings=warnings,
        source_ref=source_ref,
        provider_name=provider_name,
        fetched_at=config.get("fetched_at"),
        requested_as_of=config.get("as_of"),
        freshness=freshness,
    )


def _coerce_local_json_snapshot(config: dict[str, Any]) -> FetchedSnapshotPayload:
    source = str(config.get("snapshot_path") or "").strip()
    if not source:
        raise ValueError("local_json snapshot_path is required")
    path = Path(source)
    payload = json.loads(path.read_text(encoding="utf-8"))
    inline_config = {
        "provider_name": config.get("provider_name") or "local_json_snapshot",
        "source_ref": _source_ref(config, f"file://{path}"),
        "as_of": config.get("as_of"),
        "fetched_at": config.get("fetched_at"),
        "payload": payload,
    }
    return _coerce_inline_snapshot(inline_config)


def fetch_snapshot_from_provider_config(
    config: dict[str, Any] | None,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload | None:
    if not config:
        return None
    adapter_name = str(config.get("adapter") or "http_json").strip().lower()
    if adapter_name == "http_json":
        adapter_config = HttpJsonSnapshotAdapterConfig.from_mapping(config)
        return fetch_http_json_snapshot(
            adapter_config,
            workflow_type=workflow_type,
            account_profile_id=account_profile_id,
            as_of=as_of,
        )
    if adapter_name == "inline_snapshot":
        inline_config = dict(config)
        inline_config.setdefault("as_of", as_of)
        return _coerce_inline_snapshot(inline_config)
    if adapter_name == "local_json":
        local_config = dict(config)
        local_config.setdefault("as_of", as_of)
        return _coerce_local_json_snapshot(local_config)
    raise ValueError(f"unsupported external data adapter: {adapter_name}")


def provider_debug_metadata() -> dict[str, Any]:
    return {
        "capability_matrix": provider_capability_matrix_dicts(),
        "live_portfolio_coverage": (
            find_provider_coverage("live_portfolio").to_dict()
            if find_provider_coverage("live_portfolio") is not None
            else None
        ),
    }


__all__ = [
    "ExternalSnapshotAdapterError",
    "fetch_snapshot_from_provider_config",
    "provider_debug_metadata",
]
