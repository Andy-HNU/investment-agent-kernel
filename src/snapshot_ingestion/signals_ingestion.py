from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.signals.types import SignalPack


def apply_signals(raw_inputs: dict[str, Any], pack: SignalPack | None) -> dict[str, Any]:
    if pack is None:
        return raw_inputs
    merged = deepcopy(raw_inputs)
    merged.setdefault("signals", {})
    payload = pack.to_dict()
    if payload.get("policies"):
        merged["signals"]["policies"] = list(payload["policies"])  # shallow copy
    if payload.get("news"):
        merged["signals"]["news"] = list(payload["news"])  # shallow copy
    return merged


__all__ = ["apply_signals"]

