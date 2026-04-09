from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    asset_class: str
    region: str
    style: str


FIXED_FACTOR_DICTIONARY: dict[str, FactorDefinition] = {
    "CN_EQ_BROAD": FactorDefinition("CN_EQ_BROAD", "equity", "CN", "broad"),
    "CN_EQ_GROWTH": FactorDefinition("CN_EQ_GROWTH", "equity", "CN", "growth"),
    "CN_EQ_VALUE": FactorDefinition("CN_EQ_VALUE", "equity", "CN", "value"),
    "US_EQ_BROAD": FactorDefinition("US_EQ_BROAD", "equity", "US", "broad"),
    "US_EQ_GROWTH": FactorDefinition("US_EQ_GROWTH", "equity", "US", "growth"),
    "HK_EQ_BROAD": FactorDefinition("HK_EQ_BROAD", "equity", "HK", "broad"),
    "CN_RATE_DURATION": FactorDefinition("CN_RATE_DURATION", "rates", "CN", "duration"),
    "CN_CREDIT_SPREAD": FactorDefinition("CN_CREDIT_SPREAD", "credit", "CN", "spread"),
    "GOLD_GLOBAL": FactorDefinition("GOLD_GLOBAL", "commodity", "GLOBAL", "gold"),
    "USD_CNH": FactorDefinition("USD_CNH", "fx", "GLOBAL", "usd_cnh"),
}


@dataclass(frozen=True)
class FactorLibrarySnapshot:
    snapshot_id: str
    as_of: str
    factors: tuple[FactorDefinition, ...]

    @property
    def factor_ids(self) -> tuple[str, ...]:
        return tuple(factor.factor_id for factor in self.factors)

    @property
    def factor_definition_by_id(self) -> dict[str, FactorDefinition]:
        return {factor.factor_id: factor for factor in self.factors}


def _coerce_factor_definition(value: Any) -> FactorDefinition:
    payload = dict(value)
    return FactorDefinition(
        factor_id=str(payload["factor_id"]),
        asset_class=str(payload["asset_class"]),
        region=str(payload["region"]),
        style=str(payload["style"]),
    )


def load_factor_library_snapshot(snapshot_path: str | Path) -> FactorLibrarySnapshot:
    path = Path(snapshot_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    factors = tuple(_coerce_factor_definition(item) for item in list(payload.get("factors") or []))
    snapshot = FactorLibrarySnapshot(
        snapshot_id=str(payload.get("snapshot_id", "")),
        as_of=str(payload.get("as_of", "")),
        factors=factors,
    )

    expected_ids = tuple(FIXED_FACTOR_DICTIONARY.keys())
    if snapshot.factor_ids != expected_ids:
        raise ValueError("factor library snapshot does not match fixed factor dictionary")

    return snapshot
