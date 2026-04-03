from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt


@dataclass(frozen=True)
class CycleCoverageSummary:
    coverage_ok: bool
    reasons: list[str] = field(default_factory=list)
    observed_days: int = 0


def _min_observed_span(frequency: str) -> int:
    normalized = str(frequency or "daily").strip().lower()
    if normalized == "monthly":
        return 36
    if normalized == "weekly":
        return 104
    return 252


def _annualization_scale(frequency: str) -> float:
    normalized = str(frequency or "daily").strip().lower()
    if normalized == "monthly":
        return 12.0
    if normalized == "weekly":
        return 52.0
    return 252.0


def evaluate_cycle_coverage(*, dates: list[str], returns: list[float], frequency: str = "daily") -> CycleCoverageSummary:
    observed_days = min(len(dates), len(returns)) if dates else len(returns)
    series = [float(value) for value in returns[:observed_days]] if observed_days else []
    if not series:
        return CycleCoverageSummary(
            coverage_ok=False,
            reasons=["missing_observed_history", "missing_upcycle", "missing_downcycle", "missing_high_volatility"],
            observed_days=0,
        )

    cumulative = 1.0
    peak = 1.0
    saw_upcycle = False
    saw_downcycle = False

    mean_value = sum(series) / len(series)
    variance = sum((value - mean_value) ** 2 for value in series) / len(series) if series else 0.0
    annualized_vol = sqrt(max(variance, 0.0)) * sqrt(_annualization_scale(frequency))
    saw_high_volatility = annualized_vol >= 0.18

    for value in series:
        cumulative *= 1.0 + value
        peak = max(peak, cumulative)
        drawdown = (peak - cumulative) / peak if peak else 0.0
        if cumulative >= 1.20:
            saw_upcycle = True
        if drawdown >= 0.15:
            saw_downcycle = True

    reasons: list[str] = []
    if observed_days < _min_observed_span(frequency):
        reasons.append("insufficient_observed_span")
    if not saw_upcycle:
        reasons.append("missing_upcycle")
    if not saw_downcycle:
        reasons.append("missing_downcycle")
    if not saw_high_volatility:
        reasons.append("missing_high_volatility")

    return CycleCoverageSummary(
        coverage_ok=not reasons,
        reasons=reasons,
        observed_days=observed_days,
    )


__all__ = ["CycleCoverageSummary", "evaluate_cycle_coverage"]
