from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shared.datasets.types import DatasetSpec, VersionPin


class DatasetCache:
    def __init__(self, *, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    # Layout: <base>/<kind>/<dataset_id>/<provider>/<symbol>/<version_id>/
    def _dir_for(self, spec: DatasetSpec, pin: VersionPin) -> Path:
        parts = [spec.kind, spec.dataset_id, spec.provider, spec.symbol or "_"]
        return self.base_dir.joinpath(*parts).joinpath(pin.version_id)

    def _manifest_path(self, spec: DatasetSpec) -> Path:
        parts = [spec.kind, spec.dataset_id, spec.provider, spec.symbol or "_"]
        return self.base_dir.joinpath(*parts).joinpath("manifest.json")

    def write(self, spec: DatasetSpec, pin: VersionPin, rows: list[dict[str, Any]]) -> None:
        target_dir = self._dir_for(spec, pin)
        target_dir.mkdir(parents=True, exist_ok=True)
        data_path = target_dir / "data.json"
        data_path.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        manifest_path = self._manifest_path(spec)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "spec": {
                        "kind": spec.kind,
                        "dataset_id": spec.dataset_id,
                        "provider": spec.provider,
                        "symbol": spec.symbol,
                    },
                    "version_id": pin.version_id,
                    "source_ref": pin.source_ref,
                    "provider": spec.provider,
                    "current_dir": str(target_dir),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def read(self, spec: DatasetSpec, pin: VersionPin) -> list[dict[str, Any]] | None:
        target_dir = self._dir_for(spec, pin)
        data_path = target_dir / "data.json"
        if not data_path.exists():
            return None
        return json.loads(data_path.read_text(encoding="utf-8"))

    def read_manifest(self, spec: DatasetSpec) -> dict[str, Any] | None:
        manifest_path = self._manifest_path(spec)
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def latest_cached_pin(self, spec: DatasetSpec) -> VersionPin | None:
        manifest = self.read_manifest(spec)
        if not manifest:
            return None
        return VersionPin(version_id=str(manifest.get("version_id")), source_ref=str(manifest.get("source_ref")))


__all__ = ["DatasetCache"]

