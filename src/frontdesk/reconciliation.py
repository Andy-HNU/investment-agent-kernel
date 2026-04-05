from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReconciliationState:
    account_profile_id: str
    snapshot_id: str | None
    status: str
    compared_against: str
    observed_snapshot_id: str | None
    coverage_summary: dict[str, Any]
    bucket_deltas: list[dict[str, Any]]
    product_deltas: list[dict[str, Any]]
    missing_products: list[str]
    unexpected_products: list[str]
    required_actions: list[str]
    blockers: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_profile_id": self.account_profile_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "compared_against": self.compared_against,
            "observed_snapshot_id": self.observed_snapshot_id,
            "coverage_summary": dict(self.coverage_summary),
            "bucket_deltas": list(self.bucket_deltas),
            "product_deltas": list(self.product_deltas),
            "missing_products": list(self.missing_products),
            "unexpected_products": list(self.unexpected_products),
            "required_actions": list(self.required_actions),
            "blockers": list(self.blockers),
            "notes": list(self.notes),
        }


def _bucket_item_index(plan_summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in list((plan_summary or {}).get("items") or []):
        payload = dict(item or {})
        bucket = str(payload.get("asset_bucket") or "").strip()
        if bucket:
            index[bucket] = payload
    return index


def _observed_product_ids_by_bucket(observed_portfolio: dict[str, Any]) -> dict[str, list[str]]:
    by_bucket: dict[str, list[str]] = {}
    for holding in list(observed_portfolio.get("holdings") or []):
        payload = dict(holding or {})
        bucket = str(payload.get("asset_bucket") or "").strip()
        product_id = str(payload.get("product_id") or "").strip()
        if not bucket or not product_id:
            continue
        by_bucket.setdefault(bucket, [])
        if product_id not in by_bucket[bucket]:
            by_bucket[bucket].append(product_id)
    return by_bucket


def reconcile_observed_portfolio(
    *,
    account_profile_id: str,
    observed_portfolio: dict[str, Any],
    active_execution_plan: dict[str, Any] | None,
    pending_execution_plan: dict[str, Any] | None,
) -> ReconciliationState:
    snapshot_id = str(observed_portfolio.get("snapshot_id") or "").strip() or None
    compared_against = (
        "both"
        if active_execution_plan and pending_execution_plan
        else "pending"
        if pending_execution_plan
        else "active"
        if active_execution_plan
        else "none"
    )
    primary_plan = pending_execution_plan or active_execution_plan or {}
    primary_target = (
        "pending"
        if pending_execution_plan
        else "active"
        if active_execution_plan
        else "none"
    )

    observed_weights = dict(observed_portfolio.get("weights") or {})
    total_value = float(observed_portfolio.get("total_value") or 0.0)
    target_items = _bucket_item_index(primary_plan)
    observed_product_ids = _observed_product_ids_by_bucket(observed_portfolio)
    bucket_deltas: list[dict[str, Any]] = []
    product_deltas: list[dict[str, Any]] = []
    all_buckets = sorted(set(observed_weights) | set(target_items))
    max_abs_delta = 0.0

    for bucket in all_buckets:
        target_item = dict(target_items.get(bucket) or {})
        observed_weight = round(float(observed_weights.get(bucket, 0.0) or 0.0), 4)
        target_weight = round(float(target_item.get("target_weight", 0.0) or 0.0), 4)
        delta = round(observed_weight - target_weight, 4)
        max_abs_delta = max(max_abs_delta, abs(delta))
        bucket_deltas.append(
            {
                "asset_bucket": bucket,
                "observed_weight": observed_weight,
                "target_weight": target_weight,
                "weight_delta": delta,
                "observed_amount": round(total_value * observed_weight, 2) if total_value else None,
                "target_amount": target_item.get("target_amount"),
                "note": (
                    "plan coverage target bucket"
                    if bucket in target_items
                    else "observed bucket not present in target plan coverage"
                ),
            }
        )

        target_product_id = str(target_item.get("primary_product_id") or "").strip()
        observed_ids = list(observed_product_ids.get(bucket) or [])
        if target_product_id or observed_ids:
            product_deltas.append(
                {
                    "asset_bucket": bucket,
                    "target_product_id": target_product_id or None,
                    "observed_product_ids": observed_ids,
                    "missing_target_product": bool(target_product_id and target_product_id not in observed_ids),
                    "unexpected_observed_products": [
                        product_id for product_id in observed_ids if product_id != target_product_id
                    ],
                    "note": "plan coverage by product",
                }
            )

    target_product_ids = {
        str(item.get("primary_product_id") or "").strip()
        for item in list(primary_plan.get("items") or [])
        if str(item.get("primary_product_id") or "").strip()
    }
    observed_product_ids_flat = {
        product_id
        for product_ids in observed_product_ids.values()
        for product_id in product_ids
    }
    missing_products = sorted(target_product_ids - observed_product_ids_flat)
    unexpected_products = sorted(observed_product_ids_flat - target_product_ids)

    blockers: list[str] = []
    notes = [
        f"plan coverage primary_target={primary_target}",
        f"plan coverage compared_against={compared_against}",
    ]
    if primary_target == "none":
        status = "pending_user_action"
        blockers.append("no_target_plan")
    elif missing_products or unexpected_products or max_abs_delta > 0.03:
        status = "drifted"
    else:
        status = "aligned"

    required_actions: list[str] = []
    if status == "pending_user_action":
        required_actions.append("approve_or_generate_target_plan")
    if status == "drifted":
        required_actions.append("review_reconciliation_delta")
    if missing_products:
        required_actions.append("confirm_missing_target_products")
    if unexpected_products:
        required_actions.append("confirm_unexpected_observed_products")

    coverage_summary = {
        "active": None if not active_execution_plan else {"plan_id": active_execution_plan.get("plan_id")},
        "pending": None if not pending_execution_plan else {"plan_id": pending_execution_plan.get("plan_id")},
        "primary_target": primary_target,
        "observed_bucket_count": len(observed_weights),
        "target_bucket_count": len(target_items),
        "plan_coverage_note": "plan coverage computed from observed weights/products against the preferred target plan",
    }

    return ReconciliationState(
        account_profile_id=account_profile_id,
        snapshot_id=snapshot_id,
        status=status,
        compared_against=compared_against,
        observed_snapshot_id=snapshot_id,
        coverage_summary=coverage_summary,
        bucket_deltas=bucket_deltas,
        product_deltas=product_deltas,
        missing_products=missing_products,
        unexpected_products=unexpected_products,
        required_actions=required_actions,
        blockers=blockers,
        notes=notes,
    )

