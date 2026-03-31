# 交给 Codex 的测试先行开发指令

你正在为一个多模块投资决策系统搭建测试先行（TDD）骨架。

## 最高优先目标

先不要铺开全部业务代码。请先完成以下事项：

1. 建立与文档一致的 `src/` 目录与空模块
2. 让本启动包中的测试文件可 import
3. 先实现最小 dataclass / Enum / 主入口，使 contract tests 跑通
4. 再补最小业务逻辑，使 smoke test 跑通
5. 配置 CI，使 PR 至少经过：
   - lint
   - typecheck
   - contract-core
   - smoke-e2e
   - coverage-core

## 必须遵守的边界

- `calibration.types` 是 `MarketState / ConstraintState / BehaviorState / RuntimeOptimizerParams / EVParams / CalibrationResult` 的唯一 canonical source
- `goal_solver.types` 提供 `GoalSolverInput / GoalSolverOutput / GoalSolverParams / MarketAssumptions`
- `runtime_optimizer.state_builder` 负责状态构建
- `runtime_optimizer.candidates` 负责候选动作生成
- `runtime_optimizer.ev_engine.engine.run_ev_engine(...)` 负责 EV 主入口
- `decision_card.builder` 只消费结构化结果，不得补做策略判断

## 正式接口（冻结）

### 1. run_ev_engine
```python
run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: str,
) -> EVReport
```

### 2. build_ev_state
```python
build_ev_state(
    solver_output: GoalSolverOutput,
    solver_baseline_inp: GoalSolverInput,
    live_portfolio: LivePortfolioSnapshot,
    market_state: MarketState,
    behavior_state: BehaviorState,
    constraint_state: ConstraintState,
    ev_params: EVParams,
) -> EVState
```

### 3. run_runtime_optimizer
```python
run_runtime_optimizer(...)
```
由你按文档补齐，但输出必须是 `RuntimeOptimizerResult`，且内含 `ev_report`。

### 4. Decision Card
`decision_card.builder.build_decision_card(...)` 必须只吃结构化输入，不得自己重算 EV / Goal Solver。

## 通过标准

### 第一步通过标准
- 所有 contract tests 通过
- smoke test 通过
- coverage 达到门限

### 第二步通过标准
- 补充 unit tests
- 补充 scenario tests
- 引入 probability calibration / regression tests

## 实现策略建议
- 先用 dataclass + 明确字段把接口收住
- 再写最小逻辑，让测试变绿
- 不要一开始引入复杂外部依赖
- 不要在 `shared/` 写业务判断
- 不要让 orchestrator 越权实现策略

