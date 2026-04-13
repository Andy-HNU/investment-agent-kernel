from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(getattr(value, "value", value)).strip()
    return rendered or None


def _unique_string_list(values: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        rendered = _text(value)
        if rendered is None or rendered in seen:
            continue
        seen.add(rendered)
        items.append(rendered)
    return items


def _difference_basis_view(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    return {
        "comparison_scope": _text(payload.get("comparison_scope")),
        "reference_allocation_name": _text(payload.get("reference_allocation_name")),
        "reference_search_expansion_level": _text(payload.get("reference_search_expansion_level")),
    }


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    return True


def build_recommendation_expansion_view(execution_plan_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = _as_dict(execution_plan_summary)
    payload = _as_dict(summary.get("recommendation_expansion"))
    if not payload:
        return {}

    search_expansion_level = _text(payload.get("search_expansion_level")) or _text(summary.get("search_expansion_level"))
    requested_search_expansion_level = _text(payload.get("requested_search_expansion_level"))
    why_this_level_was_run = _text(payload.get("why_this_level_was_run"))
    why_search_stopped = _text(payload.get("why_search_stopped"))
    new_product_ids_added = _unique_string_list(payload.get("new_product_ids_added"))
    products_removed = _unique_string_list(payload.get("products_removed"))

    expanded_alternatives: list[dict[str, Any]] = []
    for item in list(payload.get("expanded_alternatives") or []):
        entry = _as_dict(item)
        alternative = {
            "recommendation_kind": _text(entry.get("recommendation_kind")),
            "allocation_name": _text(entry.get("allocation_name")),
            "search_expansion_level": _text(entry.get("search_expansion_level")),
            "difference_basis": _difference_basis_view(entry.get("difference_basis")),
            "selected_product_ids": _unique_string_list(entry.get("selected_product_ids")),
            "new_product_ids_added": _unique_string_list(entry.get("new_product_ids_added")),
            "products_removed": _unique_string_list(entry.get("products_removed")),
        }
        if _has_meaningful_value(alternative):
            expanded_alternatives.append(alternative)

    view = {
        "search_expansion_level": search_expansion_level,
        "requested_search_expansion_level": requested_search_expansion_level,
        "why_this_level_was_run": why_this_level_was_run,
        "why_search_stopped": why_search_stopped,
        "new_product_ids_added": new_product_ids_added,
        "products_removed": products_removed,
        "expanded_alternatives": expanded_alternatives,
    }
    return view if _has_meaningful_value(view) else {}
