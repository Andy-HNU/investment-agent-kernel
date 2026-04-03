from __future__ import annotations

from typing import Any

from product_mapping.catalog import load_builtin_catalog


def _catalog_index() -> dict[str, dict[str, Any]]:
    return {candidate.product_id: candidate.to_dict() for candidate in load_builtin_catalog()}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_observed_holdings(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    catalog = _catalog_index()
    normalized_holdings: list[dict[str, Any]] = []
    total_market_value = 0.0
    for raw_item in holdings:
        item = dict(raw_item or {})
        product_id = str(item.get("product_id") or "").strip()
        if not product_id:
            continue
        catalog_entry = dict(catalog.get(product_id) or {})
        market_value = _safe_float(item.get("market_value"))
        total_market_value += market_value
        normalized = {
            "product_id": product_id,
            "product_name": str(
                item.get("product_name")
                or catalog_entry.get("product_name")
                or product_id
            ),
            "market_value": market_value,
            "cost_basis": _safe_float(item.get("cost_basis")) if item.get("cost_basis") is not None else None,
            "confidence": _safe_float(item.get("confidence")) if item.get("confidence") is not None else None,
            "asset_bucket": str(catalog_entry.get("asset_bucket") or "unmapped"),
            "wrapper_type": str(catalog_entry.get("wrapper_type") or "other"),
            "market": str(catalog_entry.get("market") or "UNKNOWN"),
        }
        normalized_holdings.append(normalized)

    for item in normalized_holdings:
        item["portfolio_weight"] = (
            round(item["market_value"] / total_market_value, 6) if total_market_value > 0.0 else 0.0
        )

    return {
        "holdings": normalized_holdings,
        "total_market_value": round(total_market_value, 6),
    }


def _target_plan_items(target_plan_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((target_plan_payload or {}).get("items") or [])


def _target_plan_product_ids(target_plan_payload: dict[str, Any] | None) -> set[str]:
    product_ids: set[str] = set()
    for item in _target_plan_items(target_plan_payload):
        payload = dict(item or {})
        primary_product = dict(payload.get("primary_product") or {})
        direct_primary = str(payload.get("primary_product_id") or primary_product.get("product_id") or "").strip()
        if direct_primary:
            product_ids.add(direct_primary)
        for alternate in list(payload.get("alternate_product_ids") or []):
            alternate_id = str(alternate or "").strip()
            if alternate_id:
                product_ids.add(alternate_id)
        for recommended in list(payload.get("recommended_products") or []):
            recommended_id = str(dict(recommended or {}).get("product_id") or "").strip()
            if recommended_id:
                product_ids.add(recommended_id)
    return product_ids


def reconcile_observed_portfolio(
    *,
    observed_portfolio: dict[str, Any],
    target_plan_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_plan_payload = dict(target_plan_payload or {})
    holdings = list(observed_portfolio.get("holdings") or [])
    observed_by_bucket: dict[str, float] = {}
    drift_by_product: dict[str, dict[str, Any]] = {}
    for holding in holdings:
        bucket = str(holding.get("asset_bucket") or "unmapped")
        observed_by_bucket[bucket] = observed_by_bucket.get(bucket, 0.0) + _safe_float(
            holding.get("portfolio_weight")
        )
        drift_by_product[str(holding.get("product_id") or "")] = {
            "product_name": holding.get("product_name"),
            "market_value": _safe_float(holding.get("market_value")),
            "portfolio_weight": _safe_float(holding.get("portfolio_weight")),
            "asset_bucket": bucket,
            "confidence": holding.get("confidence"),
        }

    target_by_bucket: dict[str, float] = {}
    for item in _target_plan_items(target_plan_payload):
        payload = dict(item or {})
        bucket = str(payload.get("asset_bucket") or "unmapped")
        target_by_bucket[bucket] = _safe_float(payload.get("target_weight"))

    drift_by_bucket: dict[str, dict[str, Any]] = {}
    for bucket in sorted(set(observed_by_bucket) | set(target_by_bucket)):
        observed_weight = round(observed_by_bucket.get(bucket, 0.0), 6)
        target_weight = round(target_by_bucket.get(bucket, 0.0), 6)
        drift_by_bucket[bucket] = {
            "observed_weight": observed_weight,
            "target_weight": target_weight,
            "weight_delta": round(observed_weight - target_weight, 6),
        }

    target_product_ids = _target_plan_product_ids(target_plan_payload)
    unexpected_products = sorted(
        product_id
        for product_id in drift_by_product
        if product_id and product_id not in target_product_ids
    )
    max_bucket_drift = max(
        (abs(dict(item or {}).get("weight_delta") or 0.0) for item in drift_by_bucket.values()),
        default=0.0,
    )
    if not target_plan_payload:
        planned_action_status = "stale"
    elif unexpected_products or max_bucket_drift >= 0.03:
        planned_action_status = "partial"
    else:
        planned_action_status = "completed"

    return {
        "target_plan_id": str(target_plan_payload.get("plan_id") or ""),
        "target_plan_version": int(target_plan_payload.get("plan_version") or 0),
        "planned_action_status": planned_action_status,
        "drift_by_bucket": drift_by_bucket,
        "drift_by_product": drift_by_product,
        "unexpected_products": unexpected_products,
        "summary": [
            f"observed {len(holdings)} products",
            f"unexpected_products={len(unexpected_products)}",
            f"max_bucket_drift={max_bucket_drift:.2%}",
        ],
    }
