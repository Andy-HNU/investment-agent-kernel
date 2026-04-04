from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DataStatus(str, Enum):
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


@dataclass(frozen=True)
class AuditWindow:
    observed_start: str | None = None
    observed_end: str | None = None
    observed_history_days: int = 0
    inferred_history_days: int = 0

    @classmethod
    def from_any(cls, value: "AuditWindow | dict[str, Any] | None") -> "AuditWindow | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        payload = dict(value)
        return cls(
            observed_start=None if payload.get("observed_start") is None else str(payload.get("observed_start")),
            observed_end=None if payload.get("observed_end") is None else str(payload.get("observed_end")),
            observed_history_days=int(payload.get("observed_history_days") or 0),
            inferred_history_days=int(payload.get("inferred_history_days") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditRecord:
    field: str
    source_ref: str
    as_of: str
    data_status: DataStatus
    label: str | None = None
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
            data_status=coerce_data_status(payload.get("data_status") or DataStatus.DEGRADED),
            audit_window=AuditWindow.from_any(payload.get("audit_window")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "field": self.field,
            "label": self.label,
            "source_ref": self.source_ref,
            "as_of": self.as_of,
            "data_status": self.data_status.value,
            "audit_window": None if self.audit_window is None else self.audit_window.to_dict(),
        }
        return payload


__all__ = [
    "AuditRecord",
    "AuditWindow",
    "DataStatus",
    "coerce_data_status",
]
