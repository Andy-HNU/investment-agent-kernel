from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import urlopen


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json_text(source: str | Path, *, timeout_seconds: float) -> tuple[str, str]:
    source_text = str(source).strip()
    parsed = urlparse(source_text)
    if parsed.scheme in {"http", "https"}:
        with urlopen(source_text, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        return raw, source_text
    if parsed.scheme == "file":
        file_path = Path(unquote(parsed.path))
        return file_path.read_text(encoding="utf-8"), str(file_path)
    if source_text.startswith("{") or source_text.startswith("["):
        return source_text, "inline-json"
    file_path = Path(source_text)
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8"), str(file_path)
    except OSError:
        return source_text, "inline-json"
    return source_text, "inline-json"


def _unwrap_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("snapshot", "raw_inputs", "payload"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    return payload


@dataclass(frozen=True)
class FrontdeskExternalSnapshot:
    source: str
    source_kind: str
    fetched_at: str
    payload: dict[str, Any]


class FrontdeskExternalSnapshotAdapter:
    def __init__(self, source: str | Path, *, timeout_seconds: float = 5.0) -> None:
        self.source = str(source)
        self.timeout_seconds = float(timeout_seconds)

    def load(self) -> FrontdeskExternalSnapshot:
        raw_text, source_kind = _load_json_text(self.source, timeout_seconds=self.timeout_seconds)
        payload = json.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("external snapshot must decode to a JSON object")
        return FrontdeskExternalSnapshot(
            source=self.source,
            source_kind=source_kind,
            fetched_at=_now_iso(),
            payload=_unwrap_snapshot_payload(payload),
        )
