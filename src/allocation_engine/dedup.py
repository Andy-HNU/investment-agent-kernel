from __future__ import annotations

from allocation_engine.templates import family_priority, template_family_name
from allocation_engine.types import CandidateDiagnostics
from goal_solver.types import StrategicAllocation


def deduplicate_candidate_pairs(
    pairs: list[tuple[StrategicAllocation, CandidateDiagnostics]],
    dedup_l1_threshold: float,
) -> list[tuple[StrategicAllocation, CandidateDiagnostics]]:
    unique: list[tuple[StrategicAllocation, CandidateDiagnostics]] = []
    for allocation, diagnostics in pairs:
        is_duplicate = False
        family = template_family_name(diagnostics.template_name)
        for existing, _existing_diag in unique:
            existing_family = template_family_name(_existing_diag.template_name)
            if family != existing_family:
                continue
            keys = set(allocation.weights) | set(existing.weights)
            distance = sum(
                abs(allocation.weights.get(key, 0.0) - existing.weights.get(key, 0.0))
                for key in keys
            )
            if distance < dedup_l1_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            unique.append((allocation, diagnostics))
    return unique


def stable_sort_candidate_pairs(
    pairs: list[tuple[StrategicAllocation, CandidateDiagnostics]],
) -> list[tuple[StrategicAllocation, CandidateDiagnostics]]:
    return sorted(
        pairs,
        key=lambda pair: (
            family_priority(pair[1].template_name),
            pair[0].complexity_score,
            pair[0].name,
        ),
    )


def trim_candidate_pairs(
    pairs: list[tuple[StrategicAllocation, CandidateDiagnostics]],
    min_candidates: int,
    max_candidates: int,
) -> list[tuple[StrategicAllocation, CandidateDiagnostics]]:
    del min_candidates
    if len(pairs) <= max_candidates:
        return pairs

    selected: list[tuple[StrategicAllocation, CandidateDiagnostics]] = []
    selected_names: set[str] = set()
    seen_families: set[str] = set()

    for allocation, diagnostics in pairs:
        family = template_family_name(diagnostics.template_name)
        if family in seen_families:
            continue
        selected.append((allocation, diagnostics))
        selected_names.add(allocation.name)
        seen_families.add(family)
        if len(selected) >= max_candidates:
            return selected

    for allocation, diagnostics in pairs:
        if allocation.name in selected_names:
            continue
        selected.append((allocation, diagnostics))
        if len(selected) >= max_candidates:
            break
    return selected
