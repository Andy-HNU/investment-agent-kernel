from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.parse import urlparse


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


@contextmanager
def serve_json_routes(routes: dict[str, tuple[int, dict[str, Any]]]) -> Iterator[str]:
    patched_modules: list[tuple[object, Any]] = []
    base_url = "http://snapshot.test"

    def _fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
        url = getattr(request, "full_url", str(request))
        path = urlparse(url).path
        status, payload = routes.get(path, (404, {"error": "not_found", "path": path}))
        if status >= 400:
            raise HTTPError(url, status, "mocked http error", hdrs=None, fp=None)
        return _FakeResponse(payload)

    for module_name in (
        "snapshot_ingestion.adapters.http_json_adapter",
        "frontdesk.adapter",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        original = getattr(module, "urlopen", None)
        setattr(module, "urlopen", _fake_urlopen)
        patched_modules.append((module, original))

    try:
        yield base_url
    finally:
        for module, original in reversed(patched_modules):
            setattr(module, "urlopen", original)
