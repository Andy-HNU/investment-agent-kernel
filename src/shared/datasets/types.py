from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable


@dataclass(frozen=True)
class VersionPin:
    version_id: str
    source_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetSpec:
    kind: str
    dataset_id: str
    provider: str
    symbol: str | None = None

    def key(self) -> str:
        parts = [self.kind, self.dataset_id, self.provider]
        if self.symbol:
            parts.append(self.symbol)
        return ":".join(parts)


@dataclass
class HistoryBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_mapping(cls, m: dict[str, Any]) -> "HistoryBar":
        return cls(
            date=str(m.get("date")),
            open=float(m.get("open")),
            high=float(m.get("high")),
            low=float(m.get("low")),
            close=float(m.get("close")),
            volume=float(m.get("volume")),
        )

    @classmethod
    def coerce_many(cls, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [asdict(cls.from_mapping(r)) for r in rows]


__all__ = [
    "DatasetSpec",
    "VersionPin",
    "HistoryBar",
]

