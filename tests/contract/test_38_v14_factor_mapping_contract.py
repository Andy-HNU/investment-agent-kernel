from __future__ import annotations

from pathlib import Path

import pytest

from probability_engine.factor_library import FIXED_FACTOR_DICTIONARY, load_factor_library_snapshot
from probability_engine.factor_mapping import build_factor_mapping, load_product_mapping_bundle


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v14"


@pytest.mark.contract
def test_factor_library_snapshot_loads_fixed_factor_dictionary() -> None:
    snapshot = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")

    assert tuple(snapshot.factor_ids) == tuple(FIXED_FACTOR_DICTIONARY.keys())
    assert snapshot.snapshot_id == "v14_factor_library_snapshot_2026-04-09"


@pytest.mark.contract
def test_build_factor_mapping_blends_holdings_and_returns_evidence_with_high_or_medium_confidence() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    result = next(
        item for item in build_factor_mapping(bundle.products, factor_library, as_of=bundle.as_of) if item.product_id == "cn_equity_balanced_fund"
    )

    assert result.factor_mapping_source == "prior+holdings+returns+shrinkage"
    assert result.mapping_confidence in {"high", "medium"}
    assert result.factor_betas["CN_EQ_BROAD"] != result.beta_prior["CN_EQ_BROAD"]
    assert result.factor_betas["CN_EQ_BROAD"] != result.beta_returns["CN_EQ_BROAD"]
    assert any(entry["source"] == "holdings" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)
    assert any(entry["source"] == "returns" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)


@pytest.mark.contract
def test_short_history_product_zeroes_returns_weight_and_uses_anchor_fallback() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    result = next(
        item for item in build_factor_mapping(bundle.products, factor_library, as_of=bundle.as_of) if item.product_id == "cn_bond_short_history"
    )

    assert result.history_days < 63
    assert result.beta_returns == {factor: 0.0 for factor in factor_library.factor_ids}
    assert result.shrinkage_lambda < 1.0
    assert any(entry["source"] == "returns" and entry["weight"] == 0 for entry in result.factor_mapping_evidence)
    assert any(entry["source"] == "anchor" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)
