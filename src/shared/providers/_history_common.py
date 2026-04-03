from __future__ import annotations

from dataclasses import asdict
from importlib import import_module
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, HistoryBar, VersionPin


def import_optional_module(module_name: str, *, missing_message: str) -> Any:
    try:
        module = import_module(module_name)
    except Exception as exc:
        raise RuntimeError(missing_message) from exc
    if module is None:
        raise RuntimeError(missing_message)
    return module


def parse_source_ref(source_ref: str | None) -> tuple[str, dict[str, str]]:
    if not source_ref:
        return "", {}
    parsed = urlparse(source_ref)
    endpoint = f"{parsed.netloc}{parsed.path}".strip("/")
    params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=False).items() if values}
    return endpoint, params


def _stringify_date(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw)
    if " " in text:
        text = text.split(" ", 1)[0]
    return text


def normalize_history_rows(
    rows: Iterable[dict[str, Any]],
    *,
    aliases: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict(raw_row)

        def _pick(name: str) -> Any:
            for candidate in aliases[name]:
                if candidate in row and row[candidate] not in (None, ""):
                    return row[candidate]
            return None

        normalized.append(
            asdict(
                HistoryBar(
                    date=_stringify_date(_pick("date")),
                    open=float(_pick("open")),
                    high=float(_pick("high")),
                    low=float(_pick("low")),
                    close=float(_pick("close")),
                    volume=float(_pick("volume") or 0.0),
                )
            )
        )
    return normalized


def read_cached_rows(
    spec: DatasetSpec,
    *,
    cache: DatasetCache,
    return_used_pin: bool,
) -> Any:
    latest = cache.latest_cached_pin(spec)
    if latest is None:
        return None
    cached = cache.read(spec, latest)
    if cached is None:
        return None
    return (cached, latest) if return_used_pin else cached


def cache_rows(
    spec: DatasetSpec,
    *,
    pin: VersionPin,
    cache: DatasetCache,
    rows: list[dict[str, Any]],
    allow_fallback: bool,
    return_used_pin: bool,
) -> Any:
    if rows:
        cache.write(spec, pin, rows)
        return (rows, pin) if return_used_pin else rows
    if allow_fallback:
        cached = read_cached_rows(spec, cache=cache, return_used_pin=return_used_pin)
        if cached is not None:
            return cached
    raise RuntimeError(f"{spec.provider} provider returned no rows")


__all__ = [
    "cache_rows",
    "import_optional_module",
    "normalize_history_rows",
    "parse_source_ref",
    "read_cached_rows",
]
