from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from frontdesk.external_data import fetch_external_snapshot
from snapshot_ingestion.adapters import FetchedSnapshotPayload


def load_json_source(source: str | Path) -> dict[str, Any]:
    source_path = Path(str(source))
    if source_path.exists():
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(str(source))
    if not isinstance(payload, dict):
        raise ValueError("provider config must decode to an object")
    return payload


def fetch_provider_snapshot(
    source: str | Path,
    *,
    workflow_type: str,
    account_profile_id: str,
    as_of: str,
) -> FetchedSnapshotPayload | None:
    config = load_json_source(source)
    return fetch_external_snapshot(
        config,
        workflow_type=workflow_type,
        account_profile_id=account_profile_id,
        as_of=as_of,
    )


def payload_from_snapshot(fetched: FetchedSnapshotPayload | None) -> dict[str, Any]:
    if fetched is None:
        return {}
    payload = deepcopy(fetched.raw_overrides)
    if fetched.provenance_items:
        payload["input_provenance"] = {"externally_fetched": deepcopy(fetched.provenance_items)}
    return payload
