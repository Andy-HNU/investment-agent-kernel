# P1 升级拓扑与 Subagent 调度

日期：2026-03-31

目标：
- 把 `P1` 从“建议升级项”推进成可验收的产品增强
- 在不伪装 solver 能力的前提下，补齐分层画像、连续风险画像、目标现实语义和无可行方案文案
- 延续 `P0` 的 reviewer / tester 红线流程

## P1 清单

1. `P1-1` 用户画像从单层字段升级成分层 schema
2. `P1-2` 风险从三档标签升级成连续画像
3. `P1-3` 目标口径扩展到真实世界语义
4. `P1-4` 无可行方案前台表达硬化

## 拓扑总览

### 主链优先级

1. `P1-3` 目标现实语义 helper
2. `P1-1/P1-2` 分层画像与连续风险画像 helper
3. 主线程接线到 onboarding / frontdesk / defaults / CLI
4. `P1-4` 决策卡无可行方案文案硬化
5. contract + randomized acceptance
6. reviewer / tester 最终 signoff

### 依赖关系

- `P1-3` 与 `P1-1/P1-2` 可并行开发
- 主线程在两类 helper 都稳定后接主链
- `P1-4` 依赖新的目标语义披露字段
- acceptance tests 依赖主链接线完成后再补

## Subagent 分工

### Worker A: Profile Dimensions

职责：
- 新增分层画像 helper
- 产出 `goal / risk / cashflow / account / behavior` 五层 schema
- 给出 `risk_tolerance_score / risk_capacity_score / loss_limit / liquidity_need_level / goal_priority`

写集：
- `src/shared/profile_dimensions.py`
- `tests/contract/test_17_profile_dimensions_contract.py`

### Worker B: Goal Semantics

职责：
- 新增目标现实语义 helper
- 产出 `goal_amount_basis / goal_amount_scope / tax_assumption / fee_assumption / contribution_commitment_confidence`
- 明确哪些只是透明披露，哪些真正进入了现有 solver

写集：
- `src/shared/goal_semantics.py`
- `tests/contract/test_17_goal_semantics_contract.py`

### Worker C: Infeasible Copy

职责：
- 把 “no feasible allocation” 翻译成用户可读文案
- 明确“当前不存在满足你回撤约束的配置”
- 明确“下面是最接近可行的临时参考，不是正式推荐”

写集：
- `src/decision_card/builder.py`
- `tests/contract/test_09_product_feedback_regression.py`

### Main Thread

职责：
- 把 helper 接到 `onboarding / frontdesk / product defaults / CLI`
- 决定哪些 P1 字段进入 solver 输入，哪些只做透明披露
- 跑全量回归，处理 worker 之间的接线问题

主线程落点：
- `src/shared/onboarding.py`
- `src/frontdesk/service.py`
- `src/frontdesk/cli.py`
- `src/shared/product_defaults.py`
- `src/goal_solver/types.py`
- `tests/smoke/test_16_frontdesk_randomized_acceptance.py`

## 审阅与测试红线

### Review Agent

必须检查：
- `goal_amount_scope != total_assets` 时，系统是否诚实标记为 disclosure-only
- 连续风险画像是否真正影响约束或复杂度，而不是只存档
- 前台是否仍有含糊措辞，把收益/总资产混为一谈
- 无可行方案时是否还在把“最接近可行”伪装成正式推荐

### Testing Agent

必须检查：
- 新增 contract tests 是否覆盖五层画像 schema
- 是否有自然语言输入下的目标现实语义覆盖
- randomized acceptance 是否继续保持 `3x onboarding + 3x monthly + 3x full flow`
- 全量 `pytest` 是否通过

## 本次实际收口

本轮最终进入主链的关键变化：
- 新增 [profile_dimensions.py](/root/AndyFtp/investment_system_codex_ready_repo/src/shared/profile_dimensions.py)
  - 五层画像 schema
  - 连续风险画像
  - `goal_priority_from_dimensions / constraint_profile_from_dimensions / complexity_tolerance_from_dimensions`
- 新增 [goal_semantics.py](/root/AndyFtp/investment_system_codex_ready_repo/src/shared/goal_semantics.py)
  - 目标真实语义
  - disclosure-only 明示
- [onboarding.py](/root/AndyFtp/investment_system_codex_ready_repo/src/shared/onboarding.py)
  - 持久化 `goal_semantics / profile_dimensions`
  - `goal.priority` 和 `success_prob_threshold` 不再硬编码单值
- [product_defaults.py](/root/AndyFtp/investment_system_codex_ready_repo/src/shared/product_defaults.py)
  - 连续风险画像进入 `satellite_cap / liquidity_reserve_min / complexity_tolerance / ips boundaries`
- [service.py](/root/AndyFtp/investment_system_codex_ready_repo/src/frontdesk/service.py)
  - monthly / event / quarterly 继续携带 P1 画像
  - summary / snapshot 输出 `goal_semantics / profile_dimensions`
- [cli.py](/root/AndyFtp/investment_system_codex_ready_repo/src/frontdesk/cli.py)
  - 输出目标语义和画像模型摘要
  - onboarding 支持目标语义 flags
- [builder.py](/root/AndyFtp/investment_system_codex_ready_repo/src/decision_card/builder.py)
  - no-feasible 文案明确化
  - 候选方案 highlight 支持“最接近可行”

## 测试与验收

新增或扩展的测试：
- [test_17_goal_semantics_contract.py](/root/AndyFtp/investment_system_codex_ready_repo/tests/contract/test_17_goal_semantics_contract.py)
- [test_17_profile_dimensions_contract.py](/root/AndyFtp/investment_system_codex_ready_repo/tests/contract/test_17_profile_dimensions_contract.py)
- [test_09_product_feedback_regression.py](/root/AndyFtp/investment_system_codex_ready_repo/tests/contract/test_09_product_feedback_regression.py)
- [test_16_frontdesk_randomized_acceptance.py](/root/AndyFtp/investment_system_codex_ready_repo/tests/smoke/test_16_frontdesk_randomized_acceptance.py)

随机验收仍保持：
- onboarding 3 次
- monthly continuity 3 次
- full flow 3 次

覆盖点新增：
- `nominal / real`
- `total_assets / incremental_gain`
- `after_tax / pre_tax`
- `platform_fee_excluded / transaction_cost_only`
- 分层画像落库与前台可见性
- 长自然语言持仓/限制输入的真实链路回归
- CLI 文本输出中的 `goal_semantics / profile_model` 可见性

## 最终验证结果

- `python3 -m pytest -q` 全量通过
- P1 contract / smoke 子集通过
- P1 字段已进入 SQLite 快照和前台 summary
- 无可行方案文案已从内部 token 翻译为中文用户可见文案

## 当前边界说明

- `goal_amount_scope != total_assets`、`goal_amount_basis == real`、`tax_assumption == after_tax` 等语义当前是“透明披露 + 约束分层”，不是完全重新训练过的专用 solver
- 系统现在会明确说出这件事，不再把 disclosure-only 伪装成 fully-modeled
