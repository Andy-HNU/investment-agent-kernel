# CODEX System Doc Gap Backlog

更新日期: 2026-03-29

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

状态：`部分实现（本轮已收掉一批 P0）`

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
- 更贴近正式文档的 Monte Carlo / infeasibility 细节
- 更深的 `solver_notes` / 结果解释口径

本轮收口：
- Monte Carlo context notes（`paths / seed / horizon_months`）
- success-threshold gap notes（`threshold / recommended / gap / met`）
- recommended-feasibility note（推荐项可行性与 shortfall baseline）
- no-feasible dominant-constraint summary
- fallback pressure score note

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

### 07 orchestrator

状态：`大体实现，本轮已继续收口正式主入口`

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

仍缺：
- 持久化 / 审计落账的 file/json/sqlite 执行适配层
- 更深 replay / override / provenance 变体

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

状态：`阶段 1 正式化已完成，剩余语义硬化`

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

## 优先级清单

### P0

1. `Round 5`：全链 smoke / regression 硬化
2. `10 ev_engine`：继续做公式/量纲/回归硬化
3. `07 orchestrator`：继续补 replay / override / provenance 深水区与真正落账执行层

### P1

1. `05 calibration`：market assumptions 正式保守校准 + version id uniqueness
2. `03 snapshot_ingestion`：`cashflow_events_raw` 校验与更完整 raw snapshot typing
3. `07 orchestrator`：审计落账适配层
4. `09 decision_card`：语义硬化与产品化展示层增强
5. `04 runtime_optimizer`：更完整 candidate rules

### P2

1. 更真实的 `03 -> 05 -> 08 -> 02 -> 04 -> 07 -> 09` 高层 smoke
2. replay / override / provenance 组合回归
3. allocation / decision_card 的解释度增强

## 当前分派

### Developer

- 本轮已完成 `09 decision_card` 的阶段 1 正式化收口
- 范围：
  - formal input only
  - validate rules
  - low-confidence / runner-up / review conditions / next steps
  - blocked / quarterly card 语义收紧
  - 09 direct contract 补齐

- 下一优先级候选：
  - `Round 5`
  - `10 ev_engine`
  - `07 orchestrator`

### Reviewer

- 本轮结论：
  - Round 4 方向正确
  - 需警惕 `low_confidence` 与 `blocked/degraded` 混义
  - 需警惕 09 的 `review_conditions / next_steps` 侵入 07 控制语义

### Tester

- 本轮已补 `09 decision_card` 对应 contract / smoke
- 重点覆盖:
  - formal input only
  - runtime 缺主动作报错
  - non-blocked 卡拒绝 `blocking_reasons`
  - quarterly 主动作仍为 `review`
  - “真实 05 产物进入 07” 的 partial / degraded 路径
