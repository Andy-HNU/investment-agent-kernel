from __future__ import annotations

from product_mapping.types import ProductCandidate, ProductConstraintProfile, RecommendedProduct


_LIQUIDITY_PRIORITY = {"high": 0, "medium": 1, "low": 2}
_FEE_PRIORITY = {"low": 0, "medium": 1, "high": 2}
_TRACKING_PRIORITY = {"high": 0, "medium": 1, "low": 2}
_BUCKET_SLICE_TEMPLATE: dict[str, list[tuple[str, float]]] = {
    "equity_cn": [("core", 0.60), ("core", 0.25), ("core", 0.15)],
    "bond_cn": [("defense", 0.50), ("defense", 0.30), ("defense", 0.20)],
    "gold": [("defense", 0.70), ("defense", 0.30)],
    "cash_liquidity": [("cash", 0.70), ("cash", 0.30)],
    "satellite": [
        ("satellite", 0.25),
        ("satellite", 0.20),
        ("satellite", 0.20),
        ("satellite", 0.20),
        ("satellite", 0.15),
    ],
}


def normalize_user_restrictions(restrictions: list[str] | None) -> ProductConstraintProfile:
    profile = ProductConstraintProfile()
    if not restrictions:
        return profile

    forbidden_exposures = set(profile.forbidden_exposures)
    forbidden_wrappers = set(profile.forbidden_wrappers)
    forbidden_styles = set(profile.forbidden_styles)
    allowed_wrappers = set(profile.allowed_wrappers)
    allowed_markets = set(profile.allowed_markets)
    warnings = list(profile.warnings)
    notes = list(profile.notes)

    for raw_item in restrictions:
        item = str(raw_item).strip().lower()
        if not item:
            continue
        if any(token in item for token in ("不碰股票", "不买股票", "不能买股票")):
            forbidden_wrappers.add("single_stock")
            notes.append("限制条件“不买股票”默认解释为禁个股，但保留 ETF/基金形式的权益暴露。")
        if any(token in item for token in ("不碰科技", "不买科技", "不能买科技")):
            forbidden_styles.update({"technology", "chip", "innovation"})
            notes.append("限制条件“不碰科技”已过滤科技/芯片/创新风格产品。")
        if any(token in item for token in ("不买qdii", "不碰qdii", "不能买qdii")):
            allowed_markets.add("CN")
            notes.append("限制条件“不买QDII”已将候选市场收缩为中国市场。")
        if any(token in item for token in ("只接受黄金和现金", "只接受现金和黄金", "只能黄金和现金", "只要黄金和现金")):
            forbidden_exposures.update({"equity_cn", "bond_cn", "satellite"})
            warnings.append("限制条件“只接受黄金和现金”已过滤权益、债券与卫星暴露。")

    return ProductConstraintProfile(
        forbidden_exposures=forbidden_exposures,
        forbidden_wrappers=forbidden_wrappers,
        forbidden_styles=forbidden_styles,
        allowed_wrappers=allowed_wrappers,
        allowed_markets=allowed_markets,
        warnings=warnings,
        notes=notes,
    )


def product_matches_constraints(candidate: ProductCandidate, constraints: ProductConstraintProfile) -> bool:
    if candidate.asset_bucket in constraints.forbidden_exposures:
        return False
    if candidate.wrapper_type in constraints.forbidden_wrappers:
        return False
    if constraints.allowed_wrappers and candidate.wrapper_type not in constraints.allowed_wrappers:
        return False
    if constraints.allowed_markets and candidate.market not in constraints.allowed_markets:
        return False
    if set(candidate.style_tags).intersection(constraints.forbidden_styles):
        return False
    return candidate.enabled and not candidate.deprecated


def rank_bucket_candidates(bucket: str, candidates: list[ProductCandidate]) -> list[ProductCandidate]:
    def _score(candidate: ProductCandidate) -> tuple[int, int, int, float, float, str]:
        valuation_rank = candidate.valuation_percentile if candidate.valuation_percentile is not None else 0.50
        policy_rank = -(candidate.policy_news_score or 0.0) if bucket == "satellite" else 0.0
        role_rank = 0 if candidate.core_or_satellite in {"core", "defense", "cash"} else 1
        if bucket == "satellite":
            role_rank = 0 if candidate.core_or_satellite == "satellite" else 1
        return (
            role_rank,
            _LIQUIDITY_PRIORITY.get(candidate.liquidity_tier, 9),
            _FEE_PRIORITY.get(candidate.fee_tier, 9),
            valuation_rank,
            policy_rank,
            candidate.product_id,
        )

    return sorted(candidates, key=_score)


def build_recommended_products(
    *,
    bucket: str,
    target_weight: float,
    ordered_candidates: list[ProductCandidate],
) -> list[RecommendedProduct]:
    if not ordered_candidates or target_weight <= 0:
        return []

    slices = _BUCKET_SLICE_TEMPLATE.get(bucket, [("core", 1.0)])
    recommended: list[RecommendedProduct] = []
    for index, (role, weight_within_bucket) in enumerate(slices):
        candidate = ordered_candidates[index % len(ordered_candidates)]
        selection_reason = [
            f"命中 {bucket} 的 {role} 配置切片。",
            f"按流动性/费率/跟踪质量排序后纳入第 {index + 1} 顺位。",
        ]
        if candidate.valuation_percentile is not None:
            selection_reason.append(f"估值分位 {candidate.valuation_percentile:.0%}。")
        if candidate.policy_news_score is not None and bucket == "satellite":
            selection_reason.append(f"政策/新闻评分 {candidate.policy_news_score:.2f}。")
        recommended.append(
            RecommendedProduct(
                product_id=candidate.product_id,
                product_name=candidate.product_name,
                wrapper_type=candidate.wrapper_type,
                market=candidate.market,
                core_or_satellite=role,
                target_weight_within_bucket=round(weight_within_bucket, 4),
                target_portfolio_weight=round(target_weight * weight_within_bucket, 4),
                selection_reason=selection_reason,
                style_tags=list(candidate.style_tags),
                product=candidate,
            )
        )
    return recommended


def build_selection_evidence(
    *,
    bucket: str,
    ordered_candidates: list[ProductCandidate],
    constraints: ProductConstraintProfile,
) -> dict[str, object]:
    primary = ordered_candidates[0] if ordered_candidates else None
    return {
        "core_or_satellite": primary.core_or_satellite if primary else (
            "satellite" if bucket == "satellite" else ("cash" if bucket == "cash_liquidity" else "core")
        ),
        "selection_reason": [
            f"候选按 {bucket} 的产品家族、流动性、费率、估值与政策信号排序。",
            "约束先于排序执行，确保个股/风格/市场过滤生效。",
        ],
        "constraint_summary": constraints.to_dict(),
        "candidate_count": len(ordered_candidates),
        "primary_style_tags": list(primary.style_tags) if primary else [],
    }
