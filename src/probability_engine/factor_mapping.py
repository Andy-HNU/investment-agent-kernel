from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from probability_engine.factor_library import FactorDefinition, FactorLibrarySnapshot


@dataclass(frozen=True)
class ProductMappingBundle:
    bundle_id: str
    as_of: str
    products: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ProductFactorMappingResult:
    product_id: str
    factor_betas: dict[str, float]
    factor_mapping_source: str
    mapping_confidence: str
    factor_mapping_evidence: list[dict[str, Any]]
    beta_prior: dict[str, float]
    beta_holdings: dict[str, float]
    beta_returns: dict[str, float]
    beta_raw: dict[str, float]
    beta_anchor: dict[str, float]
    shrinkage_lambda: float
    history_days: int
    holdings_coverage: float


def load_product_mapping_bundle(bundle_path: str | Path) -> ProductMappingBundle:
    path = Path(bundle_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = tuple(dict(item) for item in list(payload.get("products") or []))
    return ProductMappingBundle(
        bundle_id=str(payload.get("bundle_id", "")),
        as_of=str(payload.get("as_of", "")),
        products=products,
    )


def _coerce_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return dict(value.__dict__)


def _vector_for_factor_ids(values: Mapping[str, Any] | Any | None, factor_ids: Sequence[str]) -> dict[str, float]:
    payload = _coerce_mapping(values or {})
    return {factor_id: float(payload.get(factor_id, 0.0) or 0.0) for factor_id in factor_ids}


def _normalize_history_weight(history_days: int) -> float:
    if history_days < 63:
        return 0.0
    if history_days < 126:
        return 0.20
    if history_days < 252:
        return 0.40
    return 0.60


def _normalize_holdings_weight(coverage: float) -> float:
    if coverage <= 0.0:
        return 0.0
    if coverage < 0.50:
        return 0.20
    if coverage < 0.70:
        return 0.40
    return 0.60


def _blend_vectors(vectors: Sequence[dict[str, float]], weights: Sequence[float], factor_ids: Sequence[str]) -> dict[str, float]:
    totals = {factor_id: 0.0 for factor_id in factor_ids}
    for vector, weight in zip(vectors, weights, strict=False):
        for factor_id in factor_ids:
            totals[factor_id] += float(vector.get(factor_id, 0.0)) * float(weight)
    return totals


def _confidence_for_product(history_days: int, holdings_coverage: float, holdings_weight: float, returns_weight: float) -> str:
    if history_days >= 252 and holdings_coverage >= 0.70 and holdings_weight > 0.0 and returns_weight > 0.0:
        return "high"
    if history_days >= 63 and (holdings_weight > 0.0 or returns_weight > 0.0):
        return "medium"
    return "low"


def _shrinkage_lambda(history_days: int, holdings_coverage: float, holdings_weight: float, returns_weight: float) -> float:
    evidence_strength = holdings_weight + returns_weight
    if history_days < 63 and holdings_coverage > 0.0:
        return 0.35
    if evidence_strength <= 0.0:
        return 0.20
    return min(0.90, 0.30 + 0.35 * evidence_strength)


def _coerce_factor_library(factor_library: FactorLibrarySnapshot | Mapping[str, Any] | Any) -> FactorLibrarySnapshot:
    if isinstance(factor_library, FactorLibrarySnapshot):
        return factor_library
    payload = _coerce_mapping(factor_library)
    factors = tuple(
        FactorDefinition(
            factor_id=str(item["factor_id"]),
            asset_class=str(item["asset_class"]),
            region=str(item["region"]),
            style=str(item["style"]),
        )
        for item in list(payload.get("factors") or [])
    )
    return FactorLibrarySnapshot(
        snapshot_id=str(payload.get("snapshot_id", "")),
        as_of=str(payload.get("as_of", "")),
        factors=factors,
    )


def build_factor_mapping(
    products: Iterable[Mapping[str, Any] | Any],
    factor_library: FactorLibrarySnapshot | Mapping[str, Any] | Any,
    as_of: str | None = None,
) -> list[ProductFactorMappingResult]:
    library = _coerce_factor_library(factor_library)
    factor_ids = library.factor_ids
    if not factor_ids:
        factor_ids = tuple(dict.fromkeys(list(getattr(factor_library, "factor_ids", ()))))  # pragma: no cover - fallback
    results: list[ProductFactorMappingResult] = []

    for product in products:
        payload = _coerce_mapping(product)
        product_id = str(payload.get("product_id", ""))
        history_days = int(payload.get("history_days", 0))
        holdings_coverage = float(payload.get("holdings_coverage", 0.0) or 0.0)
        regression_stability = float(payload.get("regression_stability", 1.0) or 1.0)

        beta_prior = _vector_for_factor_ids(payload.get("prior_factor_betas"), factor_ids)
        beta_holdings = _vector_for_factor_ids(payload.get("holdings_factor_betas"), factor_ids)
        beta_returns = _vector_for_factor_ids(payload.get("returns_factor_betas"), factor_ids)
        beta_anchor = _vector_for_factor_ids(payload.get("cluster_anchor_betas") or beta_prior, factor_ids)

        returns_weight = min(_normalize_history_weight(history_days) * regression_stability, _normalize_history_weight(history_days))
        holdings_weight = min(_normalize_holdings_weight(holdings_coverage) * float(payload.get("holdings_freshness", 1.0) or 1.0), _normalize_holdings_weight(holdings_coverage))
        if history_days < 63:
            returns_weight = 0.0
            beta_returns = {factor_id: 0.0 for factor_id in factor_ids}
        if holdings_coverage < 0.50:
            holdings_weight = min(holdings_weight, 0.20)
        elif holdings_coverage < 0.70:
            holdings_weight = min(holdings_weight, 0.40)

        prior_weight = max(0.0, 1.0 - holdings_weight - returns_weight)
        total_weight = prior_weight + holdings_weight + returns_weight
        if total_weight <= 0.0:
            prior_weight, holdings_weight, returns_weight = 1.0, 0.0, 0.0
        else:
            prior_weight /= total_weight
            holdings_weight /= total_weight
            returns_weight /= total_weight

        beta_raw = _blend_vectors(
            [beta_prior, beta_holdings, beta_returns],
            [prior_weight, holdings_weight, returns_weight],
            factor_ids,
        )

        sparse_anchor = history_days < 63 and holdings_coverage > 0.0
        if sparse_anchor:
            beta_anchor = _vector_for_factor_ids(payload.get("cluster_anchor_betas") or payload.get("prior_factor_betas"), factor_ids)

        shrinkage_lambda = _shrinkage_lambda(history_days, holdings_coverage, holdings_weight, returns_weight)
        beta_final = _blend_vectors([beta_raw, beta_anchor], [shrinkage_lambda, 1.0 - shrinkage_lambda], factor_ids)
        confidence = _confidence_for_product(history_days, holdings_coverage, holdings_weight, returns_weight)

        evidence: list[dict[str, Any]] = [
            {"source": "prior", "weight": prior_weight},
            {"source": "holdings", "weight": holdings_weight, "coverage": holdings_coverage},
            {"source": "returns", "weight": returns_weight, "history_days": history_days},
            {
                "source": "anchor",
                "weight": 1.0 - shrinkage_lambda,
                "anchor_source": "cluster_mean" if sparse_anchor else "prior",
            },
        ]

        source_parts = ["prior"]
        if holdings_weight > 0.0:
            source_parts.append("holdings")
        if returns_weight > 0.0:
            source_parts.append("returns")
        source_parts.append("shrinkage")

        results.append(
            ProductFactorMappingResult(
                product_id=product_id,
                factor_betas=beta_final,
                factor_mapping_source="+".join(source_parts),
                mapping_confidence=confidence,
                factor_mapping_evidence=evidence,
                beta_prior=beta_prior,
                beta_holdings=beta_holdings,
                beta_returns=beta_returns,
                beta_raw=beta_raw,
                beta_anchor=beta_anchor,
                shrinkage_lambda=shrinkage_lambda,
                history_days=history_days,
                holdings_coverage=holdings_coverage,
            )
        )

    return results
