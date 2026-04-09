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


@dataclass(frozen=True)
class FactorReturnObservation:
    date: str
    factor_returns: dict[str, float]


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


def _coerce_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return dict(value)


def _coerce_factor_definition(value: Any) -> FactorDefinition:
    payload = _coerce_mapping(value, context="factor definition")
    required = {"factor_id", "asset_class", "region", "style"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"factor definition missing fields: {sorted(missing)}")
    factor = FactorDefinition(
        factor_id=str(payload["factor_id"]),
        asset_class=str(payload["asset_class"]),
        region=str(payload["region"]),
        style=str(payload["style"]),
    )
    return factor


def _coerce_factor_return_observation(value: Any, factor_ids: tuple[str, ...]) -> FactorReturnObservation:
    payload = _coerce_mapping(value, context="factor return observation")
    if "date" not in payload:
        raise ValueError("factor return observation missing date")
    missing_factors = [factor_id for factor_id in factor_ids if factor_id not in payload]
    allowed_fields = {"date"} | set(factor_ids)
    extra_fields = [key for key in payload if key not in allowed_fields]
    if missing_factors:
        raise ValueError(f"factor return observation missing factors: {missing_factors}")
    if extra_fields:
        raise ValueError(f"factor return observation has unexpected fields: {extra_fields}")
    return FactorReturnObservation(
        date=str(payload["date"]),
        factor_returns={factor_id: float(payload[factor_id]) for factor_id in factor_ids},
    )


@dataclass(frozen=True)
class FactorLibrarySnapshot:
    snapshot_id: str
    as_of: str
    factors: tuple[FactorDefinition, ...]
    factor_return_history: tuple[FactorReturnObservation, ...]

    @property
    def factor_ids(self) -> tuple[str, ...]:
        return tuple(factor.factor_id for factor in self.factors)

    @property
    def factor_definition_by_id(self) -> dict[str, FactorDefinition]:
        return {factor.factor_id: factor for factor in self.factors}

    def factor_return_series_by_factor(self) -> dict[str, tuple[float, ...]]:
        return {
            factor_id: tuple(row.factor_returns[factor_id] for row in self.factor_return_history)
            for factor_id in self.factor_ids
        }


def load_factor_library_snapshot(snapshot_path: str | Path) -> FactorLibrarySnapshot:
    path = Path(snapshot_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("factor library snapshot must be a JSON object")

    factors_payload = payload.get("factors")
    history_payload = payload.get("factor_return_history")
    if not isinstance(factors_payload, list):
        raise ValueError("factor library snapshot requires factor list")
    if not isinstance(history_payload, list):
        raise ValueError("factor library snapshot requires factor_return_history list")

    factors = tuple(_coerce_factor_definition(item) for item in factors_payload)
    expected_ids = tuple(FIXED_FACTOR_DICTIONARY.keys())
    if tuple(factor.factor_id for factor in factors) != expected_ids:
        raise ValueError("factor library snapshot does not match fixed factor dictionary")

    factor_ids = tuple(factor.factor_id for factor in factors)
    factor_return_history = tuple(_coerce_factor_return_observation(item, factor_ids) for item in history_payload)
    if not factor_return_history:
        raise ValueError("factor library snapshot requires factor return history")

    snapshot = FactorLibrarySnapshot(
        snapshot_id=str(payload.get("snapshot_id", "")),
        as_of=str(payload.get("as_of", "")),
        factors=factors,
        factor_return_history=factor_return_history,
    )
    return snapshot
