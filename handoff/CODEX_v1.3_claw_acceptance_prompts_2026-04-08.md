# CODEX v1.3 Claw Acceptance Prompts

日期：2026-04-08

目的：

- 固化 `v1.3` 的 Claw 验收方式，避免重复命中错误测试路径
- 明确当前版本下 `static_gaussian` 不能作为 formal / Claw truth
- 明确 `snapshot-backed degraded / degraded formal / runtime auto path` 三类场景的最小 prompt 与预期结果
- 强制区分：
  - 完整 formal snapshot
  - 不完整 external snapshot
  - 纯 runtime 自动路径

## 使用原则

1. 每轮验收使用一个新的 Claw session
   - 避免旧上下文过长导致 LLM timeout

2. `formal success path` 不允许让 Claw 自己手写 snapshot JSON
   - 必须复用仓库 helper：
     - `/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-layer3/tests/support/formal_snapshot_helpers.py`

3. `formal success path` 的 external snapshot 必须包含：
   - `input_provenance.externally_fetched`
   - `external_snapshot_meta.domains`
   - `market_raw.product_universe_result`
   - `market_raw.product_valuation_result`
   - `market_raw.historical_dataset.product_simulation_input`
   - `product_simulation_input.products[*].data_status=observed`

4. 当前版本下，若 `selected_mode=static_gaussian`，不得把它验成：
   - `formal_independent_result`
   - `point_and_range`
   - `confidence_level=high`

## 当前状态修正

- `Gate 1` / `Gate 2` 已落地
- `Package 3` / `Package 4` 仍未闭环
- 当前主求解器若 `selected_mode=static_gaussian`：
  - 仅允许本地 test/demo 或 exploratory 使用
  - 不得作为 Claw formal success 通过标准
  - Claw / OpenClaw 路径必须显式降级

## 场景 A：Snapshot-Backed Formal Guard

目标：

- 验证完整 external formal snapshot 不再被 runtime 自动抓取覆盖
- 验证当主求解器仍选到 `static_gaussian` 时，formal / Claw 路径会显式降级，而不是冒充 formal success

### Prompt

```text
不要手写 snapshot JSON。只做 v1.3 formal success path 集成验证，不改代码。

worktree=/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-layer3

先用 python3 复用仓库里的 helper 生成完整 formal snapshot 文件，再用这个文件跑 onboarding。
必须使用这个 helper：
/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-layer3/tests/support/formal_snapshot_helpers.py

要求：
1. 用 helper 里的 `write_formal_snapshot_source(...)` 生成 snapshot 文件
2. profile 使用：
- account_profile_id=andy_v13_formal_success
- display_name=Andy
- current_total_assets=18000
- monthly_contribution=2500
- goal_amount=124203.16
- goal_horizon_months=36
- risk_preference=中等
- max_drawdown_tolerance=0.20
- current_holdings=现金12000，黄金6000
- restrictions=[不买个股, 不碰科技, 不碰高风险产品]
3. 生成完成后，拿这个 external_snapshot_source 跑 onboarding
4. 不允许只走 runtime tinyshare 自动路径
5. 全程用 python3，不要用 python

只输出：
- head_short
- branch
- generated_snapshot_path
- status
- run_outcome_status
- resolved_result_category
- disclosure_level
- confidence_level
- formal_path_visibility_status
- product_probability_method
- used_runtime_as_primary=true/false
- reproduced_formal_independent_with_degraded_visibility=true/false
```

### 通过标准

- `status=completed`
- `run_outcome_status=degraded`
- `resolved_result_category=degraded_formal_result`
- `disclosure_level=range_only`
- `confidence_level=low`
- `formal_path_visibility_status=degraded`
- `used_runtime_as_primary=false`
- `reproduced_formal_independent_with_degraded_visibility=false`
- `evidence_bundle.degradation_reasons` 含 `static_gaussian`

## 场景 B：Degraded Formal Path

目标：

- 验证 `execution_policy=formal_estimation_allowed` 下，非完整 formal 证据会稳定降为 `degraded_formal_result`
- 验证不会错误给出 `formal_independent_result + point_and_range`

### Prompt

```text
只做 v1.3 场景B，不改代码。
worktree=/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-layer3

先输出：
- head_short
- branch

要求：
- execution_policy=formal_estimation_allowed
- 构造 partial / prior_default / 非完整 formal 证据
- 不要求 blocked
- 目标是验证会不会降成 degraded_formal_result

只输出这些字段：
- status
- run_outcome_status
- resolved_result_category
- disclosure_level
- confidence_level
- formal_path_visibility_status
- failure_artifact_present=true/false
- still_wrongly_formal_independent_with_point_and_range=true/false
- expected_category_under_current_policy
```

### 通过标准

- `status=completed`
- `run_outcome_status=degraded`
- `resolved_result_category=degraded_formal_result`
- `disclosure_level=range_only`
- `confidence_level=low`
- `formal_path_visibility_status=degraded`
- `failure_artifact_present=false`
- `still_wrongly_formal_independent_with_point_and_range=false`
- `expected_category_under_current_policy=degraded_formal_result`

## 场景 C：Runtime Auto Path Regression

目标：

- 验证不提供 external formal snapshot 时，runtime tinyshare 自动路径仍可正常工作
- 验证它没有被误判成 snapshot-primary

### Prompt

```text
只做 v1.3 runtime 自动路径回归，不改代码。
worktree=/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-layer3

要求：
- 不提供 external formal snapshot
- 只走 runtime tinyshare 自动路径

只输出：
- status
- run_outcome_status
- resolved_result_category
- product_universe_audit_summary.requested
- product_universe_audit_summary.source_status
- valuation_audit_summary.requested
- valuation_audit_summary.source_status
- pending_execution_plan_present=true/false
- was_misclassified_as_snapshot_primary=true/false
```

### 通过标准

- `product_universe_audit_summary.requested=true`
- `product_universe_audit_summary.source_status=observed`
- `valuation_audit_summary.requested=true`
- `valuation_audit_summary.source_status=observed`
- `pending_execution_plan_present=true`
- `was_misclassified_as_snapshot_primary=false`

## 结果解释

### A 通过、B 通过、C 通过

表示：

- `snapshot-primary formal path` 已修好
- `degraded formal` 语义已修好
- runtime 自动路径未被误伤
- `static_gaussian` 已被挡在 formal / Claw truth 之外

### A 不通过，但 B/C 通过

优先判断：

- 是否没有复用 helper 生成 snapshot
- 是否手写 snapshot 时缺少：
  - `input_provenance.externally_fetched`
  - `external_snapshot_meta.domains`
  - `product_simulation_input.products[*].data_status=observed`

此时更可能是测试构造问题，不是主链 bug。

### B 不通过

优先判断：

- 是否又出现 `formal_independent_result + point_and_range`
- 是否 `formal_estimation_allowed` 下错误走成 `blocked/unavailable`

### C 不通过

优先判断：

- runtime 路径是否被误标为 `snapshot_primary_formal_path`
- `product_universe_result / valuation_result` 是否没有自动补齐

## 当前已验证结论

截至当前版本：

- helper 生成的完整 snapshot 不再被 runtime 自动路径污染
- `degraded formal path` 稳定落成 `degraded_formal_result`
- runtime 自动路径未被误判成 snapshot-primary
- `static_gaussian` 不再允许被 Claw 验成 formal success
