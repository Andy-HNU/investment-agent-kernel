# Search Expansion And Profile-Aware Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progressive recommendation search expansion and profile-aware bucket-internal product selection so recommendation mode can introduce new products naturally across user profiles and deeper follow-up searches.

**Architecture:** Keep `v1.4` probability outputs as the recommendation truth source. Add a lightweight recommendation-layer search controller that widens candidate pools and variant generation by `search_expansion_level`, then rerank expanded variants with existing `v1.4 primary` summaries. Do not change user-specified portfolio evaluation semantics or probability engine path math.

**Tech Stack:** Python 3, dataclass contracts, existing `product_mapping` / `orchestrator` modules, `pytest`

---

## File Structure

**Create**
- `src/product_mapping/search_expansion.py`
  Expansion-level enums, pool-limit helpers, stop-reason helpers, and candidate-variant metadata builders.
- `tests/contract/test_46_search_expansion_selection_contract.py`
  Contract coverage for expansion levels, stop reasons, and profile-aware bucket ranking.

**Modify**
- `src/product_mapping/types.py`
- `src/product_mapping/engine.py`
- `src/product_mapping/construction.py`
- `src/orchestrator/engine.py`
- `src/frontdesk/service.py`
- `src/decision_card/builder.py`
- `tests/contract/test_07_orchestrator_contract.py`
- `tests/contract/test_09_decision_card_contract.py`
- `tests/contract/test_12_frontdesk_regression.py`
- `tests/integration/test_v14_probability_engine_integration.py`

## Task 1: Add Search Expansion Contracts And Focused Failing Tests

**Files:**
- Create: `src/product_mapping/search_expansion.py`
- Modify: `src/product_mapping/types.py`
- Test: `tests/contract/test_46_search_expansion_selection_contract.py`

- [ ] **Step 1: Write the failing contract tests**

Add tests that lock the new recommendation-layer contracts:

```python
def test_candidate_pool_limit_grows_by_search_expansion_level():
    assert candidate_pool_limit("equity_cn", "L0_compact") == 4
    assert candidate_pool_limit("equity_cn", "L1_expanded") == 6
    assert candidate_pool_limit("satellite", "L2_diversified") == 10
```

```python
def test_search_expansion_stop_reason_emits_target_distance_stall():
    reason = resolve_search_stop_reason(
        success_improvement=0.001,
        target_distance_improvement=0.0005,
        drawdown_improvement=0.001,
        hard_stop_reason=None,
        consecutive_small_gain_count=2,
    )
    assert reason == "marginal_target_distance_gain_too_small"
```

```python
def test_search_expansion_result_requires_visible_delta_fields():
    result = SearchExpansionRecommendation(
        search_expansion_level="L1_expanded",
        why_this_level_was_run="user_not_satisfied",
        why_search_stopped="candidate_supply_exhausted",
        new_product_ids_added=["cn_equity_low_vol_fund"],
        products_removed=["cn_equity_dividend_etf"],
    )
    assert result.search_expansion_level == "L1_expanded"
    assert result.new_product_ids_added == ["cn_equity_low_vol_fund"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_46_search_expansion_selection_contract.py -q
```

Expected:
- FAIL with missing module / missing contract symbols

- [ ] **Step 3: Add the new contracts**

Implement:
- `SearchExpansionLevel` helpers or normalized string constants
- `candidate_pool_limit(bucket, search_expansion_level)`
- `resolve_search_stop_reason(...)`
- `SearchExpansionRecommendation` dataclass in `src/product_mapping/types.py`

Use this shape:

```python
@dataclass(frozen=True)
class SearchExpansionRecommendation:
    search_expansion_level: str
    why_this_level_was_run: str
    why_search_stopped: str | None
    new_product_ids_added: list[str] = field(default_factory=list)
    products_removed: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_46_search_expansion_selection_contract.py -q
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/product_mapping/search_expansion.py src/product_mapping/types.py tests/contract/test_46_search_expansion_selection_contract.py
git commit -m "feat: add search expansion contracts"
```

## Task 2: Make Bucket-Internal Selection Profile-Aware And Expansion-Aware

**Files:**
- Modify: `src/product_mapping/engine.py`
- Modify: `src/product_mapping/construction.py`
- Modify: `src/product_mapping/types.py`
- Modify: `src/product_mapping/search_expansion.py`
- Test: `tests/contract/test_43_intra_bucket_construction_contract.py`
- Test: `tests/contract/test_46_search_expansion_selection_contract.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove profile and expansion level can change selected products, not only weights:

```python
def test_equity_candidate_order_changes_with_required_return_and_risk_profile():
    low_gap = profile_aware_candidate_sort_key(
        runtime_candidate=make_runtime_candidate("cn_equity_dividend_etf", bucket="equity_cn"),
        bucket="equity_cn",
        required_annual_return=0.05,
        goal_horizon_months=36,
        risk_preference="moderate",
        max_drawdown_tolerance=0.20,
        market_pressure_score=40.0,
    )
    high_gap = profile_aware_candidate_sort_key(
        runtime_candidate=make_runtime_candidate("cn_equity_dividend_etf", bucket="equity_cn"),
        bucket="equity_cn",
        required_annual_return=0.11,
        goal_horizon_months=36,
        risk_preference="aggressive",
        max_drawdown_tolerance=0.35,
        market_pressure_score=8.0,
    )
    assert low_gap != high_gap
```

```python
def test_l1_expanded_considers_more_satellite_candidates_than_l0():
    l0 = build_bucket_subset(
        bucket="satellite",
        bucket_weight=0.20,
        requested_resolution=resolution_auto(2),
        candidates=make_ranked_satellite_candidates(8),
        search_expansion_level="L0_compact",
        ranking_context=ranking_context(required_annual_return=0.08, risk_preference="moderate"),
    )
    l1 = build_bucket_subset(
        bucket="satellite",
        bucket_weight=0.20,
        requested_resolution=resolution_auto(2),
        candidates=make_ranked_satellite_candidates(8),
        search_expansion_level="L1_expanded",
        ranking_context=ranking_context(required_annual_return=0.08, risk_preference="moderate"),
    )
    assert [item.candidate.product_id for item in l0] != [item.candidate.product_id for item in l1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_46_search_expansion_selection_contract.py -q
```

Expected:
- FAIL because ranking/build helpers do not yet accept expansion level or profile-aware context

- [ ] **Step 3: Implement profile-aware ranking**

Replace the current static `_candidate_sort_key(...)` path with a new helper that accepts recommendation context:

```python
def _profile_aware_candidate_sort_key(
    runtime_candidate: RuntimeProductCandidate,
    *,
    bucket: str,
    required_annual_return: float | None,
    goal_horizon_months: int | None,
    risk_preference: str | None,
    max_drawdown_tolerance: float | None,
    market_pressure_score: float | None,
) -> tuple[float, ...]:
    ...
```

Behavior to enforce:
- `equity_cn`: higher required return / longer horizon can raise growth-oriented candidates
- `equity_cn`: tight drawdown / high pressure can raise defensive candidates
- `satellite`: policy/news and required return can materially reorder candidates
- `bond_cn`: stay coarse and stable

- [ ] **Step 4: Make subset construction expansion-aware**

Thread `search_expansion_level` and ranking context into `build_bucket_subset(...)`.

Use:
- `candidate_pool_limit(...)` to trim the working pool by level
- profile-aware ordering before subset construction
- the existing duplicate-exposure and diversification-gain guards as the final subset constraints

Do not brute-force all subsets. Keep the current greedy/high-quality subset pattern.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_46_search_expansion_selection_contract.py -q
```

Expected:
- PASS

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/product_mapping/engine.py src/product_mapping/construction.py src/product_mapping/types.py src/product_mapping/search_expansion.py tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_46_search_expansion_selection_contract.py
git commit -m "feat: add profile-aware bucket selection"
```

## Task 3: Add Progressive Recommendation Expansion In Orchestrator

**Files:**
- Modify: `src/orchestrator/engine.py`
- Modify: `src/product_mapping/engine.py`
- Modify: `src/product_mapping/types.py`
- Test: `tests/contract/test_07_orchestrator_contract.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_initial_recommendation_uses_l0_compact():
    result = run_orchestrator(...)
    assert result.decision_card["execution_plan_summary"]["search_expansion_level"] == "L0_compact"
```

```python
def test_deeper_search_surfaces_expanded_alternative_without_overwriting_original(monkeypatch):
    payload = rerank_with_search_expansion(..., search_expansion_level="L1_expanded")
    assert payload["recommended"]["search_expansion_level"] == "L0_compact"
    assert payload["expanded_alternatives"][0]["search_expansion_level"] == "L1_expanded"
```

```python
def test_when_no_plan_meets_target_return_closest_target_stays_primary_and_highest_success_remains_alternative():
    reranked = _rerank_goal_solver_output_with_v14_primary(...)
    frontier = reranked[0].frontier_analysis.to_dict()
    assert frontier["recommended"]["allocation_name"] != frontier["highest_probability"]["allocation_name"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/integration/test_v14_probability_engine_integration.py -q
```

Expected:
- FAIL because recommendation output has no expansion-level semantics and no expanded alternatives

- [ ] **Step 3: Implement expansion-level orchestration**

Add a small recommendation-layer controller inside orchestrator that:

1. runs the existing compact recommendation path at `L0_compact`
2. preserves it as the main recommendation
3. can build deeper alternatives for `L1_expanded` and above when requested
4. records:
   - `search_expansion_level`
   - `why_this_level_was_run`
   - `why_search_stopped`
   - `new_product_ids_added`
   - `products_removed`

The deeper alternatives must still be reranked using the existing `v1.4 primary` summaries.

- [ ] **Step 4: Thread expansion metadata into the execution plan summary**

Ensure recommendation-mode execution summaries expose the new fields so frontdesk and decision-card can render them later.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/integration/test_v14_probability_engine_integration.py -q
```

Expected:
- PASS

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/orchestrator/engine.py src/product_mapping/engine.py src/product_mapping/types.py tests/contract/test_07_orchestrator_contract.py tests/integration/test_v14_probability_engine_integration.py
git commit -m "feat: add progressive recommendation expansion"
```

## Task 4: Expose Search Expansion Facts In Frontdesk And Decision Card

**Files:**
- Modify: `src/frontdesk/service.py`
- Modify: `src/decision_card/builder.py`
- Test: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing presentation tests**

Add tests that assert frontdesk and decision-card show the new recommendation facts:

```python
def test_frontdesk_summary_exposes_search_expansion_fields():
    summary = build_frontdesk_summary(...)
    assert summary["execution_plan_summary"]["search_expansion_level"] == "L1_expanded"
    assert summary["execution_plan_summary"]["new_product_ids_added"] == ["cn_equity_low_vol_fund"]
```

```python
def test_decision_card_exposes_expanded_alternatives_without_hiding_primary():
    card = build_decision_card(...)
    assert card["execution_plan_summary"]["search_expansion_level"] == "L0_compact"
    assert card["execution_plan_summary"]["expanded_alternatives"][0]["search_expansion_level"] == "L1_expanded"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- FAIL because the surfaces do not yet render search-expansion metadata

- [ ] **Step 3: Implement minimal surface wiring**

Expose:
- `search_expansion_level`
- `why_this_level_was_run`
- `why_search_stopped`
- `new_product_ids_added`
- `products_removed`
- `expanded_alternatives`

Do not build a new UI taxonomy. Keep the surface factual and compact.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py -q
```

Expected:
- PASS

- [ ] **Step 5: Run the combined verification set**

Run:

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py tests/contract/test_43_intra_bucket_construction_contract.py tests/contract/test_46_search_expansion_selection_contract.py tests/integration/test_v14_probability_engine_integration.py -q
git diff --check
```

Expected:
- PASS
- no diff-check findings

- [ ] **Step 6: Commit**

```bash
cd /root/AndyFtp/investment_system_codex_ready_repo
git add src/frontdesk/service.py src/decision_card/builder.py tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py
git commit -m "feat: expose search expansion recommendation facts"
```

