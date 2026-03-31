from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CompletenessLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"


@dataclass
class QualityFlag:
    code: str
    severity: str
    domain: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotBundle:
    bundle_id: str
    account_profile_id: str
    created_at: Any
    market: dict[str, Any]
    account: dict[str, Any]
    goal: dict[str, Any]
    constraint: dict[str, Any]
    behavior: dict[str, Any] | None
    bundle_quality: CompletenessLevel
    missing_domains: list[str] = field(default_factory=list)
    quality_summary: list[QualityFlag] = field(default_factory=list)
    schema_version: str = "v1.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bundle_quality"] = self.bundle_quality.value
        data["quality_summary"] = [flag.to_dict() for flag in self.quality_summary]
        return data
