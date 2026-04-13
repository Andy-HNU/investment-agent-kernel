# Product Display And Expansion Delta Design

## Goal

Make user-facing product references readable and market-aligned, and make search-expansion behavior explicit when a requested expansion level fails to introduce any real new products.

This design is intentionally narrow. It does not change probability semantics, recommendation ranking, or bucket-construction policy. It only changes:
- how products are rendered to users
- how requested expansion levels report “no real product delta”

## Scope

In scope:
- Canonical user-facing product label model
- Frontdesk / decision card / execution summary / explanation surfaces using the same product display projection
- Explicit expansion result state when requested `L1/L2/L3` yields no new `product_id`

Out of scope:
- Probability engine changes
- Search auto-escalation to deeper levels
- New candidate ranking heuristics
- Product-universe expansion itself

## 1. Canonical User-Facing Product Display

### 1.1 Internal vs user-facing identity

`product_id` remains the internal stable key.
It must not be the default product label shown to end users.

User-facing surfaces must prefer:
- `product_name`
- `provider_symbol`
- `wrapper_type`

### 1.2 Canonical display object

Add a shared formatter that emits, for every product payload used in user-facing surfaces:

- `display_name`
- `display_code`
- `trading_venue_label`
- `display_label`

Frozen semantics:
- `display_name = product_name`
- `display_code = provider_symbol` when present, else `null`
- `trading_venue_label` maps from `wrapper_type`
- `display_label` is the compact rendered string for UI summaries

### 1.3 Wrapper-to-venue mapping

Frozen mapping for first version:
- `etf -> 场内ETF`
- `stock -> 场内股票`
- `fund -> 场外基金`
- `cash_mgmt -> 场外现金管理`
- `bond -> 债券产品`
- `other -> 其他产品`

### 1.4 Label rendering rules

Preferred rendering:
- if both `display_name` and `display_code` exist:
  - `display_label = "{display_name} ({display_code}, {trading_venue_label})"`
- if code missing but name exists:
  - `display_label = "{display_name} ({trading_venue_label})"`
- if name missing but code exists:
  - `display_label = "{display_code} ({trading_venue_label})"`
- internal `product_id` is only retained in machine-readable payloads

### 1.5 Required surfaces

This projection must be applied consistently to:
- execution plan items
- selected-product summaries
- recommendation-expansion alternatives
- product explanations
- product-group explanations where product references are present
- decision card product contribution rows
- frontdesk summary payloads that expose recommended products

## 2. Search Expansion Delta Semantics

### 2.1 Current problem

The system already supports `L0_compact -> L1_expanded -> L2_diversified -> L3_exhaustive`, but a requested deeper level may complete without introducing any new `product_id`.

That state must be explicit. It must not be presented as though the user successfully received a materially expanded recommendation.

### 2.2 Frozen rule

When the user requests a deeper expansion level:
- if the requested level introduces at least one new `product_id`, keep current delta behavior
- if the requested level introduces zero new `product_id` and removes zero existing `product_id`, return an explicit no-delta result

### 2.3 Canonical no-delta reason

Freeze the stop reason:
- `no_new_products_found_at_requested_level`

This reason is distinct from existing stop reasons such as level limits or candidate supply exhaustion.

### 2.4 No-delta payload contract

When no real delta exists, the expansion payload must include:
- `requested_search_expansion_level`
- `why_this_level_was_run`
- `why_search_stopped = "no_new_products_found_at_requested_level"`
- `new_product_ids_added = []`
- `products_removed = []`
- `expanded_alternatives = []` or alternatives only if they differ in a user-visible way beyond product identity

Default rule for v1:
- if no product delta exists, do not expose a same-allocation expanded alternative as a meaningful expanded alternative
- keep alternatives empty

### 2.5 User-facing explanation

When the no-delta state occurs, user-facing surfaces must say the requested level did not discover any new feasible products.

Frozen explanation intent:
- “本层扩容没有找到新的可行产品”

The UI may phrase this differently, but the fact must be explicit.

### 2.6 No auto-escalation

The system must not automatically continue to `L2/L3` when `L1` produces no real delta.

Frozen rule:
- stop at the requested level
- expose the no-delta result
- only search deeper if the user explicitly asks again

## 3. Display And Expansion Interaction

The no-delta result and expanded alternatives must use the same canonical product display projection from Section 1.

If an expanded alternative is shown, all product references in that alternative must include:
- market-facing name
- code when available
- venue label

## 4. Stock Wrapper Boundary

This design follows the already-frozen policy:
- default formal recommendation excludes `wrapper_type=stock`
- user-specified portfolio evaluation still allows recognized stock products

Accordingly:
- user-facing recommendation surfaces should not normally display stock-wrapper products in default recommended plans
- user portfolio evaluation surfaces may still display stock-wrapper labels using the same canonical formatter

## 5. Files To Touch

Expected implementation scope:
- `src/shared/` for the canonical product display formatter
- `src/shared/execution_plan_summary.py`
- `src/frontdesk/service.py`
- `src/decision_card/builder.py`
- `src/orchestrator/engine.py`
- tests covering execution summary, frontdesk, decision card, and search-expansion contracts

## 6. Acceptance Criteria

### 6.1 Product display
- User-facing recommendation outputs no longer default to raw internal `product_id`
- Product labels render as name + code + venue when available
- Frontdesk and decision card use the same rendered product labels

### 6.2 Expansion delta
- Requesting `L1/L2/L3` with zero real product delta returns `why_search_stopped = "no_new_products_found_at_requested_level"`
- No-delta expansion does not present a fake meaningful alternative
- The system does not auto-escalate beyond the requested level

### 6.3 Boundary preservation
- Default formal recommendation still excludes stock wrappers
- User-specified portfolio evaluation still allows recognized stock wrappers

