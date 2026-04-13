# Search Expansion And Profile-Aware Product Selection Design

Date: 2026-04-13
Status: Draft for review
Scope: recommendation-mode search expansion, profile-aware bucket-internal product selection, and multi-round alternative generation for `v1.4`

## 1. Objective

The current recommendation path can already build multi-product buckets, but most user-visible variation still shows up as weight changes inside a fairly stable product set.

This design extends the recommendation layer so the system can:

1. change `product_id` more naturally across different user profiles, targets, and horizons;
2. expand the search space progressively when the user is not satisfied with the first recommendation;
3. keep the first recommendation compact and explainable while preserving the ability to search deeper;
4. separate:
   - the user's requested structure,
   - the system's first recommendation,
   - later expanded alternatives.

This design does not change `v1.4` path generation math. It changes:

- candidate ranking inside splittable buckets,
- how many product variants are explored,
- how follow-up alternatives are generated when the user wants more products or better frontier coverage.

## 2. Locked Principles

1. The main recommendation is still selected by:
   - first preferring plans closest to the required annual return,
   - then preferring higher success probability,
   - then preferring lower drawdown.
2. Bucket-internal product selection must react to:
   - `required_return`,
   - `horizon`,
   - `risk_preference`,
   - `max_drawdown_tolerance`,
   - `current_market_pressure`,
   - `policy_news`.
3. Default domestic recommendation mode must not include overseas/QDII products.
4. Search expansion is progressive. The system must not jump immediately to a wide, execution-heavy portfolio.
5. User dissatisfaction is the trigger for deeper search. The system must be able to continue introducing additional products after the initial recommendation.
6. Expansion is not unbounded. The system stops when additional products no longer improve the result meaningfully.
7. User-specified portfolios remain a separate evaluation mode. Search expansion applies to recommendation mode only.

## 3. Problem Statement

Today the recommendation chain is:

1. generate candidate allocations,
2. map bucket targets to products,
3. rerank by `v1.4 primary`.

The weight layer already changes meaningfully, but bucket-internal product ordering remains too stable. As a result:

- different users often receive the same `product_id` set with different weights;
- profile changes affect `equity_cn` and `satellite` insufficiently;
- the system cannot respond naturally when a user says the initial recommendation is unsatisfactory and wants a broader search.

## 4. Search Expansion Levels

Recommendation mode must support a discrete `search_expansion_level`.

### 4.1 Allowed values

- `L0_compact`
- `L1_expanded`
- `L2_diversified`
- `L3_exhaustive`

### 4.2 Semantics

`L0_compact`
- first recommendation
- favor compactness and execution clarity
- small candidate pool per bucket
- minimal variant generation

`L1_expanded`
- used when the user wants more choice or the initial recommendation is unsatisfactory
- broaden candidate pools modestly
- allow more bucket-internal variants

`L2_diversified`
- used when the user explicitly wants richer diversification or more products
- allow deeper `equity_cn` / `satellite` construction
- still avoid brute-force enumeration

`L3_exhaustive`
- explicit opt-in only
- widest search the default domestic recommendation path is allowed to perform
- still subject to weight floors, overlap guards, and marginal-improvement stopping

### 4.3 Trigger policy

The system must use:

- `L0_compact` for the initial recommendation
- `L1_expanded` when the user says the first recommendation is unsatisfactory
- `L2_diversified` when the user wants more products, more diversification, or broader alternative coverage
- `L3_exhaustive` only when the user explicitly asks for a deeper search

### 4.4 Output visibility

Each alternative recommendation produced by deeper search must expose:

- `search_expansion_level`
- `new_product_ids_added`
- `products_removed`
- `why_this_level_was_run`
- `why_search_stopped`

## 5. Profile-Aware Candidate Ranking

Bucket-internal candidate ranking must stop behaving like a static wrapper/liquidity/fee sort.

### 5.1 Required inputs

Ranking for `equity_cn`, `satellite`, and conditionally `bond_cn` must ingest:

- `required_annual_return`
- `required_return_gap`
- `goal_horizon_months`
- `risk_preference`
- `max_drawdown_tolerance`
- `market_pressure_score`
- `current_regime`
- `policy_news_score`
- product family / theme / factor profile

### 5.2 Ranking behavior by bucket

`equity_cn`
- low required return gap + tight drawdown tolerance -> favor defensive/core products
- higher required return gap + longer horizon -> favor higher-growth products
- high pressure -> raise defensive/core preference

`satellite`
- higher required return gap -> favor higher-conviction, higher-upside themes
- high pressure -> penalize excessively crowded or overlapping themes
- policy/news can meaningfully reorder the top satellite candidates

`bond_cn`
- longer horizon + larger weight -> allow more duration/carry split
- otherwise remain stable and coarse

### 5.3 Modeling boundary

This ranking logic is a recommendation-layer prior.

It may:
- change ordering,
- change candidate pools,
- change which product variants are considered.

It may not:
- directly change `primary` returns,
- inject new simulation factors,
- override probability engine outputs.

## 6. Candidate Pool Growth By Expansion Level

Expansion level determines how many candidates per bucket are eligible for variant construction.

### 6.1 Default domestic pool limits

Recommended default limits:

`L0_compact`
- `equity_cn`: top `4`
- `satellite`: top `5`
- `bond_cn`: top `2`

`L1_expanded`
- `equity_cn`: top `6`
- `satellite`: top `8`
- `bond_cn`: top `3`

`L2_diversified`
- `equity_cn`: top `8`
- `satellite`: top `10`
- `bond_cn`: top `4`

`L3_exhaustive`
- `equity_cn`: top `10`
- `satellite`: top `12`
- `bond_cn`: top `4`

These are candidate-pool limits, not final portfolio counts.

### 6.2 Final portfolio count remains endogenous

Automatic recommendation must not use a fixed hard upper cap for the final number of products.

The actual selected count remains controlled by:

- minimum position size,
- duplicate exposure guard,
- insufficient diversification gain guard,
- marginal success improvement,
- marginal target-distance improvement.

## 7. Variant Generation Strategy

The system must not brute-force all subsets.

### 7.1 Variant generation units

Generate variants at the level of:

- `equity_cn` bucket subset
- `satellite` bucket subset
- optional `bond_cn` split

Do not generate full Cartesian products of all products in all buckets.

### 7.2 Recommended strategy

For each splittable bucket:

1. rank candidates with profile-aware ordering;
2. build a compact best subset;
3. build a small number of alternates by:
   - replacing one member with the next-ranked compatible candidate,
   - adding one member if marginal gain is high enough,
   - removing one member if overlap is too high;
4. carry only the top-scoring bucket variants forward.

### 7.3 Variant count targets

Recommended per expansion level:

`L0_compact`
- at most `1` primary subset per splittable bucket

`L1_expanded`
- at most `2` high-quality subsets per splittable bucket

`L2_diversified`
- at most `3` high-quality subsets per splittable bucket

`L3_exhaustive`
- at most `4` high-quality subsets per splittable bucket

This keeps the candidate space bounded while still allowing real `product_id` changes.

## 8. Search Stopping Rules

Search expansion must stop when additional products cease to earn their keep.

### 8.1 Hard stopping rules

Stop expanding a bucket or plan when any of these become true:

- next member would breach minimum product weight
- duplicate exposure exceeds guard threshold and marginal gain is small
- diversification gain is below threshold
- candidate supply is exhausted

### 8.2 Soft stopping rules

Stop generating deeper alternatives when:

- success probability improvement is less than `1.5pp`
- or target-return distance improvement is less than `0.25pp`
- or drawdown improvement is less than `0.5pp`

for two consecutive expansion attempts.

These thresholds are recommendation-layer defaults and may later be calibrated.

### 8.3 User-visible stop reason

Each deeper-search response must explain why search stopped, using values such as:

- `marginal_success_gain_too_small`
- `marginal_target_distance_gain_too_small`
- `minimum_weight_breach`
- `duplicate_exposure_too_high`
- `insufficient_diversification_gain`
- `candidate_supply_exhausted`

## 9. Recommendation Selection Logic

### 9.1 Initial recommendation

At `L0_compact`, the system must choose the main recommendation by:

1. smallest distance to required annual return
2. highest success probability
3. lowest drawdown

### 9.2 Alternative recommendation families

The system must preserve at least these alternative families:

- `closest_to_target`
- `highest_success_probability`
- `deeper_search_expansion`

If the user says the first recommendation is unsatisfactory:

- the system runs the next expansion level,
- keeps the original recommendation visible,
- and returns the new alternatives in parallel rather than overwriting the first answer.

### 9.3 No satisfied-target case

If no candidate plan can satisfy the target return:

- the main recommendation remains the plan closest to target return
- the highest-success plan must still be surfaced as an alternative
- the UI must explicitly say that no current candidate meets the target return requirement

## 10. Product-ID Change Expectations

This feature exists specifically so different profiles can lead to different product selections.

Expected behavior:

- small profile changes may only change weights;
- moderate changes may replace one or more `equity_cn` / `satellite` products;
- strong target/horizon/risk changes should often change both weights and `product_id` composition.

This is a recommendation goal, not a hard per-run guarantee. The system may still reuse the same products when the candidate frontier genuinely supports them.

## 11. Explanation Surface

The system must explain product changes across expansion levels.

Each recommendation alternative should include:

- `search_expansion_level`
- `selected_product_ids`
- `selected_product_weights`
- `product_ids_added_vs_previous`
- `product_ids_removed_vs_previous`
- `bucket_construction_explanations`
- `why_this_variant_was_considered`

For products newly introduced in a deeper level, the system should explain whether they were added because they:

- improved target-return proximity,
- improved success probability,
- reduced overlap,
- improved diversification,
- improved downside resilience.

## 12. Non-Goals

This design does not:

- change `v1.4` simulation formulas;
- change user-specified portfolio evaluation semantics;
- turn on overseas assets in the default path;
- guarantee that every dissatisfaction request produces a better plan.

## 13. Acceptance Criteria

This design is correctly implemented when all of the following are true:

1. Initial recommendation uses `L0_compact`.
2. A deeper-search request produces `L1_expanded` without overwriting the original recommendation.
3. Different target/horizon/risk profiles can change `product_id` sets in at least some acceptance fixtures.
4. The system does not brute-force arbitrary subset combinations.
5. Search stops with explicit reasons rather than silently expanding forever.
6. If no candidate meets the target return, the system still exposes:
   - closest-to-target main recommendation
   - highest-success alternative
7. Recommendation outputs explain what changed between compact and expanded recommendations.
