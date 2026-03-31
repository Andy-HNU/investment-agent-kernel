# 03 / 05 实现规格自检报告

> 本文档对 `03_snapshot_and_ingestion.md` 和 `05_constraint_and_calibration.md` 进行五维自检，
> 明确标注 ✅ 通过 / ⚠️ 需关注 / ❌ 存在冲突，并给出建议处理方式。

---

## 一、功能完整度

### 03 快照与采集层

| 检查项 | 状态 | 说明 |
|------|------|------|
| 五域快照类型定义完整 | ✅ | MarketRawSnapshot / AccountRawSnapshot / GoalRawSnapshot / ConstraintRawSnapshot / BehaviorRawSnapshot 均有完整字段 |
| SnapshotBundle 定义完整 | ✅ | bundle_id / 五域引用 / bundle_quality / quality_summary 均已定义 |
| 域内校验函数覆盖全部域 | ✅ | validate_*() 函数对五域分别声明 |
| 跨域一致性校验 | ✅ | validate_bundle() 覆盖桶宇宙对齐、horizon 一致性等 |
| 质量 flag 枚举完整 | ✅ | QualityCode 枚举 9 个，覆盖时效、完整性、配置异常 |
| bundle_id 与 snapshot_id 的派生关系 | ✅ | 第 5 节明确说明了 Orchestrator 负责在 bundle_id 基础上派生 |
| 降级协议（partial vs degraded）| ✅ | 第 6 节分类清楚，阻断决策明确交给 07 |
| 代码组织 | ✅ | 文件树清晰，职责不重叠 |
| `current_drawdown` 计算来源 | ⚠️ | 文档标注"峰值窗口由采集方确定"，但未明确定义峰值窗口的计算规则（滚动 12/24/36 月？全历史？）。**建议在 `builder.py` 注释中补充默认峰值窗口为滚动 24 个月。** |
| GoalRawSnapshot 与 CashFlowEvent 的类型适配 | ⚠️ | 为避免 03 依赖 goal_solver.types，GoalRawSnapshot 使用 `cashflow_events_raw: list[dict]`，但 dict 字段约定较松，存在适配时解析失败风险。**建议在第 3.5 节补充 dict 字段约定（must-have keys 列表）并在 `validate_goal_snapshot` 中显式检查。** |

### 05 约束与校准层

| 检查项 | 状态 | 说明 |
|------|------|------|
| 四类状态输出完整定义 | ✅ | MarketState / ConstraintState / BehaviorState + MarketAssumptions |
| 三类参数输出完整定义 | ✅ | GoalSolverParams / RuntimeOptimizerParams / EVParams |
| CalibrationResult 完整 | ✅ | 含状态 + 参数 + 质量 + 版本元信息 |
| 主入口 run_calibration 执行顺序 | ✅ | 第 4.1 节给出 7 步顺序，依赖关系正确（BehaviorState 在 ConstraintState 之前） |
| 参数版本治理硬约束 | ✅ | 第 6.2 节 5 条硬约束明确 |
| 降级分级（partial vs degraded）| ✅ | 第 7.1 / 7.2 节分类清楚 |
| MarketState vs MarketAssumptions 区分文档 | ✅ | 第 5 节专门说明，并禁止下游混用 |
| MarketAssumptions 保守构造约束 | ✅ | 在第 3.2 节注释中列出收缩规则与波动下限规则 |
| PSD 修正（正半定矩阵）| ✅ | calibrate_market_assumptions 注释中包含 eigenvalue clipping 说明 |
| EVParams 权重归一性校验 | ✅ | 第 3.6 节注明校验规则 total = 1.0 |
| BehaviorPenaltyCoeff 多项叠加规则 | ✅ | 第 3.4 节明确"取最大值，不累加" |
| 代码组织 | ✅ | 文件树清晰，子职责分文件隔离 |

---

## 二、是否与系统中其他模块冲突

### ❌ 冲突 1：编号冲突 —— 03 = Snapshot 还是 Allocation Engine？

**问题描述**

`02_goal_solver.md`（冻结版 v5.0）与 `04_runtime_optimizer.md`（v2.1）均明文引用 `03_allocation_engine.md` 作为候选战略配置生成模块：

```
# 来自 02_goal_solver.md §11 文件关联索引
| `03_allocation_engine.md` | 提供 `candidate_allocations` |

# 来自 04_runtime_optimizer.md §14
| `03_allocation_engine.md` | 提供候选战略配置集，用于 QUARTERLY 前置重算 |
```

而当前 `03_snapshot_and_ingestion.md` 将编号 03 分配给 Snapshot 层，`00_system_topology_and_main_flow.md` 也明文将 03 映射为 snapshot：

```
| `03_snapshot_and_ingestion.md` | 输入快照与采集层 |
```

**直接影响**

如果 Codex 按文件名自动关联，`03_allocation_engine.md` 与 `03_snapshot_and_ingestion.md` 在同一目录下会造成引用歧义，或其中一份文件不被识别。

**建议处理方式**

> **将 Allocation Engine 重编号为 `08_allocation_engine.md`**，并在 02 / 04 / 00 三份文档中同步更新引用。
> 本文档（03）已在 §0 和 §10 中预声明"原设计中曾以 03 编号描述 Allocation Engine，待独立编号为 08"，但需 02 和 04 同步修订。

---

### ❌ 冲突 2：RuntimeOptimizerParams 与 EVParams 的类型定义归属

**问题描述**

`04_runtime_optimizer.md` 的代码文件树（§11）中明确将 `RuntimeOptimizerParams` 定义在 `runtime_optimizer/types.py`：

```text
├── types.py
│   # RuntimeOptimizerParams   ← 由 04 自己定义
```

`10_ev_engine.md`（根据 00 推断）的 `ev_engine/types.py` 同理应定义 `EVParams`：

```text
ev_engine/types.py
│   # EVParams   ← 由 10 自己定义
```

但 `05_constraint_and_calibration.md`（本文档）中同样定义了 `RuntimeOptimizerParams` 和 `EVParams`，并声称 05 负责"更新并返回"这两类对象。

**直接影响**

若 04 和 10 各自在内部类型文件中定义这两个 dataclass，而 05 也定义同名类，将产生：
- **循环依赖风险**：若 05 import 04 的 RuntimeOptimizerParams，且 04 import 05 的 CalibrationResult，则形成循环；
- **类型重复定义**：两套结构难以保证字段一致性；
- **参数更新语义模糊**：05 "返回更新后的 RuntimeOptimizerParams"，但接收方 04 到底用哪个版本的类型？

**建议处理方式（三选一，需团队决策）**

| 方案 | 说明 | 适用场景 |
|------|------|---------|
| **方案 A（推荐）**：RuntimeOptimizerParams / EVParams 定义在 05（calibration/types.py），04 和 10 从 calibration 导入 | 05 是参数治理层，类型定义归治理层最合理；避免循环依赖 | 如果 04/10 不需要独立扩展自己的参数类型 |
| **方案 B**：定义在 shared/types.py，05 / 04 / 10 均从 shared 导入 | shared 只放通用类型，可能不纯 | 如果 params 是轻量配置结构，无业务语义 |
| **方案 C**：05 不返回 RuntimeOptimizerParams 对象，而是返回 `RuntimeParamUpdate: dict`，由 07 Orchestrator 应用到 04 内部对象上 | 最小侵入，但 update dict 类型安全性弱 | 快速原型，不推荐生产 |

> **本文档（05）暂按方案 A 编写**（05 定义并返回这两个类），并在 §5 类型导入约束中说明 04/10 应从 calibration 导入，需 04/10 文档同步修订。

---

### ⚠️ 潜在冲突 3：GoalSolverParams 中的 MarketAssumptions 更新路径

**问题描述**

`02_goal_solver.md` 中 `GoalSolverParams` 有以下注释：

```python
market_assumptions: MarketAssumptions = field(default_factory=MarketAssumptions)
# 注意：market_assumptions 由 CalibrationLayer 定期更新，GoalSolver 不修改
```

`05_constraint_and_calibration.md` 的 `update_goal_solver_params()` 函数声称将 `MarketAssumptions` 注入并返回新版 `GoalSolverParams`。

这条路径本身合理，但**需要明确 07 Orchestrator 的注入动作**：Orchestrator 拿到 CalibrationResult 之后，必须用 `calibration_result.goal_solver_params`（含最新 MarketAssumptions）替换旧的 GoalSolverParams，再传入 Goal Solver。

**建议处理方式**

> 在 `07_orchestrator_workflows.md` 中明确以下步骤：
> ```
> 1. 调用 run_calibration(bundle) → CalibrationResult
> 2. 用 calibration_result.goal_solver_params 替换本轮 GoalSolverInput.solver_params
> 3. 调用 run_goal_solver(goal_solver_input_with_updated_params)
> ```
> 此约定在 05 和 02 中都有暗示，但未在任何文档中显式写入 07 的编排流程。

---

## 三、内部逻辑冲突

### 03 内部

| 检查项 | 状态 | 说明 |
|------|------|------|
| bundle_quality 推断规则自洽 | ✅ | FULL / PARTIAL / DEGRADED 三级推断规则清楚，不重叠 |
| validate_bundle 与 validate_* 的关系 | ✅ | validate_bundle 是跨域增量校验，不重复域内校验，不冲突 |
| remaining_horizon_months 注入责任 | ⚠️ | 文档注明"由 Orchestrator 注入"，但 `build_snapshot_bundle` 函数签名中该参数由调用方传入。需确保 Orchestrator 在每次触发 03 时总是传入最新值，否则 Goal Solver 可能用过期期限求解。**建议 07 文档明确此注入义务。** |
| behavior 域 None 的语义 | ✅ | 明确区分"域缺失（None）"与"域存在但数据异常"，处理分支清晰 |

### 05 内部

| 检查项 | 状态 | 说明 |
|------|------|------|
| run_calibration 执行顺序依赖自洽 | ✅ | 顺序：MarketState → MarketAssumptions → BehaviorState → ConstraintState（后者依赖前者）正确 |
| ConstraintState.effective_drawdown_threshold 校准规则 | ✅ | 规则（high 环境 × 0.85）已在注释中说明，且明确 <= max_drawdown_tolerance |
| BehaviorState.behavior_penalty_coeff 与 EVParams.behavior_penalty_weight 的关系 | ⚠️ | BehaviorState 输出的是"惩罚系数"（0~1 放大因子），EVParams 中的 behavior_penalty_weight 是"评分占比"（0~1 权重）。两者含义不同，但名称相近，存在混淆风险。**建议在 10_ev_engine.md 中明确 BehaviorPenalty 的计算公式：`BehaviorPenalty_score = behavior_penalty_weight × f(behavior_penalty_coeff, action)`，并在 05 和 10 文档中交叉注释。** |
| MarketAssumptions 保守收缩系数硬编码 | ⚠️ | 文档中 `expected_returns * 0.85` 作为 v1 简化逻辑是合理的，但这个 0.85 是硬编码常量，未纳入 EVParams 或 GoalSolverParams 管理。若未来需要调整，修改点分散。**建议在 GoalSolverParams 中新增 `shrinkage_factor: float = 0.85` 字段，由 05 设置。** |
| CalibrationResult 的 calibration_quality 推断规则未显式定义 | ⚠️ | `_derive_calibration_quality()` 在函数列表中列出，但推断规则未在文档中以表格形式给出。**建议补充：FULL = 所有域均正常；PARTIAL = 至少一个 warn 级 flag 且无 error；DEGRADED = 存在 error 级 flag。** |

---

## 四、职责边界是否越界

### 03 越界检查

| 检查项 | 状态 | 说明 |
|------|------|------|
| 03 是否做了参数校准 | ✅ | 未做 |
| 03 是否做了 MarketState 解释 | ✅ | 未做，明确写在"不负责"列表 |
| 03 是否做了 MarketAssumptions 生成 | ✅ | 未做 |
| 03 是否做了 EV 相关逻辑 | ✅ | 未做 |
| 03 是否做了 workflow 判断 | ✅ | 未做，阻断决策明确由 07 负责 |
| 03 的 validate_bundle 是否侵入了 05 的职责 | ✅ | validate_bundle 只做桶宇宙对齐等结构性一致性校验，不做 regime 识别或参数推断，边界清晰 |

### 05 越界检查

| 检查项 | 状态 | 说明 |
|------|------|------|
| 05 是否做了原始数据采集 | ✅ | 未做 |
| 05 是否做了候选动作生成 | ✅ | 未做 |
| 05 是否做了 EV 打分 | ✅ | 未做 |
| 05 是否做了 Goal Solver 求解 | ✅ | 未做，只更新 params 并返回，不调用 run_goal_solver |
| 05 是否做了 workflow 触发 | ✅ | 未做，run_calibration 是纯函数 |
| 05 是否做了决策卡文案 | ✅ | 未做 |
| 05 的 update_goal_solver_params 是否侵入了 02 | ✅ | 05 只封装更新后的 GoalSolverParams 对象并返回，不直接调用 run_goal_solver，边界清晰 |
| 05 定义 RuntimeOptimizerParams 是否侵入了 04 | ⚠️ | 这正是冲突 2 的核心问题。若按方案 A 处理（05 定义，04 导入），则 05 拥有参数定义权是合理的；但需 04 文档修订配合。详见冲突 2。 |

---

## 五、与上下游对接模块逻辑是否接洽

### 03 → 05（下游）

| 接口项 | 状态 | 说明 |
|------|------|------|
| 05 的 run_calibration 接收 SnapshotBundle | ✅ | 03 输出类型与 05 输入类型完全对齐 |
| 05 的各子函数接收对应 RawSnapshot | ✅ | interpret_market_state(MarketRawSnapshot) 等均与 03 类型对齐 |
| behavior 域 None 的传递 | ✅ | SnapshotBundle.behavior: BehaviorRawSnapshot | None → 05 的 interpret_behavior_state 接收 BehaviorRawSnapshot | None，语义一致 |
| bundle_id 作为 source_bundle_id 传递 | ✅ | CalibrationResult.source_bundle_id = bundle.bundle_id，链路完整 |

### 03 → 07（Orchestrator）

| 接口项 | 状态 | 说明 |
|------|------|------|
| 07 根据 bundle_quality 决定是否阻断 | ✅ | 03 明确写入"阻断决策由 07 根据 bundle_quality 判断" |
| remaining_horizon_months 注入时机 | ⚠️ | 03 的 build_snapshot_bundle 要求调用方传入 remaining_horizon_months，07 必须在调用 03 前计算好此值。07 文档中需明确这是其责任。 |

### 05 → 02（Goal Solver）

| 接口项 | 状态 | 说明 |
|------|------|------|
| MarketAssumptions 类型来源一致 | ✅ | 05 从 goal_solver.types 导入，无重复定义 |
| GoalSolverParams 更新后的返回 | ✅ | 05 返回完整 GoalSolverParams 对象（含新 MarketAssumptions） |
| 02 只消费不修改 MarketAssumptions | ✅ | 02 文档明确"GoalSolver 不修改 market_assumptions"，与 05 职责不冲突 |
| run_goal_solver_lightweight 的 seed 来源 | ✅ | seed 在 GoalSolverParams 中，由 05 维护版本，02 消费，EV 通过 baseline_inp 使用，链路无断点 |

### 05 → 04（Runtime Optimizer）

| 接口项 | 状态 | 说明 |
|------|------|------|
| MarketState 类型对齐 | ✅ | 05 定义 MarketState，04 的 build_ev_state 消费（详见 04 §3 上下游关系图） |
| ConstraintState 类型对齐 | ✅ | 同上 |
| BehaviorState 类型对齐 | ✅ | BehaviorState.recent_chasing_flag 字段与 04 中 cooldown_applicable 标记逻辑对应 |
| RuntimeOptimizerParams 归属冲突 | ❌ | 详见冲突 2，需 04 文档修订配合 |
| effective_drawdown_threshold 与 04 的使用 | ⚠️ | 04 的 FeasibilityFilter（在 10）中会用到 drawdown 阈值。需确认 10 从 ConstraintState.effective_drawdown_threshold 读取而非 max_drawdown_tolerance。需在 10_ev_engine.md 中明确字段来源。 |

### 05 → 10（EV Engine）

| 接口项 | 状态 | 说明 |
|------|------|------|
| EVParams 类型归属 | ❌ | 同冲突 2，EVParams 在 05 和 10 均可能定义，需确定归属 |
| BehaviorPenalty 系数传递路径 | ✅（逻辑通）但需文档补 | BehaviorState.behavior_penalty_coeff → EVState（由 04 build_ev_state 组装）→ EV scorer，链路逻辑上通，但 10 文档中需明确 behavior_penalty_coeff 字段的来源是 BehaviorState |
| correlation_spike_alert 在 EV 的使用 | ⚠️ | MarketState.correlation_spike_alert = True 时，EV RiskPenalty 应提高集中度惩罚。但目前 10_ev_engine.md 中未见此信号的消费规则。需在 10 文档中补充。 |

---

## 六、综合评估与处理优先级

### 必须在实现前处理（阻断级）

| 编号 | 问题 | 影响模块 | 建议 |
|------|------|---------|------|
| C1 | 03 编号与 Allocation Engine 命名冲突 | 02 / 04 / 00 / 03 | 将 Allocation Engine 重编号为 08，更新 02 / 04 文档引用 |
| C2 | RuntimeOptimizerParams / EVParams 定义归属冲突 | 04 / 05 / 10 | 采纳方案 A：定义归属 05（calibration/types.py），04/10 从 calibration 导入；修订 04 §11 types.py 注释 |

### 建议在实现时同步处理（优化级）

| 编号 | 问题 | 影响模块 | 建议 |
|------|------|---------|------|
| O1 | remaining_horizon_months 注入责任 | 03 / 07 | 在 07 workflow 文档中明确此字段由 Orchestrator 在触发 03 前计算注入 |
| O2 | current_drawdown 峰值窗口未定义 | 03 | 在 builder.py 注释中补充默认峰值窗口为滚动 24 月 |
| O3 | GoalSolverInput.snapshot_id 注入链路 | 03 / 07 | 在 07 文档中写明 bundle_id → snapshot_id 的生成步骤 |
| O4 | behavior_penalty_coeff 与 behavior_penalty_weight 混淆风险 | 05 / 10 | 在 10_ev_engine.md 中补充 BehaviorPenalty 计算公式，并在 05 和 10 中交叉注释 |
| O5 | MarketAssumptions 收缩系数硬编码 | 05 / 02 | 在 GoalSolverParams 新增 shrinkage_factor 字段，由 05 设置 |
| O6 | CalibrationResult.calibration_quality 推断规则未显式定义 | 05 | 补充推断规则表（FULL / PARTIAL / DEGRADED 判定逻辑）|
| O7 | effective_drawdown_threshold 在 10 的消费来源 | 05 / 10 | 在 10_ev_engine.md 中明确 FeasibilityFilter 使用 ConstraintState.effective_drawdown_threshold |
| O8 | correlation_spike_alert 在 EV 的消费规则 | 05 / 10 | 在 10_ev_engine.md 中补充高相关环境下集中度惩罚增强规则 |
| O9 | GoalRawSnapshot.cashflow_events_raw 字段约定 | 03 / 07 | 在 §3.5 补充 dict 必需字段列表（month_index, amount, event_type, description），并在 validate_goal_snapshot 中校验 |
| O10 | MarketAssumptions 更新注入 GoalSolver 的 07 步骤 | 05 / 07 | 在 07 文档中明确 CalibrationResult → GoalSolverInput 的参数替换步骤 |

---

## 七、一句话结论

> **03 和 05 的核心设计正确、边界清晰、内部逻辑自洽；**
> **有两处阻断级冲突需在实现前与 02 / 04 / 10 文档对齐（Allocation Engine 编号 + 参数类型归属），十处优化级问题建议实现时同步处理。**
