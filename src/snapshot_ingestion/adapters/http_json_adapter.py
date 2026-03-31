from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

_ALLOWED_OVERRIDE_KEYS = {
    "market_raw": "市场输入",
    "account_raw": "账户快照",
    "behavior_raw": "行为输入",
    "live_portfolio": "组合快照",
}


class ExternalSnapshotAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpJsonSnapshotAdapterConfig:
    snapshot_url: str
    timeout_seconds: float = 2.0
    fail_open: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "HttpJsonSnapshotAdapterConfig":
        snapshot_url = str(payload.get("snapshot_url") or "").strip()
        if not snapshot_url:
            raise ValueError("external_data.snapshot_url is required")
        timeout_seconds = float(payload.get("timeout_seconds", 2.0))
        fail_open = bool(payload.get("fail_open", True))
        headers = {
            str(key): str(value)
            for key, value in dict(payload.get("headers") or {}).items()
        }
        query_params = dict(payload.get("query_params") or {})
        return cls(
            snapshot_url=snapshot_url,
            timeout_seconds=timeout_seconds,
            fail_open=fail_open,
            headers=headers,
            query_params=query_params,
        )


@dataclass(frozen=True)
class FetchedSnapshotPayload:
    raw_overrides: dict[str, dict[str, Any]]
    provenance_items: list[dict[str, Any]]
    warnings: list[str]
    source_ref: str
    provider_name: str | None = None
    fetched_at: str | None = None
    requested_as_of: str | None = None
    freshness: dict[str, Any] = field(default_factory=dict)


def _build_request_url(
    config: HttpJsonSnapshotAdapterConfig,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> str:
    parsed = urlparse(config.snapshot_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({str(key): str(value) for key, value in config.query_params.items()})
    query.update(
        {
            "workflow_type": workflow_type,
            "account_profile_id": account_profile_id,
            "as_of": as_of,
        }
    )
    return urlunparse(parsed._replace(query=urlencode(query)))


def _provenance_items_for_source(
    source_ref: str,
    keys: list[str],
    *,
    provider_name: str | None = None,
    fetched_at: str | None = None,
    freshness: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    note_parts = ["通过 http_json_adapter 抓取"]
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
            "note": note,
            "freshness": dict((freshness or {}).get("domains", {}).get(key) or {}),
        }
        for key in keys
    ]


def _coerce_raw_overrides(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    overrides: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for key, label in _ALLOWED_OVERRIDE_KEYS.items():
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, dict):
            raise ExternalSnapshotAdapterError(f"{label} 响应必须是对象")
        overrides[key] = dict(value)
    ignored = sorted(
        key for key in payload
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


def fetch_http_json_snapshot(
    config: HttpJsonSnapshotAdapterConfig,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload:
    request_url = _build_request_url(
        config,
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        as_of=as_of,
    )
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            **config.headers,
        },
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        if not config.fail_open:
            raise ExternalSnapshotAdapterError(f"external snapshot fetch failed: {exc}") from exc
        return FetchedSnapshotPayload(
            raw_overrides={},
            provenance_items=[],
            warnings=[f"external snapshot fetch failed: {exc}"],
            source_ref=request_url,
        )

    if not isinstance(payload, dict):
        if not config.fail_open:
            raise ExternalSnapshotAdapterError("external snapshot response must decode to an object")
        return FetchedSnapshotPayload(
            raw_overrides={},
            provenance_items=[],
            warnings=["external snapshot response must decode to an object"],
            source_ref=request_url,
        )
    try:
        overrides, warnings = _coerce_raw_overrides(payload)
    except ExternalSnapshotAdapterError as exc:
        if not config.fail_open:
            raise
        return FetchedSnapshotPayload(
            raw_overrides={},
            provenance_items=[],
            warnings=[str(exc)],
            source_ref=str(payload.get("source_ref") or request_url),
        )
    source_ref = str(payload.get("source_ref") or request_url)
    freshness = {
        "as_of": payload.get("as_of") or as_of,
        "fetched_at": payload.get("fetched_at"),
        "domains": {
            str(key): dict(value)
            for key, value in dict(payload.get("domains") or {}).items()
            if isinstance(value, dict)
        },
    }
    freshness_payload = payload.get("freshness")
    if isinstance(freshness_payload, dict):
        freshness.update({key: value for key, value in freshness_payload.items() if key != "domains"})
        if isinstance(freshness_payload.get("domains"), dict):
            freshness["domains"].update(
                {
                    str(key): dict(value)
                    for key, value in dict(freshness_payload.get("domains") or {}).items()
                    if isinstance(value, dict)
                }
            )
    provider_name = str(payload.get("provider_name") or "").strip() or None
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
