from __future__ import annotations

import io
import json

import pytest

pytest.importorskip("frontdesk.adapter")


@pytest.mark.contract
def test_frontdesk_external_snapshot_adapter_loads_file_and_http(tmp_path, monkeypatch):
    from frontdesk.adapter import FrontdeskExternalSnapshotAdapter

    payload = {
        "snapshot": {
            "market_raw": {"source": "local-file-market"},
            "account_raw": {"weights": {"equity_cn": 0.4, "bond_cn": 0.4, "gold": 0.1, "satellite": 0.1}},
            "behavior_raw": {"override_count_90d": 2, "cooldown_active": True},
            "input_provenance": {
                "externally_fetched": [
                    {
                        "field": "market_raw",
                        "label": "市场输入",
                        "value": {"source": "local-file-market"},
                        "note": "served locally",
                    }
                ]
            },
        }
    }
    file_path = tmp_path / "snapshot.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    class _FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(url: str, timeout: float):  # pragma: no cover - exercised through adapter
        assert url == "http://example.invalid/snapshot.json"
        assert timeout == pytest.approx(2.5)
        return _FakeResponse(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr("frontdesk.adapter.urlopen", _fake_urlopen)

    file_snapshot = FrontdeskExternalSnapshotAdapter(file_path).load()
    http_snapshot = FrontdeskExternalSnapshotAdapter("http://example.invalid/snapshot.json", timeout_seconds=2.5).load()

    assert file_snapshot.source == str(file_path)
    assert file_snapshot.payload["market_raw"]["source"] == "local-file-market"
    assert http_snapshot.source == "http://example.invalid/snapshot.json"
    assert http_snapshot.payload["behavior_raw"]["cooldown_active"] is True
