from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from frontdesk.adapter import FrontdeskExternalSnapshotAdapter
from snapshot_ingestion.adapters import (
    ExternalSnapshotAdapterError,
    FetchedSnapshotPayload,
    HttpJsonSnapshotAdapterConfig,
    MarketHistorySnapshotAdapterConfig,
    fetch_http_json_snapshot,
    fetch_market_history_snapshot,
)
from snapshot_ingestion.adapters.file_json_adapter import (
    FileJsonSnapshotAdapterConfig,
    fetch_file_json_snapshot,
)
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config
from shared.providers.registry import registry

_EXTERNAL_FALLBACK_LABEL = "外部抓取降级"
_EXTERNAL_FALLBACK_FIELD = "external_snapshot.fetch"


def _ensure_default_providers_registered() -> None:
    # idempotent registration of built-in providers
    if registry.get_external_snapshot("http_json") is None:
        def _http_json_fetcher(config: dict[str, Any], *, workflow_type: str, account_profile_id: str, as_of: str):
            adapter_config = HttpJsonSnapshotAdapterConfig.from_mapping(config)
            return fetch_http_json_snapshot(
                adapter_config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )

        registry.register_external_snapshot("http_json", _http_json_fetcher)

    if registry.get_external_snapshot("file_json") is None:
        def _file_json_fetcher(config: dict[str, Any], *, workflow_type: str, account_profile_id: str, as_of: str):
            adapter_config = FileJsonSnapshotAdapterConfig.from_mapping(config)
            return fetch_file_json_snapshot(
                adapter_config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )

        registry.register_external_snapshot("file_json", _file_json_fetcher)

    if registry.get_external_snapshot("inline_snapshot") is None:
        def _inline_snapshot_fetcher(config: dict[str, Any], *, workflow_type: str, account_profile_id: str, as_of: str):
            return fetch_snapshot_from_provider_config(
                config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )

        registry.register_external_snapshot("inline_snapshot", _inline_snapshot_fetcher)

    if registry.get_external_snapshot("local_json") is None:
        def _local_json_fetcher(config: dict[str, Any], *, workflow_type: str, account_profile_id: str, as_of: str):
            return fetch_snapshot_from_provider_config(
                config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )

        registry.register_external_snapshot("local_json", _local_json_fetcher)

    if registry.get_external_snapshot("market_history") is None:
        def _market_history_fetcher(config: dict[str, Any], *, workflow_type: str, account_profile_id: str, as_of: str):
            adapter_config = MarketHistorySnapshotAdapterConfig.from_mapping(config)
            return fetch_market_history_snapshot(
                adapter_config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )

        registry.register_external_snapshot("market_history", _market_history_fetcher)


def fetch_external_snapshot(
    config: dict[str, Any] | None,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload | None:
    if not config:
        return None
    _ensure_default_providers_registered()
    adapter_name = str(config.get("adapter") or "http_json").strip().lower()
    fetcher = registry.get_external_snapshot(adapter_name)
    if fetcher is None:
        return fetch_snapshot_from_provider_config(
            config,
            workflow_type=workflow_type,
            account_profile_id=account_profile_id,
            as_of=as_of,
        )
    return fetcher(
        config,
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        as_of=as_of,
    )


def _fetched_snapshot_to_external_payload(
    fetched_snapshot: FetchedSnapshotPayload,
    *,
    base_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = deepcopy(fetched_snapshot.raw_overrides)
    payload["input_provenance"] = merge_external_input_provenance(base_provenance, fetched_snapshot)
    payload["external_metadata"] = {
        "provider_name": fetched_snapshot.provider_name,
        "fetched_at": fetched_snapshot.fetched_at,
        "requested_as_of": fetched_snapshot.requested_as_of,
        "as_of": fetched_snapshot.freshness.get("as_of"),
        "domains": dict(fetched_snapshot.freshness.get("domains") or {}),
    }
    return payload


def load_external_snapshot(
    *,
    source: str | Path | None = None,
    config: dict[str, Any] | None = None,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if source is not None and config is not None:
        raise ValueError("external snapshot source and config are mutually exclusive")
    if config is not None:
        try:
            fetched_snapshot = fetch_external_snapshot(
                config,
                workflow_type=workflow_type,
                account_profile_id=account_profile_id,
                as_of=as_of,
            )
        except Exception as exc:
            return None, str(exc)
        if fetched_snapshot is None:
            return None, None
        return _fetched_snapshot_to_external_payload(fetched_snapshot), None
    if source is None:
        return None, None
    try:
        loaded = FrontdeskExternalSnapshotAdapter(source).load()
    except Exception as exc:
        return None, str(exc)
    return deepcopy(loaded.payload), None


def _merge_domain(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(dict(override or {}))
    return merged


def _goal_amount(raw_inputs: dict[str, Any], goal_solver_input: dict[str, Any] | None) -> float | None:
    if goal_solver_input is not None:
        goal = dict(goal_solver_input.get("goal") or {})
        if goal.get("goal_amount") is not None:
            return float(goal["goal_amount"])
    goal_raw = dict(raw_inputs.get("goal_raw") or {})
    if goal_raw.get("goal_amount") is None:
        return None
    return float(goal_raw["goal_amount"])


def _remaining_horizon(raw_inputs: dict[str, Any], goal_solver_input: dict[str, Any] | None) -> int | None:
    remaining = raw_inputs.get("remaining_horizon_months")
    if remaining is not None:
        return int(remaining)
    if goal_solver_input is not None:
        goal = dict(goal_solver_input.get("goal") or {})
        if goal.get("horizon_months") is not None:
            return int(goal["horizon_months"])
    return None


def apply_external_snapshot_overrides(
    raw_inputs: dict[str, Any],
    *,
    fetched_snapshot: FetchedSnapshotPayload | None,
    goal_solver_input: dict[str, Any] | None,
) -> dict[str, Any]:
    if fetched_snapshot is None or not fetched_snapshot.raw_overrides:
        return raw_inputs

    merged = deepcopy(raw_inputs)
    overrides = fetched_snapshot.raw_overrides

    for key in ("market_raw", "behavior_raw"):
        if key in overrides:
            merged[key] = _merge_domain(merged.get(key), overrides.get(key))

    if "account_raw" in overrides:
        merged["account_raw"] = _merge_domain(merged.get("account_raw"), overrides["account_raw"])

    live_portfolio = _merge_domain(merged.get("live_portfolio"), overrides.get("live_portfolio"))
    account_raw = dict(merged.get("account_raw") or {})
    account_override_present = "account_raw" in overrides
    live_override_present = "live_portfolio" in overrides

    if live_portfolio or account_raw:
        if live_override_present:
            for field in ("weights", "total_value", "available_cash", "remaining_horizon_months"):
                if field in live_portfolio and live_portfolio[field] is not None:
                    account_raw[field] = deepcopy(live_portfolio[field])
        if account_override_present or not live_override_present:
            for field in ("weights", "total_value", "available_cash", "remaining_horizon_months"):
                if field in account_raw and account_raw[field] is not None:
                    live_portfolio[field] = deepcopy(account_raw[field])
        if "weights" not in live_portfolio and "weights" in account_raw:
            live_portfolio["weights"] = dict(account_raw["weights"])
        if "total_value" not in live_portfolio and account_raw.get("total_value") is not None:
            live_portfolio["total_value"] = float(account_raw["total_value"])
        if "available_cash" not in live_portfolio and account_raw.get("available_cash") is not None:
            live_portfolio["available_cash"] = float(account_raw["available_cash"])
        remaining_horizon = _remaining_horizon(merged, goal_solver_input)
        if remaining_horizon is not None:
            live_portfolio.setdefault("remaining_horizon_months", remaining_horizon)
        live_portfolio.setdefault("as_of_date", str(merged.get("as_of", ""))[:10])
        live_portfolio.setdefault("current_drawdown", 0.0)
        if "goal_gap" not in live_portfolio and live_portfolio.get("total_value") is not None:
            goal_amount = _goal_amount(merged, goal_solver_input)
            if goal_amount is not None:
                live_portfolio["goal_gap"] = max(goal_amount - float(live_portfolio["total_value"]), 0.0)
        if goal_solver_input is not None and live_portfolio.get("total_value") is not None:
            merged_goal_solver_input = dict(merged.get("goal_solver_input") or goal_solver_input)
            merged_goal_solver_input["current_portfolio_value"] = float(live_portfolio["total_value"])
            merged["goal_solver_input"] = merged_goal_solver_input
        merged["live_portfolio"] = live_portfolio

    return merged


def merge_external_input_provenance(
    base_provenance: dict[str, Any] | None,
    fetched_snapshot: FetchedSnapshotPayload | None,
) -> dict[str, Any]:
    merged = {
        "user_provided": list((base_provenance or {}).get("user_provided", [])),
        "system_inferred": list((base_provenance or {}).get("system_inferred", [])),
        "default_assumed": list((base_provenance or {}).get("default_assumed", [])),
        "externally_fetched": list((base_provenance or {}).get("externally_fetched", [])),
    }
    if fetched_snapshot is None:
        return merged
    fetched_fields = {str(item.get("field", "unknown")) for item in fetched_snapshot.provenance_items}
    for source_type in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        merged[source_type] = [
            item for item in merged[source_type]
            if str(item.get("field", "unknown")) not in fetched_fields
        ]
    merged["externally_fetched"].extend(fetched_snapshot.provenance_items)
    for warning in fetched_snapshot.warnings:
        merged["default_assumed"].append(
            {
                "field": _EXTERNAL_FALLBACK_FIELD,
                "label": _EXTERNAL_FALLBACK_LABEL,
                "value": warning,
                "note": "外部抓取失败后沿用默认值或已保存数据",
            }
        )
    merged["items"] = []
    merged["counts"] = {}
    merged["source_labels"] = {
        "user_provided": "用户提供",
        "system_inferred": "系统推断",
        "default_assumed": "默认假设",
        "externally_fetched": "外部抓取",
    }
    for source_type in ("user_provided", "system_inferred", "default_assumed", "externally_fetched"):
        for item in merged[source_type]:
            rendered = dict(item)
            rendered.setdefault("source_type", source_type)
            rendered.setdefault("source_label", merged["source_labels"][source_type])
            if item.get("freshness") is not None:
                rendered.setdefault("freshness", item.get("freshness"))
            merged["items"].append(rendered)
        merged["counts"][source_type] = len(merged[source_type])
    return merged


def profile_patch_from_external_snapshot(
    raw_inputs: dict[str, Any],
    *,
    external_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not external_payload:
        return {}
    if external_payload.get("account_raw") is None and external_payload.get("live_portfolio") is None:
        return {}
    patch: dict[str, Any] = {}
    live_portfolio = dict(raw_inputs.get("live_portfolio") or {})
    account_raw = dict(raw_inputs.get("account_raw") or {})
    total_value = live_portfolio.get("total_value", account_raw.get("total_value"))
    weights = live_portfolio.get("weights", account_raw.get("weights"))
    available_cash = live_portfolio.get("available_cash", account_raw.get("available_cash"))
    if total_value is not None:
        patch["current_total_assets"] = float(total_value)
    if isinstance(weights, dict):
        patch["current_weights"] = dict(weights)
    if patch:
        if total_value is not None and available_cash is not None and float(available_cash) >= float(total_value):
            patch["current_holdings"] = "externally_fetched_cash"
        else:
            patch["current_holdings"] = "externally_fetched_snapshot"
    return patch


__all__ = [
    "ExternalSnapshotAdapterError",
    "apply_external_snapshot_overrides",
    "fetch_external_snapshot",
    "load_external_snapshot",
    "merge_external_input_provenance",
    "profile_patch_from_external_snapshot",
]
