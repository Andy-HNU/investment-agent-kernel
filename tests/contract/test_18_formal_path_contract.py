from __future__ import annotations

import pytest

from shared.audit import AuditRecord, AuditWindow, DataStatus, coerce_data_status


@pytest.mark.contract
def test_coerce_data_status_accepts_known_values():
    assert coerce_data_status("formal") == DataStatus.FORMAL
    assert coerce_data_status(DataStatus.DEGRADED) == DataStatus.DEGRADED
    assert coerce_data_status("fallback_used_but_not_formal") == DataStatus.FALLBACK_USED_BUT_NOT_FORMAL


@pytest.mark.contract
def test_coerce_data_status_rejects_unknown_value():
    with pytest.raises(ValueError, match="unknown data_status"):
        coerce_data_status("fresh")


@pytest.mark.contract
def test_audit_window_serializes_to_dict():
    window = AuditWindow(
        observed_start="2016-01-01",
        observed_end="2026-01-01",
        observed_history_days=2520,
        inferred_history_days=120,
    )

    assert window.to_dict() == {
        "observed_start": "2016-01-01",
        "observed_end": "2026-01-01",
        "observed_history_days": 2520,
        "inferred_history_days": 120,
    }


@pytest.mark.contract
def test_audit_record_coerces_and_serializes_with_optional_window():
    record = AuditRecord.from_any(
        {
            "field": "market_raw",
            "label": "市场输入",
            "source_ref": "akshare:sh510300",
            "as_of": "2026-04-04",
            "data_status": "formal",
            "audit_window": {
                "observed_start": "2016-01-01",
                "observed_end": "2026-01-01",
                "observed_history_days": 2520,
                "inferred_history_days": 0,
            },
        }
    )

    assert record.data_status == DataStatus.FORMAL
    assert record.audit_window is not None
    assert record.to_dict() == {
        "field": "market_raw",
        "label": "市场输入",
        "source_ref": "akshare:sh510300",
        "as_of": "2026-04-04",
        "data_status": "formal",
        "audit_window": {
            "observed_start": "2016-01-01",
            "observed_end": "2026-01-01",
            "observed_history_days": 2520,
            "inferred_history_days": 0,
        },
    }


@pytest.mark.contract
def test_audit_record_allows_missing_optional_window():
    record = AuditRecord.from_any(
        {
            "field": "market_raw",
            "source_ref": "akshare:sh510300",
            "as_of": "2026-04-04",
            "data_status": "degraded",
        }
    )

    assert record.audit_window is None
    assert record.to_dict()["data_status"] == "degraded"
