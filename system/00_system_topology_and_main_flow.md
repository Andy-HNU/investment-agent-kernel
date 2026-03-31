
# 00_system_topology_and_main_flow.md

# 系统总拓扑与主流程 v1

> **文档定位**：本文件是整套系统的顶层说明文档，用于统一模块边界、主数据流、主工作流与代码组织方式。
> 它不讨论单个模块内部实现细节，只回答四个问题：
>
> 1. 系统由哪些顶层模块组成
> 2. 模块之间如何流转
> 3. Goal Solver、EV、Orchestrator 分别做什么
> 4. 代码目录如何组织，避免模块上下文交叉

---

## 0. 一句话定义

本系统是一个：

> **以目标达成为核心、以 Goal Solver 为中枢、以运行期动作优化为前台、以约束与校准为护栏、由 Orchestrator 串联的投资决策闭环系统。**

---

## 1. 顶层模块总览

系统由 **5 个主层 + 1 个编排器角色 + 1 个 shared 工具层** 组成。

### 1.1 五个主层

> **冻结版编号映射**：宏观分层之外，当前实现编号固定为
> `00_system_topology_and_main_flow`、`02_goal_solver`、`03_snapshot_and_ingestion`、`04_runtime_optimizer`、`05_constraint_and_calibration`、`07_orchestrator_workflows`、`08_allocation_engine`、`09_decision_card_spec`、`10_ev_engine`。
> 其中：`03 = Snapshot & Ingestion`，`08 = Allocation Engine`。

1. **治理与账户定义层**
   负责定义目标、IPS、权限边界、账户约束、战略配置基线。

2. **Goal Solver / 目标求解层**
   系统中枢。负责回答“目标够不够”，输出基线成功概率、失败尾部、结构预算与风险预算；不负责生成 `candidate_allocations`。

3. **运行期评估与动作优化层**
   负责在 Goal Solver 基线之上，对当前账户进行运行期状态快照、候选动作生成、动作可行性过滤、动作评分排序、结果输出与决策卡数据供给。

   该层内部至少包含两个子职责：

   Runtime Optimizer 外层编排容器：负责模式判定、状态组装、候选动作生成、调用 EV、汇总结果
   EV Engine：负责对候选动作做过滤后评分、排序和解释

   EV 不是独立顶层系统层，而是 Runtime Optimizer Layer 的内部证据引擎。

4. **约束与校准层**
   负责参数更新、风险阈值调整、行为约束、预算修正。

5. **研究与知识扩展层**
   负责后续研究、知识沉淀、失败案例回收与策略增强，不作为 v1/v2 主闭环前提。

> **实现补充**：`03_snapshot_and_ingestion` 负责输入快照与采集；`08_allocation_engine` 负责生成 `candidate_allocations`。二者是当前冻结版实现中的关键支撑模块，不改变本节的宏观分层口径。

### 1.2 一个编排器角色

6. **Orchestrator**
   横向穿透全系统，负责触发、路由、阻断、升级、降级、日志记录与 workflow 编排。
   它不是策略模块，不直接做目标求解，也不直接做动作排序。

### 1.3 一个 shared 工具层

7. **shared 工具层**
   提供可复用的底层工具，不承载业务语义。
   例如：

* 概率模拟工具
* 协方差矩阵构造
* 时间与日期工具
* 公共校验器
* 通用类型
* 日志工具

---

## 2. 顶层职责边界

### 2.1 Goal Solver

Goal Solver 是系统中枢，负责：

* 根据目标、期限、现金流、当前资产与约束做全局目标求解
* 输出基线成功概率
* 输出失败尾部与缺口来源
* 输出基线成功概率、失败尾部、结构预算与风险预算（不生成 `candidate_allocations`）
* 输出结构预算与风险预算

Goal Solver 不负责：

* 候选动作排序
* 决策卡解释
* 行为惩罚打分
* 运行期局部动作选择

---

### 2.2 EV

### 2.2 EV 引擎（运行期证据引擎）

EV（Expected Value）引擎属于**运行期评估与动作优化层（Runtime Optimizer Layer）**，是该层内部的证据引擎子模块，而不是独立顶层系统层。

其职责是在 Runtime Optimizer 已完成运行模式判定、状态快照组装、候选动作生成之后，对候选动作进行可行性过滤、分项打分、排序与结果解释，输出结构化 EV 报告，供上游编排层与下游展示层消费。

EV 引擎负责：
- 接收 Runtime Optimizer 提供的 `EVState` 与 `candidate_actions`
- 对候选动作执行 Feasibility Filter
- 对通过过滤的动作进行 GoalImpact / RiskPenalty / SoftConstraintPenalty / BehaviorPenalty / ExecutionPenalty 五项评分
- 聚合总分并生成动作排序
- 输出推荐动作、次优动作、推荐理由与 `EVReport`

EV 引擎不负责：
- 运行模式判定（MONTHLY / EVENT / QUARTERLY）
- 运行期状态快照组装
- 候选动作生成
- RuntimeOptimizerResult 汇总
- 全局目标求解
- 参数校准
- 状态持久化
- 决策卡 UI 文本与布局生成

换言之，Runtime Optimizer 决定“当前要评估哪些动作”，EV 引擎决定“这些候选动作里哪个更优、优在哪里、为什么优”。

---

### 2.3 Goal Solver 与 EV 的关系

两者关系如下：

* Goal Solver：回答 **“够不够”**
* EV：回答 **“怎么改更优”**

Goal Solver 先定义账户当前的基线世界，EV 再在这个基线之上比较局部动作。

Goal Solver 与 EV **可以共享底层概率模拟工具**，但不得混为同一模块，也不得共用同一个业务语义接口。

---

### 2.4 Orchestrator

Orchestrator 负责：

* 识别触发条件
* 决定调用哪个 workflow
* 决定是走建档、月度巡检、事件升级、动作优化还是复盘
* 控制阻断与升级
* 记录状态流转

Orchestrator 不负责：

* 全局求解
* 局部打分
* 参数校准公式
* 资产配置逻辑本身

---

## 3. 系统总流程图

### 3.1 总体主流程（文字版）

```text id="9lbb0m"
[治理与账户定义层]
  输出：目标、IPS、权限基线、战略配置基线
                |
                v
[08 Allocation Engine]
  输出：candidate_allocations
                |
                v
[Goal Solver / 目标求解层]
  输出：基线成功概率、失败尾部、结构预算、风险预算
                |
                v
[运行期评估与动作优化层]
  输入：账户状态 + 市场状态 + 约束状态 + 行为状态 + Goal Solver 基线
  内部：Candidate Generator -> Feasibility Filter -> EV -> Decision Card
                |
                v
[执行与复审]
  输出：执行记录、偏差、状态变化、行为日志
                |
                v
[约束与校准层]
  输出：参数修正、风险阈值修正、预算修正、行为约束修正
                |
                └──────────────┐
                               v
               回写 Goal Solver / Runtime Optimizer / Orchestrator

[研究与知识扩展层]
  吸收：复盘结果、失败案例、研究结论
  反哺：未来增强，不进入 v1/v2 主闭环

[Orchestrator]
  横向穿透全流程：触发、路由、阻断、升级、降级、记录状态流转
```

---

## 4. 三条主工作流

系统至少有三条顶层主 workflow。

### 4.1 首次建档流

用于账户初始化。

流程：

1. 收集账户与目标信息
2. 生成 IPS 与治理边界
3. 调用 Goal Solver 求解基线世界
4. 形成初始战略配置与目标卡
5. 写入系统基线状态

输出：

* 目标卡
* IPS
* 基线成功概率
* 战略配置基线
* 初始风险预算

---

### 4.2 月度运行流

用于周期性巡检。

流程：

1. Orchestrator 触发月度检查
2. 读取当前账户、市场、行为、约束状态
3. 比对偏离、风险线、预算线
4. 生成候选动作
5. 过滤不可行动作
6. 由 EV 排序
7. 输出决策卡
8. 执行或记录不执行理由
9. 将执行结果回写校准层

输出：

* EVReport
* Decision Card
* 执行记录
* 月度复盘输入

---

### 4.3 事件触发流

用于市场冲击、行为异常、预算越界等事件。

流程：

1. Orchestrator 检测到事件触发
2. 判断是否需要升级 workflow
3. 进入运行期评估层
4. 强制加入特定候选动作（如 OBSERVE / FREEZE / 风险收缩）
5. EV 做动作比较
6. 输出事件型决策卡
7. 若必要，触发校准层更新行为阈值与约束参数

输出：

* 事件型 EVReport
* 风险/行为处置建议
* 约束修正输入

---

## 5. 运行期评估与动作优化层（内部总流程）

运行期评估与动作优化层由 **Runtime Optimizer** 作为父模块承载，EV Engine 作为其内部证据引擎子模块承载评分与排序能力。

该层的内部总流程如下：

```text
Runtime Optimizer
   ├── 1. State Snapshot Builder
   │       - 读取 live portfolio / market / behavior / IPS / goal baseline
   │       - 组装运行期状态快照
   │
   ├── 2. Candidate Generator
   │       - 基于运行模式与状态生成候选动作
   │       - 输出结构化 Action 列表
   │
   ├── 3. EV Engine
   │       ├── 3.1 Feasibility Filter
   │       ├── 3.2 GoalImpact
   │       ├── 3.3 RiskPenalty
   │       ├── 3.4 SoftConstraintPenalty
   │       ├── 3.5 BehaviorPenalty
   │       ├── 3.6 ExecutionPenalty
   │       └── 3.7 Ranking + EVReport
   │
   ├── 4. RuntimeOptimizerResult
   │       - 汇总推荐动作、排序结果、EV 报告与运行元数据
   │
   └── 5. Decision Card Input
           - 向 Decision Card 层提供结构化输入
```

### 5.1 Runtime Optimizer 的职责

Runtime Optimizer 是运行期评估层的外层编排容器，负责：

运行模式判定
输入校验
状态快照组装
候选动作生成
调用 EV 引擎
汇总 RuntimeOptimizerResult
将结构化结果交给 Orchestrator 与 Decision Card

### 5.2 EV Engine 的职责

EV Engine 是 Runtime 内部的评分子模块，负责：

对候选动作执行可行性过滤
对通过过滤的动作执行五项打分
输出排序结果与推荐动作
生成 EVReport

### 5.3 Decision Card 的职责

Decision Card 不属于 Runtime Optimizer 或 EV Engine 的内部实现。
其职责是消费 RuntimeOptimizerResult / EVReport 等结构化结果，生成面向用户的决策展示内容。

因此，运行期评估层的终点应理解为“生成供展示层消费的结构化结果”，而不是在本层内部直接拼装 UI 成品卡片。
---

## 6. 总体代码架构（文件树）

以下为推荐的顶层文件树。目标是：

> **按模块边界隔离上下文，避免 Codex 将 Goal Solver、EV、Orchestrator、Decision Card、Calibration 等逻辑互相污染。**

```text id="bpbnsm"
project_root/
├── system/
│   ├── 00_system_topology_and_main_flow.md
│   ├── 02_goal_solver.md
│   ├── 03_snapshot_and_ingestion.md
│   ├── 04_runtime_optimizer.md
│   ├── 05_constraint_and_calibration.md
│   ├── 07_orchestrator_workflows.md
│   ├── 08_allocation_engine.md
│   ├── 09_decision_card_spec.md
│   └── 10_ev_engine.md
│
├── src/
│   ├── shared/
│   │   ├── probability_engine.py      # 通用概率模拟工具：协方差构造、路径抽样、终值概率统计
│   │   ├── validators.py              # 通用校验器：矩阵、权重、范围检查
│   │   ├── types.py                   # 共享基础类型（仅通用，不承载业务语义）
│   │   └── logging_utils.py           # 调试/复盘模式下的结构化日志工具
│   │
│   ├── snapshot_ingestion/
│   │   ├── types.py                   # SnapshotBundle 与五域 RawSnapshot 类型
│   │   ├── validators.py              # 各域校验与 bundle 校验
│   │   └── builder.py                 # build_snapshot_bundle() / bundle_id 派生
│   │
│   ├── allocation_engine/
│   │   ├── types.py                   # candidate_allocations 及候选配置相关类型
│   │   ├── generator.py               # 候选战略配置生成主入口
│   │   └── filters.py                 # 配置候选去重、约束预筛与排序辅助
│   │
│   ├── goal_solver/
│   │   ├── types.py                   # Goal Solver 专属输入输出类型
│   │   ├── solver.py                  # 全局目标求解主入口
│   │   ├── allocation_search.py       # 对 AllocationEngine 提供的候选做评估/排序辅助
│   │   └── risk_evaluator.py          # 失败尾部、回撤、可达性评估
│   │
├── runtime_optimizer/
│   ├── types.py
│   ├── state_builder.py
│   ├── candidates.py
│   ├── optimizer.py
│   └── ev_engine/
│       ├── types.py                   # EV 专属类型：EVState / Action / EVParams / EVReport
│       ├── feasibility.py             # 硬约束过滤
│       ├── scorer.py                  # 五项打分与总分计算
│       ├── report_builder.py          # 排序、理由生成、置信度、EVReport 构造
│       ├── engine.py                  # run_ev_engine / explain_action 对外主入口
│       └── fixtures/
│           └── sample_ev_state.py     # EV 最小可运行夹具
│   │
│   ├── orchestrator/
│   │   ├── workflows.py               # workflow 选择与路由
│   │   ├── triggers.py                # 月度/事件/手动触发规则
│   │   └── state_router.py            # 状态快照流转与编排
│   │
│   ├── decision_card/
│   │   └── builder.py                 # 消费 EVReport 生成决策卡
│   │
│   └── calibration/
│       ├── params_updater.py          # 参数更新逻辑
│       └── review_loop.py             # 月度/季度复盘回写
│
└── tests/
    ├── test_goal_solver.py
    ├── test_ev_engine.py
    └── test_orchestrator.py
```

### 6.1 文件夹职责边界

goal_solver/
负责长期目标求解、基线权重生成、目标达成概率评估，以及供运行期层调用的 lightweight 目标重估能力。
runtime_optimizer/
负责运行模式判定、运行期状态快照组装、候选动作生成、调用 EV 引擎、汇总 RuntimeOptimizerResult。
runtime_optimizer/ev_engine/
负责 Feasibility Filter、五项打分、动作排序、推荐理由与 EVReport 构造。
orchestrator/
负责季度 / 月度 / 事件工作流编排、触发路由、上下游模块串联、状态持久化与调度控制。
decision_card/
负责将结构化结果转换为用户可读的决策卡内容与展示对象。
calibration/
负责参数回顾、阈值更新、偏差回灌与定期校准。

### 6.2 结构原则

Runtime Optimizer 是运行期动作优化层的父模块；EV Engine 是其内部证据引擎子模块。
因此，EV 不再作为独立顶层目录存在，而统一纳入 runtime_optimizer/ev_engine/ 之下。

---

## 7. shared 层职责说明

`shared/` 层的原则是：

> **只放通用底层工具，不放任何具体业务模块的语义。**

### 7.1 可以放进 shared 的内容

* 协方差矩阵构造
* 多元正态路径抽样
* 成功概率统计函数
* 通用矩阵校验
* 权重归一化校验
* 结构化日志工具
* 基础通用类型

### 7.2 不应该放进 shared 的内容

* Goal Solver 的“全局可达性”业务判断
* EV 的动作优先级
* Decision Card 文案规则
* Orchestrator 的 workflow 逻辑
* 行为惩罚系数与业务阈值

换句话说：

* **shared 放“怎么算”**
* **业务模块放“为什么算、何时算、输出给谁”**

---

## 8. 模块隔离约束

以下约束适用于整个项目：

### 8.1 Goal Solver 与 EV 必须分目录

* `goal_solver/` 只放全局目标求解逻辑
* `ev_engine/` 只放运行期动作优化逻辑
* 二者不得共用同一个业务语义入口

### 8.2 模块隔离与边界约束

系统采用“父层编排 + 子模块专职”的隔离原则，避免职责漂移与实现散落。

#### 8.2.1 Runtime Optimizer 与 EV Engine 的边界

`runtime_optimizer/` 负责：
- 运行模式判定
- 输入校验
- 状态快照组装
- 候选动作生成
- 调用 EV 引擎
- 汇总 `RuntimeOptimizerResult`

`runtime_optimizer/ev_engine/` 负责：
- Feasibility Filter
- GoalImpact / RiskPenalty / SoftConstraintPenalty / BehaviorPenalty / ExecutionPenalty
- 动作排序
- 推荐理由
- `EVReport` 构造
- `run_ev_engine(...)`

禁止将 EV 核心评分逻辑散落到以下目录：
- `goal_solver/`
- `orchestrator/`
- `decision_card/`
- `calibration/`
- `shared/`
- `runtime_optimizer/` 外层目录

同时，禁止将以下 Runtime 外层逻辑反向塞入 `runtime_optimizer/ev_engine/`：
- 运行模式判定
- 运行期状态快照组装
- 候选动作生成
- RuntimeOptimizerResult 汇总
- 工作流路由与调度控制

#### 8.2.2 Goal Solver 的边界

Goal Solver 负责长期目标求解与概率评估，不承担运行期动作评分。  
EV 中涉及 GoalImpact 的部分，只能通过 Goal Solver 提供的 lightweight 接口获取，不允许在 EV 内部维护第二套独立目标求解器。

#### 8.2.3 Decision Card 的边界

Decision Card 只负责展示层结构与文案生成。  
不负责候选动作生成、不负责 EV 打分、不负责运行期编排，也不负责目标求解。

#### 8.2.4 历史版本兼容说明

历史设计中曾将 EV 相关实现放在独立顶层目录 `src/ev_engine/` 下，或出现过独立 `goal_impact_estimator.py` 的设想。  
当前冻结版本不再采用该组织方式：

- EV 统一作为 `runtime_optimizer/ev_engine/` 子模块存在
- GoalImpact 一律通过 Goal Solver lightweight 接口获取
- 不再维护独立 `goal_impact_estimator.py` 业务模块

### 8.3 shared 只能做通用工具

禁止在 `shared/` 中写：

* “推荐动作是什么”
* “风险是否可接受”
* “目标是否可达”
* “该生成哪种决策卡”

shared 不能变成一个隐性业务中枢。

### 8.4 Orchestrator 不得侵入策略细节

Orchestrator 只能：

* 触发
* 路由
* 升级
* 降级
* 记录

不得直接实现：

* EV 打分
* Goal Solver 核心求解
* 参数校准公式

---

## 9. v1 代码组织目标

这套架构的目标不是“面向未来无限扩展”，而是：

1. **先把模块边界钉死**
2. **先把主流程跑通**
3. **先把 EV、Goal Solver、Orchestrator 解耦**
4. **先避免 Codex 在实现时跨模块串味**
5. **先保证后续可以分别替换 Goal Solver、EV、shared 工具而不牵一发动全身**

---

## 10. 建议实现顺序

建议按以下顺序开发：

1. `shared/` 最小工具层
2. `goal_solver/` 主入口与最小可运行求解
3. `ev_engine/` 完整闭环
4. `decision_card/`
5. `orchestrator/`
6. `calibration/`
7. 测试与夹具

原因：

* Goal Solver 先给出基线世界
* EV 再消费这个基线做动作排序
* Decision Card 消费 EVReport
* Orchestrator 最后负责把各层串起来
* Calibration 放在第一轮主闭环能跑起来之后再接

---

## 11. 文件关联索引

| 文件                                 | 关系               |
| ---------------------------------- | ---------------- |
| `02_goal_solver.md`                | 全局目标求解模块规格       |
| `03_snapshot_and_ingestion.md`     | 输入快照与采集层 |
| `04_runtime_optimizer.md`          | 运行期动作优化层总规格 |
| `05_constraint_and_calibration.md` | 参数与约束回写规则 |
| `08_allocation_engine.md`          | `candidate_allocations` 的唯一来源 |
| `07_orchestrator_workflows.md`     | 顶层 workflow 编排规则 |
| `09_decision_card_spec.md`         | 决策卡字段与展示规则       |
| `10_ev_engine.md`                  | EV 子系统详细规格       |

---

*文档版本：v1.0 | 状态：顶层结构已定稿 | 下次修订触发条件：首次模块联调完成后*

---

补充：

统一边界说明
Runtime Optimizer 是运行期评估与动作优化层的父模块，负责运行模式判定、状态快照组装、候选动作生成、调用 EV、汇总结果并向下游提供结构化输出。
EV Engine 是 Runtime Optimizer 的内部证据引擎子模块，负责对候选动作执行可行性过滤、分项打分、排序、推荐理由生成与 EVReport 构造。
Runtime 不实现 EV 评分细节；EV 不实现 Runtime 的模式控制、状态组装与候选生成。
Decision Card 消费 EVReport；Orchestrator 消费 RuntimeOptimizerResult；Goal Solver 提供基线与轻量概率重估能力。