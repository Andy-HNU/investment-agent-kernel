from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


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


def _normalize_risk_preference(value: Any) -> str:
    normalized = _text(value).lower()
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


def _normalize_goal_priority(value: Any) -> str | None:
    normalized = _text(value).lower()
    if not normalized:
        return None
    mapping = {
        "essential": "essential",
        "必要": "essential",
        "刚性": "essential",
        "important": "important",
        "重要": "important",
        "aspirational": "aspirational",
        "进取": "aspirational",
        "可选": "aspirational",
    }
    return mapping.get(normalized)


def _normalize_liquidity_need_level(value: Any) -> str | None:
    normalized = _text(value).lower()
    if not normalized:
        return None
    mapping = {
        "low": "low",
        "低": "low",
        "medium": "medium",
        "中": "medium",
        "中等": "medium",
        "high": "high",
        "高": "high",
    }
    return mapping.get(normalized)


def _normalize_account_type(value: Any) -> str:
    normalized = _text(value).lower()
    if not normalized:
        return "taxable_general"
    mapping = {
        "taxable": "taxable_general",
        "taxable_general": "taxable_general",
        "general_taxable": "taxable_general",
        "普通账户": "taxable_general",
        "养老金": "retirement",
        "retirement": "retirement",
        "教育金": "education",
        "education": "education",
    }
    return mapping.get(normalized, normalized.replace(" ", "_"))


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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _cash_fraction(parsed_profile: Mapping[str, Any] | None) -> float:
    if not isinstance(parsed_profile, Mapping):
        return 0.0
    try:
        return _clamp(float(parsed_profile.get("available_cash_fraction") or 0.0), 0.0, 1.0)
    except (TypeError, ValueError):
        return 0.0


def _goal_priority_default(profile: Mapping[str, Any], goal_semantics: Mapping[str, Any] | None) -> tuple[str, str]:
    scope = _text((goal_semantics or {}).get("goal_amount_scope") or profile.get("goal_amount_scope")).lower()
    if scope == "spending_need":
        return "essential", "目标口径为支出需求，默认按刚性目标处理。"
    if scope == "incremental_gain":
        return "aspirational", "目标口径为增量收益，默认按进取型目标处理。"
    return "important", "未提供目标类型时，默认按重要但非刚性目标处理。"


def _infer_risk_tolerance_score(*, risk_preference: str, max_drawdown_tolerance: float) -> tuple[float, str]:
    preference_anchor = {
        "conservative": 0.25,
        "moderate": 0.55,
        "aggressive": 0.80,
    }.get(risk_preference, 0.55)
    drawdown_anchor = _clamp(max_drawdown_tolerance / 0.30, 0.0, 1.0)
    score = round(_clamp(preference_anchor * 0.65 + drawdown_anchor * 0.35, 0.0, 1.0), 4)
    return score, "由风险偏好标签和最大可接受回撤共同推断。"


def _infer_contribution_sustainability(
    *,
    current_total_assets: float,
    monthly_contribution: float,
    goal_horizon_months: int,
) -> tuple[float, str]:
    annual_contribution = max(monthly_contribution, 0.0) * 12.0
    asset_base = max(current_total_assets, 1.0)
    burden_ratio = annual_contribution / asset_base
    duration_penalty = 0.05 if goal_horizon_months >= 60 else 0.0
    score = round(_clamp(0.95 - min(burden_ratio, 2.0) * 0.18 - duration_penalty, 0.35, 0.95), 4)
    return score, "由计划年投入相对当前资产的压力与目标持续时长保守推断。"


def _infer_risk_capacity_score(
    *,
    current_total_assets: float,
    monthly_contribution: float,
    goal_amount: float,
    goal_horizon_months: int,
    contribution_sustainability_score: float,
) -> tuple[float, str]:
    horizon_score = _clamp(goal_horizon_months / 120.0, 0.0, 1.0)
    projected_contributions = max(monthly_contribution, 0.0) * max(goal_horizon_months, 0)
    if goal_amount <= 0:
        funding_ratio = 1.0
    else:
        funding_ratio = _clamp((max(current_total_assets, 0.0) + projected_contributions) / goal_amount, 0.0, 1.0)
    score = round(
        _clamp(
            horizon_score * 0.55 + funding_ratio * 0.30 + contribution_sustainability_score * 0.15,
            0.0,
            1.0,
        ),
        4,
    )
    return score, "由目标期限、现有资产/计划投入覆盖度和投入可持续性共同推断。"


def _infer_liquidity_need_level(*, cash_fraction: float, max_drawdown_tolerance: float) -> tuple[str, str]:
    if cash_fraction >= 0.40 or max_drawdown_tolerance <= 0.08:
        return "high", "由高现金占比或较低回撤容忍度推断为高流动性需求。"
    if cash_fraction >= 0.15 or max_drawdown_tolerance <= 0.15:
        return "medium", "由现金缓冲和回撤容忍度推断为中等流动性需求。"
    return "low", "由较低现金缓冲和较高回撤容忍度推断为较低流动性需求。"


def _project_terminal_value(
    *,
    initial_value: float,
    monthly_contribution: float,
    goal_horizon_months: int,
    monthly_rate: float,
) -> float:
    value = float(initial_value)
    contribution = float(monthly_contribution)
    for _month in range(max(goal_horizon_months, 0)):
        value = value * (1.0 + monthly_rate) + contribution
    return float(value)


def _infer_implied_required_annual_return(
    *,
    initial_value: float,
    monthly_contribution: float,
    goal_horizon_months: int,
    goal_amount: float,
) -> float | None:
    target = float(goal_amount)
    if target <= 0.0 or goal_horizon_months <= 0:
        return None

    lower = -0.999
    upper = 0.02
    lower_value = _project_terminal_value(
        initial_value=initial_value,
        monthly_contribution=monthly_contribution,
        goal_horizon_months=goal_horizon_months,
        monthly_rate=lower,
    )
    upper_value = _project_terminal_value(
        initial_value=initial_value,
        monthly_contribution=monthly_contribution,
        goal_horizon_months=goal_horizon_months,
        monthly_rate=upper,
    )
    while upper_value < target and upper < 5.0:
        upper = upper * 2.0 + 0.01
        upper_value = _project_terminal_value(
            initial_value=initial_value,
            monthly_contribution=monthly_contribution,
            goal_horizon_months=goal_horizon_months,
            monthly_rate=upper,
        )

    if lower_value > target:
        return (1.0 + lower) ** 12 - 1.0
    if upper_value < target:
        return None

    for _ in range(100):
        mid = (lower + upper) / 2.0
        mid_value = _project_terminal_value(
            initial_value=initial_value,
            monthly_contribution=monthly_contribution,
            goal_horizon_months=goal_horizon_months,
            monthly_rate=mid,
        )
        if mid_value >= target:
            upper = mid
        else:
            lower = mid
    return (1.0 + upper) ** 12 - 1.0


def _classify_target_return_pressure(
    *,
    implied_required_annual_return: float | None,
    projected_funding_ratio: float,
) -> tuple[str, str]:
    if implied_required_annual_return is None:
        return "unknown", "目标收益要求当前不可可靠反推。"

    annual_return = float(implied_required_annual_return)
    if annual_return <= 0.04:
        pressure = "low"
    elif annual_return <= 0.07:
        pressure = "medium"
    elif annual_return <= 0.10:
        pressure = "high"
    else:
        pressure = "very_high"

    if projected_funding_ratio < 0.55:
        pressure = {
            "low": "medium",
            "medium": "high",
            "high": "very_high",
            "very_high": "very_high",
        }[pressure]
    elif projected_funding_ratio > 0.95:
        pressure = {
            "low": "low",
            "medium": "low",
            "high": "medium",
            "very_high": "high",
        }[pressure]

    return pressure, "由目标隐含所需年化与现有资产/计划投入覆盖度共同推断。"


def _manual_confirmation_threshold(
    *,
    requires_confirmation: bool,
    risk_tolerance_score: float,
    risk_capacity_score: float,
) -> tuple[str, str]:
    if requires_confirmation:
        return "tight", "当前画像存在未解析字段，人工确认阈值收紧。"
    if min(risk_tolerance_score, risk_capacity_score) <= 0.35:
        return "standard", "风险或承受能力偏低，默认保持标准确认阈值。"
    return "light", "画像较清晰且风险/承受能力不低，可使用较轻的确认阈值。"


@dataclass
class ProfileDimensions:
    schema_version: str
    goal: dict[str, Any]
    risk: dict[str, Any]
    cashflow: dict[str, Any]
    account: dict[str, Any]
    behavior: dict[str, Any]
    provenance: dict[str, str]
    model_inputs: dict[str, Any]
    parsed_profile_snapshot: dict[str, Any]
    assumptions: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "goal_profile": deepcopy(self.goal),
            "risk_profile": deepcopy(self.risk),
            "cashflow_profile": deepcopy(self.cashflow),
            "account_profile": deepcopy(self.account),
            "behavior_profile": deepcopy(self.behavior),
            "provenance": deepcopy(self.provenance),
            "model_inputs": deepcopy(self.model_inputs),
            "parsed_profile_snapshot": deepcopy(self.parsed_profile_snapshot),
            "assumptions": list(self.assumptions),
            "summary": deepcopy(self.model_inputs),
        }
        data["goal"] = deepcopy(self.goal)
        data["risk"] = deepcopy(self.risk)
        data["cashflow"] = deepcopy(self.cashflow)
        data["account"] = deepcopy(self.account)
        data["behavior"] = deepcopy(self.behavior)
        return data

    def __getitem__(self, key: str) -> Any:
        if key in {"goal", "risk", "cashflow", "account", "behavior"}:
            return getattr(self, key)
        if key == "goal_profile":
            return self.goal
        if key == "risk_profile":
            return self.risk
        if key == "cashflow_profile":
            return self.cashflow
        if key == "account_profile":
            return self.account
        if key == "behavior_profile":
            return self.behavior
        if key == "summary":
            return self.model_inputs
        return self.to_dict()[key]

    @property
    def goal_profile(self) -> dict[str, Any]:
        return self.goal

    @property
    def risk_profile(self) -> dict[str, Any]:
        return self.risk

    @property
    def cashflow_profile(self) -> dict[str, Any]:
        return self.cashflow

    @property
    def account_profile(self) -> dict[str, Any]:
        return self.account

    @property
    def behavior_profile(self) -> dict[str, Any]:
        return self.behavior


def build_profile_dimensions(
    profile: Mapping[str, Any] | Any | None = None,
    *,
    parsed_profile: Mapping[str, Any] | None = None,
    goal_semantics: Mapping[str, Any] | None = None,
    explicit_dimensions: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> ProfileDimensions:
    profile_data = _as_mapping(profile)
    if not profile_data:
        profile_data = dict(kwargs)
    parsed_profile_data = dict(parsed_profile or {})
    goal_semantics_data = dict(goal_semantics or {})
    explicit_dimensions = dict(explicit_dimensions or profile_data.get("profile_dimensions") or {})

    def _explicit(section: str, field_name: str) -> Any:
        aliases = {
            "goal_profile": ("goal_profile", "goal"),
            "risk_profile": ("risk_profile", "risk"),
            "cashflow_profile": ("cashflow_profile", "cashflow"),
            "account_profile": ("account_profile", "account"),
            "behavior_profile": ("behavior_profile", "behavior"),
        }
        for alias in aliases.get(section, (section,)):
            value = dict(explicit_dimensions.get(alias) or {}).get(field_name)
            if value is not None:
                return value
        return None

    current_total_assets = float(profile_data.get("current_total_assets") or 0.0)
    monthly_contribution = float(profile_data.get("monthly_contribution") or 0.0)
    goal_amount = float(profile_data.get("goal_amount") or 0.0)
    goal_horizon_months = int(profile_data.get("goal_horizon_months") or 0)
    risk_preference = _normalize_risk_preference(profile_data.get("risk_preference"))
    max_drawdown_tolerance = _clamp(_float_or_none(profile_data.get("max_drawdown_tolerance")) or 0.10, 0.01, 1.0)
    requires_confirmation = bool(profile_data.get("requires_confirmation"))
    cash_fraction = _cash_fraction(parsed_profile_data)

    contribution_sustainability_explicit = _float_or_none(
        _explicit("cashflow_profile", "contribution_commitment_confidence")
        if _explicit("cashflow_profile", "contribution_commitment_confidence") is not None
        else profile_data.get("monthly_contribution_stability")
    )
    if contribution_sustainability_explicit is None:
        confidence_from_goal = _float_or_none(goal_semantics_data.get("contribution_commitment_confidence"))
        if confidence_from_goal is not None:
            contribution_sustainability_score = _clamp(confidence_from_goal, 0.0, 1.0)
            contribution_basis = "沿用目标现实语义中的每月投入兑现可信度。"
            contribution_source = "system_inferred"
        else:
            contribution_sustainability_score, contribution_basis = _infer_contribution_sustainability(
                current_total_assets=current_total_assets,
                monthly_contribution=monthly_contribution,
                goal_horizon_months=goal_horizon_months,
            )
            contribution_source = "system_inferred"
    else:
        contribution_sustainability_score = _clamp(contribution_sustainability_explicit, 0.0, 1.0)
        contribution_basis = "沿用用户显式提供的月度投入可持续性。"
        contribution_source = "user_provided"

    explicit_risk_tolerance = _float_or_none(
        _explicit("risk_profile", "risk_tolerance_score")
        if _explicit("risk_profile", "risk_tolerance_score") is not None
        else profile_data.get("risk_tolerance_score")
    )
    if explicit_risk_tolerance is None:
        risk_tolerance_score, risk_tolerance_basis = _infer_risk_tolerance_score(
            risk_preference=risk_preference,
            max_drawdown_tolerance=max_drawdown_tolerance,
        )
        risk_tolerance_source = "system_inferred"
    else:
        risk_tolerance_score = _clamp(explicit_risk_tolerance, 0.0, 1.0)
        risk_tolerance_basis = "沿用用户显式提供的风险容忍度评分。"
        risk_tolerance_source = "user_provided"

    explicit_risk_capacity = _float_or_none(
        _explicit("risk_profile", "risk_capacity_score")
        if _explicit("risk_profile", "risk_capacity_score") is not None
        else profile_data.get("risk_capacity_score")
    )
    if explicit_risk_capacity is None:
        risk_capacity_score, risk_capacity_basis = _infer_risk_capacity_score(
            current_total_assets=current_total_assets,
            monthly_contribution=monthly_contribution,
            goal_amount=goal_amount,
            goal_horizon_months=goal_horizon_months,
            contribution_sustainability_score=contribution_sustainability_score,
        )
        risk_capacity_source = "system_inferred"
    else:
        risk_capacity_score = _clamp(explicit_risk_capacity, 0.0, 1.0)
        risk_capacity_basis = "沿用用户显式提供的风险承受能力评分。"
        risk_capacity_source = "user_provided"

    explicit_loss_limit = _float_or_none(
        _explicit("risk_profile", "loss_limit")
        if _explicit("risk_profile", "loss_limit") is not None
        else profile_data.get("loss_limit")
    )
    if explicit_loss_limit is None:
        loss_limit = max_drawdown_tolerance
        loss_limit_basis = "沿用最大可接受回撤作为损失上限。"
        loss_limit_source = "system_inferred"
    else:
        loss_limit = _clamp(explicit_loss_limit, 0.0, 1.0)
        loss_limit_basis = "沿用用户显式提供的损失上限。"
        loss_limit_source = "user_provided"

    explicit_liquidity_need_level = _normalize_liquidity_need_level(
        _explicit("risk_profile", "liquidity_need_level")
        if _explicit("risk_profile", "liquidity_need_level") is not None
        else profile_data.get("liquidity_need_level")
    )
    if explicit_liquidity_need_level is None:
        liquidity_need_level, liquidity_basis = _infer_liquidity_need_level(
            cash_fraction=cash_fraction,
            max_drawdown_tolerance=max_drawdown_tolerance,
        )
        liquidity_source = "system_inferred"
    else:
        liquidity_need_level = explicit_liquidity_need_level
        liquidity_basis = "沿用用户显式提供的流动性需求等级。"
        liquidity_source = "user_provided"
    liquidity_need_score = {
        "low": 0.25,
        "medium": 0.55,
        "high": 0.85,
    }[liquidity_need_level]

    explicit_goal_priority = _normalize_goal_priority(
        _explicit("goal_profile", "goal_priority")
        if _explicit("goal_profile", "goal_priority") is not None
        else profile_data.get("goal_priority")
    )
    if explicit_goal_priority is None:
        goal_priority, goal_priority_basis = _goal_priority_default(profile_data, goal_semantics_data)
        goal_priority_source = "default_assumed"
    else:
        goal_priority = explicit_goal_priority
        goal_priority_basis = "沿用用户显式提供的目标优先级。"
        goal_priority_source = "user_provided"

    review_frequency = _text(
        _explicit("behavior_profile", "review_frequency")
        if _explicit("behavior_profile", "review_frequency") is not None
        else profile_data.get("review_frequency")
    ) or "monthly"
    account_type = _normalize_account_type(
        _explicit("account_profile", "account_type")
        if _explicit("account_profile", "account_type") is not None
        else profile_data.get("account_type")
    )
    confirmation_threshold, confirmation_basis = _manual_confirmation_threshold(
        requires_confirmation=requires_confirmation,
        risk_tolerance_score=risk_tolerance_score,
        risk_capacity_score=risk_capacity_score,
    )
    projected_contributions = float(monthly_contribution) * max(goal_horizon_months, 0)
    projected_funding_ratio = (
        1.0
        if goal_amount <= 0.0
        else _clamp((max(current_total_assets, 0.0) + projected_contributions) / goal_amount, 0.0, 1.0)
    )
    implied_required_annual_return = _infer_implied_required_annual_return(
        initial_value=current_total_assets,
        monthly_contribution=monthly_contribution,
        goal_horizon_months=goal_horizon_months,
        goal_amount=goal_amount,
    )
    target_return_pressure, target_return_pressure_basis = _classify_target_return_pressure(
        implied_required_annual_return=implied_required_annual_return,
        projected_funding_ratio=projected_funding_ratio,
    )

    goal_gap = max(goal_amount - current_total_assets, 0.0)
    goal_profile = {
        "goal_type": _text(profile_data.get("goal_type")) or "wealth_accumulation",
        "goal_priority": goal_priority,
        "goal_gap": round(goal_gap, 2),
        "projected_funding_ratio": round(projected_funding_ratio, 4),
        "implied_required_annual_return": (
            None if implied_required_annual_return is None else round(implied_required_annual_return, 4)
        ),
        "target_return_pressure": target_return_pressure,
        "goal_amount_basis": _text(goal_semantics_data.get("goal_amount_basis")) or "nominal",
        "goal_amount_scope": _text(goal_semantics_data.get("goal_amount_scope")) or "total_assets",
        "goal_priority_source": goal_priority_source,
        "goal_priority_basis": goal_priority_basis,
        "target_return_pressure_source": "system_inferred",
        "target_return_pressure_basis": target_return_pressure_basis,
    }
    risk_profile = {
        "risk_preference_label": risk_preference,
        "risk_tolerance_score": risk_tolerance_score,
        "risk_capacity_score": risk_capacity_score,
        "loss_limit": round(loss_limit, 4),
        "volatility_aversion_score": round(_clamp(1.0 - risk_tolerance_score, 0.0, 1.0), 4),
        "liquidity_need_level": liquidity_need_level,
        "risk_tolerance_score_source": risk_tolerance_source,
        "risk_tolerance_score_basis": risk_tolerance_basis,
        "risk_capacity_score_source": risk_capacity_source,
        "risk_capacity_score_basis": risk_capacity_basis,
        "loss_limit_source": loss_limit_source,
        "loss_limit_basis": loss_limit_basis,
        "liquidity_need_level_source": liquidity_source,
        "liquidity_need_level_basis": liquidity_basis,
    }
    cashflow_profile = {
        "monthly_contribution_stability_score": contribution_sustainability_score,
        "contribution_commitment_confidence": contribution_sustainability_score,
        "contribution_commitment_confidence_source": contribution_source,
        "contribution_commitment_confidence_basis": contribution_basis,
        "emergency_fund_assumption_months": 3,
        "emergency_fund_assumption_source": "default_assumed",
        "emergency_fund_assumption_basis": "当前未采集生活支出数据，默认仅保留三个月应急金假设用于展示，不直接进入 solver。",
    }
    account_profile = {
        "account_type": account_type,
        "liquidity_need_level": liquidity_need_level,
        "tax_assumption": _text(goal_semantics_data.get("tax_assumption")) or "pre_tax",
        "fee_assumption": _text(goal_semantics_data.get("fee_assumption")) or "transaction_cost_only",
        "cash_buffer_fraction": round(cash_fraction, 4),
        "cash_buffer_fraction_source": "system_inferred",
        "cash_buffer_fraction_basis": "由当前持仓解析出的现金占比推断。",
    }
    behavior_profile = {
        "review_frequency": review_frequency,
        "manual_confirmation_threshold": confirmation_threshold,
        "manual_confirmation_threshold_source": "system_inferred",
        "manual_confirmation_threshold_basis": confirmation_basis,
        "requires_confirmation": requires_confirmation,
    }

    provenance = {
        "goal_priority": goal_priority_source,
        "target_return_pressure": "system_inferred",
        "risk_tolerance_score": risk_tolerance_source,
        "risk_capacity_score": risk_capacity_source,
        "loss_limit": loss_limit_source,
        "liquidity_need_level": liquidity_source,
        "contribution_commitment_confidence": contribution_source,
        "tax_assumption": "user_provided" if account_profile["tax_assumption"] != "pre_tax" else "default_assumed",
        "fee_assumption": "user_provided" if account_profile["fee_assumption"] != "transaction_cost_only" else "default_assumed",
    }

    assumptions = [
        goal_priority_basis if goal_priority_source != "user_provided" else None,
        contribution_basis if contribution_source != "user_provided" else None,
        "收入稳定性和真实生活支出当前未直接采集，因此相关维度仅作保守推断。",
    ]
    return ProfileDimensions(
        schema_version="p1.v1",
        goal=goal_profile,
        risk=risk_profile,
        cashflow=cashflow_profile,
        account=account_profile,
        behavior=behavior_profile,
        provenance=provenance,
        model_inputs={
            "risk_tolerance_score": risk_tolerance_score,
            "risk_capacity_score": risk_capacity_score,
            "loss_limit": round(loss_limit, 4),
            "liquidity_need_level": liquidity_need_level,
            "liquidity_need_score": liquidity_need_score,
            "goal_priority": goal_priority,
            "projected_funding_ratio": round(projected_funding_ratio, 4),
            "implied_required_annual_return": (
                None if implied_required_annual_return is None else round(implied_required_annual_return, 4)
            ),
            "target_return_pressure": target_return_pressure,
            "contribution_commitment_confidence": contribution_sustainability_score,
        },
        parsed_profile_snapshot=dict(parsed_profile_data),
        assumptions=[item for item in assumptions if item],
    )


def goal_priority_from_dimensions(dimensions: ProfileDimensions | Mapping[str, Any]) -> str:
    data = dimensions.to_dict() if hasattr(dimensions, "to_dict") else dict(dimensions)
    return str((data.get("goal_profile") or {}).get("goal_priority") or "important")


def constraint_profile_from_dimensions(dimensions: ProfileDimensions | Mapping[str, Any]) -> dict[str, float]:
    data = dimensions.to_dict() if hasattr(dimensions, "to_dict") else dict(dimensions)
    risk = dict(data.get("risk_profile") or {})
    cashflow = dict(data.get("cashflow_profile") or {})
    goal = dict(data.get("goal_profile") or {})
    headroom = min(
        float(risk.get("risk_tolerance_score", 0.55)),
        float(risk.get("risk_capacity_score", 0.55)),
    )
    liquidity = str(risk.get("liquidity_need_level") or "medium").lower()
    contribution_confidence = float(cashflow.get("contribution_commitment_confidence", 0.80))
    target_return_pressure = str((data.get("model_inputs") or {}).get("target_return_pressure") or "").lower()
    satellite_cap = 0.15 if headroom >= 0.75 else 0.08 if headroom >= 0.45 else 0.05
    liquidity_reserve_min = 0.10 if liquidity == "high" else 0.08 if contribution_confidence < 0.70 else 0.05
    equity_cap = 0.75 if headroom >= 0.75 else 0.60 if headroom >= 0.45 else 0.45
    if target_return_pressure in {"high", "very_high"} and headroom >= 0.45 and liquidity != "high":
        satellite_cap = max(satellite_cap, 0.12 if target_return_pressure == "high" else 0.15)
        equity_cap = max(equity_cap, 0.70 if target_return_pressure == "high" else 0.75)
    goal_priority = str(goal.get("goal_priority") or "important")
    success_prob_threshold = 0.75 if goal_priority == "essential" else 0.70 if goal_priority == "important" else 0.60
    return {
        "satellite_cap": satellite_cap,
        "liquidity_reserve_min": liquidity_reserve_min,
        "equity_cap": equity_cap,
        "success_prob_threshold": success_prob_threshold,
    }


def allocation_profile_flags(dimensions: ProfileDimensions | Mapping[str, Any]) -> dict[str, Any]:
    data = dimensions.to_dict() if hasattr(dimensions, "to_dict") else dict(dimensions)
    return dict(data.get("model_inputs") or {})


def complexity_tolerance_from_dimensions(dimensions: ProfileDimensions | Mapping[str, Any]) -> str:
    data = dimensions.to_dict() if hasattr(dimensions, "to_dict") else dict(dimensions)
    risk = dict(data.get("risk_profile") or {})
    goal = dict(data.get("goal_profile") or {})
    headroom = min(
        float(risk.get("risk_tolerance_score", 0.55)),
        float(risk.get("risk_capacity_score", 0.55)),
    )
    liquidity = str(risk.get("liquidity_need_level") or "medium").lower()
    if liquidity == "high" or headroom <= 0.45:
        return "low"
    if headroom >= 0.75 and str(goal.get("goal_priority") or "important") != "essential":
        return "high"
    return "medium"
