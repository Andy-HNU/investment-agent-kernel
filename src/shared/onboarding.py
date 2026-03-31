from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared.product_defaults import (
    build_default_account_raw,
    build_default_allocation_input,
    build_default_behavior_raw,
    build_default_constraint_raw,
    build_default_goal_raw,
    build_default_market_raw,
    product_market_assumptions,
)
from shared.goal_semantics import build_goal_semantics
from shared.profile_dimensions import (
    build_profile_dimensions,
    constraint_profile_from_dimensions,
    goal_priority_from_dimensions,
)
from shared.profile_parser import parse_profile_semantics

_PROVENANCE_SOURCE_LABELS = {
    "user_provided": "用户提供",
    "system_inferred": "系统推断",
    "default_assumed": "默认假设",
    "externally_fetched": "外部抓取",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_risk_preference(value: str) -> str:
    normalized = str(value).strip().lower()
    mapping = {
        "保守": "conservative",
        "conservative": "conservative",
        "中等": "moderate",
        "适中": "moderate",
        "moderate": "moderate",
        "激进": "aggressive",
        "进取": "aggressive",
        "aggressive": "aggressive",
    }
    return mapping.get(normalized, "moderate")


def _normalize_drawdown(value: float) -> float:
    numeric = float(value)
    if numeric > 1.0:
        return numeric / 100.0
    return numeric


def _source_item(field: str, label: str, value: Any, note: str | None = None) -> dict[str, Any]:
    item = {
        "field": field,
        "label": label,
        "value": value,
    }
    if note:
        item["note"] = note
    return item


def _finalize_input_provenance(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    normalized = {
        "items": [],
        "counts": {},
        "source_labels": dict(_PROVENANCE_SOURCE_LABELS),
        "summary": [],
    }
    for source_type, source_label in _PROVENANCE_SOURCE_LABELS.items():
        entries: list[dict[str, Any]] = []
        for item in groups.get(source_type, []):
            payload = dict(item)
            payload.setdefault("source_type", source_type)
            payload.setdefault("source_label", source_label)
            entries.append(payload)
            normalized["items"].append(payload)
        normalized[source_type] = entries
        normalized["counts"][source_type] = len(entries)
        normalized["summary"].append(f"{source_label} {len(entries)} 项")
    return normalized


@dataclass
class UserOnboardingProfile:
    account_profile_id: str
    display_name: str
    current_total_assets: float
    monthly_contribution: float
    goal_amount: float
    goal_horizon_months: int
    risk_preference: str
    max_drawdown_tolerance: float
    current_holdings: str = "cash"
    restrictions: list[str] = field(default_factory=list)
    current_weights: dict[str, float] | None = None
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)
    qdii_allowed: bool | None = None
    profile_parse_notes: list[str] = field(default_factory=list)
    profile_parse_warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    goal_priority: str | None = None
    goal_type: str = "wealth_accumulation"
    goal_amount_basis: str = "nominal"
    goal_amount_scope: str = "total_assets"
    tax_assumption: str = "pre_tax"
    fee_assumption: str = "transaction_cost_only"
    contribution_commitment_confidence: float | None = None
    monthly_contribution_stability: float | None = None
    risk_tolerance_score: float | None = None
    risk_capacity_score: float | None = None
    loss_limit: float | None = None
    liquidity_need_level: str | None = None
    account_type: str = "general_taxable"
    review_frequency: str = "monthly"
    manual_confirmation_threshold: str = "standard"
    goal_semantics: dict[str, Any] = field(default_factory=dict)
    profile_dimensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardingBuildResult:
    profile: UserOnboardingProfile
    input_provenance: dict[str, Any]
    goal_solver_input: dict[str, Any]
    raw_inputs: dict[str, Any]
    live_portfolio: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "input_provenance": self.input_provenance,
            "goal_solver_input": self.goal_solver_input,
            "raw_inputs": self.raw_inputs,
            "live_portfolio": self.live_portfolio,
        }


def _current_weights(profile: UserOnboardingProfile) -> dict[str, float]:
    explicit_weights = _effective_explicit_current_weights(profile)
    if explicit_weights is not None:
        return explicit_weights
    parsed = parse_profile_semantics(
        current_holdings=profile.current_holdings,
        restrictions=profile.restrictions,
        explicit_current_weights=explicit_weights,
    )
    if parsed.current_weights is not None:
        return dict(parsed.current_weights)
    return {}


def _effective_explicit_current_weights(profile: UserOnboardingProfile) -> dict[str, float] | None:
    if profile.current_weights is None:
        return None
    notes = [str(item) for item in profile.profile_parse_notes]
    current_holdings = str(profile.current_holdings or "").strip().lower()
    if any("显式提供 current_weights" in item for item in notes):
        return dict(profile.current_weights)
    if current_holdings.startswith("externally_fetched_"):
        return dict(profile.current_weights)
    return None


def build_user_onboarding_inputs(
    profile: UserOnboardingProfile,
    *,
    as_of: str | None = None,
) -> OnboardingBuildResult:
    as_of = as_of or _iso_now()
    risk_preference = _normalize_risk_preference(profile.risk_preference)
    max_drawdown_tolerance = _normalize_drawdown(profile.max_drawdown_tolerance)
    explicit_current_weights = _effective_explicit_current_weights(profile)
    parsed_profile = parse_profile_semantics(
        current_holdings=profile.current_holdings,
        restrictions=profile.restrictions,
        explicit_current_weights=explicit_current_weights,
    )
    goal_semantics_obj = build_goal_semantics(profile, explicit_semantics=profile.goal_semantics)
    goal_semantics = goal_semantics_obj.to_dict()
    profile_dimensions_obj = build_profile_dimensions(
        profile,
        parsed_profile=parsed_profile.to_dict(),
        goal_semantics=goal_semantics,
    )
    profile_dimensions = profile_dimensions_obj.to_dict()
    constraint_profile = constraint_profile_from_dimensions(profile_dimensions_obj)
    goal_priority = goal_priority_from_dimensions(profile_dimensions_obj)
    success_prob_threshold = 0.75 if goal_priority == "essential" else 0.60 if goal_priority == "aspirational" else 0.70
    persisted_current_weights = (
        dict(explicit_current_weights)
        if explicit_current_weights is not None
        else (dict(parsed_profile.current_weights) if parsed_profile.current_weights is not None else None)
    )
    normalized_profile = UserOnboardingProfile(
        **{
            **profile.to_dict(),
            "current_weights": persisted_current_weights,
            "allowed_buckets": sorted(set(profile.allowed_buckets or parsed_profile.allowed_buckets)),
            "forbidden_buckets": sorted(set(profile.forbidden_buckets or parsed_profile.forbidden_buckets)),
            "preferred_themes": sorted(set(profile.preferred_themes or parsed_profile.preferred_themes)),
            "forbidden_themes": sorted(set(profile.forbidden_themes or parsed_profile.forbidden_themes)),
            "qdii_allowed": profile.qdii_allowed if profile.qdii_allowed is not None else parsed_profile.qdii_allowed,
            "profile_parse_notes": list(parsed_profile.notes),
            "profile_parse_warnings": list(parsed_profile.warnings),
            "requires_confirmation": bool(parsed_profile.requires_confirmation),
            "goal_priority": goal_priority,
            "goal_amount_basis": goal_semantics["goal_amount_basis"],
            "goal_amount_scope": goal_semantics["goal_amount_scope"],
            "tax_assumption": goal_semantics["tax_assumption"],
            "fee_assumption": goal_semantics["fee_assumption"],
            "contribution_commitment_confidence": goal_semantics["contribution_commitment_confidence"],
            "monthly_contribution_stability": profile_dimensions["cashflow_profile"]["monthly_contribution_stability_score"],
            "risk_tolerance_score": profile_dimensions["risk_profile"]["risk_tolerance_score"],
            "risk_capacity_score": profile_dimensions["risk_profile"]["risk_capacity_score"],
            "loss_limit": profile_dimensions["risk_profile"]["loss_limit"],
            "liquidity_need_level": profile_dimensions["risk_profile"]["liquidity_need_level"],
            "account_type": str(profile.account_type or profile_dimensions["account"]["account_type"]),
            "review_frequency": str(profile.review_frequency or profile_dimensions["behavior"]["review_frequency"]),
            "manual_confirmation_threshold": str(
                profile.manual_confirmation_threshold or profile_dimensions["behavior"]["manual_confirmation_threshold"]
            ),
            "goal_semantics": goal_semantics,
            "profile_dimensions": profile_dimensions,
        }
    )
    current_weights = _current_weights(profile)
    current_total_assets = float(profile.current_total_assets)
    monthly_contribution = float(profile.monthly_contribution)
    goal_amount = float(profile.goal_amount)
    goal_horizon_months = int(profile.goal_horizon_months)

    goal_solver_input = {
        "snapshot_id": f"{profile.account_profile_id}_{as_of.replace(':', '').replace('-', '')}",
        "account_profile_id": profile.account_profile_id,
        "goal": {
            "goal_amount": goal_amount,
            "horizon_months": goal_horizon_months,
            "goal_description": f"{goal_horizon_months // 12 or goal_horizon_months}年内目标期末总资产达到{int(goal_amount)}",
            "success_prob_threshold": success_prob_threshold,
            "priority": goal_priority,
            "risk_preference": risk_preference,
            "goal_type": profile.goal_type,
            "goal_amount_basis": goal_semantics["goal_amount_basis"],
            "goal_amount_scope": goal_semantics["goal_amount_scope"],
            "tax_assumption": goal_semantics["tax_assumption"],
            "fee_assumption": goal_semantics["fee_assumption"],
            "contribution_commitment_confidence": goal_semantics["contribution_commitment_confidence"],
        },
        "cashflow_plan": {
            "monthly_contribution": monthly_contribution,
            "annual_step_up_rate": 0.0,
            "cashflow_events": [],
        },
        "current_portfolio_value": current_total_assets,
        "candidate_allocations": [
            {
                "name": "base_allocation",
                "weights": {"equity_cn": 0.55, "bond_cn": 0.30, "gold": 0.05, "satellite": 0.10},
                "complexity_score": 0.2,
                "description": "product default onboarding allocation placeholder",
            }
        ],
        "constraints": build_default_constraint_raw(
            max_drawdown_tolerance=max_drawdown_tolerance,
            parsed_profile=parsed_profile.to_dict(),
            profile_dimensions=profile_dimensions,
        ),
        "solver_params": {
            "version": "v4.0.0",
            "n_paths": 5000,
            "n_paths_lightweight": 1000,
            "seed": 42,
            "market_assumptions": product_market_assumptions(),
        },
        "ranking_mode_override": None,
        "goal_semantics": goal_semantics,
        "profile_dimensions": profile_dimensions,
    }

    live_portfolio = {
        "weights": current_weights,
        "total_value": current_total_assets,
        "available_cash": round(current_total_assets * parsed_profile.available_cash_fraction, 2)
        if parsed_profile.available_cash_fraction > 0
        else (current_total_assets if sum(current_weights.values()) == 0.0 else 0.0),
        "goal_gap": max(goal_amount - current_total_assets, 0.0),
        "remaining_horizon_months": goal_horizon_months,
        "as_of_date": as_of.split("T", 1)[0],
        "current_drawdown": 0.0,
    }

    input_provenance = _finalize_input_provenance({
        "user_provided": [
            _source_item("account_profile.display_name", "账户名", profile.display_name),
            _source_item("goal.goal_amount", "目标期末总资产", goal_amount, "这是总资产目标，不是收益目标"),
            _source_item("goal.horizon_months", "目标期限（月）", goal_horizon_months),
            _source_item("goal.risk_preference", "风险偏好", risk_preference),
            _source_item("goal.priority", "目标优先级", goal_priority_from_dimensions(profile_dimensions)),
            _source_item("account.total_value", "当前总资产", current_total_assets),
            _source_item("cashflow.monthly_contribution", "每月投入", monthly_contribution),
            _source_item(
                "constraint.max_drawdown_tolerance",
                "最大可接受回撤",
                max_drawdown_tolerance,
            ),
            _source_item("account.current_holdings", "当前持仓", profile.current_holdings),
            _source_item("account.restrictions", "限制条件", list(profile.restrictions)),
        ],
        "system_inferred": [
            _source_item("account.available_cash", "可用现金", live_portfolio["available_cash"], "由当前持仓推导"),
            _source_item("goal.goal_gap", "目标缺口", live_portfolio["goal_gap"], "由目标期末总资产和当前总资产推导"),
            _source_item(
                "goal.goal_description",
                "目标描述",
                goal_solver_input["goal"]["goal_description"],
                "由目标期末总资产和期限生成",
            ),
            _source_item(
                "profile_dimensions.risk_tolerance_score",
                "风险承受评分",
                profile_dimensions["risk"]["risk_tolerance_score"],
                "结合风险偏好标签与最大回撤容忍度推断",
            ),
            _source_item(
                "profile_dimensions.risk_capacity_score",
                "风险承载评分",
                profile_dimensions["risk"]["risk_capacity_score"],
                "结合期限、流动性需求和投入可信度推断",
            ),
            _source_item(
                "profile_dimensions.liquidity_need_level",
                "流动性需求等级",
                profile_dimensions["risk"]["liquidity_need_level"],
                "当前产品按 low/medium/high 三档透明展示",
            ),
        ],
        "default_assumed": [
            _source_item("market_raw", "市场输入", "product_default_market_snapshot"),
            _source_item("behavior_raw", "行为输入", "product_default_behavior_snapshot"),
            _source_item("constraint.qdii_cap", "QDII 上限", 0.20),
            _source_item("constraint.liquidity_reserve_min", "最低流动性储备", constraint_profile["liquidity_reserve_min"]),
            _source_item("solver.success_prob_threshold", "目标达成阈值", success_prob_threshold),
        ],
        "externally_fetched": [],
    })
    semantics_value_map = {
        "goal_amount_basis": goal_semantics["goal_amount_basis"],
        "goal_amount_scope": goal_semantics["goal_amount_scope"],
        "tax_assumption": goal_semantics["tax_assumption"],
        "fee_assumption": goal_semantics["fee_assumption"],
        "contribution_commitment_confidence": goal_semantics["contribution_commitment_confidence"],
    }
    semantics_label_map = {
        "goal_amount_basis": "目标金额口径",
        "goal_amount_scope": "目标范围",
        "tax_assumption": "税务口径",
        "fee_assumption": "费用口径",
        "contribution_commitment_confidence": "每月投入兑现置信度",
    }
    semantics_note_map = {
        "goal_amount_basis": "当前只做透明披露，尚未单独折算通胀",
        "goal_amount_scope": goal_semantics["explanation"],
        "tax_assumption": "当前 goal solver 未单独建模税差",
        "fee_assumption": "当前 goal solver 未完整建模综合费率",
        "contribution_commitment_confidence": "当前主要进入解释层和风险分层，不会伪装成已完全进入 solver",
    }
    for field_name, source_type in goal_semantics["provenance"].items():
        input_provenance.setdefault(source_type, []).append(
            _source_item(
                f"goal.{field_name}",
                semantics_label_map[field_name],
                semantics_value_map[field_name],
                semantics_note_map[field_name],
            )
        )
    input_provenance["system_inferred"].append(
        _source_item(
            "profile_dimensions",
            "画像分层模型",
            {
                "goal": profile_dimensions["goal"],
                "risk": profile_dimensions["risk"],
                "cashflow": profile_dimensions["cashflow"],
                "account": profile_dimensions["account"],
                "behavior": profile_dimensions["behavior"],
            },
            "内部按 goal/risk/cashflow/account/behavior 五层建模，前台风险风格仍保留易读标签",
        )
    )
    if parsed_profile.current_weights is not None:
        input_provenance["system_inferred"].append(
            _source_item(
                "account.weights",
                "当前资产桶权重",
                current_weights,
                "根据当前持仓描述结构化解析",
            )
        )
    elif profile.current_weights is None:
        input_provenance["default_assumed"].append(
            _source_item(
                "account.weights",
                "当前资产桶权重",
                current_weights,
                "当前持仓描述未能稳定解析，临时按全现金占位，不代表真实持仓",
            )
        )
    if parsed_profile.notes:
        input_provenance["system_inferred"].append(
            _source_item(
                "account.profile_parse_notes",
                "画像解析说明",
                list(parsed_profile.notes),
                "自然语言画像已被结构化处理",
            )
        )
    if parsed_profile.warnings:
        input_provenance["default_assumed"].append(
            _source_item(
                "account.profile_parse_warnings",
                "画像解析警示",
                list(parsed_profile.warnings),
                "存在无法可靠解析的自然语言字段，本轮结果含占位默认值",
            )
        )
    input_provenance = _finalize_input_provenance({
        "user_provided": input_provenance["user_provided"],
        "system_inferred": input_provenance["system_inferred"],
        "default_assumed": input_provenance["default_assumed"],
        "externally_fetched": input_provenance["externally_fetched"],
    })

    raw_inputs = {
        "account_profile_id": profile.account_profile_id,
        "as_of": as_of,
        "market_raw": build_default_market_raw(goal_solver_input),
        "account_raw": build_default_account_raw(goal_solver_input, live_portfolio),
        "goal_raw": build_default_goal_raw(goal_solver_input),
        "constraint_raw": build_default_constraint_raw(
            max_drawdown_tolerance=max_drawdown_tolerance,
            parsed_profile=parsed_profile.to_dict(),
            profile_dimensions=profile_dimensions,
        ),
        "behavior_raw": build_default_behavior_raw(),
        "remaining_horizon_months": goal_horizon_months,
        "allocation_engine_input": build_default_allocation_input(
            goal_solver_input=goal_solver_input,
            parsed_profile=parsed_profile.to_dict(),
            profile_dimensions=profile_dimensions,
        ),
        "goal_solver_input": goal_solver_input,
        "input_provenance": input_provenance,
        "profile_display_name": profile.display_name,
        "profile_parse": parsed_profile.to_dict(),
        "goal_semantics": goal_semantics,
        "profile_dimensions": profile_dimensions,
    }

    return OnboardingBuildResult(
        profile=normalized_profile,
        input_provenance=input_provenance,
        goal_solver_input=goal_solver_input,
        raw_inputs=raw_inputs,
        live_portfolio=live_portfolio,
    )
