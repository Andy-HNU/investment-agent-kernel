# AGENTS.md

## 仓库目标
这是一个“文档先行 + TDD 先行”的多模块投资决策系统仓库种子。

当前阶段的首要任务不是一次性补完全部业务，而是：
1. 建立 `src/` 最小骨架
2. 固定 canonical types 与冻结接口
3. 先通过 contract tests
4. 再通过最小 smoke e2e
5. 之后再按模块补真实实现、场景测试与回归测试

禁止把本仓库当成“自由发挥的量化策略实验场”。优先保证：接口稳定、边界稳定、测试稳定、目录稳定。

---

## 指令优先级
当不同文件存在口径冲突时，按以下顺序裁决：

1. 本文件 `AGENTS.md`
2. 根目录 `tests/` 中 contract / smoke tests
3. `handoff/CODEX_first_round_prompt.md`
4. `system/*patched*.md` 或带附录收口的冻结版系统文档
5. `docs/tdd/` 中的测试说明文档
6. `docs/review/` 与 `docs/legacy/` 文档

如果正文与“patched / appendix / 冻结版 / 补丁收口”冲突，以后者为准。

---

## 非目标
除非冻结文档或测试明确要求，当前阶段不要做以下事项：

- 不接真实券商 / 基金平台 API
- 不接真实行情源
- 不做数据库持久化
- 不做前端页面
- 不做复杂 Monte Carlo 优化器强化版
- 不把业务逻辑塞进 `shared/`
- 不让 `orchestrator/` 越权实现策略判断
- 不为“06 模块”发明新目录；原始系统文档当前没有可执行的 06 冻结规格

---

## 模块边界（强制）
- `goal_solver/`：回答“目标够不够”
- `allocation_engine/`：只产出 `candidate_allocations`，供 `goal_solver` 使用
- `calibration/`：输入解释、状态构建、参数治理的 canonical source
- `runtime_optimizer/`：只编排，不评分
- `runtime_optimizer/ev_engine/`：只评分，不生成候选
- `decision_card/`：只消费结构化结果，不重算策略
- `orchestrator/`：只做 workflow 触发、路由、阻断、升级/降级

---

## 类型所有权（强制）
`calibration.types` 是以下类型的唯一 canonical source：
- `MarketState`
- `ConstraintState`
- `BehaviorState`
- `RuntimeOptimizerParams`
- `EVParams`
- `CalibrationResult`

`goal_solver.types` 提供：
- `GoalSolverInput`
- `GoalSolverOutput`
- `GoalSolverParams`
- `MarketAssumptions`
- `StrategicAllocation`

`runtime_optimizer` / `ev_engine` / `decision_card` 不得平行重定义上述类型。

---

## 冻结接口

### EV 主入口
```python
run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: str,
) -> EVReport
```
参数名必须保持：`state`, `candidate_actions`, `trigger_type`。

### EV 状态构建入口
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

### Runtime 主入口
`run_runtime_optimizer(...) -> RuntimeOptimizerResult`

要求：
- 返回结构中必须包含 `ev_report`
- Runtime 负责模式判定、输入校验、状态组装、候选生成、结果汇总
- Runtime 不得内嵌 EV 评分逻辑

### Decision Card 主入口
`decision_card.builder.build_decision_card(...)`

要求：
- 只吃结构化输入
- 不得重算 EV
- 不得重算 Goal Solver
- 不得发明新策略判断

---

## 当前最小目录建议
```text
src/
  calibration/
    __init__.py
    types.py
  goal_solver/
    __init__.py
    types.py
  runtime_optimizer/
    __init__.py
    engine.py
    state_builder.py
    candidates.py
    types.py
    ev_engine/
      __init__.py
      engine.py
      scorer.py
      filter.py
      report.py
  decision_card/
    __init__.py
    builder.py
    types.py
  orchestrator/
    __init__.py
    engine.py
    types.py
  allocation_engine/
    __init__.py
    engine.py
    types.py
  shared/
    __init__.py
```

---

## 开发顺序（必须遵守）
### 第 1 阶段：先让测试可运行
- 建最小目录与空模块
- 修通 import path
- 用 dataclass / TypedDict / Enum 把契约形状收住

### 第 2 阶段：先让 contract tests 变绿
优先保证：
- `tests/contract/test_04_to_10_contract.py`
- `tests/contract/test_05_to_04_contract.py`
- `tests/contract/test_05_to_02_contract.py`
- `tests/contract/test_07_to_09_contract.py`

### 第 3 阶段：让 smoke test 变绿
- `tests/smoke/test_end_to_end_minimal.py`

### 第 4 阶段：再补真实逻辑
- unit tests
- scenario tests
- regression tests

不要跳过前面阶段直接大规模写业务。

---

## 允许的最小实现策略
首轮允许使用保守的最小实现以先通过测试：
- 用 dataclass / dict adapter 固定字段
- EV 先实现最小可解释排序，如 `freeze` / `observe` / `add_cash_core`
- Decision Card 先输出最小结构：`recommended_action`、`summary`、`reasons`
- Runtime Optimizer 初期可只支持最小 monthly 流程

但必须保证：
- 结构不越权
- 后续可平滑替换为正式实现

---

## 代码规范
- 优先使用标准库与轻依赖
- 明确类型注解
- dataclass 优先于随意 dict 拼接
- 不要写巨型 God object
- 不要把文档口径“猜测性补全”为复杂实现
- 新增文件尽量用 ASCII 文件名

---

## 完成定义
一次有效提交至少满足：
- contract tests 全通过
- smoke test 通过
- 没有越权重定义 canonical types
- 没有改坏冻结接口
- 输出变更摘要、测试结果、未完成项与下一轮建议
