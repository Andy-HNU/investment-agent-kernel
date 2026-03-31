from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 < numeric <= 100.0:
        return numeric / 100.0
    return numeric


def _normalize_basis(value: Any) -> str:
    normalized = _text(value).lower()
    mapping = {
        "nominal": "nominal",
        "名义": "nominal",
        "real": "real",
        "实际购买力": "real",
        "real_terms": "real",
    }
    return mapping.get(normalized, "nominal")


def _normalize_scope(value: Any) -> str:
    normalized = _text(value).lower()
    mapping = {
        "total_assets": "total_assets",
        "总资产": "total_assets",
        "期末总资产": "total_assets",
        "incremental_gain": "incremental_gain",
        "收益": "incremental_gain",
        "增量收益": "incremental_gain",
        "spending_need": "spending_need",
        "支出": "spending_need",
        "支出需求": "spending_need",
    }
    return mapping.get(normalized, "total_assets")


def _normalize_tax_assumption(value: Any) -> str:
    normalized = _text(value).lower()
    mapping = {
        "pre_tax": "pre_tax",
        "税前": "pre_tax",
        "after_tax": "after_tax",
        "税后": "after_tax",
        "unknown": "unknown",
        "未指定": "unknown",
    }
    return mapping.get(normalized, "pre_tax")


def _normalize_fee_assumption(value: Any) -> str:
    normalized = _text(value).lower()
    mapping = {
        "transaction_cost_defaults_only": "transaction_cost_only",
        "transaction_cost_only": "transaction_cost_only",
        "默认交易费": "transaction_cost_only",
        "default_transaction_cost_only": "transaction_cost_only",
        "platform_fee_excluded": "platform_fee_excluded",
        "不含平台费": "platform_fee_excluded",
        "all_inclusive": "all_included",
        "all_included": "all_included",
        "全费用": "all_included",
        "unknown": "unknown",
        "未指定": "unknown",
    }
    return mapping.get(normalized, "transaction_cost_only")


@dataclass
class GoalSemantics:
    schema_version: str
    goal_amount_basis: str
    goal_amount_scope: str
    goal_amount_label: str
    tax_assumption: str
    fee_assumption: str
    contribution_commitment_confidence: float
    modeled_goal_scope: str
    solver_alignment: str
    field_sources: dict[str, str]
    explanation: str
    user_visible_summary: str
    user_visible_disclosures: list[str]
    modeling_status: dict[str, bool]

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provenance"] = data.pop("field_sources")
        data["disclosure_lines"] = list(data.get("user_visible_disclosures", []))
        data["summary_lines"] = [
            data.get("user_visible_summary"),
            *list(data.get("user_visible_disclosures", [])),
        ]
        return data


def build_goal_semantics(
    profile: Any | None = None,
    *,
    profile_dimensions: Any | None = None,
    explicit_semantics: dict[str, Any] | None = None,
    **profile_kwargs: Any,
) -> GoalSemantics:
    profile_data = _as_mapping(profile)
    if profile_kwargs:
        profile_data.update(profile_kwargs)
    if explicit_semantics:
        for key, value in explicit_semantics.items():
            profile_data.setdefault(key, value)
    profile_dimensions_data = _as_mapping(profile_dimensions)

    goal_amount_basis_explicit = _text(profile_data.get("goal_amount_basis"))
    goal_amount_scope_explicit = _text(profile_data.get("goal_amount_scope"))
    tax_assumption_explicit = _text(profile_data.get("tax_assumption"))
    fee_assumption_explicit = _text(profile_data.get("fee_assumption"))
    contribution_confidence_explicit = _float_or_none(profile_data.get("contribution_commitment_confidence"))

    goal_amount_basis = _normalize_basis(goal_amount_basis_explicit)
    goal_amount_scope = _normalize_scope(goal_amount_scope_explicit)
    tax_assumption = _normalize_tax_assumption(tax_assumption_explicit)
    fee_assumption = _normalize_fee_assumption(fee_assumption_explicit)
    goal_amount_label = {
        "total_assets": "目标期末总资产",
        "incremental_gain": "目标累计增量收益",
        "spending_need": "目标资金需求",
    }[goal_amount_scope]

    inferred_confidence = _float_or_none(
        (
            (profile_dimensions_data.get("cashflow_profile") or profile_dimensions_data.get("cashflow") or {})
        ).get("contribution_commitment_confidence")
    )
    contribution_commitment_confidence = (
        _clamp(contribution_confidence_explicit, 0.0, 1.0)
        if contribution_confidence_explicit is not None
        else _clamp(inferred_confidence if inferred_confidence is not None else 0.75, 0.0, 1.0)
    )

    amount_scope_note = {
        "total_assets": "目标按目标期末总资产理解，包含当前资产与计划持续投入，不是收益目标。",
        "incremental_gain": "目标按增量收益口径记录；当前 solver 仍以总资产路径代理求解，前台只做透明披露，不会伪装成已完成专门建模。",
        "spending_need": "目标按未来支出需求口径记录；当前 solver 仍以总资产路径代理求解，前台只做透明披露，不会伪装成专门现金流支出模型。",
    }[goal_amount_scope]
    amount_basis_note = {
        "nominal": "当前按名义金额展示，未单独折算通胀。",
        "real": "你要求按实际购买力理解目标；当前系统只做透明披露，尚未把通胀折现真正接入 solver。",
    }[goal_amount_basis]
    tax_note = {
        "pre_tax": "当前按税前口径展示，未单独建模税负差异。",
        "after_tax": "你要求按税后口径理解目标；当前系统只做透明披露，尚未把税后现金流真正接入 solver。",
        "unknown": "税务口径尚未指定，当前结果不能被理解为税后可支配金额。",
    }[tax_assumption]
    fee_note = {
        "transaction_cost_only": "当前仅纳入默认交易费率，没有单独加入平台费/顾问费。",
        "platform_fee_excluded": "当前结果未纳入平台费/顾问费，只纳入默认交易费率。",
        "all_included": "你要求按全费用口径理解目标；当前系统只做透明披露，尚未把额外平台费/顾问费真正接入 solver。",
        "unknown": "费用口径尚未指定；当前结果只保证纳入默认交易费率，额外平台费/顾问费未单独建模。",
    }[fee_assumption]
    contribution_note = (
        f"系统把未来每月投入视为计划持续发生，持续性置信度约 {contribution_commitment_confidence * 100:.0f}% 。"
    )

    solver_alignment = "fully_modeled"
    modeled_goal_scope = "total_assets"
    if goal_amount_scope != "total_assets" or goal_amount_basis != "nominal" or tax_assumption != "pre_tax" or fee_assumption != "transaction_cost_only":
        solver_alignment = "disclosure_only"
    if goal_amount_scope != "total_assets":
        modeled_goal_scope = "total_assets_proxy"

    explicit_keys = set(explicit_semantics or {})

    return GoalSemantics(
        schema_version="p1.goal_semantics.v1",
        goal_amount_basis=goal_amount_basis,
        goal_amount_scope=goal_amount_scope,
        goal_amount_label=goal_amount_label,
        tax_assumption=tax_assumption,
        fee_assumption=fee_assumption,
        contribution_commitment_confidence=round(contribution_commitment_confidence, 4),
        modeled_goal_scope=modeled_goal_scope,
        solver_alignment=solver_alignment,
        field_sources={
            "goal_amount_basis": "user_provided"
            if "goal_amount_basis" in explicit_keys or (goal_amount_basis_explicit and goal_amount_basis != "nominal")
            else "default_assumed",
            "goal_amount_scope": "user_provided"
            if "goal_amount_scope" in explicit_keys or (goal_amount_scope_explicit and goal_amount_scope != "total_assets")
            else "default_assumed",
            "tax_assumption": "user_provided"
            if "tax_assumption" in explicit_keys or (tax_assumption_explicit and tax_assumption != "pre_tax")
            else "default_assumed",
            "fee_assumption": "user_provided"
            if "fee_assumption" in explicit_keys or (fee_assumption_explicit and fee_assumption != "transaction_cost_only")
            else "default_assumed",
            "contribution_commitment_confidence": "user_provided"
            if "contribution_commitment_confidence" in explicit_keys or contribution_confidence_explicit is not None
            else "system_inferred",
        },
        explanation=amount_scope_note,
        user_visible_summary=amount_scope_note,
        user_visible_disclosures=[
            amount_scope_note,
            amount_basis_note,
            tax_note,
            fee_note,
            contribution_note,
        ],
        modeling_status={
            "goal_amount_scope_modeled_directly": goal_amount_scope == "total_assets",
            "goal_amount_basis_modeled_directly": goal_amount_basis == "nominal",
            "tax_modeled_directly": False,
            "fee_modeled_directly": fee_assumption == "transaction_cost_only",
        },
    )
