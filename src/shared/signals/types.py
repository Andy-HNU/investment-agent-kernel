from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Iterable


@dataclass
class PolicySignal:
    signal_id: str
    kind: str
    title: str
    impact_buckets: list[str] = field(default_factory=list)
    impact_direction: dict[str, str] = field(default_factory=dict)
    as_of: str | None = None
    confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsSignal:
    signal_id: str
    source: str
    title: str
    tickers: list[str] = field(default_factory=list)
    as_of: str | None = None
    sentiment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignalPack:
    policies: list[PolicySignal] = field(default_factory=list)
    news: list[NewsSignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policies": [p.to_dict() for p in self.policies],
            "news": [n.to_dict() for n in self.news],
        }


__all__ = ["PolicySignal", "NewsSignal", "SignalPack"]

