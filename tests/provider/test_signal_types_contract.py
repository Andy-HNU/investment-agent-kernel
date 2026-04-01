from __future__ import annotations

from dataclasses import asdict

import pytest


@pytest.mark.contract
def test_policy_and_news_signal_types_and_ingestion():
    from shared.signals.types import PolicySignal, NewsSignal, SignalPack
    from snapshot_ingestion.signals_ingestion import apply_signals

    policy = PolicySignal(
        signal_id="policy-001",
        kind="macro_policy",
        title="RRR cut by 25bps",
        impact_buckets=["equity_cn", "bond_cn"],
        impact_direction={"equity_cn": "+", "bond_cn": "+"},
        as_of="2026-03-30",
        confidence="medium",
    )
    news = NewsSignal(
        signal_id="news-xyz",
        source="Reuters",
        title="ETF net inflows reach 3-month high",
        tickers=["510300"],
        as_of="2026-03-29",
        sentiment="positive",
    )
    pack = SignalPack(policies=[policy], news=[news])

    raw_inputs = {"market_raw": {"valuation_z_scores": {"equity_cn": -0.1}}}
    merged = apply_signals(raw_inputs, pack)

    assert "signals" in merged
    assert merged["signals"]["policies"][0]["signal_id"] == "policy-001"
    assert merged["signals"]["news"][0]["source"] == "Reuters"

