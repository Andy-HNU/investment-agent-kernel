# Product Display And Expansion Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw internal product ids with market-facing product labels across user-facing surfaces, and make requested search-expansion levels explicitly report when they produce no real new products.

**Architecture:** Add a shared product-display formatter in `src/shared`, thread its projection through execution summary, decision card, and frontdesk surfaces, and tighten orchestrator search-expansion payloads so zero-delta requests return a canonical no-delta reason with no fake alternatives. Keep probability semantics unchanged and preserve the existing boundary where stock wrappers remain allowed in user-specified portfolio evaluation but excluded from formal recommendation.

**Tech Stack:** Python, pytest, existing frontdesk/orchestrator/product-mapping pipeline

---

## File Map

- Create: `src/shared/product_display.py`
- Modify: `src/shared/execution_plan_summary.py`
- Modify: `src/orchestrator/engine.py`
- Modify: `src/frontdesk/service.py`
- Modify: `src/decision_card/builder.py`
- Modify: `tests/contract/test_09_decision_card_contract.py`
- Modify: `tests/contract/test_12_frontdesk_regression.py`
- Modify: `tests/contract/test_46_search_expansion_selection_contract.py`

### Task 1: Add Canonical Product Display Formatter

**Files:**
- Create: `src/shared/product_display.py`
- Test: `tests/contract/test_09_decision_card_contract.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/contract/test_09_decision_card_contract.py`:

```python
def test_product_display_label_uses_name_code_and_venue() -> None:
    from shared.product_display import build_product_display

    payload = build_product_display(
        {
            "product_name": "沪深300ETF",
            "provider_symbol": "510300",
            "wrapper_type": "etf",
        }
    )

    assert payload["display_name"] == "沪深300ETF"
    assert payload["display_code"] == "510300"
    assert payload["trading_venue_label"] == "场内ETF"
    assert payload["display_label"] == "沪深300ETF (510300, 场内ETF)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -k product_display_label_uses_name_code_and_venue -q`
Expected: FAIL with `ModuleNotFoundError` or missing function import.

- [ ] **Step 3: Write minimal implementation**

Create `src/shared/product_display.py` with this implementation:

```python
from __future__ import annotations

from typing import Any

_WRAPPER_TO_VENUE = {
    "etf": "场内ETF",
    "stock": "场内股票",
    "fund": "场外基金",
    "cash_mgmt": "场外现金管理",
    "bond": "债券产品",
    "other": "其他产品",
}


def build_product_display(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    display_name = str(data.get("product_name") or "").strip() or None
    display_code = str(data.get("provider_symbol") or "").strip() or None
    wrapper_type = str(data.get("wrapper_type") or "other").strip() or "other"
    trading_venue_label = _WRAPPER_TO_VENUE.get(wrapper_type, "其他产品")

    if display_name and display_code:
        display_label = f"{display_name} ({display_code}, {trading_venue_label})"
    elif display_name:
        display_label = f"{display_name} ({trading_venue_label})"
    elif display_code:
        display_label = f"{display_code} ({trading_venue_label})"
    else:
        display_label = trading_venue_label

    return {
        "display_name": display_name,
        "display_code": display_code,
        "trading_venue_label": trading_venue_label,
        "display_label": display_label,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -k product_display_label_uses_name_code_and_venue -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shared/product_display.py tests/contract/test_09_decision_card_contract.py
git commit -m "feat: add canonical product display formatter"
```

### Task 2: Thread Product Display Through User-Facing Summaries

**Files:**
- Modify: `src/shared/execution_plan_summary.py`
- Modify: `src/decision_card/builder.py`
- Modify: `src/frontdesk/service.py`
- Test: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing decision-card and frontdesk tests**

Add this test to `tests/contract/test_09_decision_card_contract.py`:

```python
def test_decision_card_product_contributions_prefer_market_facing_labels() -> None:
    from decision_card.builder import build_decision_card
    from decision_card.types import DecisionCardBuildInput

    card = build_decision_card(
        DecisionCardBuildInput(
            execution_plan_summary={
                "items": [
                    {
                        "primary_product_id": "cn_equity_csi300_etf",
                        "primary_product_name": "沪深300ETF",
                        "primary_product": {
                            "product_id": "cn_equity_csi300_etf",
                            "product_name": "沪深300ETF",
                            "provider_symbol": "510300",
                            "wrapper_type": "etf",
                        },
                        "target_weight": 0.6,
                    }
                ]
            }
        )
    )

    contribution = card["product_contributions"][0]
    assert contribution["product_label"] == "沪深300ETF (510300, 场内ETF)"
```

Add this test to `tests/contract/test_12_frontdesk_regression.py`:

```python
def test_frontdesk_summary_uses_market_facing_product_labels_for_pending_items() -> None:
    from frontdesk.service import _build_summary

    summary = _build_summary(
        {
            "pending_execution_plan": {
                "items": [
                    {
                        "primary_product_id": "cn_equity_dividend_etf",
                        "primary_product": {
                            "product_id": "cn_equity_dividend_etf",
                            "product_name": "红利ETF",
                            "provider_symbol": "510880",
                            "wrapper_type": "etf",
                        },
                    }
                ]
            }
        }
    )

    assert summary["pending_execution_plan"]["items"][0]["primary_product"]["display_label"] == "红利ETF (510880, 场内ETF)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -k market_facing_labels -q`
Expected: FAIL because `product_label` is missing or still uses raw ids.

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -k market_facing_product_labels -q`
Expected: FAIL because `display_label` is not present in summary payload.

- [ ] **Step 3: Write minimal implementation**

In `src/shared/execution_plan_summary.py`, add a helper that projects nested product payloads through `build_product_display`:

```python
from shared.product_display import build_product_display


def _attach_product_display(product: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(product or {})
    payload.update(build_product_display(payload))
    return payload
```

Apply the same projection to:
- execution-plan item `primary_product`
- recommendation-expansion alternatives where product payloads are surfaced

In `src/decision_card/builder.py`, change product contribution rows to emit:

```python
product_payload = dict(item.get("primary_product") or {})
product_payload.update(build_product_display(product_payload))

rendered.append(
    {
        "product_id": str(product_id),
        "product_name": product_payload.get("display_name") or _metric(item.get("primary_product_name")) or "",
        "product_label": product_payload.get("display_label") or _metric(item.get("primary_product_name")) or "",
    }
)
```

In `src/frontdesk/service.py`, when serializing `pending_execution_plan.items`, ensure each nested `primary_product` payload gets:

```python
product_payload = dict(item.get("primary_product") or {})
if product_payload:
    product_payload.update(build_product_display(product_payload))
    rendered_item["primary_product"] = product_payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py -k market_facing_labels -q`
Expected: PASS

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -k market_facing_product_labels -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shared/execution_plan_summary.py src/decision_card/builder.py src/frontdesk/service.py tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py
git commit -m "feat: surface market-facing product labels"
```

### Task 3: Emit Explicit No-Delta Expansion Result

**Files:**
- Modify: `src/orchestrator/engine.py`
- Modify: `src/shared/execution_plan_summary.py`
- Test: `tests/contract/test_46_search_expansion_selection_contract.py`
- Test: `tests/contract/test_12_frontdesk_regression.py`

- [ ] **Step 1: Write the failing tests**

Add this test to `tests/contract/test_46_search_expansion_selection_contract.py`:

```python
def test_requested_expansion_without_product_delta_uses_no_delta_stop_reason() -> None:
    from orchestrator.engine import _search_expansion_delta

    compact_context = {"selected_product_ids": ["eq_a", "bond_a"]}
    expanded_context = {"selected_product_ids": ["eq_a", "bond_a"]}

    new_ids, removed_ids = _search_expansion_delta(compact_context, expanded_context)

    assert new_ids == []
    assert removed_ids == []
```

Add this contract in the same file:

```python
def test_recommendation_expansion_view_omits_fake_alternatives_when_no_product_delta() -> None:
    from shared.execution_plan_summary import build_recommendation_expansion_view

    view = build_recommendation_expansion_view(
        {
            "search_expansion_level": "L0_compact",
            "recommendation_expansion": {
                "requested_search_expansion_level": "L1_expanded",
                "why_this_level_was_run": "user_requested_deeper_search",
                "why_search_stopped": "no_new_products_found_at_requested_level",
                "new_product_ids_added": [],
                "products_removed": [],
                "expanded_alternatives": [],
            },
        }
    )

    assert view["why_search_stopped"] == "no_new_products_found_at_requested_level"
    assert view["alternatives"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/contract/test_46_search_expansion_selection_contract.py -k "no_delta_stop_reason or fake_alternatives" -q`
Expected: FAIL because the existing stop reason stays at level-limit semantics or still carries same-allocation alternatives.

- [ ] **Step 3: Write minimal implementation**

In `src/orchestrator/engine.py`, tighten the no-delta branch:

```python
new_product_ids_added, products_removed = _search_expansion_delta(compact_context, expanded_context)
has_product_delta = bool(new_product_ids_added or products_removed)

why_search_stopped = (
    "level_limit_requested_search_expansion_reached"
    if has_product_delta
    else "no_new_products_found_at_requested_level"
)

expanded_alternatives = [] if not has_product_delta else expanded_alternatives
```

In `src/shared/execution_plan_summary.py`, preserve the no-delta payload exactly and avoid fabricating alternatives:

```python
if why_search_stopped == "no_new_products_found_at_requested_level":
    alternatives = []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/contract/test_46_search_expansion_selection_contract.py -k "no_delta_stop_reason or fake_alternatives" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/engine.py src/shared/execution_plan_summary.py tests/contract/test_46_search_expansion_selection_contract.py
git commit -m "feat: expose no-delta search expansion result"
```

### Task 4: Full Regression And Surface Validation

**Files:**
- Modify: `tests/contract/test_12_frontdesk_regression.py`
- Modify: `tests/contract/test_09_decision_card_contract.py`
- Test: `tests/integration/test_v14_probability_engine_integration.py`

- [ ] **Step 1: Add final regression assertions**

Extend `tests/contract/test_12_frontdesk_regression.py` with a regression that checks no-delta requested expansion is visible in frontdesk summary:

```python
def test_frontdesk_surfaces_requested_expansion_without_product_delta() -> None:
    from frontdesk.service import _build_summary

    summary = _build_summary(
        {
            "execution_plan_summary": {
                "search_expansion_level": "L0_compact",
                "recommendation_expansion": {
                    "requested_search_expansion_level": "L1_expanded",
                    "why_this_level_was_run": "user_requested_deeper_search",
                    "why_search_stopped": "no_new_products_found_at_requested_level",
                    "new_product_ids_added": [],
                    "products_removed": [],
                    "expanded_alternatives": [],
                },
            }
        }
    )

    assert summary["recommendation_expansion_view"]["why_search_stopped"] == "no_new_products_found_at_requested_level"
    assert summary["recommendation_expansion_view"]["alternatives"] == []
```

- [ ] **Step 2: Run targeted regression to verify it fails**

Run: `python3 -m pytest tests/contract/test_12_frontdesk_regression.py -k no_new_products_found_at_requested_level -q`
Expected: FAIL before the frontdesk projection is fully threaded.

- [ ] **Step 3: Finish minimal integration wiring**

If the previous tasks were implemented correctly, only small glue should remain. Ensure:

```python
recommendation_expansion_view = build_recommendation_expansion_view(decision_card_execution_summary)
if recommendation_expansion_view:
    summary["recommendation_expansion_view"] = deepcopy(recommendation_expansion_view)
```

and that the same view is preserved in both frontdesk and decision-card surfaces.

- [ ] **Step 4: Run verification suite**

Run: `python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py tests/contract/test_46_search_expansion_selection_contract.py tests/integration/test_v14_probability_engine_integration.py -q`
Expected: PASS

Run: `git -C /root/AndyFtp/investment_system_codex_ready_repo diff --check`
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_09_decision_card_contract.py tests/contract/test_12_frontdesk_regression.py tests/contract/test_46_search_expansion_selection_contract.py src/frontdesk/service.py src/decision_card/builder.py src/shared/execution_plan_summary.py src/orchestrator/engine.py
git commit -m "feat: finalize product display and expansion delta surfaces"
```

## Self-Review

- Spec coverage: Task 1 covers canonical product display object; Task 2 covers required surfaces; Task 3 covers the no-delta stop reason and no fake alternatives; Task 4 covers frontdesk/decision-card/integration regression and boundary preservation.
- Placeholder scan: no `TODO`, `TBD`, or open-ended “add tests later” steps remain.
- Type consistency: the plan consistently uses `display_name`, `display_code`, `trading_venue_label`, `display_label`, and `no_new_products_found_at_requested_level`.
