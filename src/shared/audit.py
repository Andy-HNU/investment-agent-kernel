from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any


class DataStatus(str, Enum):
    OBSERVED = "observed"
    COMPUTED_FROM_OBSERVED = "computed_from_observed"
    INFERRED = "inferred"
    PRIOR_DEFAULT = "prior_default"
    SYNTHETIC_DEMO = "synthetic_demo"
    MANUAL_ANNOTATION = "manual_annotation"


class RunOutcomeStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


FormalPathStatus = RunOutcomeStatus

_RESULT_CATEGORIES = {
    "formal_independent_result",
    "formal_estimated_result",
    "degraded_formal_result",
    "exploratory_result",
}
_FORMAL_EXECUTION_POLICIES = {"FORMAL_STRICT", "FORMAL_ESTIMATION_ALLOWED"}
_DISCLOSURE_LEVELS = {"point_and_range", "range_only", "diagnostic_only", "unavailable"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}
_DATA_COMPLETENESS = {"complete", "partial", "sparse"}


_LEGACY_FORMAL_PATH_STATUS_ALIASES = {
    "formal": RunOutcomeStatus.COMPLETED.value,
    "ok": RunOutcomeStatus.COMPLETED.value,
    "fallback_used_but_not_formal": RunOutcomeStatus.DEGRADED.value,
    "not_requested": RunOutcomeStatus.UNAVAILABLE.value,
}


def coerce_data_status(value: DataStatus | str) -> DataStatus:
    if isinstance(value, DataStatus):
        return value
    try:
        return DataStatus(str(value).strip().lower())
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown data_status: {value}") from exc


def coerce_run_outcome_status(value: RunOutcomeStatus | str) -> RunOutcomeStatus:
    if isinstance(value, RunOutcomeStatus):
        return value
    try:
        return RunOutcomeStatus(str(value).strip().lower())
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown run_outcome_status: {value}") from exc


def coerce_formal_path_status(value: FormalPathStatus | str) -> FormalPathStatus:
    if isinstance(value, FormalPathStatus):
        return value
    normalized = str(value).strip().lower()
    normalized = _LEGACY_FORMAL_PATH_STATUS_ALIASES.get(normalized, normalized)
    try:
        return FormalPathStatus(normalized)
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown formal_path_status: {value}") from exc


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _normalize_ratio(value: Any, *, fallback: float) -> float:
    if value is None:
        normalized = fallback
    else:
        normalized = float(value)
        if normalized > 1.0 and normalized <= 100.0 and normalized.is_integer():
            normalized /= 100.0
    if normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"coverage ratio must be between 0.0 and 1.0: {value}")
    return normalized


@dataclass(frozen=True)
class CoverageSummary:
    security_level_coverage: float = 0.0
    weight_adjusted_coverage: float = 0.0
    independent_weight_adjusted_coverage: float = 0.0
    horizon_complete_coverage: float = 0.0
    independent_horizon_complete_coverage: float = 0.0
    distribution_ready_coverage: float = 0.0
    explanation_ready_coverage: float = 0.0
    selected_product_count: int = 0
    observed_product_count: int = 0
    inferred_product_count: int = 0
    missing_product_count: int = 0
    blocking_products: list[str] = field(default_factory=list)
    observed_ratio: float = 0.0
    inferred_ratio: float = 0.0
    missing_ratio: float = 0.0
    covered_ratio: float = 0.0

    @classmethod
    def from_any(cls, value: "CoverageSummary | dict[str, Any] | None") -> "CoverageSummary | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        payload = dict(value)
        selected_product_count = max(int(payload.get("selected_product_count") or 0), 0)
        observed_product_count = max(int(payload.get("observed_product_count") or 0), 0)
        inferred_product_count = max(int(payload.get("inferred_product_count") or 0), 0)
        missing_product_count = max(int(payload.get("missing_product_count") or 0), 0)
        denominator = float(selected_product_count or 0)
        observed_ratio = _normalize_ratio(
            payload.get("observed_ratio"),
            fallback=0.0 if denominator == 0.0 else observed_product_count / denominator,
        )
        inferred_ratio = _normalize_ratio(
            payload.get("inferred_ratio"),
            fallback=0.0 if denominator == 0.0 else inferred_product_count / denominator,
        )
        missing_ratio = _normalize_ratio(
            payload.get("missing_ratio"),
            fallback=0.0 if denominator == 0.0 else missing_product_count / denominator,
        )
        covered_ratio = _normalize_ratio(
            payload.get("covered_ratio"),
            fallback=min(1.0, observed_ratio + inferred_ratio),
        )
        security_level_coverage = _normalize_ratio(
            payload.get("security_level_coverage"),
            fallback=covered_ratio,
        )
        weight_adjusted_coverage = _normalize_ratio(
            payload.get("weight_adjusted_coverage"),
            fallback=security_level_coverage,
        )
        independent_weight_adjusted_coverage = _normalize_ratio(
            payload.get("independent_weight_adjusted_coverage", payload.get("independent_coverage")),
            fallback=weight_adjusted_coverage,
        )
        horizon_complete_coverage = _normalize_ratio(
            payload.get("horizon_complete_coverage", payload.get("horizon_coverage")),
            fallback=security_level_coverage,
        )
        independent_horizon_complete_coverage = _normalize_ratio(
            payload.get("independent_horizon_complete_coverage"),
            fallback=min(horizon_complete_coverage, independent_weight_adjusted_coverage),
        )
        distribution_ready_coverage = _normalize_ratio(
            payload.get("distribution_ready_coverage", payload.get("distribution_coverage")),
            fallback=independent_weight_adjusted_coverage,
        )
        explanation_ready_coverage = _normalize_ratio(
            payload.get("explanation_ready_coverage", payload.get("explanation_coverage")),
            fallback=security_level_coverage,
        )
        return cls(
            security_level_coverage=security_level_coverage,
            weight_adjusted_coverage=weight_adjusted_coverage,
            independent_weight_adjusted_coverage=independent_weight_adjusted_coverage,
            horizon_complete_coverage=horizon_complete_coverage,
            independent_horizon_complete_coverage=independent_horizon_complete_coverage,
            distribution_ready_coverage=distribution_ready_coverage,
            explanation_ready_coverage=explanation_ready_coverage,
            selected_product_count=selected_product_count,
            observed_product_count=observed_product_count,
            inferred_product_count=inferred_product_count,
            missing_product_count=missing_product_count,
            blocking_products=[
                str(item) for item in list(payload.get("blocking_products") or []) if str(item).strip()
            ],
            observed_ratio=observed_ratio,
            inferred_ratio=inferred_ratio,
            missing_ratio=missing_ratio,
            covered_ratio=covered_ratio,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DisclosureDecision:
    result_category: str = ""
    disclosure_level: str = "diagnostic_only"
    confidence_level: str = "low"
    data_completeness: str = "partial"
    calibration_quality: str = "insufficient_sample"
    point_value_allowed: bool = False
    range_required: bool = False
    diagnostic_only: bool = True
    precision_cap: str = "diagnostic_only"
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized_category = str(self.result_category or "").strip().lower()
        if normalized_category and normalized_category not in _RESULT_CATEGORIES:
            raise ValueError(f"unknown result_category: {self.result_category}")
        disclosure_level = str(self.disclosure_level or "diagnostic_only").strip().lower()
        if disclosure_level not in _DISCLOSURE_LEVELS:
            raise ValueError(f"unknown disclosure_level: {self.disclosure_level}")
        confidence_level = str(self.confidence_level or "low").strip().lower()
        if confidence_level not in _CONFIDENCE_LEVELS:
            raise ValueError(f"unknown confidence_level: {self.confidence_level}")
        data_completeness = str(self.data_completeness or "partial").strip().lower()
        if data_completeness not in _DATA_COMPLETENESS:
            raise ValueError(f"unknown data_completeness: {self.data_completeness}")
        calibration_quality = str(self.calibration_quality or "insufficient_sample").strip().lower()
        if calibration_quality not in {"strong", "acceptable", "weak", "insufficient_sample"}:
            raise ValueError(f"unknown calibration_quality: {self.calibration_quality}")
        precision_cap = str(self.precision_cap or disclosure_level).strip().lower()
        if precision_cap not in _DISCLOSURE_LEVELS:
            raise ValueError(f"unknown precision_cap: {self.precision_cap}")
        object.__setattr__(self, "result_category", normalized_category)
        object.__setattr__(self, "disclosure_level", disclosure_level)
        object.__setattr__(self, "confidence_level", confidence_level)
        object.__setattr__(self, "data_completeness", data_completeness)
        object.__setattr__(self, "calibration_quality", calibration_quality)
        object.__setattr__(self, "point_value_allowed", bool(self.point_value_allowed))
        object.__setattr__(self, "range_required", bool(self.range_required))
        object.__setattr__(self, "diagnostic_only", bool(self.diagnostic_only))
        object.__setattr__(self, "precision_cap", precision_cap)
        object.__setattr__(
            self,
            "reasons",
            [str(item).strip() for item in list(self.reasons or []) if str(item).strip()],
        )

    @classmethod
    def from_any(cls, value: "DisclosureDecision | dict[str, Any] | None") -> "DisclosureDecision | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        payload = dict(value)
        disclosure_level = str(
            payload.get("disclosure_level")
            or {
                "full": "point_and_range",
                "ranges_only": "range_only",
                "range_only": "range_only",
                "diagnostic_only": "diagnostic_only",
                "unavailable": "unavailable",
            }.get(str(payload.get("decision") or "").strip().lower(), "diagnostic_only")
        ).strip().lower()
        return cls(
            result_category=str(
                payload.get("result_category") or payload.get("resolved_result_category") or ""
            ).strip().lower(),
            disclosure_level=disclosure_level,
            confidence_level=str(payload.get("confidence_level") or "low").strip().lower(),
            data_completeness=str(payload.get("data_completeness") or "partial").strip().lower(),
            calibration_quality=str(payload.get("calibration_quality") or "insufficient_sample").strip().lower(),
            point_value_allowed=bool(
                payload.get(
                    "point_value_allowed",
                    payload.get("allow_probability_point", payload.get("allow_return_point", False)),
                )
            ),
            range_required=bool(
                payload.get(
                    "range_required",
                    disclosure_level in {"point_and_range", "range_only"}
                    or payload.get("allow_probability_range", payload.get("allow_return_range", False)),
                )
            ),
            diagnostic_only=bool(payload.get("diagnostic_only", disclosure_level == "diagnostic_only")),
            precision_cap=str(payload.get("precision_cap") or disclosure_level or "diagnostic_only").strip().lower(),
            reasons=[
                str(item).strip()
                for item in list(payload.get("reasons", payload.get("reason_codes")) or [])
                if str(item).strip()
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    bundle_schema_version: str = "v1.3"
    execution_policy_version: str = "v1.3"
    disclosure_policy_version: str = "v1.3"
    mapping_signature: str = ""
    history_revision: str = ""
    distribution_revision: str = ""
    solver_revision: str = ""
    code_revision: str = ""
    calibration_revision: str = ""
    request_id: str = ""
    account_profile_id: str = ""
    as_of: str = ""
    requested_result_category: str = ""
    resolved_result_category: str | None = None
    run_outcome_status: RunOutcomeStatus = RunOutcomeStatus.DEGRADED
    execution_policy: str = ""
    disclosure_policy: str = ""
    simulation_mode: str | None = None
    input_refs: dict[str, str] = field(default_factory=dict)
    evidence_refs: dict[str, str] = field(default_factory=dict)
    coverage_summary: CoverageSummary | dict[str, Any] | None = None
    calibration_summary: dict[str, Any] | None = None
    formal_path_status: FormalPathStatus | str | None = None
    failed_stage: str | None = None
    blocking_predicates: list[str] = field(default_factory=list)
    degradation_reasons: list[str] = field(default_factory=list)
    next_recoverable_actions: list[str] = field(default_factory=list)
    diagnostics_trustworthy: bool = False
    disclosure_decision: DisclosureDecision | dict[str, Any] | None = None
    secondary_companion_artifacts: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bundle_schema_version = str(self.bundle_schema_version or "").strip() or "v1.3"
        self.execution_policy_version = str(self.execution_policy_version or "").strip() or "v1.3"
        self.disclosure_policy_version = str(self.disclosure_policy_version or "").strip() or "v1.3"
        self.mapping_signature = str(self.mapping_signature or "").strip()
        self.history_revision = str(self.history_revision or "").strip()
        self.distribution_revision = str(self.distribution_revision or "").strip()
        self.solver_revision = str(self.solver_revision or "").strip()
        self.code_revision = str(self.code_revision or "").strip()
        self.calibration_revision = str(self.calibration_revision or "").strip()
        self.request_id = str(self.request_id or "").strip()
        self.account_profile_id = str(self.account_profile_id or "").strip()
        self.as_of = str(self.as_of or "").strip()
        self.requested_result_category = str(self.requested_result_category or "").strip().lower()
        if self.requested_result_category and self.requested_result_category not in _RESULT_CATEGORIES:
            raise ValueError(f"unknown requested_result_category: {self.requested_result_category}")
        self.resolved_result_category = (
            None if self.resolved_result_category in (None, "") else str(self.resolved_result_category).strip().lower()
        )
        if self.resolved_result_category and self.resolved_result_category not in _RESULT_CATEGORIES:
            raise ValueError(f"unknown resolved_result_category: {self.resolved_result_category}")
        self.run_outcome_status = coerce_run_outcome_status(self.run_outcome_status)
        self.execution_policy = str(self.execution_policy or "").strip()
        self.disclosure_policy = str(self.disclosure_policy or "").strip()
        self.simulation_mode = None if self.simulation_mode in (None, "") else str(self.simulation_mode).strip().lower()
        self.input_refs = {str(key): str(value) for key, value in dict(self.input_refs).items() if str(key).strip()}
        self.evidence_refs = {
            str(key): str(value) for key, value in dict(self.evidence_refs).items() if str(key).strip()
        }
        self.coverage_summary = CoverageSummary.from_any(self.coverage_summary)
        self.calibration_summary = None if self.calibration_summary is None else dict(self.calibration_summary)
        self.formal_path_status = coerce_formal_path_status(self.formal_path_status or self.run_outcome_status.value)
        if self.formal_path_status != self.run_outcome_status:
            raise ValueError(
                "formal_path_status must match run_outcome_status: "
                f"{self.formal_path_status.value} != {self.run_outcome_status.value}"
            )
        self.failed_stage = None if self.failed_stage in (None, "") else str(self.failed_stage).strip().lower()
        self.blocking_predicates = [str(item) for item in self.blocking_predicates if str(item).strip()]
        self.degradation_reasons = [str(item) for item in self.degradation_reasons if str(item).strip()]
        self.next_recoverable_actions = [str(item) for item in self.next_recoverable_actions if str(item).strip()]
        self.disclosure_decision = DisclosureDecision.from_any(self.disclosure_decision)
        self.secondary_companion_artifacts = list(self.secondary_companion_artifacts)
        if (
            self.execution_policy in _FORMAL_EXECUTION_POLICIES
            and self.resolved_result_category == "exploratory_result"
        ):
            raise ValueError("formal execution_policy cannot resolve exploratory_result")

    @classmethod
    def from_any(cls, value: "EvidenceBundle | dict[str, Any] | None") -> "EvidenceBundle | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            bundle_schema_version=payload.get("bundle_schema_version", payload.get("contract_version", "v1.3")),
            execution_policy_version=payload.get("execution_policy_version", "v1.3"),
            disclosure_policy_version=payload.get("disclosure_policy_version", "v1.3"),
            mapping_signature=payload.get("mapping_signature", payload.get("bundle_signature") or ""),
            history_revision=payload.get("history_revision") or "",
            distribution_revision=payload.get("distribution_revision") or "",
            solver_revision=payload.get("solver_revision") or "",
            code_revision=payload.get("code_revision") or "",
            calibration_revision=payload.get("calibration_revision") or "",
            request_id=payload.get("request_id") or "",
            account_profile_id=payload.get("account_profile_id") or "",
            as_of=payload.get("as_of") or "",
            requested_result_category=payload.get("requested_result_category") or "",
            resolved_result_category=payload.get("resolved_result_category") or "",
            run_outcome_status=payload.get("run_outcome_status", RunOutcomeStatus.DEGRADED),
            execution_policy=payload.get("execution_policy") or "",
            disclosure_policy=payload.get("disclosure_policy") or "",
            simulation_mode=payload.get("simulation_mode"),
            input_refs=dict(payload.get("input_refs") or {}),
            evidence_refs=dict(payload.get("evidence_refs") or {}),
            coverage_summary=payload.get("coverage_summary"),
            calibration_summary=payload.get("calibration_summary"),
            formal_path_status=payload.get("formal_path_status"),
            failed_stage=payload.get("failed_stage"),
            blocking_predicates=list(payload.get("blocking_predicates") or []),
            degradation_reasons=list(payload.get("degradation_reasons") or []),
            next_recoverable_actions=list(payload.get("next_recoverable_actions") or []),
            diagnostics_trustworthy=bool(payload.get("diagnostics_trustworthy")),
            disclosure_decision=payload.get("disclosure_decision"),
            secondary_companion_artifacts=list(payload.get("secondary_companion_artifacts") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "bundle_schema_version": self.bundle_schema_version,
                "execution_policy_version": self.execution_policy_version,
                "disclosure_policy_version": self.disclosure_policy_version,
                "mapping_signature": self.mapping_signature,
                "history_revision": self.history_revision,
                "distribution_revision": self.distribution_revision,
                "solver_revision": self.solver_revision,
                "code_revision": self.code_revision,
                "calibration_revision": self.calibration_revision,
                "request_id": self.request_id,
                "account_profile_id": self.account_profile_id,
                "as_of": self.as_of,
                "requested_result_category": self.requested_result_category,
                "resolved_result_category": self.resolved_result_category,
                "run_outcome_status": self.run_outcome_status,
                "execution_policy": self.execution_policy,
                "disclosure_policy": self.disclosure_policy,
                "simulation_mode": self.simulation_mode,
                "input_refs": self.input_refs,
                "evidence_refs": self.evidence_refs,
                "coverage_summary": self.coverage_summary,
                "calibration_summary": self.calibration_summary,
                "formal_path_status": self.formal_path_status,
                "failed_stage": self.failed_stage,
                "blocking_predicates": self.blocking_predicates,
                "degradation_reasons": self.degradation_reasons,
                "next_recoverable_actions": self.next_recoverable_actions,
                "diagnostics_trustworthy": self.diagnostics_trustworthy,
                "disclosure_decision": self.disclosure_decision,
                "secondary_companion_artifacts": self.secondary_companion_artifacts,
            }
        )


@dataclass(frozen=True)
class AuditWindow:
    start_date: str | None = None
    end_date: str | None = None
    trading_days: int | None = None
    observed_days: int | None = None
    inferred_days: int | None = None

    @classmethod
    def from_any(cls, value: "AuditWindow | dict[str, Any] | None") -> "AuditWindow | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            start_date=None
            if payload.get("start_date", payload.get("observed_start")) is None
            else str(payload.get("start_date", payload.get("observed_start"))),
            end_date=None
            if payload.get("end_date", payload.get("observed_end")) is None
            else str(payload.get("end_date", payload.get("observed_end"))),
            trading_days=None
            if payload.get("trading_days") is None
            else int(payload.get("trading_days")),
            observed_days=None
            if payload.get("observed_days", payload.get("observed_history_days")) is None
            else int(payload.get("observed_days", payload.get("observed_history_days"))),
            inferred_days=None
            if payload.get("inferred_days", payload.get("inferred_history_days")) is None
            else int(payload.get("inferred_days", payload.get("inferred_history_days"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def has_required_window(self) -> bool:
        return bool(self.start_date and self.end_date and self.trading_days)


@dataclass(frozen=True)
class AuditRecord:
    field: str
    source_ref: str
    as_of: str
    data_status: DataStatus
    label: str | None = None
    source_type: str | None = None
    source_label: str | None = None
    detail: str | None = None
    fetched_at: str | None = None
    freshness_state: str | None = None
    audit_window: AuditWindow | None = None

    @classmethod
    def from_any(cls, value: "AuditRecord | dict[str, Any]") -> "AuditRecord":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            field=str(payload.get("field") or "unknown"),
            label=None if payload.get("label") is None else str(payload.get("label")),
            source_ref=str(payload.get("source_ref") or ""),
            as_of=str(payload.get("as_of") or ""),
            data_status=coerce_data_status(payload.get("data_status") or DataStatus.INFERRED),
            source_type=None if payload.get("source_type") is None else str(payload.get("source_type")),
            source_label=None if payload.get("source_label") is None else str(payload.get("source_label")),
            detail=None if payload.get("detail") is None else str(payload.get("detail")),
            fetched_at=None if payload.get("fetched_at") is None else str(payload.get("fetched_at")),
            freshness_state=None
            if payload.get("freshness_state") is None
            else str(payload.get("freshness_state")),
            audit_window=AuditWindow.from_any(payload.get("audit_window")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "field": self.field,
            "label": self.label,
            "source_ref": self.source_ref,
            "as_of": self.as_of,
            "data_status": self.data_status.value,
            "source_type": self.source_type,
            "source_label": self.source_label,
            "detail": self.detail,
            "fetched_at": self.fetched_at,
            "freshness_state": self.freshness_state,
            "audit_window": None if self.audit_window is None else self.audit_window.to_dict(),
        }
        return payload


@dataclass(frozen=True)
class FormalPathVisibility:
    status: FormalPathStatus
    execution_eligible: bool
    execution_eligibility_reason: str
    degraded_scope: list[str]
    fallback_used: bool
    fallback_scope: list[str]
    reasons: list[str]
    missing_audit_fields: list[str]

    @classmethod
    def from_any(cls, value: "FormalPathVisibility | dict[str, Any]") -> "FormalPathVisibility":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            status=coerce_formal_path_status(payload.get("status") or FormalPathStatus.DEGRADED),
            execution_eligible=bool(payload.get("execution_eligible")),
            execution_eligibility_reason=str(payload.get("execution_eligibility_reason") or "unknown"),
            degraded_scope=[str(item) for item in list(payload.get("degraded_scope") or []) if str(item).strip()],
            fallback_used=bool(payload.get("fallback_used")),
            fallback_scope=[str(item) for item in list(payload.get("fallback_scope") or []) if str(item).strip()],
            reasons=[str(item) for item in list(payload.get("reasons") or []) if str(item).strip()],
            missing_audit_fields=[
                str(item) for item in list(payload.get("missing_audit_fields") or []) if str(item).strip()
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


__all__ = [
    "AuditRecord",
    "AuditWindow",
    "CoverageSummary",
    "DataStatus",
    "DisclosureDecision",
    "EvidenceBundle",
    "FormalPathStatus",
    "FormalPathVisibility",
    "RunOutcomeStatus",
    "coerce_data_status",
    "coerce_formal_path_status",
    "coerce_run_outcome_status",
]
