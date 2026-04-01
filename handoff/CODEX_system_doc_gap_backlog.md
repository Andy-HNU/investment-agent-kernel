# CODEX System Doc Gap Backlog

更新日期: 2026-04-01

## 协作约定

- 继续使用 3 条子线:
  - `Developer`
  - `Reviewer`
  - `Tester`
- 子 agent 模型保持 `gpt-5.4` + `xhigh`
- 本文件只记录“`system/` 文档 vs 当前实现”的差异，不重复记录已通过测试的主干状态

## 总判断

当前系统已经具备阶段 1 的核心可执行闭环，但对照 `system/` 文档，仍有一批“已能跑但未完全按 v1 文档实现”的能力点。

结论上可以分成三层：

- `P0`：核心算法/治理语义还没按文档完全落地，值得先做
- `P1`：当前不阻塞主干，但会影响可解释性、可追踪性和回放质量
- `P2`：增强项和更深覆盖

## 模块差异矩阵

### 02 goal_solver

状态：`部分实现（Phase 1A goal-solver notes 已收口）`

文档锚点：
- [`system/02_goal_solver.md#L804`](/root/AndyFtp/investment_system_codex_ready_repo/system/02_goal_solver.md#L804)
- [`system/02_goal_solver.md#L164`](/root/AndyFtp/investment_system_codex_ready_repo/system/02_goal_solver.md#L164)
- [`system/02_goal_solver.md#L532`](/root/AndyFtp/investment_system_codex_ready_repo/system/02_goal_solver.md#L532)

当前已实现：
- typed input/output
- `CashFlowPlan` / `CashFlowEvent`
- `run_goal_solver(...)`
- `run_goal_solver_lightweight(...)`
- `theme_remaining_budget`
- `RiskBudget.drawdown_budget_used_pct`
- `RANKING_MODE_MATRIX`
- `infer_ranking_mode()`
- ranking-mode driven 排序
- no-feasible fallback
- `solver_notes`

仍缺：
- typed `GoalSolverParams.shrinkage_factor` 仍未恢复到正式文档口径；当前仅在 `solver_notes` 中诚实披露是否可得
- 更深的 `solver_notes` / 结果解释口径仍可继续增强，但本轮 Phase 1A 合同要求已覆盖

本轮收口：
- Monte Carlo context notes（`paths / seed / horizon_months`）
- Monte Carlo limitation note（补充 `shrinkage_factor` 可得性与 parametric/non-historical 限制）
- success-threshold gap notes（`threshold / recommended / gap / met`）
- recommended-feasibility note（推荐项可行性与 shortfall baseline）
- no-feasible dominant-constraint summary
- fallback pressure score note
- selected fallback context note（推荐兜底候选的主导违规原因与 score inputs）
- probability-model honesty notes
- goal semantics notes
- contribution-confidence not-yet-absorbed note

### 03 snapshot_ingestion

状态：`部分实现`

文档锚点：
- [`system/03_snapshot_and_ingestion.md#L511`](/root/AndyFtp/investment_system_codex_ready_repo/system/03_snapshot_and_ingestion.md#L511)

当前已实现：
- `SnapshotBundle`
- `bundle_id`
- 域内校验函数
- `bundle_quality`
- 基本跨域校验

仍缺：
- 五域原始快照的更完整 typed 定义
- `cashflow_events_raw` 四键结构校验
- 更完整的 quality flag 体系
- 更细的跨域一致性检查

### 05 calibration

状态：`大体实现（Round 3 已完成阶段 1 治理闭环）`

文档锚点：
- [`system/05_constraint_and_calibration_v1.1_patched.md#L706`](/root/AndyFtp/investment_system_codex_ready_repo/system/05_constraint_and_calibration_v1.1_patched.md#L706)

当前已实现：
- 5 个核心 canonical types
- `CalibrationResult`
- `run_calibration(...)`
- market / behavior / constraint 基本解释
- 向 02/04/10 输出对象
- `ParamVersionMeta`
- `update_goal_solver_params(...)`
- `update_runtime_optimizer_params(...)`
- `update_ev_params(...)`
- `previous_version_id / updated_reason / can_be_replayed / is_temporary`
- manual override / replay metadata
- prior behavior reuse
- degraded market prior reuse
- constraint conflict -> degraded + manual review
- 07 -> 05 的 `manual_override / replay_mode` 透传

仍缺：
- 更贴近文档的保守 market calibration
  - short-history uplift
  - shrinkage / volatility floor
  - 更正式的 correlation handling / PSD repair
- `version_id` 的“同时间戳多次更新唯一化”机制
- 更完整的 05-local degraded 推断与 notes 解释链

### 04 runtime_optimizer

状态：`部分实现`

文档锚点：
- [`system/04_runtime_optimizer_v2.2_patched.md#L1161`](/root/AndyFtp/investment_system_codex_ready_repo/system/04_runtime_optimizer_v2.2_patched.md#L1161)

当前已实现：
- typed outer result
- state builder
- candidate generation
- `run_runtime_optimizer(...)`
- mode routing
- `candidate_poverty`

仍缺：
- 更完整的候选动作规则族
- 更贴近文档的 amount 预填与裁剪细节
- 更系统的 cooldown / event / quarterly 差异规则

本轮收口：
- `ADD_DEFENSE` reserved for drawdown-event path
- runtime candidate-poverty protocol now patches EVReport to safe-action semantics
- EV feasibility now consumes calibrated cooldown state in addition to emotion flags
- quarterly drawdown path now filters `ADD_DEFENSE`, preserving event-only defensive injection semantics
- `ADD_DEFENSE` now selects defense target buckets dynamically, clips to actual deficit, and falls back to `sell_rebalance` when cash is insufficient
- `recommendation_reason` now explains when the winner beats the runner-up via lower penalties rather than the highest raw goal impact
- `confidence_reason` now distinguishes mixed safe-vs-active low-spread candidate sets instead of emitting only generic spread text

### 07 orchestrator

状态：`大体实现，Phase 1B 第一波已接入 execution plan`

文档锚点：
- [`system/07_orchestrator_workflows_v1.1_patched.md#L636`](/root/AndyFtp/investment_system_codex_ready_repo/system/07_orchestrator_workflows_v1.1_patched.md#L636)

当前已实现：
- 4 条 workflow
- blocked / degraded / escalated 归属
- version anchor 主要链路
- `card_build_input`
- `decision_card`
- `audit_record`
- 在存在 raw snapshot 时由 07 内部驱动 `03 -> 05`
- `OrchestratorPersistencePlan`
- `snapshot_bundle_origin / calibration_origin` 审计标记
- deterministic `execution_plan` artifact generation for onboarding / monthly / event / quarterly non-blocked paths
- execution-plan restrictions now consume onboarding provenance instead of silently dropping user constraints
- `card_build_input` / `decision_card` now receive `execution_plan_summary`
- persistence plan now carries versioned execution-plan artifact metadata for downstream sqlite/frontdesk consumption

仍缺：
- 持久化 / 审计落账的 file/json/sqlite 执行适配层
- 更深 replay / override / provenance 变体
- execution-plan approval / supersede / confirmation state transitions still remain at the frontdesk persistence layer, not yet a full orchestrator-managed state machine

### 08 allocation_engine

状态：`接近完成`

文档锚点：
- [`system/08_allocation_engine.md#L718`](/root/AndyFtp/investment_system_codex_ready_repo/system/08_allocation_engine.md#L718)

当前已实现：
- 输入输出结构
- 多模板家族
- bucket-level 生成
- projection / validator / complexity / dedup
- 08 -> 02 直连

仍缺：
- 更多模板族与诊断信息
- 更接近文档的候选多样性/解释度细节

### 09 decision_card

状态：`阶段 1 正式化已完成，Phase 1B 已接入 execution-plan 摘要`

文档锚点：
- [`system/09_decision_card_spec_v1.1_patched.md#L544`](/root/AndyFtp/investment_system_codex_ready_repo/system/09_decision_card_spec_v1.1_patched.md#L544)

当前已实现：
- 4 类正式卡片
- `DecisionCardBuildInput`
- `DecisionCard`
- blocked / degraded / observe / trace 主要规则
- `build_decision_card(...)` 单一正式入口
- `DecisionCardBuildInput.validate()`
- `evidence_highlights / review_conditions / next_steps / runner_up_action / low_confidence`
- `QUARTERLY_REVIEW` 双证据消费:
  - `GoalSolverOutput`
  - `RuntimeOptimizerResult`
- `execution_plan_summary` 已接入 goal-baseline / runtime-action / blocked / quarterly 卡片，前台可直接读取计划摘要
- 09 专属 direct contract:
  - formal input only
  - quarterly 缺输入报错
  - runtime 缺主动作报错
  - non-blocked 卡拒绝 `blocking_reasons`
  - quarterly 主动作仍为 `review`

仍缺：
- `low_confidence` 与 `blocked / degraded / escalated` 语义进一步拆分
- `review_conditions / next_steps` 继续保持 render convention，避免 09 吞 07 的控制责任
- 若后续进入更严格 typing，可考虑逐步收紧 `from_any / _obj` 的宽松容忍

### 10 ev_engine

状态：`部分实现（本轮已收掉一批 P0）`

文档锚点：
- [`system/10_ev_engine_v1.2_patched.md#L840`](/root/AndyFtp/investment_system_codex_ready_repo/system/10_ev_engine_v1.2_patched.md#L840)

当前已实现：
- `EVReport`
- `FeasibilityResult`
- `run_ev_engine(...)`
- `run_goal_solver_lightweight()` 调用链
- `recommended_score / confidence_flag / confidence_reason`
- `_validate_state / _validate_action`
- QDII / 资金 / cooldown / IPS / satellite 多原因 feasibility
- 五项分量拆分:
  - `compute_goal_impact`
  - `compute_risk_penalty`
  - `compute_soft_constraint_penalty`
  - `compute_behavior_penalty`
  - `compute_execution_penalty`
- `confidence_flag` 已开始消费分差阈值与低置信度覆盖条件
- `recommendation_reason` 已开始按分项语义生成

仍缺：
- 更正式的 FeasibilityFilter 全覆盖
- 更细的五项分量公式与量纲校准
- 推荐理由生成规则继续系统化
- 更深的 mixed-candidate smoke / regression

本轮收口：
- calibrated cooldown state participates in feasibility filtering
- low-confidence explanations now call out mixed safe/active candidate sets when spread is narrow
- recommendation reasons now disclose penalty-led wins when raw goal impact is not the highest

### 11 product_mapping / execution_planner

状态：`Phase 1B 第一波已完成正式接线`

文档锚点：
- [`system/11_product_mapping_and_execution_planner_v2.md#L1`](/root/AndyFtp/investment_system_codex_ready_repo/system/11_product_mapping_and_execution_planner_v2.md#L1)

当前已实现：
- `ProductCandidate`
- `ExecutionPlanItem`
- `ExecutionPlan`
- builtin catalog for:
  - `equity_cn`
  - `bond_cn`
  - `gold`
  - `cash_liquidity`
- deterministic `build_execution_plan(...)`
- restriction-aware pruning for:
  - `不碰股票`
  - `只接受黄金和现金`
- alternate-product surfacing at plan-item level
- documented `cash / liquidity` alias now normalizes to `cash_liquidity`
- stable `plan_id` lineage + separate `plan_version`
- first-class sqlite persistence for execution-plan records with version history
- `approved_at / superseded_by_plan_id` fields preserved in summaries and storage
- frontdesk now separates:
  - `user_state.active_execution_plan` as the confirmed baseline (`approved`, unsuperseded)
  - `user_state.pending_execution_plan` as the latest unconfirmed review plan
- decision-card `execution_plan_summary` remains wired to the latest plan generated by the current run
- CLI summary / snapshot rendering now surfaces both `active_execution_plan` and `pending_execution_plan`
- inline `--profile-json` JSON input now works for long payloads without path-length crashes

仍缺：
- 用户确认、批准、替换旧计划的正式状态机与交互入口
- 更完整的产品池、替代规则、停用策略与用户解释层
- monthly / quarterly follow-up 针对“现行执行计划 vs 建议新计划”的差异化比对与升级规则

## 优先级清单

### P0

1. `10 ev_engine`：继续做公式/量纲/回归硬化
2. `07 orchestrator`：继续补 replay / override / provenance 深水区与 execution-plan state-machine 接线
3. `11 product_mapping / execution_planner`：补用户确认、计划升级/替换与前台显式确认闭环

### P1

1. `05 calibration`：market assumptions 正式保守校准 + version id uniqueness
2. `03 snapshot_ingestion`：`cashflow_events_raw` 校验与更完整 raw snapshot typing
3. `07 orchestrator`：审计落账适配层
4. `09 decision_card`：语义硬化与产品化展示层增强
5. `04 runtime_optimizer`：更完整 candidate rules
6. `11 product_mapping / execution_planner`：更完整产品池、替代规则、停用策略与解释层

### P2

1. 更真实的 `03 -> 05 -> 08 -> 02 -> 04 -> 07 -> 09` 高层 smoke
2. replay / override / provenance 组合回归
3. allocation / decision_card 的解释度增强

## 当前分派

### Developer

- 本轮已完成：
  - `02 goal_solver` notes/infeasibility 语义收口
  - `04/10` 一批高优先级 runtime / EV 语义硬化
  - `11 -> 07/09/frontdesk` execution-plan 第一波正式接线
- 范围：
  - `plan_id / plan_version` versioned persistence
  - decision-card execution-plan summary
  - frontdesk confirmed baseline vs pending review plan split
  - CLI inline JSON fix

- 下一优先级候选：
  - `10 ev_engine`
  - `07 orchestrator`
  - `11 execution plan state machine`

### Reviewer

- 本轮结论：
  - execution-plan 接线方向正确，但必须持续防止：
    - restrictions 在 orchestrator/product-mapping 边界再次丢失
    - `plan_id / plan_version` 被重新硬编码回单版本路径
    - `decision_card.execution_plan_summary` 再次与 active plan 脱节
  - 仍需警惕 `low_confidence` 与 `blocked/degraded` 混义
  - 仍需警惕 09 的 `review_conditions / next_steps` 侵入 07 控制语义

### Tester

- 本轮已补：
  - `11 execution_plan` persistence contract
  - `07 orchestrator` restrictions + decision-card wiring contract
  - `frontdesk` inline profile-json / active-vs-pending execution plan smoke
- 重点覆盖:
  - execution-plan artifact persistence
  - `decision_card.execution_plan_summary`
  - `active_execution_plan` / `pending_execution_plan`
  - inline `--profile-json` compatibility
