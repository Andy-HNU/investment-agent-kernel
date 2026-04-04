from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DataStatus(str, Enum):
    OBSERVED = "observed"
    COMPUTED_FROM_OBSERVED = "computed_from_observed"
    INFERRED = "inferred"
    PRIOR_DEFAULT = "prior_default"
    SYNTHETIC_DEMO = "synthetic_demo"
    MANUAL_ANNOTATION = "manual_annotation"


class FormalPathStatus(str, Enum):
    FORMAL = "formal"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FALLBACK_USED_BUT_NOT_FORMAL = "fallback_used_but_not_formal"


def coerce_data_status(value: DataStatus | str) -> DataStatus:
    if isinstance(value, DataStatus):
        return value
    try:
        return DataStatus(str(value).strip().lower())
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown data_status: {value}") from exc


def coerce_formal_path_status(value: FormalPathStatus | str) -> FormalPathStatus:
    if isinstance(value, FormalPathStatus):
        return value
    try:
        return FormalPathStatus(str(value).strip().lower())
    except ValueError as exc:  # pragma: no cover - exercised via contract test
        raise ValueError(f"unknown formal_path_status: {value}") from exc


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
    "DataStatus",
    "FormalPathStatus",
    "FormalPathVisibility",
    "coerce_data_status",
    "coerce_formal_path_status",
]
