from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from probability_engine.factor_library import FactorDefinition, FactorLibrarySnapshot, FactorReturnObservation


@dataclass(frozen=True)
class ProductHolding:
    security_id: str
    security_name: str
    weight: float
    factor_exposures: dict[str, float]


@dataclass(frozen=True)
class ProductReturnObservation:
    date: str
    product_return: float


@dataclass(frozen=True)
class ProductMappingProduct:
    product_id: str
    product_name: str
    asset_class: str
    region: str
    style: str
    benchmark: str
    wrapper_type: str
    category: str
    cluster_id: str
    history_days: int
    holdings_coverage: float
    holdings_freshness: float
    holdings: tuple[ProductHolding, ...]
    return_series: tuple[ProductReturnObservation, ...]
    cluster_anchor_betas: dict[str, float]


@dataclass(frozen=True)
class ProductMappingBundle:
    bundle_id: str
    as_of: str
    products: tuple[ProductMappingProduct, ...]


@dataclass(frozen=True)
class ReturnsRegressionResult:
    factor_betas: dict[str, float]
    alpha: float
    r_squared: float
    sample_count: int


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
    anchor_source: str
    stage_weights: dict[str, float]


def _coerce_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return dict(value)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _factor_zero_vector(factor_ids: Iterable[str]) -> dict[str, float]:
    return {factor_id: 0.0 for factor_id in factor_ids}


def _vector_for_factor_ids(values: Mapping[str, Any] | None, factor_ids: Iterable[str]) -> dict[str, float]:
    payload = dict(values or {})
    return {factor_id: float(payload.get(factor_id, 0.0) or 0.0) for factor_id in factor_ids}


def _validate_no_precomputed_stage_outputs(payload: dict[str, Any]) -> None:
    forbidden = {
        "prior_factor_betas",
        "holdings_factor_betas",
        "returns_factor_betas",
        "beta_prior",
        "beta_holdings",
        "beta_returns",
        "beta_raw",
        "beta_final",
    }
    unexpected = sorted(key for key in forbidden if key in payload)
    if unexpected:
        raise ValueError(f"product mapping bundle must not contain precomputed stage outputs: {unexpected}")


def _coerce_holdings(value: Any) -> tuple[ProductHolding, ...]:
    if value is None:
        return tuple()
    if not isinstance(value, list):
        raise ValueError("holdings must be a list")
    holdings: list[ProductHolding] = []
    for item in value:
        payload = _coerce_mapping(item, context="holding")
        required = {"security_id", "security_name", "weight", "factor_exposures"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"holding missing fields: {sorted(missing)}")
        exposures = _coerce_mapping(payload["factor_exposures"], context="holding.factor_exposures")
        holdings.append(
            ProductHolding(
                security_id=str(payload["security_id"]),
                security_name=str(payload["security_name"]),
                weight=float(payload["weight"]),
                factor_exposures={str(key): float(value) for key, value in exposures.items()},
            )
        )
    return tuple(holdings)


def _coerce_return_series(value: Any) -> tuple[ProductReturnObservation, ...]:
    if value is None:
        return tuple()
    if not isinstance(value, list):
        raise ValueError("return_series must be a list")
    series: list[ProductReturnObservation] = []
    for item in value:
        payload = _coerce_mapping(item, context="return series observation")
        required = {"date", "return"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"return series observation missing fields: {sorted(missing)}")
        series.append(
            ProductReturnObservation(
                date=str(payload["date"]),
                product_return=float(payload["return"]),
            )
        )
    return tuple(series)


def _coerce_product(value: Any) -> ProductMappingProduct:
    payload = _coerce_mapping(value, context="product")
    _validate_no_precomputed_stage_outputs(payload)
    required = {
        "product_id",
        "product_name",
        "asset_class",
        "region",
        "style",
        "benchmark",
        "wrapper_type",
        "category",
        "cluster_id",
        "history_days",
        "holdings_coverage",
        "holdings_freshness",
        "holdings",
        "return_series",
        "cluster_anchor_betas",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"product missing fields: {sorted(missing)}")
    cluster_anchor_betas = _coerce_mapping(payload["cluster_anchor_betas"], context="cluster_anchor_betas")
    return ProductMappingProduct(
        product_id=str(payload["product_id"]),
        product_name=str(payload["product_name"]),
        asset_class=str(payload["asset_class"]),
        region=str(payload["region"]),
        style=str(payload["style"]),
        benchmark=str(payload["benchmark"]),
        wrapper_type=str(payload["wrapper_type"]),
        category=str(payload["category"]),
        cluster_id=str(payload["cluster_id"]),
        history_days=int(payload["history_days"]),
        holdings_coverage=_clamp(float(payload["holdings_coverage"])),
        holdings_freshness=_clamp(float(payload["holdings_freshness"])),
        holdings=_coerce_holdings(payload["holdings"]),
        return_series=_coerce_return_series(payload["return_series"]),
        cluster_anchor_betas={str(key): float(value) for key, value in cluster_anchor_betas.items()},
    )


def load_product_mapping_bundle(bundle_path: str | Path) -> ProductMappingBundle:
    path = Path(bundle_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("product mapping bundle must be a JSON object")
    products = payload.get("products")
    if not isinstance(products, list):
        raise ValueError("product mapping bundle requires products list")
    return ProductMappingBundle(
        bundle_id=str(payload.get("bundle_id", "")),
        as_of=str(payload.get("as_of", "")),
        products=tuple(_coerce_product(item) for item in products),
    )


def _coerce_factor_library(factor_library: FactorLibrarySnapshot | Mapping[str, Any] | Any) -> FactorLibrarySnapshot:
    if isinstance(factor_library, FactorLibrarySnapshot):
        return factor_library
    payload = _coerce_mapping(factor_library, context="factor library")
    factors_payload = payload.get("factors")
    history_payload = payload.get("factor_return_history")
    if not isinstance(factors_payload, list):
        raise ValueError("factor library must include factors list")
    if not isinstance(history_payload, list):
        raise ValueError("factor library must include factor_return_history list")
    factors = tuple(
        FactorDefinition(
            factor_id=str(item["factor_id"]),
            asset_class=str(item["asset_class"]),
            region=str(item["region"]),
            style=str(item["style"]),
        )
        for item in factors_payload
    )
    factor_ids = tuple(factor.factor_id for factor in factors)
    factor_return_history = tuple(
        FactorReturnObservation(
            date=str(item["date"]),
            factor_returns={factor_id: float(item[factor_id]) for factor_id in factor_ids},
        )
        for item in history_payload
    )
    return FactorLibrarySnapshot(
        snapshot_id=str(payload.get("snapshot_id", "")),
        as_of=str(payload.get("as_of", "")),
        factors=factors,
        factor_return_history=factor_return_history,
    )


def _build_matrix_rows(
    product: ProductMappingProduct,
    factor_library: FactorLibrarySnapshot,
) -> tuple[list[list[float]], list[float]]:
    factor_history_by_date = {row.date: row.factor_returns for row in factor_library.factor_return_history}
    product_history_by_date = {row.date: row.product_return for row in product.return_series}
    common_dates = [row.date for row in factor_library.factor_return_history if row.date in product_history_by_date]

    rows: list[list[float]] = []
    targets: list[float] = []
    for date in common_dates:
        factor_row = factor_history_by_date[date]
        rows.append([1.0] + [float(factor_row[factor_id]) for factor_id in factor_library.factor_ids])
        targets.append(float(product_history_by_date[date]))
    return rows, targets


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[idx]] for idx, row in enumerate(matrix)]
    for col in range(size):
        pivot_row = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        pivot_value = augmented[pivot_row][col]
        if abs(pivot_value) < 1e-12:
            raise ValueError("regression system is singular")
        if pivot_row != col:
            augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot_value = augmented[col][col]
        for idx in range(col, size + 1):
            augmented[col][idx] /= pivot_value
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0.0:
                continue
            for idx in range(col, size + 1):
                augmented[row][idx] -= factor * augmented[col][idx]
    return [augmented[row][size] for row in range(size)]


def _weighted_ridge_regression(
    rows: list[list[float]],
    targets: list[float],
    *,
    ridge: float = 1e-3,
    weights: list[float] | None = None,
) -> tuple[list[float], float]:
    if not rows:
        return [], 0.0
    row_count = len(rows)
    col_count = len(rows[0])
    weights = weights or [1.0] * row_count
    xtwx = [[0.0 for _ in range(col_count)] for _ in range(col_count)]
    xtwy = [0.0 for _ in range(col_count)]
    for row, target, weight in zip(rows, targets, weights, strict=False):
        w = max(0.0, float(weight))
        for i in range(col_count):
            xtwy[i] += w * row[i] * target
            for j in range(col_count):
                xtwx[i][j] += w * row[i] * row[j]
    for i in range(1, col_count):
        xtwx[i][i] += ridge
    xtwx[0][0] += ridge * 0.1
    coeffs = _solve_linear_system(xtwx, xtwy)
    predictions = []
    for row in rows:
        predictions.append(sum(coeff * value for coeff, value in zip(coeffs, row, strict=False)))
    target_mean = sum(targets) / len(targets)
    ss_res = sum((target - pred) ** 2 for target, pred in zip(targets, predictions, strict=False))
    ss_tot = sum((target - target_mean) ** 2 for target in targets)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return coeffs, max(0.0, min(1.0, r_squared))


def build_prior_beta(product: ProductMappingProduct, factor_library: FactorLibrarySnapshot) -> dict[str, float]:
    factor_ids = factor_library.factor_ids
    beta = _factor_zero_vector(factor_ids)
    benchmark = product.benchmark.upper()
    category = product.category.lower()
    asset_class = product.asset_class.lower()
    region = product.region.upper()
    style = product.style.lower()

    if asset_class in {"equity", "stock"} or "equity" in category:
        region_broad = {
            "CN": "CN_EQ_BROAD",
            "US": "US_EQ_BROAD",
            "HK": "HK_EQ_BROAD",
        }.get(region, "CN_EQ_BROAD")
        beta[region_broad] = 0.70
        if "GROWTH" in benchmark or "growth" in style:
            beta[region_broad] -= 0.08
            if "CN" == region:
                beta["CN_EQ_GROWTH"] = 0.16
            elif "US" == region:
                beta["US_EQ_GROWTH"] = 0.16
        if "VALUE" in benchmark or "value" in style:
            beta[region_broad] -= 0.05
            if "CN" == region:
                beta["CN_EQ_VALUE"] = 0.14
        if "CSI300" in benchmark or "BROAD" in benchmark or "core" in category:
            beta[region_broad] = max(beta[region_broad], 0.85)
        beta["GOLD_GLOBAL"] = 0.03
        beta["USD_CNH"] = 0.02
    elif asset_class in {"bond", "fixed_income", "rates"} or "bond" in category:
        beta["CN_RATE_DURATION"] = 0.72
        beta["CN_CREDIT_SPREAD"] = 0.18
        beta["GOLD_GLOBAL"] = 0.03
        beta["USD_CNH"] = 0.02
    elif asset_class in {"commodity", "gold"} or "gold" in category or "gold" in benchmark.lower():
        beta["GOLD_GLOBAL"] = 0.95
        beta["USD_CNH"] = 0.03
    elif asset_class in {"fx", "currency"}:
        beta["USD_CNH"] = 0.95
    else:
        beta["CN_EQ_BROAD"] = 0.40
        beta["CN_RATE_DURATION"] = 0.20
        beta["GOLD_GLOBAL"] = 0.10

    return beta


def build_holdings_beta(product: ProductMappingProduct, factor_library: FactorLibrarySnapshot) -> tuple[dict[str, float], float]:
    factor_ids = factor_library.factor_ids
    beta = _factor_zero_vector(factor_ids)
    if not product.holdings:
        return beta, 0.0

    total_weight = 0.0
    for holding in product.holdings:
        holding_weight = _clamp(holding.weight)
        if holding_weight <= 0.0:
            continue
        total_weight += holding_weight
        for factor_id in factor_ids:
            exposure = _clamp(holding.factor_exposures.get(factor_id, 0.0), 0.0, 10.0)
            beta[factor_id] += holding_weight * exposure

    coverage = _clamp(product.holdings_coverage)
    if total_weight > 0.0 and coverage <= 0.0:
        coverage = _clamp(total_weight)
    return beta, coverage


def build_returns_beta(product: ProductMappingProduct, factor_library: FactorLibrarySnapshot) -> ReturnsRegressionResult:
    rows, targets = _build_matrix_rows(product, factor_library)
    factor_ids = factor_library.factor_ids
    if len(rows) < 2:
        return ReturnsRegressionResult(
            factor_betas=_factor_zero_vector(factor_ids),
            alpha=0.0,
            r_squared=0.0,
            sample_count=len(rows),
        )

    row_count = len(rows)
    weights = [0.5 ** ((row_count - 1 - index) / 63.0) for index in range(row_count)]
    coeffs, r_squared = _weighted_ridge_regression(rows, targets, ridge=1e-3, weights=weights)
    if not coeffs:
        return ReturnsRegressionResult(
            factor_betas=_factor_zero_vector(factor_ids),
            alpha=0.0,
            r_squared=0.0,
            sample_count=row_count,
        )

    return ReturnsRegressionResult(
        factor_betas={factor_id: coeffs[index + 1] for index, factor_id in enumerate(factor_ids)},
        alpha=coeffs[0],
        r_squared=r_squared,
        sample_count=row_count,
    )


def _history_band_max(history_days: int) -> float:
    if history_days < 63:
        return 0.0
    if history_days < 126:
        return 0.20
    if history_days < 252:
        return 0.40
    return 1.0


def _holdings_band_max(coverage: float) -> float:
    if coverage <= 0.0:
        return 0.0
    if coverage < 0.50:
        return 0.20
    if coverage < 0.70:
        return 0.40
    return 0.60


def _stage_weights(product: ProductMappingProduct, returns_r_squared: float) -> dict[str, float]:
    holdings_quality = _clamp(product.holdings_coverage * product.holdings_freshness)
    holdings_weight = min(_holdings_band_max(product.holdings_coverage), 0.5 * holdings_quality)
    returns_weight = min(_history_band_max(product.history_days), 0.5 * _clamp(returns_r_squared))
    if product.history_days < 63:
        returns_weight = 0.0
    if product.holdings_coverage <= 0.0:
        holdings_weight = 0.0
    if product.history_days < 63 and product.holdings_coverage <= 0.0:
        holdings_weight = 0.0
    prior_weight = max(0.0, 1.0 - holdings_weight - returns_weight)
    total = prior_weight + holdings_weight + returns_weight
    if total <= 0.0:
        return {"prior": 1.0, "holdings": 0.0, "returns": 0.0}
    return {
        "prior": prior_weight / total,
        "holdings": holdings_weight / total,
        "returns": returns_weight / total,
    }


def _shrinkage_lambda(product: ProductMappingProduct, stage_weights: dict[str, float]) -> float:
    stage_strength = stage_weights["holdings"] + stage_weights["returns"]
    if product.history_days < 63 and product.holdings_coverage <= 0.0:
        return 0.25
    return min(0.95, 0.55 + 0.35 * stage_strength)


def _resolve_anchor_beta(
    product: ProductMappingProduct,
    prior_beta: dict[str, float],
    factor_library: FactorLibrarySnapshot,
) -> tuple[dict[str, float], str]:
    factor_ids = factor_library.factor_ids
    if product.history_days < 63 and product.holdings_coverage <= 0.0 and product.cluster_anchor_betas:
        return _vector_for_factor_ids(product.cluster_anchor_betas, factor_ids), "cluster_mean"
    return prior_beta, "prior"


def apply_shrinkage_fusion(
    prior_beta: dict[str, float],
    holdings_beta: dict[str, float],
    returns_beta: dict[str, float],
    anchor_beta: dict[str, float],
    stage_weights: dict[str, float],
    shrinkage_lambda: float,
    factor_ids: Iterable[str],
) -> dict[str, float]:
    raw = _factor_zero_vector(factor_ids)
    for factor_id in factor_ids:
        raw[factor_id] = (
            stage_weights["prior"] * prior_beta.get(factor_id, 0.0)
            + stage_weights["holdings"] * holdings_beta.get(factor_id, 0.0)
            + stage_weights["returns"] * returns_beta.get(factor_id, 0.0)
        )

    final = {}
    for factor_id in factor_ids:
        final[factor_id] = shrinkage_lambda * raw[factor_id] + (1.0 - shrinkage_lambda) * anchor_beta.get(factor_id, 0.0)
    return final


def _mapping_confidence(product: ProductMappingProduct, stage_weights: dict[str, float], returns_r_squared: float) -> str:
    score = 0
    if stage_weights["holdings"] > 0.0:
        score += 1
    if stage_weights["returns"] > 0.0:
        score += 1
    if product.holdings_coverage >= 0.70:
        score += 1
    if product.history_days >= 252 and returns_r_squared >= 0.60:
        score += 1
    if product.history_days < 63 and product.holdings_coverage <= 0.0:
        score = 0
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def build_factor_mapping(
    products: Iterable[ProductMappingProduct | Mapping[str, Any] | Any],
    factor_library: FactorLibrarySnapshot | Mapping[str, Any] | Any,
    as_of: str | None = None,
) -> list[ProductFactorMappingResult]:
    library = _coerce_factor_library(factor_library)
    factor_ids = library.factor_ids
    if not factor_ids:
        raise ValueError("factor library must define factor ids")

    results: list[ProductFactorMappingResult] = []
    for item in products:
        product = item if isinstance(item, ProductMappingProduct) else _coerce_product(item)
        if as_of is not None and str(as_of) != library.as_of:
            raise ValueError("as_of does not match factor library snapshot")

        prior_beta = build_prior_beta(product, library)
        holdings_beta, holdings_coverage = build_holdings_beta(product, library)
        returns_result = build_returns_beta(product, library)
        returns_beta = returns_result.factor_betas
        stage_weights = _stage_weights(product, returns_result.r_squared)
        anchor_beta, anchor_source = _resolve_anchor_beta(product, prior_beta, library)
        shrinkage_lambda = _shrinkage_lambda(product, stage_weights)
        raw_beta = {}
        for factor_id in factor_ids:
            raw_beta[factor_id] = (
                stage_weights["prior"] * prior_beta[factor_id]
                + stage_weights["holdings"] * holdings_beta[factor_id]
                + stage_weights["returns"] * returns_beta[factor_id]
            )
        final_beta = apply_shrinkage_fusion(
            prior_beta,
            holdings_beta,
            returns_beta,
            anchor_beta,
            stage_weights,
            shrinkage_lambda,
            factor_ids,
        )
        confidence = _mapping_confidence(product, stage_weights, returns_result.r_squared)
        source = "prior" if stage_weights["holdings"] == 0.0 and stage_weights["returns"] == 0.0 else "blended"
        evidence = [
            {"source": "prior", "weight": stage_weights["prior"]},
            {"source": "holdings", "weight": stage_weights["holdings"], "coverage": holdings_coverage},
            {
                "source": "returns",
                "weight": stage_weights["returns"],
                "sample_count": returns_result.sample_count,
                "r_squared": returns_result.r_squared,
            },
            {"source": "anchor", "weight": 1.0 - shrinkage_lambda, "anchor_source": anchor_source},
        ]

        results.append(
            ProductFactorMappingResult(
                product_id=product.product_id,
                factor_betas=final_beta,
                factor_mapping_source=source,
                mapping_confidence=confidence,
                factor_mapping_evidence=evidence,
                beta_prior=prior_beta,
                beta_holdings=holdings_beta,
                beta_returns=returns_beta,
                beta_raw=raw_beta,
                beta_anchor=anchor_beta,
                shrinkage_lambda=shrinkage_lambda,
                history_days=product.history_days,
                holdings_coverage=holdings_coverage,
                anchor_source=anchor_source,
                stage_weights=stage_weights,
            )
        )

    return results
