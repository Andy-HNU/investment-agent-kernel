# Tool Contracts

## Workflow Surface

### `onboard`
- input:
  - `profile-json` 或 interactive profile
  - 可选 `external_snapshot_source` / `external_data_config`
- output:
  - `decision_card`
  - `candidate_options`
  - `goal_alternatives`
  - `pending_execution_plan`
  - provenance / refresh summary

### `monthly`
- input:
  - `account_profile_id`
  - 可选账户快照类 profile 更新
  - 可选 external provider config
- output:
  - `decision_card`
  - `execution_plan_comparison`
  - 若生成新计划，则 `pending_execution_plan`

### `event`
- input:
  - `account_profile_id`
  - `event_context`
- output:
  - runtime action decision card
  - optional pending execution plan

### `quarterly`
- input:
  - `account_profile_id`
  - 可接受更完整 profile refresh
- output:
  - goal + runtime joint review
  - updated baseline
  - optional pending execution plan

### `approve-plan`
- input:
  - `account_profile_id`
  - `plan_id`
  - `plan_version`
- output:
  - `approved_execution_plan`
  - active/pending plan state after promotion

### `feedback`
- input:
  - `account_profile_id`
  - `source_run_id`
  - execution confirmation fields
- output:
  - latest execution feedback state

## External Data Contract

- supported adapters:
  - `http_json`
  - `inline_snapshot`
  - `local_json`
- domain payloads:
  - `market_raw`
  - `account_raw`
  - `behavior_raw`
  - `live_portfolio`

## Historical / Policy Sidecar Contract

- historical data enters as `market_raw.historical_dataset`
- policy/news enters as `policy_news_signals`
- accepted structured fields:
  - `policy_regime`
  - `macro_uncertainty`
  - `sentiment_stress`
  - `liquidity_stress`
  - `manual_review_required`

## Failure Contract

- fail-open provider path must preserve warning + fallback provenance
- fail-closed provider path may raise explicit adapter error
- blocked/degraded outputs must still be serializable and auditable
