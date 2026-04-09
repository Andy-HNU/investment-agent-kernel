from __future__ import annotations

from pathlib import Path

import pytest

from probability_engine.factor_library import FIXED_FACTOR_DICTIONARY, load_factor_library_snapshot
from probability_engine.factor_mapping import build_factor_mapping, load_product_mapping_bundle


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v14"


@pytest.mark.contract
def test_factor_library_snapshot_loads_factor_return_history_and_fixed_dictionary() -> None:
    snapshot = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")

    assert tuple(snapshot.factor_ids) == tuple(FIXED_FACTOR_DICTIONARY.keys())
    assert snapshot.snapshot_id == "v14_factor_library_snapshot_2026-04-09"
    assert len(snapshot.factor_return_history) == 126
    assert snapshot.factor_return_history[0].date == "2025-10-06"
    assert snapshot.factor_return_history[0].factor_returns["CN_EQ_BROAD"] == pytest.approx(0.006)


@pytest.mark.contract
def test_build_factor_mapping_blends_prior_holdings_returns_and_shrinkage() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    result = next(
        item
        for item in build_factor_mapping(bundle.products, factor_library, as_of=bundle.as_of)
        if item.product_id == "cn_equity_balanced_fund"
    )

    assert result.stage_weights["prior"] > 0.0
    assert result.stage_weights["holdings"] > 0.0
    assert 0.0 < result.stage_weights["returns"] <= 0.40
    assert result.anchor_source == "prior"
    assert result.mapping_confidence in {"high", "medium"}
    assert any(
        entry["source"] == "returns" and entry["sample_count"] >= 126 and entry["weight"] > 0
        for entry in result.factor_mapping_evidence
    )
    assert result.beta_raw["CN_EQ_BROAD"] != pytest.approx(result.beta_prior["CN_EQ_BROAD"])
    assert min(result.beta_raw["CN_EQ_BROAD"], result.beta_anchor["CN_EQ_BROAD"]) <= result.factor_betas["CN_EQ_BROAD"] <= max(
        result.beta_raw["CN_EQ_BROAD"], result.beta_anchor["CN_EQ_BROAD"]
    )
    assert any(entry["source"] == "holdings" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)
    assert any(entry["source"] == "returns" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)


@pytest.mark.contract
def test_empty_holdings_payload_does_not_create_holdings_weight_even_with_declared_coverage() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    result = next(
        item
        for item in build_factor_mapping(bundle.products, factor_library, as_of=bundle.as_of)
        if item.product_id == "cn_equity_empty_holdings"
    )

    assert result.stage_weights["holdings"] == 0.0
    assert result.holdings_coverage == 0.0
    assert result.anchor_source == "prior"
    assert any(entry["source"] == "holdings" and entry["weight"] == 0.0 for entry in result.factor_mapping_evidence)


@pytest.mark.contract
def test_short_history_sparse_product_zeroes_returns_weight_and_uses_cluster_anchor() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    result = next(
        item
        for item in build_factor_mapping(bundle.products, factor_library, as_of=bundle.as_of)
        if item.product_id == "cn_bond_short_history"
    )

    assert result.history_days < 63
    assert result.stage_weights["returns"] == 0.0
    assert result.anchor_source == "cluster_mean"
    assert result.stage_weights["holdings"] == 0.0
    assert any(entry["source"] == "returns" and entry["weight"] == 0.0 for entry in result.factor_mapping_evidence)
    assert any(entry["source"] == "anchor" and entry["weight"] > 0 for entry in result.factor_mapping_evidence)


@pytest.mark.contract
def test_factor_library_public_coercion_rejects_missing_factor_return_history() -> None:
    factor_library = load_factor_library_snapshot(FIXTURE_DIR / "factor_library_snapshot.json")
    bundle = load_product_mapping_bundle(FIXTURE_DIR / "product_mapping_bundle.json")

    with pytest.raises(ValueError, match="factor_return_history"):
        build_factor_mapping(bundle.products, {"snapshot_id": factor_library.snapshot_id, "as_of": factor_library.as_of, "factors": [factor.__dict__ for factor in factor_library.factors]}, as_of=bundle.as_of)
