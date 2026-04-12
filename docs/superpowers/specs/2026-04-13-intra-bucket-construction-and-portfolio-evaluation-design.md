# Intra-Bucket Construction And Portfolio Evaluation Design

Date: 2026-04-13
Status: Draft for review
Scope: recommendation-mode bucket construction, user-specified portfolio evaluation, and per-product / per-group explanation surfaces for `v1.4`

## 1. Objective

The current system still collapses each asset bucket to one primary product plus alternates. That is too narrow for realistic recommendation and evaluation behavior.

This design changes the product layer so the system can:

1. Recommend multi-product constructions inside `equity_cn`, `satellite`, and conditionally `bond_cn`.
2. Respect user-specified product-count preferences such as `主力 2 个，卫星 5 个`.
3. Evaluate user-specified portfolios as entered, without silently rewriting them.
4. Explain the portfolio at three levels:
   - whole-portfolio
   - per-product
   - per-group

This design does not change the `v1.4` probability engine core math. It changes how portfolios are constructed, fed into the engine, and explained to the user.

## 2. Locked Principles

1. `gold` and `cash_liquidity` remain single-product buckets by default.
2. Overseas / QDII assets are not considered in the default domestic recommendation path.
3. Overseas / QDII assets are only considered when the user explicitly requests an overseas-aware path.
4. User-entered portfolios are evaluated as entered. The system may diagnose and suggest alternatives, but may not silently rewrite them.
5. Unknown products must first surface as `unrecognized_product`. The system must not auto-map them without user confirmation.
6. Product-count preferences are strong preferences, not hard constraints.
7. If the requested count cannot be satisfied cleanly, the system must:
   - first evaluate the requested structure
   - then present a more feasible alternative structure in parallel
8. Product-level and group-level usefulness must be assessed by impact on the whole portfolio, not only by standalone return.

## 3. Bucket Policy

### 3.1 Default bucket behavior

- `gold`: single product only
- `cash_liquidity`: single product only
- `bond_cn`: single product by default; optionally split when explicitly requested or when the automatic policy enables coarse dual construction
- `equity_cn`: multi-product allowed
- `satellite`: multi-product allowed

### 3.2 User-facing count semantics

The front-end should support the following natural-language mapping:

- `主力 N 个` -> `equity_cn.target_count = N`
- `卫星 M 个` -> `satellite.target_count = M`
- `债券拆 K 个` -> `bond_cn.target_count = K`

No count semantics are exposed for `gold` or `cash_liquidity` in the default UX.

### 3.3 Count policy modes

Each relevant bucket must support:

- `auto`
- `target_count`
- `count_range`

Recommended representation:

```python
@dataclass(frozen=True)
class BucketCardinalityPreference:
    bucket: str
    mode: str                  # auto / target_count / count_range
    target_count: int | None
    min_count: int | None
    max_count: int | None
    source: str                # system_default / user_requested
```

## 4. When To Split A Bucket

Bucket splitting is conditional. It is not always desirable.

### 4.1 Inputs

Automatic bucket splitting must consider:

- `goal_horizon_months`
- `implied_required_annual_return`
- `risk_preference`
- `max_drawdown_tolerance`
- `current_market_pressure_score`
- `bucket_weight`

### 4.2 Hard non-split rules

- `gold`: never split in default domestic mode
- `cash_liquidity`: never split
- `horizon_months < 12`: no bucket splitting anywhere

### 4.3 Auto activation states

Each splittable bucket resolves to:

- `off`
- `light`
- `standard`

Interpretation:

- `off`: single-product bucket
- `light`: multi-product allowed but lower count target
- `standard`: full multi-product construction allowed

### 4.4 Recommended auto rules

`equity_cn`
- `off` if:
  - `horizon_months < 18`, or
  - `required_return_gap > 0.02` and `risk_preference == "aggressive"`
- `light` if:
  - `18 <= horizon_months < 24`
- `standard` if:
  - `horizon_months >= 24` and
  - (`current_market_pressure_score >= 25` or `max_drawdown_tolerance <= 0.20`)

`satellite`
- `off` if:
  - `horizon_months < 12`, or
  - `bucket_weight < 0.08`
- `light` if:
  - `bucket_weight >= 0.08` and `horizon_months >= 12`
- `standard` if:
  - `bucket_weight >= 0.12` and `horizon_months >= 18`

`bond_cn`
- `off` unless:
  - user explicitly requests a split, or
  - `bucket_weight >= 0.20` and `horizon_months >= 24`

These rules are defaults only. User count requests override activation level as a strong preference.

## 5. Product Count Resolution

### 5.1 Automatic target counts

Recommended default auto counts:

`equity_cn`
- `off` -> `1`
- `light` -> `2`
- `standard` -> `2`

`satellite`
- `off` -> `1`
- `light` -> `2`
- `standard` -> `2~4` depending on bucket weight in automatic recommendation mode

`bond_cn`
- `off` -> `1`
- `standard` -> `2`

### 5.2 Weight-sensitive satellite count

For `satellite` in `standard` mode:

- `0.12 <= weight < 0.18` -> target `2`
- `0.18 <= weight < 0.28` -> target `3`
- `weight >= 0.28` -> target `4`

This table only applies to automatic recommendation mode.

### 5.3 User-requested count override

User-requested counts are not capped by the automatic recommendation table.

If the user explicitly requests:

- `主力 N 个`
- `卫星 M 个`
- `债券拆 K 个`

the system must treat those values as strong preferences even when they exceed automatic recommendation counts.

Examples:

- `主力 2 个，卫星 5 个`
- `卫星 6 个`
- `债券拆 2 个`

The system must then:

1. attempt to construct the requested count first
2. evaluate the requested structure as requested
3. emit feasibility diagnostics
4. produce one or more more-feasible alternatives only after the requested structure has been evaluated

Automatic recommendation caps therefore govern:

- system-generated initial portfolios

but do not govern:

- user-requested portfolio count preferences

### 5.4 Count-resolution precedence

Bucket count resolution must follow this precedence:

1. explicit user request
2. persisted user preference from prior confirmed session
3. system automatic count policy

Recommended representation:

```python
@dataclass(frozen=True)
class BucketCountResolution:
    bucket: str
    requested_count: int | None
    resolved_count: int
    source: str                  # explicit_user / persisted_user / auto_policy
    fully_satisfied: bool
    unmet_reasons: list[str]
    alternative_counts_considered: list[int]
```

### 5.5 Minimum position sizes

To avoid meaningless micro-positions:

- `equity_cn` product minimum weight: `5%`
- `satellite` product minimum weight: `2%`
- `bond_cn` product minimum weight: `5%`

If requested count implies weights below those thresholds:

1. still evaluate the user-requested structure if it is explicitly user-specified
2. attach a `count_preference_not_fully_satisfied` diagnostic
3. produce a more feasible alternative structure in parallel

### 5.6 Count-feasibility diagnostics

When the resolved or requested count cannot be cleanly supported, the system must expose explicit reasons rather than silently reducing the count.

Allowed reasons include:

- `insufficient_eligible_candidates`
- `minimum_weight_breach`
- `duplicate_exposure_too_high`
- `insufficient_diversification_gain`
- `formal_path_coverage_insufficient`
- `estimated_only_member_required`

These reasons must be available both in the execution layer and in the user-visible explanation surface.

## 6. Candidate Relationship Model

The system must not define diversification from names alone.

### 6.1 Relationship types

Inside a bucket, products may be related as:

- `substitute`
- `diversifier`
- `defensive_offset`
- `style_offset`
- `theme_offset`
- `duplicate_exposure`

### 6.2 Industry-prior matrix

The system should start from industry priors rather than discovering all relations from scratch.

Domestic default priors:

`equity_cn`
- `broad_market <-> dividend_value`: strong diversification prior
- `broad_market <-> low_vol`: strong diversification prior
- `dividend_value <-> low_vol`: weak diversification prior
- same-index different wrapper: substitute prior

`satellite`
- domestic tech theme <-> domestic cyclical theme: strong diversification prior
- chip <-> robotics: duplicate or weak-diversification prior
- same-theme different wrapper: substitute prior

`bond_cn`
- gov_duration <-> short_credit_carry: medium diversification prior

### 6.3 Statistical validation

The prior must then be validated by observed behavior. Recommended features:

- 1-year daily linear correlation
- downside correlation on negative market days
- drawdown overlap score
- diversification gain score

Recommended compatibility score:

```text
hedge_compatibility_score =
0.55 * prior_relation_score
+ 0.15 * (1 - linear_corr)
+ 0.15 * (1 - downside_corr)
+ 0.15 * diversification_gain_score
```

The score is used to rank valid diversification candidates. It must not create relations between products with no prior relationship family.

### 6.4 Modeling boundary

The candidate relationship model is a construction-time and explanation-time layer only.

It may be used for:

- intra-bucket subset construction
- overlap filtering
- diversification ranking
- product explanation
- product-group explanation

It may not be used for:

- direct return uplift or haircut inside `primary`
- direct success probability adjustment inside `primary`, `historical_replay`, or deteriorated scenarios
- any extra path-generation factor added on top of the `v1.4` probability engine

The `v1.4` probability engine remains the single source of truth for path generation, dependence, volatility, jump, and market-state evolution.

## 7. Intra-Bucket Construction

### 7.1 `equity_cn`

`equity_cn` should be built as:

- one main equity leg
- optionally one supporting diversifier leg

It should not blindly include all available equity variants.

Construction logic:

1. choose a main product from valid `equity_cn` candidates
2. find one or more compatible diversifier candidates
3. reject candidates with high duplication and low diversification gain
4. stop when count target is met or feasible candidate set is exhausted

### 7.2 `satellite`

`satellite` is not a fixed pair. It is a small subset construction problem.

Allowed structure:

- 1 product when off
- 2 products when light
- 2 to 4 products when standard in automatic recommendation mode
- user-requested count may exceed 4 when the user explicitly asks for it

Construction logic:

1. define candidate pool from domestic satellite products only
2. classify them by subtype and theme family
3. generate subsets within the target size band
4. score each subset on:
   - expected contribution
   - overlap penalty
   - diversification gain
   - count-feasibility
   - minimum position feasibility
5. if multiple subsets are close, prefer the subset that:
   - avoids duplicate exposure
   - preserves clearer role separation
   - has higher formal-path coverage quality
6. choose the best-scoring subset

This must support cases where the user wants multiple policy-sensitive or event-driven satellite themes at once.

### 7.4 Requested-vs-suggested structure handling

For `equity_cn`, `satellite`, and `bond_cn`, the system must distinguish between:

- `requested_structure`
- `suggested_structure`

If the user explicitly requests a higher count than the automatic policy would choose:

1. the requested structure must be built and evaluated first
2. the requested structure may still be flagged as low-quality or partially infeasible
3. the system must then generate a suggested structure that improves feasibility or diversification
4. both structures must remain visible

The suggested structure must never overwrite the requested structure in storage or in the primary evaluation payload.

### 7.3 `bond_cn`

Bond splitting remains coarse.

When enabled, the construction is:

- one duration-defense leg
- one short-credit or short-duration carry leg

No finer segmentation is introduced in this design.

## 8. User-Specified Portfolio Evaluation Mode

### 8.1 Evaluation principle

When the user enters a portfolio:

- compute the portfolio as entered
- do not silently normalize it into the system's preferred structure
- produce diagnostics and suggested alternatives separately

### 8.2 Unknown products

Unknown products must be surfaced first as:

- `unrecognized_product`

The system must then wait for user direction:

- provide a better identifier
- select a proxy
- exclude the product
- accept a non-formal estimate path

If the user does not resolve the unknown product, the system may not silently remap it.

### 8.3 Formal behavior with unknown products

If unresolved unknown products remain:

- do not emit a strict formal result
- emit diagnostic-only or degraded guidance depending on recognized coverage

### 8.4 Unknown-product resolution workflow

Unknown-product handling must behave as an explicit resolution state machine.

Recommended states:

- `recognized`
- `unrecognized_requires_user_action`
- `user_selected_proxy`
- `user_excluded_product`
- `estimated_non_formal_allowed`
- `resolved_formal_ready`

Recommended transitions:

1. product ingest
   - if recognized -> `recognized`
   - else -> `unrecognized_requires_user_action`
2. user action
   - if user provides better identifier and recognition succeeds -> `resolved_formal_ready`
   - if user selects a proxy -> `user_selected_proxy`
   - if user excludes the product -> `user_excluded_product`
   - if user permits non-formal estimate -> `estimated_non_formal_allowed`
3. run gating
   - `recognized` and `resolved_formal_ready` may continue through formal flow
   - `user_selected_proxy` may continue only under the selected proxy policy
   - `user_excluded_product` continues with the remaining portfolio
   - `estimated_non_formal_allowed` may not emit strict formal output
   - `unrecognized_requires_user_action` blocks strict formal output

### 8.5 Persistence requirements for unknown products

The system must persist unresolved-product context so the user can return without losing the pending decision.

Persisted fields must include:

- raw entered identifier
- tentative product name if provided
- current resolution state
- allowed next actions
- chosen proxy if one exists
- whether a formal run is currently blocked

The evaluation flow must resume from the persisted unresolved state rather than silently dropping the product.

## 9. Per-Product Explanation Surface

Each product must expose:

1. `product_result_summary`
   - current-market annualized range
   - historical-replay annualized range
   - mild-deterioration annualized range
   - moderate-deterioration annualized range
   - severe-deterioration annualized range
   - current-market terminal value range
   - historical-replay terminal value range
   - mild-deterioration terminal value range
   - moderate-deterioration terminal value range
   - severe-deterioration terminal value range

2. `role_in_portfolio`
   - `main_growth`
   - `defensive_buffer`
   - `style_offset`
   - `event_satellite`
   - `liquidity_management`

3. `marginal_contribution`
   - success probability delta if removed
   - terminal value mean delta if removed
   - max drawdown delta if removed
   - annualized return median delta if removed

4. `relationship_summary`
   - highest-overlap peers
   - highest-diversification peers

5. `quality_labels`
   - `high_expected_return`
   - `defensive`
   - `high_beta`
   - `duplicate_exposure`
   - `limited_contribution`
   - `replaceable`

6. `suggested_action`
   - `keep`
   - `reduce`
   - `replace`
   - `keep_as_hedge_leg`
   - `only_for_aggressive_goal`

The system must use factual output language, not persuasive marketing language.

### 9.1 Scenario ladder alignment

Per-product explanation must align exactly with the `v1.4` scenario ladder. It may not collapse the deterioration ladder into one generic stress bucket.

Required scenario keys:

- `historical_replay`
- `current_market`
- `deteriorated_mild`
- `deteriorated_moderate`
- `deteriorated_severe`

If any product-level explanation is missing one of those scenarios, the explanation surface is incomplete.

### 9.2 Product-level output contract

Recommended extension:

```python
@dataclass(frozen=True)
class ProductScenarioMetrics:
    scenario_kind: str
    annualized_range: tuple[float, float] | None
    terminal_value_range: tuple[float, float] | None
    pressure_score: float | None
    pressure_level: str | None
```

```python
@dataclass(frozen=True)
class ProductExplanation:
    product_id: str
    role_in_portfolio: str
    scenario_metrics: list[ProductScenarioMetrics]
    success_delta_if_removed: float | None
    terminal_mean_delta_if_removed: float | None
    drawdown_delta_if_removed: float | None
    median_return_delta_if_removed: float | None
    highest_overlap_product_ids: list[str]
    highest_diversification_product_ids: list[str]
    quality_labels: list[str]
    suggested_action: str | None
```

## 10. Per-Group Explanation Surface

The system must support group-level leave-out analysis for:

- `duplicate_exposure_group`
- `limited_contribution_group`
- `user_selected_group`

### 10.1 Comparison rule

Default group leave-out behavior:

- remove the product or group
- redistribute the freed weight pro rata across the remaining products
- recompute the portfolio outcome

This same rule applies to single-product leave-one-out.

### 10.2 Group diagnostics

For each group:

- removed members
- why the group was formed
- success probability delta
- terminal value mean delta
- max drawdown delta
- annualized median return delta

## 11. Output Additions

Recommended new contracts:

```python
@dataclass(frozen=True)
class ProductExplanation:
    product_id: str
    role_in_portfolio: str
    current_market_cagr_range: tuple[float, float] | None
    historical_replay_cagr_range: tuple[float, float] | None
    deteriorated_market_cagr_range: tuple[float, float] | None
    current_market_terminal_range: tuple[float, float] | None
    success_delta_if_removed: float | None
    terminal_mean_delta_if_removed: float | None
    drawdown_delta_if_removed: float | None
    median_return_delta_if_removed: float | None
    highest_overlap_product_ids: list[str]
    highest_diversification_product_ids: list[str]
    quality_labels: list[str]
    suggested_action: str | None
```

```python
@dataclass(frozen=True)
class ProductGroupExplanation:
    group_type: str
    product_ids: list[str]
    rationale: str
    success_delta_if_removed: float | None
    terminal_mean_delta_if_removed: float | None
    drawdown_delta_if_removed: float | None
    median_return_delta_if_removed: float | None
```

```python
@dataclass(frozen=True)
class BucketConstructionExplanation:
    bucket: str
    requested_count: int | None
    actual_count: int
    count_source: str
    count_satisfied: bool
    unmet_reason: str | None
    why_split: list[str]
    no_split_counterfactual: list[str]
    member_roles: dict[str, str]
```

## 12. Recommendation-Mode Fallback Behavior

When the user specifies bucket counts that are not cleanly feasible:

1. evaluate the requested structure first
2. flag violations such as:
   - count preference not fully satisfied
   - minimum position breached
   - duplicate exposure too high
   - insufficient eligible candidates
3. generate one or more alternative structures
4. present user-requested and system-suggested structures side by side

The system must not overwrite the user-requested structure and present the alternative as if it were the original request.

### 12.1 Requested-structure primary status

When the user explicitly requests counts such as `主力 2 个，卫星 5 个`, the requested structure must be treated as the primary result of the evaluation mode, even if it is not the system-preferred suggestion.

The suggested structure must be labeled as:

- `system_suggested_alternative`

and must never be labeled as the user's original portfolio.

## 13. What This Design Does Not Yet Include

- default overseas-aware construction
- UI wording polish
- final production thresholds for all bucket count bands

The unknown-product resolution state machine is included in this design. The later follow-up work is only the detailed proxy-selection UX.

Those belong to follow-up implementation and tuning passes.

## 14. Acceptance Criteria

This design is considered implemented when:

1. `equity_cn` and `satellite` can emit multi-product constructions in recommendation mode.
2. User count preferences such as `主力 2 个，卫星 5 个` are accepted as strong preferences.
3. User-entered portfolios are evaluated as entered.
4. Unknown products surface explicitly before any remapping.
5. Product-level explanation objects are emitted.
6. Group-level leave-out analysis is emitted.
7. Bucket construction explanations are emitted.
8. The system can show both:
   - requested structure result
   - system-suggested alternative result
9. Explicit user requests such as `主力 2 个，卫星 5 个` can exceed automatic recommendation count bands without being silently clipped.
10. Unknown products enter a persisted explicit resolution state instead of being silently mapped or dropped.
11. Product-level explanation uses the full five-scenario ladder instead of a single generic stress field.

## 15. Recommended Implementation Order

1. Add contracts for bucket cardinality preferences and explanation objects.
2. Refactor product construction from single-product-per-bucket to subset construction for `equity_cn` and `satellite`.
3. Add user-specified portfolio evaluation entry path.
4. Add unknown-product surfacing and diagnostic gating.
5. Add per-product and per-group explanation calculations.
6. Wire explanations into frontdesk and decision card surfaces.
