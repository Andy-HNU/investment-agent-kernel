from __future__ import annotations

import pytest

from shared.audit import (
    AuditRecord,
    AuditWindow,
    DataStatus,
    FormalPathStatus,
    FormalPathVisibility,
    coerce_data_status,
    coerce_formal_path_status,
)


@pytest.mark.contract
def test_coerce_data_status_accepts_known_values():
    assert coerce_data_status("observed") == DataStatus.OBSERVED
    assert coerce_data_status(DataStatus.INFERRED) == DataStatus.INFERRED
    assert coerce_data_status("prior_default") == DataStatus.PRIOR_DEFAULT


@pytest.mark.contract
def test_coerce_data_status_rejects_unknown_value():
    with pytest.raises(ValueError, match="unknown data_status"):
        coerce_data_status("fresh")


@pytest.mark.contract
def test_coerce_formal_path_status_accepts_known_values():
    assert coerce_formal_path_status("formal") == FormalPathStatus.FORMAL
    assert coerce_formal_path_status(FormalPathStatus.DEGRADED) == FormalPathStatus.DEGRADED


@pytest.mark.contract
def test_audit_window_serializes_to_dict():
    window = AuditWindow(
        start_date="2016-01-01",
        end_date="2026-01-01",
        trading_days=2520,
        observed_days=2520,
        inferred_days=120,
    )

    assert window.to_dict() == {
        "start_date": "2016-01-01",
        "end_date": "2026-01-01",
        "trading_days": 2520,
        "observed_days": 2520,
        "inferred_days": 120,
    }
    assert window.has_required_window() is True


@pytest.mark.contract
def test_audit_record_coerces_and_serializes_with_optional_window():
    record = AuditRecord.from_any(
        {
            "field": "market_raw",
            "label": "市场输入",
            "source_ref": "akshare:sh510300",
            "as_of": "2026-04-04",
            "data_status": "observed",
            "source_type": "externally_fetched",
            "source_label": "外部抓取",
            "fetched_at": "2026-04-04T00:00:00Z",
            "freshness_state": "fresh",
            "audit_window": {
                "start_date": "2016-01-01",
                "end_date": "2026-01-01",
                "trading_days": 2520,
                "observed_days": 2520,
                "inferred_days": 0,
            },
        }
    )

    assert record.data_status == DataStatus.OBSERVED
    assert record.audit_window is not None
    assert record.to_dict() == {
        "field": "market_raw",
        "label": "市场输入",
        "source_ref": "akshare:sh510300",
        "as_of": "2026-04-04",
        "data_status": "observed",
        "source_type": "externally_fetched",
        "source_label": "外部抓取",
        "detail": None,
        "fetched_at": "2026-04-04T00:00:00Z",
        "freshness_state": "fresh",
        "audit_window": {
            "start_date": "2016-01-01",
            "end_date": "2026-01-01",
            "trading_days": 2520,
            "observed_days": 2520,
            "inferred_days": 0,
        },
    }


@pytest.mark.contract
def test_audit_record_allows_missing_optional_window():
    record = AuditRecord.from_any(
        {
            "field": "market_raw",
            "source_ref": "akshare:sh510300",
            "as_of": "2026-04-04",
            "data_status": "prior_default",
        }
    )

    assert record.audit_window is None
    assert record.to_dict()["data_status"] == "prior_default"


@pytest.mark.contract
def test_formal_path_visibility_serializes_status_and_reasons():
    visibility = FormalPathVisibility.from_any(
        {
            "status": "fallback_used_but_not_formal",
            "execution_eligible": False,
            "execution_eligibility_reason": "missing_audit_window",
            "degraded_scope": ["market"],
            "fallback_used": True,
            "fallback_scope": ["goal_solver"],
            "reasons": ["synthetic fallback allocation was used"],
            "missing_audit_fields": ["market_raw.audit_window"],
        }
    )

    assert visibility.status == FormalPathStatus.FALLBACK_USED_BUT_NOT_FORMAL
    assert visibility.to_dict()["status"] == "fallback_used_but_not_formal"
    assert visibility.to_dict()["missing_audit_fields"] == ["market_raw.audit_window"]
