# 给 Codex 的首轮执行 Prompt（多 Agent 模式）

你现在接手的是一个“文档先行 + TDD 启动包已整理”的多模块投资决策系统仓库。

你的任务不是一次性补完全部业务，而是严格按照仓库中的 `AGENTS.md`、`system/` 与 `tests/`，完成第一轮可运行主干。
如果运行环境支持子 agent，请显式创建 Developer / Reviewer / Tester 三个子 agent 并并行或分阶段协作；如果当前环境不支持显式子 agent，也必须严格按三角色流程模拟执行，并分别输出三角色结论，不允许把开发、审阅、测试混成一个未区分的结果。

---

## 执行模式：主 Agent + 3 个子 Agent 协作

你必须采用以下协作模式推进本轮任务：

### 0. 主 Agent（总控 / Orchestrator）
主 Agent 负责：
- 阅读仓库规范并建立本轮执行计划
- 拆分工作给 3 个子 Agent
- 控制边界，不允许任何子 Agent 越过冻结口径
- 汇总开发、审阅、测试结果
- 决定是否进入下一轮修复闭环
- 最终统一输出本轮修改摘要、测试结果与未完成项

主 Agent 自己不要跳过审阅和测试直接宣布完成。

---

### 1. 开发 Agent（Developer）
开发 Agent 负责：
- 阅读 `AGENTS.md`、`system/`、`tests/`
- 建立最小 `src/` 骨架
- 以“最小实现、先过 contract、再过 smoke”为原则补代码
- 严格遵守 frozen signature、canonical type source 与模块边界
- 不得擅自扩展业务范围
- 不得为缺失模块发明系统外逻辑
- 不得引入真实外部依赖、数据库、前端扩写

开发 Agent 的目标不是“做大”，而是“做小、做稳、做准”。

---

### 2. 审阅 Agent（Reviewer）
审阅 Agent 负责：
- 审阅开发 Agent 的改动是否违反系统边界
- 检查是否破坏 frozen signature
- 检查是否重复定义 canonical types
- 检查模块职责是否漂移
- 检查是否把业务判断写进 `shared/`
- 检查是否让 `runtime_optimizer` 内嵌 EV 打分
- 检查是否让 `decision_card` 做二次策略计算
- 检查 import 路径、命名、类型收口是否一致
- 输出明确审阅结论：
  - `PASS`
  - `PASS with concerns`
  - `FAIL`

审阅 Agent 不负责扩写新需求，只负责找出偏差、风险和越界点。

---

### 3. 测试 Agent（Tester）
测试 Agent 负责：
- 阅读 `tests/`、`pytest.ini` 与 CI workflow
- 优先运行 contract tests
- 再运行最小 smoke e2e
- 报告失败测试、失败原因、涉及模块
- 区分：
  - 类型/签名问题
  - import/path 问题
  - 数据结构问题
  - 运行时最小闭环问题
- 给出最小修复建议，但不要擅自改变架构目标

测试 Agent 目标是验证“是否已经形成最小可运行主干”，不是补业务。

---

## 子 Agent 协作规则

1. 主 Agent 先阅读规范，再拆任务，不允许盲改。
2. 开发 Agent 先产出最小实现。
3. 审阅 Agent 基于开发结果做边界审查。
4. 测试 Agent 基于当前实现执行测试验证。
5. 若审阅或测试失败：
   - 主 Agent 汇总失败点
   - 将失败点回派给开发 Agent 做最小修复
   - 再次进入审阅与测试
6. 只有当：
   - 审阅未发现冻结口径破坏
   - contract tests 通过
   - 最小 smoke e2e 通过
   才允许主 Agent 宣布本轮完成。
7. 不要因为想“补全系统”而扩大首轮范围。
8. 本轮优先级始终是：
   - 类型收口
   - frozen signature 对齐
   - contract tests
   - smoke e2e
   - 最小实现
   - 清晰总结

---

## 目标
请按以下顺序执行：

1. 阅读仓库根目录 `AGENTS.md`
2. 阅读 `system/` 中冻结规格，尤其是 04 / 05 / 09 / 10
3. 阅读 `tests/`、`pytest.ini` 与 CI workflow
4. 建立并补齐最小 `src/` 目录骨架与 import 路径
5. 先让 contract tests 通过
6. 再让最小 smoke e2e 通过
7. 在不破坏边界的前提下，补最小实现
8. 输出本轮修改摘要、测试结果与未完成项

---

## 绝对约束
- 不要引入真实外部数据源
- 不要接数据库
- 不要扩写前端
- 不要在 `shared/` 中写业务判断
- 不要让 `runtime_optimizer` 内嵌 EV 打分
- 不要让 `decision_card` 二次重算策略
- 不要平行重复定义 `MarketState / ConstraintState / BehaviorState / RuntimeOptimizerParams / EVParams`
- 不要为缺失的“06”发明新子系统

---

## 你必须遵守的冻结口径

### Canonical type source
- `calibration.types` 是：
  - `MarketState`
  - `ConstraintState`
  - `BehaviorState`
  - `RuntimeOptimizerParams`
  - `EVParams`
  - `CalibrationResult`
  的唯一 canonical source。

### Goal solver type source
- `goal_solver.types` 提供：
  - `GoalSolverInput`
  - `GoalSolverOutput`
  - `GoalSolverParams`
  - `MarketAssumptions`
  - `StrategicAllocation`

### EV frozen signature
```python
run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: str,
) -> EVReport
```

### EV state builder

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

---

## 推荐实现步骤

### 第一步：搭骨架

至少创建并补齐：

* `src/calibration/types.py`
* `src/goal_solver/types.py`
* `src/runtime_optimizer/state_builder.py`
* `src/runtime_optimizer/candidates.py`
* `src/runtime_optimizer/ev_engine/engine.py`
* `src/decision_card/builder.py`

### 第二步：先收住类型

* 用 dataclass / TypedDict / Enum 定义最小结构
* 保证 `tests/fixtures/factories.py` 里的字段能被正式实现消费

### 第三步：先通过 contract tests

重点保证：

* `run_ev_engine` 的签名精确匹配
* `calibration_result` 输出字段齐全
* `decision_card` 输出是纯 render 结果

### 第四步：通过 smoke test

最小闭环：

* `run_ev_engine(...)` 能接受 `ev_state + candidate_actions`
* 返回一个 `EVReport`
* `build_decision_card(...)` 能把 `EVReport` 渲染成最小卡片结构

---

## 执行时的输出格式要求

在真正改代码前，主 Agent 先输出：

### A. 本轮执行计划

* 本轮范围
* 预计先改哪些文件
* 哪些约束最容易被破坏
* 本轮不做什么

完成改动后，统一输出以下结构：

### B. 开发 Agent 输出

* 新增/修改文件清单
* 每个文件的最小职责
* 关键实现点
* 仍为 stub 的部分

### C. 审阅 Agent 输出

* 审阅结论：PASS / PASS with concerns / FAIL
* 是否存在越界实现
* 是否存在类型重复定义
* 是否存在职责漂移
* 是否存在后续风险点

### D. 测试 Agent 输出

* 已运行测试
* 通过项
* 失败项
* 失败原因
* 是否达到“最小可运行主干”

### E. 主 Agent 最终结论

1. 新增/修改的文件清单
2. 哪些测试已通过
3. 仍是 stub 的模块
4. 下一轮建议优先级
5. 如果未完成，明确阻塞点

---

## 重要执行原则

* 先收口，再实现
* 先 contract，再 smoke
* 先最小闭环，再补内容
* 所有子 Agent 都不得擅自扩大系统边界
* 如果出现规范冲突，以冻结口径、测试契约、模块边界优先

````

避免 Codex 在某些环境下“知道有多 agent 概念，但实际上偷懒只走单线程思维”。
保证即便当前入口不显式暴露 subagent 控制，输出结构仍然保留三角色分离。

