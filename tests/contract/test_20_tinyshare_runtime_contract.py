from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from frontdesk.service import run_frontdesk_onboarding
from product_mapping.runtime_inputs import (
    build_runtime_product_universe_context,
    build_runtime_product_valuation_context,
)
from product_mapping.types import ProductCandidate
from shared.datasets.cache import DatasetCache
from shared.datasets.types import DatasetSpec, VersionPin
from shared.providers import tinyshare as tinyshare_provider
from shared.onboarding import UserOnboardingProfile
from shared.providers.timeseries import fetch_timeseries
from snapshot_ingestion.providers import fetch_snapshot_from_provider_config


def _profile(*, account_profile_id: str = "layer2_tinyshare_user") -> UserOnboardingProfile:
    return UserOnboardingProfile(
        account_profile_id=account_profile_id,
        display_name="Andy",
        current_total_assets=18_000.0,
        monthly_contribution=2_500.0,
        goal_amount=120_000.0,
        goal_horizon_months=36,
        risk_preference="中等",
        max_drawdown_tolerance=0.20,
        current_holdings="cash 12000, gold 6000",
        restrictions=["forbidden_theme:technology", "no_stock_picking"],
    )


def _runtime_catalog() -> list[ProductCandidate]:
    return [
        ProductCandidate(
            product_id="ts_equity_core_etf",
            product_name="核心宽基ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="market_history_tinyshare",
            provider_symbol="510300.SH",
            tags=["core", "broad_market"],
        ),
        ProductCandidate(
            product_id="ts_bond_core_etf",
            product_name="国债ETF",
            asset_bucket="bond_cn",
            product_family="defense",
            wrapper_type="etf",
            provider_source="market_history_tinyshare",
            provider_symbol="511010.SH",
            tags=["defense", "bond"],
        ),
        ProductCandidate(
            product_id="ts_gold_core_etf",
            product_name="黄金ETF",
            asset_bucket="gold",
            product_family="defense",
            wrapper_type="etf",
            provider_source="market_history_tinyshare",
            provider_symbol="518880.SH",
            tags=["gold"],
        ),
    ]


def _tinyshare_universe_result() -> dict[str, object]:
    return {
        "snapshot_id": "tinyshare_runtime_catalog_2026-04-05",
        "source_status": "observed",
        "source_name": "tinyshare_runtime_catalog",
        "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
        "as_of": "2026-04-05",
        "data_status": "observed",
        "item_count": 3,
        "audit_window": None,
        "products": {
            candidate.product_id: {
                "status": "observed",
                "tradable": True,
                "source_name": "tinyshare_runtime_catalog",
                "source_ref": "tinyshare://runtime_catalog?markets=stocks,funds",
                "as_of": "2026-04-05",
                "data_status": "observed",
                "audit_window": None,
            }
            for candidate in _runtime_catalog()
        },
        "runtime_candidates": [candidate.to_dict() for candidate in _runtime_catalog()],
    }


def _tinyshare_valuation_result() -> dict[str, object]:
    return {
        "source_status": "observed",
        "source_name": "tinyshare_runtime_valuation",
        "source_ref": "tinyshare://daily_basic?trade_date=20260403",
        "as_of": "2026-04-05",
        "products": {
            "ts_equity_core_etf": {
                "status": "observed",
                "pe_ratio": 18.0,
                "pb_ratio": 2.1,
                "percentile": 0.22,
                "data_status": "computed_from_observed",
                "audit_window": {
                    "start_date": "2025-04-03",
                    "end_date": "2026-04-03",
                    "trading_days": 243,
                    "observed_days": 243,
                    "inferred_days": 0,
                },
                "source_ref": "tinyshare://valuation/equity_cn",
                "as_of": "2026-04-05",
            }
        },
    }


@pytest.mark.contract
def test_fetch_timeseries_supports_tinyshare_provider(monkeypatch, tmp_path):
    class _FakePro:
        def daily(self, ts_code, start_date, end_date):  # type: ignore[no-untyped-def]
            assert ts_code == "600519.SH"
            return pd.DataFrame(
                [
                    {"ts_code": ts_code, "trade_date": "20260402", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "vol": 100.0},
                    {"ts_code": ts_code, "trade_date": "20260403", "open": 1.5, "high": 2.2, "low": 1.2, "close": 2.0, "vol": 120.0},
                ]
            )

        def fund_daily(self, ts_code, start_date, end_date):  # type: ignore[no-untyped-def]
            assert ts_code == "510300.SH"
            return pd.DataFrame(
                [
                    {"ts_code": ts_code, "trade_date": "20260402", "pre_close": 1.0, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "vol": 90.0},
                    {"ts_code": ts_code, "trade_date": "20260403", "pre_close": 1.05, "open": 1.06, "high": 1.2, "low": 1.0, "close": 1.15, "vol": 95.0},
                ]
            )

    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr("shared.providers.tinyshare._pro_api", lambda token=None: _FakePro())

    cache = DatasetCache(base_dir=tmp_path / "cache")
    stock_rows = fetch_timeseries(
        DatasetSpec(kind="timeseries", dataset_id="market_history", provider="tinyshare", symbol="600519.SH"),
        pin=VersionPin("tinyshare:stock", "tinyshare://600519.SH?start=2026-04-02&end=2026-04-03"),
        cache=cache,
    )
    fund_rows = fetch_timeseries(
        DatasetSpec(kind="timeseries", dataset_id="market_history", provider="tinyshare", symbol="510300.SH"),
        pin=VersionPin("tinyshare:fund", "tinyshare://510300.SH?start=2026-04-02&end=2026-04-03"),
        cache=cache,
    )

    assert [row["date"] for row in stock_rows] == ["2026-04-02", "2026-04-03"]
    assert stock_rows[-1]["close"] == pytest.approx(2.0, abs=1e-6)
    assert [row["date"] for row in fund_rows] == ["2026-04-02", "2026-04-03"]
    assert fund_rows[-1]["close"] == pytest.approx(1.15, abs=1e-6)


@pytest.mark.contract
def test_build_runtime_product_universe_context_uses_tinyshare_runtime_catalog_without_market_history(monkeypatch):
    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.load_tinyshare_runtime_catalog",
        lambda *, as_of, cache_dir=None: (_runtime_catalog(), _tinyshare_universe_result()),
    )

    inputs, result = build_runtime_product_universe_context(
        market_raw={},
        as_of="2026-04-05T10:00:00Z",
        cache_dir=Path("/tmp/layer2_tinyshare_contract"),
    )

    assert inputs["requested"] is True
    assert inputs["source_kind"] == "tinyshare_runtime_catalog"
    assert result is not None
    assert result["source_status"] == "observed"
    assert result["source_name"] == "tinyshare_runtime_catalog"
    assert result["snapshot_id"] == "tinyshare_runtime_catalog_2026-04-05"
    assert result["item_count"] == 3
    assert result["data_status"] == "observed"
    assert len(result["runtime_candidates"]) == 3
    assert result["products"]["ts_equity_core_etf"]["status"] == "observed"


@pytest.mark.contract
def test_build_runtime_product_valuation_context_uses_tinyshare_runtime_result_without_market_inputs(monkeypatch):
    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.load_tinyshare_runtime_catalog",
        lambda *, as_of, cache_dir=None: (_runtime_catalog(), _tinyshare_universe_result()),
    )
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.build_tinyshare_runtime_valuation_result",
        lambda candidates, *, as_of, cache_dir=None: _tinyshare_valuation_result(),
    )

    inputs, result = build_runtime_product_valuation_context(
        market_raw={},
        as_of="2026-04-05T10:00:00Z",
    )

    assert inputs["requested"] is True
    assert inputs["source_kind"] == "tinyshare_runtime_valuation"
    assert result is not None
    assert result["source_status"] == "observed"
    assert result["products"]["ts_equity_core_etf"]["pe_ratio"] == pytest.approx(18.0, abs=1e-6)
    assert result["products"]["ts_equity_core_etf"]["percentile"] == pytest.approx(0.22, abs=1e-6)


@pytest.mark.contract
def test_frontdesk_onboarding_auto_uses_tinyshare_runtime_inputs_when_token_present(monkeypatch, tmp_path):
    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.load_tinyshare_runtime_catalog",
        lambda *, as_of, cache_dir=None: (_runtime_catalog(), _tinyshare_universe_result()),
    )
    monkeypatch.setattr(
        "product_mapping.runtime_inputs.build_tinyshare_runtime_valuation_result",
        lambda candidates, *, as_of, cache_dir=None: _tinyshare_valuation_result(),
    )

    summary = run_frontdesk_onboarding(
        _profile(account_profile_id="layer2_tinyshare_runtime_user"),
        db_path=tmp_path / "frontdesk.sqlite",
    )

    pending = summary["pending_execution_plan"]
    assert pending is not None
    assert pending["product_universe_audit_summary"]["requested"] is True
    assert pending["product_universe_audit_summary"]["source_status"] == "observed"
    assert pending["valuation_audit_summary"]["requested"] is True
    assert pending["valuation_audit_summary"]["source_status"] == "observed"
    assert pending["runtime_candidate_count"] == 3


@pytest.mark.contract
def test_market_history_provider_supports_tinyshare(monkeypatch):
    def fake_fetch_timeseries(spec, *, pin, cache, allow_fallback, return_used_pin):  # type: ignore[no-untyped-def]
        rows = [
            {"date": "2026-04-01", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100.0},
            {"date": "2026-04-02", "open": 1.0, "high": 1.2, "low": 0.95, "close": 1.1, "volume": 110.0},
            {"date": "2026-04-03", "open": 1.1, "high": 1.25, "low": 1.0, "close": 1.15, "volume": 120.0},
        ]
        return rows, pin

    monkeypatch.setattr("snapshot_ingestion.providers.fetch_timeseries", fake_fetch_timeseries)

    payload = fetch_snapshot_from_provider_config(
        {
            "adapter": "market_history",
            "provider": "tinyshare",
            "coverage_asset_class": "etf",
            "symbol_map": {
                "equity_cn": {"tinyshare": "510300.SH"},
                "bond_cn": {"tinyshare": "511010.SH"},
                "gold": {"tinyshare": "518880.SH"},
                "satellite": {"tinyshare": "159915.SZ"},
            },
            "start_date": "2026-04-01",
            "end_date": "2026-04-03",
        },
        workflow_type="onboarding",
        account_profile_id="tinyshare_market_history",
        as_of="2026-04-05T00:00:00Z",
    )

    historical_dataset = payload.raw_overrides["market_raw"]["historical_dataset"]
    assert payload.provider_name == "market_history"
    assert historical_dataset["source_name"] == "tinyshare"
    assert historical_dataset["coverage_status"] == "verified"
    assert historical_dataset["audit_window"]["trading_days"] == 3


@pytest.mark.contract
def test_build_runtime_valuation_result_uses_bulk_daily_basic_snapshot(monkeypatch, tmp_path):
    stock_candidates = [
        ProductCandidate(
            product_id="ts_stock_000001_sz",
            product_name="平安银行",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="000001.SZ",
            tags=["equity", "stock_wrapper", "cn"],
        ),
        ProductCandidate(
            product_id="ts_stock_600519_sh",
            product_name="贵州茅台",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="600519.SH",
            tags=["equity", "stock_wrapper", "cn"],
        ),
        ProductCandidate(
            product_id="ts_fund_510300_sh",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_fund_basic",
            provider_symbol="510300.SH",
            tags=["equity", "etf", "cn"],
        ),
    ]

    class _FakePro:
        def __init__(self) -> None:
            self.daily_basic_calls: list[dict[str, object]] = []

        def trade_cal(self, exchange, start_date, end_date):  # type: ignore[no-untyped-def]
            return pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260403", "is_open": 1, "pretrade_date": "20260402"},
                    {"exchange": "SSE", "cal_date": "20260404", "is_open": 0, "pretrade_date": "20260403"},
                ]
            )

        def daily_basic(self, **kwargs):  # type: ignore[no-untyped-def]
            self.daily_basic_calls.append(dict(kwargs))
            assert kwargs.get("trade_date") == "20260403"
            assert kwargs.get("ts_code") in (None, "")
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260403", "pe": 4.7, "pe_ttm": 4.6, "pb": 0.44},
                    {"ts_code": "600519.SH", "trade_date": "20260403", "pe": 21.2, "pe_ttm": 20.3, "pb": 8.05},
                ]
            )

    fake_pro = _FakePro()
    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr("shared.providers.tinyshare._pro_api", lambda token=None: fake_pro)

    result = tinyshare_provider.build_runtime_valuation_result(
        stock_candidates,
        as_of="2026-04-05",
        cache_dir=tmp_path,
    )

    assert result["source_status"] == "observed"
    assert len(fake_pro.daily_basic_calls) == 1
    assert result["products"]["ts_stock_000001_sz"]["pe_ratio"] == pytest.approx(4.7, abs=1e-6)
    assert result["products"]["ts_stock_600519_sh"]["pb_ratio"] == pytest.approx(8.05, abs=1e-6)
    assert result["products"]["ts_stock_600519_sh"]["audit_window"]["trading_days"] == 1
    assert result["bucket_proxies"]["equity_cn"]["status"] == "observed"
    assert result["bucket_proxies"]["equity_cn"]["pe_ratio"] == pytest.approx(12.95, abs=1e-6)
    assert result["bucket_proxies"]["equity_cn"]["percentile"] > 0.0


@pytest.mark.contract
def test_build_runtime_valuation_result_ignores_stale_missing_cache_from_non_stock_run(monkeypatch, tmp_path):
    fund_only_candidates = [
        ProductCandidate(
            product_id="ts_fund_510300_sh",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_fund_basic",
            provider_symbol="510300.SH",
            tags=["equity", "etf", "cn"],
        )
    ]
    stock_candidates = [
        ProductCandidate(
            product_id="ts_stock_000001_sz",
            product_name="平安银行",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="000001.SZ",
            tags=["equity", "stock_wrapper", "cn"],
        )
    ]

    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"exchange": "SSE", "cal_date": "20260403", "is_open": 1, "pretrade_date": "20260402"}])

        def daily_basic(self, **kwargs):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260403", "pe": 4.7, "pe_ttm": 4.6, "pb": 0.44}])

    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr("shared.providers.tinyshare._pro_api", lambda token=None: _FakePro())

    first = tinyshare_provider.build_runtime_valuation_result(
        fund_only_candidates,
        as_of="2026-04-05",
        cache_dir=tmp_path,
    )
    second = tinyshare_provider.build_runtime_valuation_result(
        stock_candidates,
        as_of="2026-04-05",
        cache_dir=tmp_path,
    )

    assert first["source_status"] == "missing"
    assert second["source_status"] == "observed"
    assert second["products"]["ts_stock_000001_sz"]["status"] == "observed"




@pytest.mark.contract
def test_build_runtime_valuation_result_recomputes_when_product_ids_change_for_same_symbol(monkeypatch, tmp_path):
    first_candidates = [
        ProductCandidate(
            product_id="ts_stock_alias_a",
            product_name="平安银行A",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="000001.SZ",
            tags=["equity", "stock_wrapper", "cn"],
        )
    ]
    second_candidates = [
        ProductCandidate(
            product_id="ts_stock_alias_b",
            product_name="平安银行B",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="000001.SZ",
            tags=["equity", "stock_wrapper", "cn"],
        )
    ]

    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"exchange": "SSE", "cal_date": "20260403", "is_open": 1, "pretrade_date": "20260402"}])

        def daily_basic(self, **kwargs):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260403", "pe": 4.7, "pe_ttm": 4.6, "pb": 0.44}])

    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr("shared.providers.tinyshare._pro_api", lambda token=None: _FakePro())

    first = tinyshare_provider.build_runtime_valuation_result(first_candidates, as_of="2026-04-05", cache_dir=tmp_path)
    second = tinyshare_provider.build_runtime_valuation_result(second_candidates, as_of="2026-04-05", cache_dir=tmp_path)

    assert list(first["products"].keys()) == ["ts_stock_alias_a"]
    assert list(second["products"].keys()) == ["ts_stock_alias_b"]


@pytest.mark.contract
def test_build_runtime_valuation_result_invalidates_old_cache_without_bucket_proxies(monkeypatch, tmp_path):
    candidates = [
        ProductCandidate(
            product_id="ts_stock_000001_sz",
            product_name="平安银行",
            asset_bucket="equity_cn",
            product_family="a_share_stock",
            wrapper_type="stock",
            provider_source="tinyshare_stock_basic",
            provider_symbol="000001.SZ",
            tags=["equity", "stock_wrapper", "cn"],
        ),
        ProductCandidate(
            product_id="ts_fund_510300_sh",
            product_name="沪深300ETF",
            asset_bucket="equity_cn",
            product_family="core",
            wrapper_type="etf",
            provider_source="tinyshare_fund_basic",
            provider_symbol="510300.SH",
            tags=["equity", "etf", "cn"],
        ),
    ]

    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"exchange": "SSE", "cal_date": "20260403", "is_open": 1, "pretrade_date": "20260402"}])

        def daily_basic(self, **kwargs):  # type: ignore[no-untyped-def]
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260403", "pe": 4.7, "pe_ttm": 4.6, "pb": 0.44}])

    monkeypatch.setenv("TINYSHARE_TOKEN", "test-token")
    monkeypatch.setattr("shared.providers.tinyshare._pro_api", lambda token=None: _FakePro())

    old_cache = tmp_path / "runtime_valuation_2026-04-05.json"
    old_cache.write_text(
        """
{
  "source_status": "observed",
  "source_name": "tinyshare_runtime_valuation",
  "source_ref": "tinyshare://daily_basic?trade_date=20260403",
  "as_of": "2026-04-05",
  "products": {
    "ts_stock_000001_sz": {
      "status": "observed",
      "pe_ratio": 4.7,
      "pb_ratio": 0.44,
      "percentile": 0.05875,
      "data_status": "computed_from_observed",
      "source_ref": "tinyshare://daily_basic?trade_date=20260403&ts_code=000001.SZ",
      "as_of": "2026-04-05"
    }
  },
  "stock_candidate_count": 1,
  "stock_candidate_signature": "ts_stock_000001_sz:000001.SZ"
}
        """.strip(),
        encoding="utf-8",
    )

    result = tinyshare_provider.build_runtime_valuation_result(candidates, as_of="2026-04-05", cache_dir=tmp_path)

    assert result["bucket_proxies"]["equity_cn"]["status"] == "observed"
    assert result["cache_format_version"] >= 2
@pytest.mark.contract
def test_tinyshare_provider_ignores_repo_local_token_file_under_pytest_by_default(monkeypatch, tmp_path):
    token_file = tmp_path / ".secrets" / "tinyshare.token"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("file-token\n", encoding="utf-8")

    monkeypatch.delenv("TINYSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TINYSHARE_TOKEN_FILE", raising=False)
    monkeypatch.delenv("TINYSHARE_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::token-file")
    monkeypatch.setattr("shared.providers.tinyshare._repo_root", lambda: tmp_path)

    assert tinyshare_provider.has_token() is False


@pytest.mark.contract
def test_tinyshare_provider_reads_repo_local_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / ".secrets" / "tinyshare.token"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("file-token\n", encoding="utf-8")

    monkeypatch.delenv("TINYSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TINYSHARE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TINYSHARE_ALLOW_REPO_TOKEN_FILE_UNDER_PYTEST", "1")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::token-file")
    monkeypatch.setattr("shared.providers.tinyshare._repo_root", lambda: tmp_path)

    assert tinyshare_provider.has_token() is True
    assert tinyshare_provider._require_token() == "file-token"
