from __future__ import annotations

from typing import Any, Callable, Dict


# Signature used by external snapshot providers
ExternalSnapshotFetcher = Callable[
    [dict[str, Any]],  # raw config mapping
    # kwargs: workflow_type, account_profile_id, as_of
    # returns FetchedSnapshotPayload | None
    Any,
]


class ProviderRegistry:
    def __init__(self) -> None:
        self._external_snapshot: Dict[str, ExternalSnapshotFetcher] = {}

    # External snapshot providers -----------------------------------------
    def register_external_snapshot(self, name: str, fetcher: ExternalSnapshotFetcher) -> None:
        key = str(name).strip().lower()
        if not key:
            raise ValueError("provider name is required")
        self._external_snapshot[key] = fetcher

    def get_external_snapshot(self, name: str) -> ExternalSnapshotFetcher | None:
        return self._external_snapshot.get(str(name).strip().lower())

    def list_external_snapshot(self) -> list[str]:
        return sorted(self._external_snapshot.keys())


# Global singleton used by frontdesk and tests
registry = ProviderRegistry()


__all__ = ["registry", "ProviderRegistry"]

