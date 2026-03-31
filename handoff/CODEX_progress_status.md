# CODEX Progress Status

更新日期: 2026-03-30

## 协作约定

- 后续开发继续使用 3 条子线:
  - `Developer`
  - `Reviewer`
  - `Tester`
- 子 agent 模型统一使用 `gpt-5.4` + `xhigh`
- 主线程负责:
  - 汇总 `handoff/`、`system/`、`tests/` 约束
  - 决定每轮实现切片
  - 集成三条子线结果
  - 统一回归测试与阶段结论

## 当前阶段结论

当前仍处于阶段 1，但“阶段 1 核心可执行闭环”已经完成：

1. 系统本体开发与测试已形成最小正式主干
2. 还未开始 OpenClaw skill 集成

当前执行计划已完成 `Round 1`、`Round 2`、`Round 3`、`Round 4`、`Round 5`。

`Round 5` 完成口径：

1. 已补齐 `03 -> 05 -> 08 -> 02 -> 04 -> 07 -> 09` 的可运行 demo lifecycle
2. 已补 replay / override / provenance regression
3. 已把 demo 入口收口到单一 canonical report path，并保留 legacy alias 兼容层
4. `OrchestratorResult.to_dict()` 已加固为更稳定的 JSON-safe 输出

下一步默认进入 [`CODEX_7_round_ship_plan.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_7_round_ship_plan.md) 的 `Round 6`，但 OpenClaw skill 集成尚未开始。

当前前台 / 外部数据方向的后续重点已收口为:

1. 第一个真实 provider adapter
2. 自动刷新与数据新鲜度展示
3. 用户执行后回填闭环
4. 最终用户产品壳层

范围约束:

- 当前不做自动交易 / 不做代下单
- 系统职责是输出建议动作，并接收用户执行后的反馈回填

本仓库已经不再只是“骨架 + contract seed”，而是具备以下可执行主链：

`03 raw snapshot -> 03 SnapshotBundle -> 05 CalibrationResult -> 07 Orchestrator -> 09 DecisionCard`

同时保留并通过了原先的：

`08 allocation -> 02 goal_solver -> 04 runtime_optimizer -> 10 ev_engine -> 09 decision_card`

## 模块状态

### snapshot_ingestion

- 已新增最小可执行 `src/snapshot_ingestion/`
- 已实现:
  - `build_snapshot_bundle(...)`
  - 域内校验函数
  - bundle 质量判定
  - `bundle_id` 生成
- 当前是阶段 1 的最小实现，不含真实外部适配器接入

### calibration

- canonical types 继续由 [`types.py`](/root/AndyFtp/investment_system_codex_ready_repo/src/calibration/types.py) 持有
- 已新增最小可执行 [`engine.py`](/root/AndyFtp/investment_system_codex_ready_repo/src/calibration/engine.py)
- 已实现:
  - `run_calibration(...)`
  - `interpret_market_state(...)`
  - `interpret_behavior_state(...)`
  - `interpret_constraint_state(...)`
  - `calibrate_market_assumptions(...)`
  - `ParamVersionMeta`
  - `update_goal_solver_params(...)`
  - `update_runtime_optimizer_params(...)`
  - `update_ev_params(...)`
  - prior behavior 复用
  - degraded market 下 prior market assumptions 复用
  - manual override / replay metadata
  - constraint conflict -> degraded + manual review note
  - `previous_version_id / updated_reason / can_be_replayed / is_temporary`
- 本轮新增:
  - 07 在 raw-input 生成 calibration 时会把 `manual_override` / `replay_mode` 语义传给 05
  - 07 生成 calibration 时会按 workflow 给出默认 `updated_reason`
  - `05 -> 02 / 04` 的语义传播 contract 已补
  - “真实 05 产物进入 07” 的 `partial / degraded` smoke 已补
- 当前 05 已达到“阶段 1 参数治理闭环”标准，但仍不是完整正式校准器

### goal_solver

- `GoalSolverInput / GoalSolverOutput` typed 路径稳定
- 02/05/08/07 之间的最小输入输出链路稳定
- 已补:
  - `RANKING_MODE_MATRIX`
  - `infer_ranking_mode()`
  - ranking-mode driven 排序
  - no-feasible fallback
  - `solver_notes`
  - lightweight 路径回归测试
- 当前仍不是完整正式求解器，但已不再是“只会取最高成功概率”的最小版

### runtime_optimizer / ev_engine

- `build_ev_state(...) -> EVState` 与 `run_ev_engine(...) -> EVReport` 已稳定
- `candidate_poverty`、behavior-event、cooldown/high-risk 等边界已有测试覆盖
- 本轮新增:
  - `run_ev_engine(...)` 前置 `_validate_state / _validate_action`
  - `FeasibilityResult` 现在支持多原因累积，不再只返回首个失败理由
  - feasibility 已补:
    - `QDII` 配额检查
    - 资金不足检查
    - IPS / satellite / cooldown 多重失败理由
  - `score_action(...)` 已拆成:
    - `compute_goal_impact`
    - `compute_risk_penalty`
    - `compute_soft_constraint_penalty`
    - `compute_behavior_penalty`
    - `compute_execution_penalty`
  - 五项分量现在正式消费 `EVParams` 与状态字段，不再主要依赖动作类型硬编码
  - `confidence_flag / confidence_reason` 已开始按文档阈值、情绪标志、淘汰率、GoalImpact 近零规则收口
  - `recommendation_reason` 已从“分数回显”升级为“按主贡献/主扣分项解释”
- 当前 10 已明显高于最小启发式版，但仍不是最终完整版

### allocation_engine

- 已完成阶段 1 主干拆分:
  - `templates.py`
  - `generator.py`
  - `projection.py`
  - `complexity.py`
  - `dedup.py`
  - `validator.py`
  - `engine.py`
- 已实现并验证:
  - template family 生成
  - IPS/theme/qdii/liquidity 投影
  - family-aware dedup / trim
  - `essential` / `low complexity` / 多主题 / liquidity-buffered 规则
  - 08 -> 02 handoff
- 08 当前可视为“阶段 1 可交付版本”

### orchestrator

- 已完成 07 的正式控制流主干:
  - workflow selection 不再完全依赖外部硬传
  - `bundle_quality / calibration_quality / candidate_poverty` 可翻译为 `blocked / degraded / escalated`
  - provenance 校验已收口
  - runtime restriction 已覆盖:
    - candidate poverty
    - cooldown
    - manual review requested
    - manual override requested
    - high-risk request
  - 已生成结构化:
    - `WorkflowDecision`
    - `RuntimeRestriction`
    - `OrchestratorAuditRecord`
- 07 现在不只返回 `card_build_input`，还会直接返回最终 `decision_card`
- 本轮新增:
  - 07 在存在原始五域输入时可自行驱动 `03 -> 05`
  - 07 支持直接从 raw snapshot 构造 `SnapshotBundle`
  - 07 支持在缺少显式 `calibration_result` 时内部生成 `CalibrationResult`
  - `audit_record.artifact_refs` 现在会标记 `snapshot_bundle_origin / calibration_origin`
  - 已新增 `OrchestratorPersistencePlan`，明确“本轮应落账什么”
  - 07 现在会把 `manual_override_requested` 透传到 05 的 calibration metadata
  - 07 现在支持显式 `replay_mode` 触发 05 的 replay metadata
  - `OrchestratorResult.to_dict()` 现已显式序列化 `datetime/date/set/SimpleNamespace-like` 负载，demo/report JSON 不再依赖 `default=str`

### decision_card

- `DecisionCardBuildInput` / `build_decision_card(...)` 已从“最小闭环”推进到“阶段 1 正式版”
- 已能正式消费 07 输出的:
  - trace refs
  - workflow decision
  - runtime restriction
  - audit record
  - blocking / degraded / escalation notes
  - control directives
- 本轮新增:
  - `build_decision_card(...)` 已收紧为单一正式入口，只接受 `DecisionCardBuildInput`
  - `DecisionCardBuildInput.validate()` 已接入 builder，季度卡缺输入、非 blocked 卡误带 `blocking_reasons` 时会显式报错
  - `DecisionCard` 现已稳定输出:
    - `evidence_highlights`
    - `review_conditions`
    - `next_steps`
    - `runner_up_action`
    - `low_confidence`
  - runtime card 现在会正式表达:
    - low-confidence
    - candidate poverty
    - review conditions
    - runner-up / evidence highlights
  - `RUNTIME_ACTION` 在缺少 `recommended_action / ranked_actions` 时会显式报错，不再静默补默认动作
  - blocked / degraded 相关展示现在会区分 `status_badge=blocked|degraded`
  - blocked 卡不再泄漏正常动作建议，07 的 `control_directives` 会显式转成 next step / review conditions
  - quarterly review card 现在正式消费 `GoalSolverOutput + RuntimeOptimizerResult`
  - 已新增 `09` 专属 contract，直接锁住:
    - formal input only
    - quarterly 缺输入报错
    - runtime 无主动作时报错
    - blocked / quarterly card 语义
- 09 当前已达到“阶段 1 正式化收口”标准，但仍不是最终产品化卡片体系

### demo / cli

- 已新增 canonical demo scenario/report 层:
  - [`src/shared/demo_scenarios.py`](/root/AndyFtp/investment_system_codex_ready_repo/src/shared/demo_scenarios.py)
  - [`src/demo_cli.py`](/root/AndyFtp/investment_system_codex_ready_repo/src/demo_cli.py)
  - [`scripts/full_flow_demo.py`](/root/AndyFtp/investment_system_codex_ready_repo/scripts/full_flow_demo.py)
- `src/shared/demo_flow.py` 现已退化为 compatibility wrapper，不再维持第二套独立 demo 实现
- legacy alias 仍可用，但会解析到 canonical scenario:
  - `journey -> full_lifecycle`
  - `quarterly_full_chain -> quarterly_review`
  - `monthly_provenance_blocked -> provenance_blocked`
  - `monthly_provenance_relaxed -> provenance_relaxed`

## 当前测试状态

- contract tests: `89`
- smoke tests: `24`
- total tests: `113`

最近一轮验证口径:

- `python3 -m pytest tests/contract/test_03_to_05_contract.py -q -rs`
- `python3 -m pytest tests/contract/test_05_to_02_contract.py tests/contract/test_05_to_04_contract.py tests/smoke/test_snapshot_to_orchestrator_smoke.py -q -rs`
- `python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/contract/test_07_to_09_contract.py tests/smoke/test_orchestrator_workflows_smoke.py -q -rs`
- `python3 -m pytest tests/contract/test_09_decision_card_contract.py tests/contract/test_07_to_09_contract.py tests/smoke/test_end_to_end_minimal.py tests/smoke/test_orchestrator_workflows_smoke.py -q -rs`
- `python3 -m pytest tests/smoke/test_snapshot_to_orchestrator_smoke.py -q -rs`
- `python3 -m pytest tests/smoke/test_orchestrator_workflows_smoke.py tests/smoke/test_snapshot_to_orchestrator_smoke.py tests/smoke/test_end_to_end_minimal.py -q -rs`
- `python3 -m pytest tests/contract/test_07_orchestrator_contract.py tests/smoke/test_demo_cli_smoke.py tests/smoke/test_round5_demo_scenarios_smoke.py tests/smoke/test_round5_demo_lifecycle_smoke.py tests/smoke/test_demo_journey_smoke.py -q -rs`
- `python3 -m pytest -m contract -q -rs`
- `python3 -m pytest -q`

当前结果: 绿色

## 阶段判断

### 阶段 1 已完成的部分

- 最小正式可执行主干
- `03 -> 05 -> 07 -> 09` 闭环
- `08 -> 02 -> 04 -> 10 -> 09` 闭环
- 多 workflow smoke 覆盖
- 07 审计/trace/control 信息向 09 的正式透传

### 阶段 1 剩余但不再阻塞主干的事项

- `calibration` 的 market assumptions 仍未达到文档里的完整保守校准版
- `calibration` 的 version id 仍未做到“同时间戳多次更新自动唯一化”
- `ev_engine` 从当前“规则化中间态”继续向正式完整版推进
- `decision_card` 的最终产品化展示体系和更细内容层字段
- `decision_card.low_confidence` 仍需和 `blocked / degraded / escalated` 语义进一步拆分
- `decision_card.review_conditions / next_steps` 仍需继续守住“render convention，不吞 07 控制责任”的边界
- `orchestrator` 审计记录的 file/json/sqlite 落账执行层
- 更深的 replay / override / provenance 变体测试

### 阶段 2 仍未开始

- 作为 OpenClaw 子项目接入
- skill 封装
- OpenClaw 侧集成测试

## 下一步建议

1. 若继续阶段 1 硬化，优先做:
   - `07 orchestrator` 的 replay / provenance 深水区与落账执行层
   - `ev_engine` 剩余硬化项
   - Round 5 全链 smoke / regression 补强
   - `calibration` 的剩余高级硬化项
2. 若进入阶段 2，则开始:
   - 迁入 OpenClaw workspace
   - 设计 skill 输入输出面
   - OpenClaw 集成测试
