# 04_runtime_optimizer.md
# 运行期评估与动作优化层设计规格 v2.1

> **文档定位**：本文件描述 **Runtime Optimizer（运行期评估与动作优化层父模块）** 的完整规格。
> 它是运行期层的外层容器文档；`10_ev_engine.md` 是其内部子模块规格。
>
> **统一边界（冻结版）**：
> - `04`（本文件）负责：运行模式判定、输入校验、状态组装、候选动作生成、主入口编排、结果汇总
> - `10_ev_engine.md` 负责：FeasibilityFilter、五项打分、排序、推荐理由、EVReport 构造
> - **候选生成不属于 EV；评分不属于 Runtime Optimizer；两者边界强制，不得混写。**
>
> **目录关系（冻结版）**：
> - `src/runtime_optimizer/` 是运行期层父目录
> - `src/runtime_optimizer/ev_engine/` 是 EV 子目录
> - EV 不再作为独立顶层目录存在
>
> **版本变更（v2.0 → v2.1）**：
> - (A) `min_candidates` 改为 2，明确 v1 兜底仅保证 FREEZE+OBSERVE；分离"生成目标"与"兜底"语义
> - (B) `_deduplicate_candidates` 去重键改为语义键（ActionType + target_bucket + from_bucket + to_bucket）
> - (C) 删除 `RuntimeOptimizerParams.optimizer_params_version` 冗余字段，只保留 `version`
> - (D) `build_ev_state()` 补字段映射说明：`live_portfolio.total_value → AccountState.total_portfolio_value`
>
> **版本变更（v1 → v2.0）**：
> - (#1)  统一 EVENT OBSERVE 触发规则：仅行为子触发时强制加入，其他子触发不强制
> - (#2)  统一 MONTHLY REBALANCE_FULL：默认禁止，硬偏离例外放开，全文语义统一
> - (#3)  修正 min_candidates 补充逻辑：依次补 FREEZE、OBSERVE 直到下限，参数注释对齐
> - (#4)  EVENT REBALANCE_FULL 细分四类子触发，各自决定是否允许生成
> - (#5)  runtime_optimizer/ 与 ev_engine/ 边界在文档多处显式声明
> - (#6)  EVReport.trigger_type 扩展支持 "quarterly"；QUARTERLY 禁止伪装成 "monthly"
> - (#7)  GoalImpact 调用禁止 override；路径数/seed/假设统一由 GoalSolverInput.solver_params 提供
> - (#8)  goal_impact_estimator.py 明文裁决不应创建，GoalImpact 在 scorer.py 调用轻量入口
> - (#9)  LivePortfolioSnapshot 新增 current_drawdown 正式字段，占位移除
> - (#10) validate_ev_state_inputs() 新增三条跨模块一致性校验
> - (#11) 新增候选贫乏降级协议 _apply_poverty_protocol()，RuntimeOptimizerResult 新增 candidate_poverty
> - (#12) 硬化 _find_underweight_buckets() 四级排序键
> - (#13) 新增 _clip_amount_pct() 生成前裁剪
> - (#14) 硬化 ADD_DEFENSE 目标桶选择规则（四级优先级 + cash_source 约定）
> - (#15) 硬化行为冷静期阻断契约：触发条件 / FREEZE+OBSERVE 强制保留 / recent_chasing_flag 仅软罚
> - (#16) QUARTERLY 必须使用本轮新基线，禁止读取旧基线参与本轮比较
> - (#17) 1.2 与主入口均明文声明不输出 Decision Card，不构造 UI 文本
> - (#18) 末尾新增与 00_system_topology_and_main_flow.md 实现层差异冻结说明

---
## 0. 一句话定义

**Runtime Optimizer 是运行期评估与动作优化层的父模块。**

它不做全局目标求解，不做参数校准，不做决策卡渲染，也不做 EV 评分细节。它只做一件事：

> 在 Orchestrator 触发后，基于当前账户状态、市场状态、约束状态、行为状态与 Goal Solver 基线，
> 组装运行期状态快照，生成候选动作，调用 EV Engine 完成过滤与评分，
> 最终汇总为 `RuntimeOptimizerResult`，供 Orchestrator 与 Decision Card 消费。

核心分工如下：

| 模块 | 职责 |
|------|------|
| Goal Solver（02） | 回答“目标够不够” |
| **Runtime Optimizer（04）** | 回答“当前该评估哪些候选动作，以及如何组织本轮运行期优化流程” |
| EV Engine（10） | 回答“候选动作里哪个更优、为什么更优” |
| Decision Card（09） | 消费结构化结果，生成用户可见展示内容 |

---
## 1. 职责边界

### 1.1 Runtime Optimizer 负责

Runtime Optimizer 负责以下事项：

- 接收 Orchestrator 触发信号，确定运行模式（MONTHLY / EVENT / QUARTERLY）
- 执行前置输入校验（快照一致性 / 时效 / 桶宇宙兼容）
- 构建本轮运行期状态快照（`EVState`）
- 按模式与子触发规则生成候选动作集合
- 预填并裁剪 `amount_pct`
- 标记 `cooldown_applicable`
- 调用 `run_ev_engine(...)`
- 执行候选贫乏降级协议
- 汇总 `RuntimeOptimizerResult`
- 向 Orchestrator 与 Decision Card 提供结构化输出

### 1.2 Runtime Optimizer 不负责

Runtime Optimizer 不负责以下事项：

- **全局目标求解**：由 `02_goal_solver.md` 负责
- **GoalImpact 计算**：由 `10_ev_engine.md` 中 `scorer.py` 内部调用 Goal Solver lightweight 接口完成
- **FeasibilityFilter 实现**：由 EV Engine 负责
- **五项 EV 打分**：由 EV Engine 负责
- **动作排序与推荐理由生成**：由 EV Engine 负责
- **EVReport 构造**：由 EV Engine 负责
- **Decision Card 文本与布局输出**：由 `09_decision_card_spec.md` 负责
- **参数校准**：由 `05_constraint_and_calibration.md` 负责
- **持久化、执行日志写入、workflow 路由**：由 Orchestrator 负责

### 1.3 Runtime 与 EV 的关系

Runtime Optimizer 是运行期动作优化层的父模块；EV Engine 是其内部证据引擎子模块。

两者关系固定如下：

- Runtime 决定“本轮评估哪些候选动作”
- EV 决定“候选动作中哪个更优”
- Runtime 汇总 EV 输出，形成运行期结果
- Decision Card 消费运行期结果，生成展示内容

因此：

- Runtime **只编排，不评分**
- EV **只评分，不生成候选**

---

## 2. 层内子模块总览

Runtime Optimizer 作为运行期层父模块，内部由以下两个职责域构成：

```text
Runtime Optimizer
   ├── validate_ev_state_inputs()   # 输入校验
   ├── build_ev_state()             # 状态快照组装
   ├── generate_candidates()        # 候选动作生成
   ├── run_ev_engine()              # 调用 EV 子模块
   ├── _apply_poverty_protocol()    # 候选贫乏降级
   └── RuntimeOptimizerResult       # 结果汇总
```
其中：

```text
runtime_optimizer/
   ├── 外层职责
   │   ├── mode routing
   │   ├── validation
   │   ├── state building
   │   ├── candidate generation
   │   ├── result aggregation
   │   └── runtime metadata
   │
   └── ev_engine/
       ├── feasibility filter
       ├── EV scoring
       ├── ranking
       ├── recommendation reasons
       └── EVReport
```

### 2.1 父子边界（硬约束）
runtime_optimizer/ 外层只承载：
运行模式
输入校验
状态组装
候选动作生成
主入口编排
RuntimeOptimizerResult 汇总
runtime_optimizer/ev_engine/ 子目录只承载：
FeasibilityFilter
五项打分
排序
推荐理由
EVReport
### 2.2 禁止事项
禁止在 runtime_optimizer/ 外层实现 EV 评分细节
禁止在 runtime_optimizer/ev_engine/ 中实现候选动作生成
禁止 Runtime 与 EV 互相侵入对方正式职责

---


---
## 3. 上下游关系

```text
GoalSolverOutput / GoalSolverInput --+
LivePortfolio                        +-> validate_ev_state_inputs()
MarketState / ConstraintState        |
BehaviorState / EVParams             +-> build_ev_state() -> EVState --+
RuntimeOptimizerParams -------------------------------------------------+
                                                                         |
                                                           generate_candidates()
                                                                         |
                                                              list[Action]
                                                                         |
                                                             run_ev_engine()
                                                                         |
                                                 +-----------------------+----------------------+
                                                 |                                              |
                                                 v                                              v
                                           EVReport                                  ranked_actions / reasons
                                                 |
                                                 v
                                      RuntimeOptimizerResult
                                                 |
                           +---------------------+----------------------+
                           |                                            |
                           v                                            v
                    Orchestrator 消费                              Decision Card 消费
```

### 3.1 上游

本层的上游包括：

Goal Solver 基线输出与输入快照
当前 live portfolio
当前 market / constraint / behavior 状态
校准后的 EVParams 与 RuntimeOptimizerParams

### 3.2 下游

本层的下游输出是 RuntimeOptimizerResult，其中包含：

ev_report
state_snapshot
candidates_generated
candidates_after_filter
candidate_poverty
运行元数据

### 3.3 输出边界说明

EVReport 是 EV 子模块输出的结构化评分结果
RuntimeOptimizerResult 是 Runtime 父层输出的结构化运行期结果
Decision Card 消费前者或后者，但不属于本层内部实现

---

## 4. 触发条件与运行模式

### 4.1 RuntimeOptimizerMode 枚举

```python
from enum import Enum

class RuntimeOptimizerMode(Enum):
    MONTHLY   = "monthly"   # 月度例行巡检
    EVENT     = "event"     # 事件触发（偏离/行为/风险线，细分四类子触发）
    QUARTERLY = "quarterly" # 季度复审（Goal Solver 完整重算前置）
```

### 4.2 月度例行模式（MONTHLY）

**触发条件**：当月固定日期（Orchestrator 检测）

**候选生成规则**（#2）：
- 候选集以"不动 / 补低配"为主轴
- **REBALANCE_FULL：默认不生成；仅当最大桶偏离 >= deviation_hard_threshold 时，作为例外加入**
- REBALANCE_LIGHT：偏离 >= deviation_soft_threshold 时生成
- 优先使用新增资金，不主动触发卖出型再平衡

**基线**：Goal Solver 不做完整重算，使用 Orchestrator 持有的上次 GoalSolverOutput

### 4.3 事件触发模式（EVENT）

EVENT 模式内部区分**四类子触发**，规则各不相同（#4）。
一次 EVENT 可同时触发多个子触发，候选集取并集，去重后截断到 max_candidates。
子触发类型由 Orchestrator 判断，以标志参数传入本层（详见 §9.1 主入口签名）。

#### 子触发 A：结构性偏离事件

- **触发条件**：任意资产桶偏离 >= deviation_hard_threshold
- OBSERVE：**不强制加入**（#1）
- REBALANCE_LIGHT：偏离 >= deviation_soft_threshold 即可生成
- **REBALANCE_FULL：偏离 >= deviation_soft_threshold 即可生成**（比 MONTHLY 宽松）

#### 子触发 B：行为事件

- **触发条件**：high_emotion_flag == True 或 panic_flag == True 或用户发起高热叙事请求
- **FREEZE：强制保留**（截断时不得移除）
- **OBSERVE：强制加入**（#1）
- **REBALANCE_FULL：禁止生成**
- 所有其他动作：cooldown_applicable = True，由 FeasibilityFilter 冷静期规则拦截
- recent_chasing_flag == True：**仅进入 BehaviorPenalty 软惩罚，不触发冷静期阻断**（#15）

#### 子触发 C：回撤风险事件

- **触发条件**：LivePortfolioSnapshot.current_drawdown >= drawdown_event_threshold
- **ADD_DEFENSE：强制生成**（目标桶按 §7.5 规则选择）
- REBALANCE_FULL：**不默认生成**（除非同时触发子触发 A）
- OBSERVE：不强制（除非同时触发子触发 B）

#### 子触发 D：卫星超配事件

- **触发条件**：卫星总仓 > satellite_cap + satellite_overweight_threshold
- **REDUCE_SATELLITE：强制生成**
- OBSERVE：不强制

### 4.4 季度复审模式（QUARTERLY）

**触发条件**：每季度一次或 CalibrationLayer 重大参数变更时

**前置约束（Orchestrator 负责执行）**：
- Orchestrator 必须在调用本层**之前**先完成 run_goal_solver() 完整重算，得到新基线
- **本轮所有 GoalImpact 计算必须基于当轮刚完成的新基线；禁止传入上季度旧基线参与本轮比较**（#16）

**候选生成**：规则与 MONTHLY 相同

**EVReport.trigger_type**：**必须填写 "quarterly"，禁止填 "monthly" 掩盖季度复审语义**（#6）

### 4.5 模式对照表

| 特性                     | MONTHLY       | EVENT-A 结构偏离  | EVENT-B 行为    | EVENT-C 回撤   | EVENT-D 卫星  | QUARTERLY      |
|------------------------|-------------|-----------------|---------------|--------------|-------------|---------------|
| FREEZE 保留              | 是           | 是               | **强制**        | 是             | 是           | 是             |
| OBSERVE 强制加入           | 否          | **否**（#1）      | **强制**（#1）   | 否             | 否          | 否            |
| ADD_CASH_*              | 若有可用资金   | 若有可用资金         | 冷静期拦截        | 若有可用资金      | 若有可用资金   | 若有可用资金      |
| REBALANCE_LIGHT         | 偏离>=soft   | 偏离>=soft        | 冷静期拦截        | 偏离>=soft     | 偏离>=soft   | 偏离>=soft     |
| REBALANCE_FULL          | **偏离>=hard** | **偏离>=soft**  | **禁止**（#4）  | 不默认          | 偏离>=hard   | **偏离>=hard** |
| REDUCE_SATELLITE        | 若超配        | 若超配              | 冷静期拦截        | 若超配           | **强制**      | 若超配          |
| ADD_DEFENSE             | 否          | 否               | 否             | **强制**         | 否           | 否            |
| Goal Solver 完整重算（前置） | 否          | 否               | 否             | 否             | 否           | **是（Orchestrator）** |
| EVReport.trigger_type   | "monthly"   | "event"          | "event"        | "event"       | "event"     | **"quarterly"**（#6） |

---

## 5. 数据类型定义

### 5.1 LivePortfolioSnapshot（#9）

```python
@dataclass
class LivePortfolioSnapshot:
    weights: dict[str, float]      # 资产桶 -> 当前实际占比（0~1），合计约为 1
    total_value: float             # 总组合市值（元）
    available_cash: float          # 可用于本次投入的资金（元）
    goal_gap: float                # 目标缺口（正=缺，负=超；元）
    remaining_horizon_months: int  # 距目标剩余月数，必须 > 0
    as_of_date: str                # 快照日期，ISO 格式
    current_drawdown: float        # 账户从近期历史高点的回撤比例（0~1）
                                   # 由 Orchestrator 维护历史高点并计算后填入
                                   # 账户初始化阶段填 0.0，不触发子触发 C
```

> **current_drawdown 责任归属**：Orchestrator 负责维护历史高点净值并计算。
> 本层不做任何估算或占位处理。current_drawdown 是 v1 的正式字段，非占位。（#9）

### 5.2 DeviationLevel

```python
class DeviationLevel(Enum):
    NONE   = "none"   # 最大桶偏离 < deviation_soft_threshold
    MINOR  = "minor"  # deviation_soft_threshold <= 最大偏离 < deviation_hard_threshold
    SEVERE = "severe" # 最大偏离 >= deviation_hard_threshold
```

### 5.3 RuntimeOptimizerParams

本层不拥有 `RuntimeOptimizerParams` 的类型定义权。冻结版的唯一正式定义位于
`05_constraint_and_calibration.md` / `calibration.types`；04 只 import 使用，不在本地重复声明同名 dataclass。

```python
from calibration.types import RuntimeOptimizerParams
```

本层实际消费的关键字段如下（字段定义与默认值以 05 为准）：

| 字段 | 在 04 中的用途 |
|---|---|
| `deviation_soft_threshold / deviation_hard_threshold` | 判定偏离等级、触发 `REBALANCE_LIGHT / REBALANCE_FULL` |
| `satellite_overweight_threshold` | 判定卫星超配事件（EVENT-D） |
| `drawdown_event_threshold` | 判定回撤风险事件（EVENT-C） |
| `min_candidates / max_candidates` | 候选集兜底与截断 |
| `min_cash_for_action / new_cash_split_buckets / new_cash_use_pct` | 新增资金候选生成 |
| `defense_add_pct` | `ADD_DEFENSE` 的默认目标增量 |
| `rebalance_full_allowed_monthly` | MONTHLY 模式下的完整再平衡开关约束 |
| `amount_pct_min / amount_pct_max` | 生成前裁剪与最小可执行比例 |
| `max_portfolio_snapshot_age_days` | live snapshot 与 Goal Solver 基线的时效校验 |
```

### 5.4 RuntimeOptimizerResult（#11）

```python
@dataclass
class RuntimeOptimizerResult:
    # 本层不构造决策卡，不输出 UI 文本成品。（#17）
    mode: RuntimeOptimizerMode
    ev_report: "EVReport"           # 定义于 10；DecisionCardBuilder（09）的直接输入
    state_snapshot: "EVState"       # 完整状态快照，供审计和复盘重放
    candidates_generated: int       # generate_candidates() 输出的候选数量
    candidates_after_filter: int    # 通过 FeasibilityFilter 后的数量（= len(ev_report.ranked_actions)）
    candidate_poverty: bool         # True = ranked_actions < 2，已触发降级协议
    run_timestamp: str              # ISO 8601 UTC 时间戳
    optimizer_params_version: str
    goal_solver_params_version: str
```

---

## 6. 状态快照构建（State Builder）

### 6.1 四组状态来源

| 状态组              | 类型定义位置 | 数据来源                               | 构建时机            |
|-------------------|------------|--------------------------------------|-------------------|
| `AccountState`    | 10         | build_account_state_baseline()（02）  | 每次触发重建          |
| `MarketState`     | 10         | 市场数据 + CalibrationLayer 最新参数    | Orchestrator 注入   |
| `ConstraintState` | 10         | IPS（01）+ CalibrationLayer 阈值      | Orchestrator 注入   |
| `BehaviorState`   | 10         | 行为监控模块（行为日志、情绪信号）         | Orchestrator 注入   |

### 6.2 前置校验（validate_ev_state_inputs）（#10）

```python
def validate_ev_state_inputs(
    live_portfolio: LivePortfolioSnapshot,
    constraint_state: ConstraintState,
    solver_output: GoalSolverOutput,
    solver_baseline_inp: GoalSolverInput,
    optimizer_params: RuntimeOptimizerParams,
) -> None:
    # 基础结构校验
    total = sum(live_portfolio.weights.values())
    assert abs(total - 1.0) < 0.01, f"weights 合计 {total:.4f}，应接近 1.0"

    assert constraint_state.bucket_category, "bucket_category 不能为空；必须显式提供，禁止字符串推断"

    unmapped = [b for b in live_portfolio.weights if b not in constraint_state.bucket_category]
    assert not unmapped, f"以下资产桶未在 bucket_category 中映射：{unmapped}"

    assert live_portfolio.remaining_horizon_months > 0
    assert live_portfolio.available_cash >= 0
    assert 0.0 <= live_portfolio.current_drawdown <= 1.0

    # 跨模块一致性校验 A：solver_output 与 solver_baseline_inp 必须来自同一次求解
    # 依据：02 中 GoalSolverInput.snapshot_id 与 GoalSolverOutput.input_snapshot_id 对应
    assert solver_output.input_snapshot_id == solver_baseline_inp.snapshot_id, (
        f"solver_output.input_snapshot_id ({solver_output.input_snapshot_id!r}) "
        f"与 solver_baseline_inp.snapshot_id ({solver_baseline_inp.snapshot_id!r}) 不匹配；"
        f"禁止将不同批次的求解输入与输出混用"
    )

    # 跨模块一致性校验 B：live_portfolio 时效
    import datetime
    try:
        snapshot_date = datetime.date.fromisoformat(live_portfolio.as_of_date)
        baseline_date = datetime.date.fromisoformat(solver_output.generated_at[:10])
        age_days = abs((baseline_date - snapshot_date).days)
        assert age_days <= optimizer_params.max_portfolio_snapshot_age_days, (
            f"live_portfolio.as_of_date ({live_portfolio.as_of_date}) 与基线生成日期 "
            f"({solver_output.generated_at[:10]}) 相差 {age_days} 天，"
            f"超过允许时效 {optimizer_params.max_portfolio_snapshot_age_days} 天"
        )
    except (ValueError, AttributeError) as e:
        raise AssertionError(f"日期字段格式错误，无法校验时效：{e}")

    # 跨模块一致性校验 C：桶宇宙兼容性
    target_buckets = set(solver_output.recommended_allocation.weights.keys())
    unknown_buckets = set(live_portfolio.weights.keys()) - target_buckets
    if unknown_buckets:
        unknown_weight = sum(live_portfolio.weights.get(b, 0.0) for b in unknown_buckets)
        assert unknown_weight <= 0.05, (
            f"基线目标桶外的持仓 {unknown_buckets} 权重合计 {unknown_weight:.1%}，"
            f"超过 5% 容忍上限；请先清仓或更新基线配置"
        )
```

### 6.3 EVState 组装（build_ev_state）

```python
def build_ev_state(
    solver_output: GoalSolverOutput,
    solver_baseline_inp: GoalSolverInput,
    live_portfolio: LivePortfolioSnapshot,
    market_state: MarketState,
    behavior_state: BehaviorState,
    constraint_state: ConstraintState,
    ev_params: EVParams,
) -> EVState:
    # 不持久化；每次触发均重新构建
    # 字段映射说明：
    #   live_portfolio.total_value  -->  AccountState.total_portfolio_value
    #   live_portfolio.weights      -->  AccountState.current_weights
    # AccountState 的字段定义以 10_ev_engine.md 为准。
    # build_account_state_baseline() 负责上述映射，本层不重复实现。
    account_state = build_account_state_baseline(
        solver_output=solver_output,
        live_portfolio=live_portfolio,
        current_portfolio_value=live_portfolio.total_value,
    )
    return EVState(
        account=account_state,
        market=market_state,
        constraints=constraint_state,
        behavior=behavior_state,
        ev_params=ev_params,
        goal_solver_baseline_inp=solver_baseline_inp,
    )
```

### 6.4 GoalImpact 调用约束（冻结版）

GoalImpact 属于 EV Engine 的评分职责，不属于 Runtime Optimizer。

Runtime 层在任何情况下都不得：

- 自行实现 GoalImpact 估计逻辑
- 维护独立 `goal_impact_estimator.py`
- 复制 Goal Solver 的轻量求解逻辑
- 向 `run_goal_solver_lightweight()` 传入 override 参数
- 在 Runtime 层维护第二套长期目标评估口径

唯一允许的实现方式是：

- EV Engine 在 `runtime_optimizer/ev_engine/scorer.py` 内部
- 基于 Runtime 提供的 `EVState`
- 调用 Goal Solver 的 `run_goal_solver_lightweight()`
- 计算动作前后目标达成概率差值

路径数、seed、市场假设统一由 `GoalSolverInput.solver_params` 提供；Runtime 层不得覆盖。

### 6.5 ConstraintState.bucket_category 约定

bucket_category 和 bucket_to_theme 必须由 IPS（01）显式维护，每次触发时通过 Orchestrator 注入。
**禁止通过桶名字符串模式匹配自动推断类别。**

---

## 7. 候选动作生成（CandidateGenerator）

### 7.1 职责说明

- 只**生成**候选，不做可行性判断（可行性由 FeasibilityFilter（10）负责）
- 所有候选动作**必须在此预填并裁剪 amount_pct**，禁止以 None 传入 EVScorer
- cooldown_applicable 必须在此设置（FeasibilityFilter 冷静期规则依赖此字段）
- 候选集数量控制在 [min_candidates, max_candidates] 之间

### 7.2 偏离程度计算

```python
def _compute_deviation_level(state, params) -> DeviationLevel:
    if not state.account.deviation:
        return DeviationLevel.NONE
    max_dev = max(abs(v) for v in state.account.deviation.values())
    if max_dev < params.deviation_soft_threshold:
        return DeviationLevel.NONE
    elif max_dev < params.deviation_hard_threshold:
        return DeviationLevel.MINOR
    else:
        return DeviationLevel.SEVERE
```

### 7.3 候选动作生成主逻辑（#1/#2/#3/#4/#15）

```python
def generate_candidates(
    state, params, mode,
    behavior_event=False, structural_event=False,
    drawdown_event=False, satellite_event=False,
) -> list[Action]:
    candidates = []
    dev_level = _compute_deviation_level(state, params)
    satellite_weight = _compute_satellite_weight(state)
    has_cash = state.account.available_cash >= params.min_cash_for_action

    # 规则 1：FREEZE 始终存在
    candidates.append(_make_action_freeze())

    # 规则 2：行为子触发 -> 强制加入 OBSERVE（#1）
    # 非行为子触发不强制加入 OBSERVE
    if behavior_event or state.behavior.high_emotion_flag or state.behavior.panic_flag:
        candidates.append(_make_action_observe())

    # 规则 3：有可用资金 -> ADD_CASH_* 候选
    if has_cash:
        underweight_buckets = _find_underweight_buckets(state, params)
        for bucket in underweight_buckets[:params.new_cash_split_buckets]:
            action = _make_action_add_cash(state, params, bucket)
            if action is not None:
                candidates.append(action)

    # 规则 4：偏离触发再平衡候选
    if dev_level in (DeviationLevel.MINOR, DeviationLevel.SEVERE):
        candidates.append(_make_action_rebalance_light(state, params))

    # REBALANCE_FULL 生成条件（#2/#4，按子触发类型统一处理）：
    # - behavior_event：禁止生成
    # - structural_event（EVENT-A）：偏离 >= soft 即可生成
    # - 其他所有模式（MONTHLY / QUARTERLY / EVENT-C / EVENT-D）：仅 SEVERE 偏离时生成
    if not behavior_event:
        if structural_event and dev_level in (DeviationLevel.MINOR, DeviationLevel.SEVERE):
            candidates.append(_make_action_rebalance_full(state, params))
        elif not structural_event and dev_level == DeviationLevel.SEVERE:
            candidates.append(_make_action_rebalance_full(state, params))

    # 规则 5：卫星超配（子触发 D）-> REDUCE_SATELLITE
    sat_cap = state.constraints.satellite_cap
    if satellite_event or satellite_weight > sat_cap + params.satellite_overweight_threshold:
        candidates.append(_make_action_reduce_satellite(state, params, satellite_weight, sat_cap))

    # 规则 6：回撤风险（子触发 C）-> ADD_DEFENSE
    if drawdown_event:
        defense_action = _make_action_add_defense(state, params)
        if defense_action is not None:
            candidates.append(defense_action)

    # 规则 7：标记 cooldown_applicable（#15）
    is_cooldown_active = (
        behavior_event or state.behavior.high_emotion_flag or state.behavior.panic_flag
    )
    for action in candidates:
        if action.type in (ActionType.FREEZE, ActionType.OBSERVE):
            action.cooldown_applicable = False
        else:
            action.cooldown_applicable = is_cooldown_active

    # 规则 8：去重 + 截断（行为事件时强制保留 FREEZE 和 OBSERVE）
    # 去重键 = (ActionType, target_bucket, from_bucket, to_bucket)
    # 同语义的重复动作只保留第一个；ActionType 相同但桶不同（如两个 ADD_CASH_TO_CORE 分别指向不同桶）视为不同候选
    candidates = _deduplicate_candidates(candidates)
    if is_cooldown_active:
        protected = [c for c in candidates if c.type in (ActionType.FREEZE, ActionType.OBSERVE)]
        others = [c for c in candidates if c.type not in (ActionType.FREEZE, ActionType.OBSERVE)]
        others = _trim_by_action_priority(others, params.max_candidates - len(protected))
        candidates = protected + others
    else:
        candidates = _trim_by_action_priority(candidates, params.max_candidates)

    # 规则 9：保证最小候选集（#3）
    # 依次补充 FREEZE（若不存在）、OBSERVE（若不存在），直到达到 min_candidates（= 2）
    # v1 只保证 FREEZE + OBSERVE，不补更多模板候选
    # 若经规则 1~8 正常运行，候选集一般会达到 4+ 个；
    # 规则 9 只是极端情况下的最后兜底，不代表系统"承诺生成 4 个"
    if len(candidates) < params.min_candidates:
        if not any(c.type == ActionType.FREEZE for c in candidates):
            candidates.insert(0, _make_action_freeze())
    if len(candidates) < params.min_candidates:
        if not any(c.type == ActionType.OBSERVE for c in candidates):
            candidates.append(_make_action_observe())

    return candidates
```

### 7.4 `_find_underweight_buckets`：四级排序键（#12）

返回低配桶列表，排序键（优先级从高到低）：

1. 偏离幅度绝对值降序（偏离越大越优先补）
2. bucket_category 优先级：`core(0) > defense(1) > satellite(2)`
3. 目标权重降序（大桶优先）
4. 桶名称字典序升序（稳定打破平局，保证复盘可复现）

过滤规则：
- 只返回 deviation < -deviation_soft_threshold 的桶（真正低配）
- 卫星总仓已超配时，不返回任何 satellite 类桶

```python
def _find_underweight_buckets(state, params) -> list[str]:
    CATEGORY_PRIORITY = {"core": 0, "defense": 1, "satellite": 2}
    satellite_weight = _compute_satellite_weight(state)
    sat_cap = state.constraints.satellite_cap
    satellite_overweight = satellite_weight > sat_cap + params.satellite_overweight_threshold

    underweight = [
        b for b, dev in state.account.deviation.items()
        if dev < -params.deviation_soft_threshold
        and not (satellite_overweight and state.constraints.bucket_category.get(b) == "satellite")
    ]
    underweight.sort(key=lambda b: (
        state.account.deviation[b],                                           # 负数越小越优先
        CATEGORY_PRIORITY.get(state.constraints.bucket_category.get(b, "satellite"), 2),
        -state.account.target_weights.get(b, 0.0),
        b,
    ))
    return underweight
```

### 7.5 `ADD_DEFENSE` 目标桶选择规则（#14）

```python
def _select_defense_target_bucket(state) -> str | None:
    """
    从 defense 类桶中按四级优先级选择目标桶：
    1. 低配幅度最大（deviation 最负）
    2. 流动性最好（liquidity_flag == False 优先）
    3. 交易成本最低（transaction_fee_rate 最低）
    4. 桶名称字典序升序（稳定打破平局）
    若无 defense 类桶，返回 None。
    """
    defense_buckets = [b for b, cat in state.constraints.bucket_category.items() if cat == "defense"]
    if not defense_buckets:
        return None
    defense_buckets.sort(key=lambda b: (
        state.account.deviation.get(b, 0.0),
        1 if state.market.liquidity_flag.get(b, False) else 0,
        state.constraints.transaction_fee_rate.get(b, 0.0),
        b,
    ))
    return defense_buckets[0]


def _make_action_add_defense(state, params) -> "Action | None":
    """
    构造 ADD_DEFENSE 动作。
    amount_pct = min(defense_add_pct, 目标防御桶实际缺口)，再经 _clip_amount_pct 裁剪。
    裁剪后 amount_pct <= 0.0，返回 None。

    cash_source 规则：
    - available_cash >= defense_amount: cash_source = "new_cash", requires_sell = False
    - 否则: cash_source = "sell_rebalance", requires_sell = True,
      from_bucket = 超配最多的非 defense 桶
    """
    target_bucket = _select_defense_target_bucket(state)
    if target_bucket is None:
        return None

    bucket_deficit = max(0.0, -(state.account.deviation.get(target_bucket, 0.0)))
    raw_pct = min(params.defense_add_pct, bucket_deficit)
    amount_pct = _clip_amount_pct(raw_pct)

    if amount_pct <= 0.0:
        return None

    defense_amount = amount_pct * state.account.total_portfolio_value
    if state.account.available_cash >= defense_amount:
        cash_source, requires_sell, from_bucket = "new_cash", False, None
    else:
        cash_source, requires_sell = "sell_rebalance", True
        from_bucket = _find_most_overweight_bucket(state, exclude_category="defense")

    return Action(
        type=ActionType.ADD_DEFENSE,
        target_bucket=target_bucket,
        amount=defense_amount,
        amount_pct=amount_pct,
        from_bucket=from_bucket,
        to_bucket=target_bucket,
        cash_source=cash_source,
        requires_sell=requires_sell,
        expected_turnover=amount_pct,
        policy_tag="risk_reduce",
        cooldown_applicable=False,
        rationale=f"回撤触发防御补仓：{target_bucket}（+{amount_pct:.1%}）",
        explanation_facts=[
            f"账户回撤触发风险事件阈值 {params.drawdown_event_threshold:.0%}",
            f"目标防御桶 {target_bucket} 低配幅度 {bucket_deficit:.1%}",
        ],
    )
```

### 7.6 `amount_pct` 预填规范与生成前裁剪（#13）

```python
def _clip_amount_pct(raw_pct: float, upper_bound: float = 1.0) -> float:
    """
    将 amount_pct 裁剪到合法范围 [0.0, upper_bound]。
    裁剪后若 <= 0.0，调用方应跳过该候选。
    """
    return max(0.0, min(raw_pct, upper_bound))
```

各动作类型的 amount_pct 计算规范：

| 动作类型               | 计算方法                                                                         | 裁剪上限                                        |
|---------------------|--------------------------------------------------------------------------------|-----------------------------------------------|
| FREEZE              | 0.0                                                                            | —                                             |
| OBSERVE             | 0.0                                                                            | —                                             |
| ADD_CASH_TO_CORE    | min(available_cash × new_cash_use_pct, core_bucket_deficit_value) / total_value | 1.0                                           |
| ADD_CASH_TO_DEF     | 同上，取防御桶缺口                                                                | 1.0                                           |
| ADD_CASH_TO_SAT     | 同上，卫星桶缺口；且不超过 satellite_cap - current_satellite_weight               | satellite_cap - current_satellite_weight      |
| REBALANCE_LIGHT     | 最大负偏离桶的偏离绝对值 × 50%                                                     | IPS 该桶上限与当前权重之差                         |
| REBALANCE_FULL      | 最大偏离桶的偏离绝对值（裁剪至不越过 target_weight 或 IPS 边界）                    | IPS 该桶边界与当前权重之差                         |
| REDUCE_SATELLITE    | satellite_weight - satellite_cap（超配量）                                       | satellite_weight                              |
| ADD_DEFENSE         | min(defense_add_pct, 目标防御桶实际缺口)                                          | 目标防御桶 IPS 上限与当前权重之差                   |

通用约束：
- 裁剪后 amount_pct <= 0.0，不生成该候选
- REBALANCE_* 若裁剪后仍越过 target_weight 或 IPS 边界，进一步裁剪至边界内

### 7.7 cooldown_applicable 设置规范与行为冷静期阻断契约（#15）

**冷静期触发条件**（任一为 True）：behavior_event / high_emotion_flag / panic_flag

**冷静期规则**：

| 动作类型              | cooldown_applicable | 说明                                  |
|--------------------|--------------------|---------------------------------------|
| FREEZE、OBSERVE     | False              | 始终允许，截断时强制保留                 |
| 其他所有动作           | True（冷静期激活时） | FeasibilityFilter 执行拦截              |
| 其他所有动作           | False（冷静期未激活）| 正常参与 EV 打分                        |

**recent_chasing_flag**：**仅进入 BehaviorPenalty 软惩罚，不触发冷静期阻断，不影响候选集构成。**

> CandidateGenerator 负责标记 cooldown_applicable；实际拦截由 FeasibilityFilter（10）执行。两层职责不得混写。

### 7.8 辅助函数清单（内部，下划线前缀）

| 函数名                              | 职责                                              |
|----------------------------------|--------------------------------------------------|
| _compute_satellite_weight        | 计算卫星总仓占比                                   |
| _compute_deviation_level         | 计算 DeviationLevel                              |
| _find_underweight_buckets        | 低配桶四级排序（§7.4）                             |
| _select_defense_target_bucket    | ADD_DEFENSE 目标桶四级优先级（§7.5）               |
| _find_most_overweight_bucket     | 找超配最多的桶（ADD_DEFENSE sell_rebalance 用）     |
| _make_action_freeze              | 构造 FREEZE                                      |
| _make_action_observe             | 构造 OBSERVE                                     |
| _make_action_add_cash            | 构造 ADD_CASH_*（按桶类别选 ActionType，预填裁剪）   |
| _make_action_rebalance_light     | 构造 REBALANCE_LIGHT                             |
| _make_action_rebalance_full      | 构造 REBALANCE_FULL                              |
| _make_action_reduce_satellite    | 构造 REDUCE_SATELLITE                            |
| _make_action_add_defense         | 构造 ADD_DEFENSE（§7.5，含 cash_source 判断）      |
| _clip_amount_pct                 | 裁剪到 [0, upper_bound]（§7.6）                   |
| _deduplicate_candidates          | 按语义键（ActionType + target_bucket + from_bucket + to_bucket）去重，同语义保留第一个；FREEZE/OBSERVE 等无桶动作按 ActionType 去重 |
| _trim_by_action_priority         | 按 ActionType 优先级截断                          |

---


## 8. 运行期主入口与内部流程

### 8.1 主入口签名

```python
def run_runtime_optimizer(
    solver_output: GoalSolverOutput,
    solver_baseline_inp: GoalSolverInput,
    live_portfolio: LivePortfolioSnapshot,
    market_state: MarketState,
    behavior_state: BehaviorState,
    constraint_state: ConstraintState,
    ev_params: EVParams,
    optimizer_params: RuntimeOptimizerParams,
    mode: RuntimeOptimizerMode,
    structural_event: bool = False,
    behavior_event: bool = False,
    drawdown_event: bool = False,
    satellite_event: bool = False,
) -> RuntimeOptimizerResult:
    """
    Runtime Optimizer 对外唯一正式入口。

    约束：
    - 纯函数：不写外部状态，不做持久化，不发网络请求
    - 本函数不构造 Decision Card，不输出 UI 文本
    - QUARTERLY 模式下，Orchestrator 必须先完成 Goal Solver 完整重算
    """
```


### 8.2 执行流程

```
1. validate_ev_state_inputs()          # 快照一致性 + 时效 + 桶宇宙
2. build_ev_state()                    # 组装 EVState
3. generate_candidates()               # 按模式和子触发标志生成候选集
4. run_ev_engine(ev_state, candidates) # FeasibilityFilter -> EVScorer -> ReportBuilder
5. _apply_poverty_protocol()           # 候选贫乏降级（ranked_actions < 2 时触发）
6. 组装 RuntimeOptimizerResult         # 含 EVReport + state_snapshot + candidate_poverty
```

**执行语义说明**

第 1 步由 Runtime 外层负责数据契约检查
第 2 步由 Runtime 外层负责状态快照组装
第 3 步由 Runtime 外层负责候选动作生成
第 4 步进入 EV 子模块，完成过滤、评分、排序、报告构造
第 5 步回到 Runtime 外层，处理候选贫乏降级
第 6 步由 Runtime 外层汇总正式输出


```

### 8.3 主入口伪代码

```python
def run_runtime_optimizer(...) -> RuntimeOptimizerResult:
    import datetime

    validate_ev_state_inputs(
        live_portfolio=live_portfolio,
        constraint_state=constraint_state,
        solver_output=solver_output,
        solver_baseline_inp=solver_baseline_inp,
        optimizer_params=optimizer_params,
    )

    ev_state = build_ev_state(
        solver_output=solver_output,
        solver_baseline_inp=solver_baseline_inp,
        live_portfolio=live_portfolio,
        market_state=market_state,
        behavior_state=behavior_state,
        constraint_state=constraint_state,
        ev_params=ev_params,
    )

    candidates = generate_candidates(
        state=ev_state,
        params=optimizer_params,
        mode=mode,
        structural_event=structural_event,
        behavior_event=behavior_event,
        drawdown_event=drawdown_event,
        satellite_event=satellite_event,
    )
    candidates_generated = len(candidates)

    ev_report = run_ev_engine(
        ev_state=ev_state,
        candidates=candidates,
        trigger_type=mode.value,
    )

    candidates_after_filter = len(ev_report.ranked_actions)
    ev_report, poverty = _apply_poverty_protocol(ev_report)

    return RuntimeOptimizerResult(
        mode=mode,
        ev_report=ev_report,
        state_snapshot=ev_state,
        candidates_generated=candidates_generated,
        candidates_after_filter=candidates_after_filter,
        candidate_poverty=poverty,
        run_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        optimizer_params_version=optimizer_params.version,
        goal_solver_params_version=solver_baseline_inp.solver_params.version,
    )
```

### 8.4 QUARTERLY 模式前置约定（#16）

Orchestrator 在调用本层之前必须完成以下步骤：

```python
# Orchestrator 侧（非本层代码）
# --- QUARTERLY 前置：完整 Goal Solver 重算 ---
updated_solver_output = run_goal_solver(updated_solver_input)

# --- 然后调用本层，传入本轮新基线 ---
result = run_runtime_optimizer(
    solver_output=updated_solver_output,       # 本轮新基线，非上季度旧值
    solver_baseline_inp=updated_solver_input,  # 本轮新输入
    mode=RuntimeOptimizerMode.QUARTERLY,
    ...
)
# 禁止传入上季度遗留的 solver_output / solver_baseline_inp 参与本轮比较（#16）
```

本层不主动调用完整 Goal Solver，不检测传入值是否为"最新"；这是 Orchestrator 的职责。

### 8.5 候选贫乏降级协议（_apply_poverty_protocol）（#11）

```python
def _apply_poverty_protocol(ev_report: EVReport) -> tuple[EVReport, bool]:
    """
    若 ranked_actions < 2，触发降级协议。
    返回 (修改后的 ev_report, poverty_flag)。

    升级规则（由 Orchestrator 处理，不在本函数内）：
    - QUARTERLY 出现 poverty       -> 触发人工复审或参数检查
    - 连续两次 MONTHLY 出现 poverty -> 同上
    """
    if len(ev_report.ranked_actions) < 2:
        safe_types = {ActionType.FREEZE, ActionType.OBSERVE}
        # 强制低置信度
        ev_report = ev_report.replace(confidence_flag="low")
        # 推荐动作只允许 FREEZE 或 OBSERVE
        if ev_report.recommended_action and ev_report.recommended_action.type not in safe_types:
            safe_actions = [a for a in ev_report.ranked_actions if a.type in safe_types]
            ev_report = ev_report.replace(
                recommended_action=safe_actions[0] if safe_actions else None
            )
        return ev_report, True
    return ev_report, False
```

> Orchestrator 收到 `candidate_poverty=True` 时必须写入执行日志（`candidate_poverty_event`），
> 并检查是否需要升级为人工复审。

---

## 9. 输出规格与跨文档对齐

### 9.1 EVReport 字段对齐表

本层消费的 EVReport 字段（定义于 `10_ev_engine.md`，只读不修改）：

| 字段                              | 类型              | 说明                                              |
|---------------------------------|-----------------|--------------------------------------------------|
| `ranked_actions`                | list[Action]    | 可行动作排序列表；长度决定 candidates_after_filter      |
| `eliminated_actions`            | list[Action]    | FeasibilityFilter 淘汰的动作                        |
| `recommended_action`            | Action or None  | 推荐动作；_apply_poverty_protocol 可覆盖             |
| `confidence_flag`               | str             | "normal" or "low"；_apply_poverty_protocol 可覆盖  |
| `goal_solver_baseline`          | GoalSolverOutput| 基线求解结果                                        |
| `goal_solver_after_recommended` | GoalSolverOutput or None | 推荐动作后预测的求解结果                      |
| `trigger_type`                  | str             | "monthly" or "event" or **"quarterly"**（#6）     |

**trigger_type 约定（#6）**：QUARTERLY 模式必须填 "quarterly"；禁止填 "monthly" 掩盖季度复审语义。
复盘时通过 trigger_type 区分模式，不能依赖外部上下文。

### 9.2 goal_impact_estimator 裁决（#8）

> 本层不接受任何独立 `GoalImpactEstimator` 实现，不负责创建 `goal_impact_estimator.py`。
>
> GoalImpact 一律由 `ev_engine/scorer.py` 的 `compute_goal_impact()` 内部通过
> `run_goal_solver_lightweight()` 获取。
>
> 如果 Codex 按 00 旧文件树找到 `goal_impact_estimator.py` 的引用，
> 以本文件（04）和 10_ev_engine.md 为准，该模块不应创建。（#8）

### 9.3 跨文档差异说明

| 差异                                | 以哪版为准        | 说明                                                    |
|-----------------------------------|----------------|-------------------------------------------------------|
| 00 未列出 `runtime_optimizer/` 目录  | 以 04 为准      | 加法不冲突；实现以 §11 目录结构为准                          |
| 00 列出 `goal_impact_estimator.py` | 以 10 / 04 为准 | 该文件不应创建；GoalImpact 由 scorer.py 调用轻量 Goal Solver |
| 00 EVReport 字段名 scored_actions   | 以 10 / 04 为准 | 字段名已改为 `ranked_actions`，00 旧名称不应使用              |
| 00 trigger_type 无 "quarterly"    | 以 10 / 04 为准 | "quarterly" 是合法值，QUARTERLY 模式必须填写                |

---

## 10. 与其他层的边界重申

### 10.1 本层与 EV Engine（10）的边界

| 职责 | 归属 |
|------|------|
| 运行模式判定 | 04（Runtime 外层） |
| 子触发分类 | 04（Runtime 外层） |
| 输入校验 | 04（Runtime 外层） |
| EVState 组装 | 04（Runtime 外层） |
| 候选动作生成 | 04（Runtime 外层） |
| `amount_pct` 预填与裁剪 | 04（Runtime 外层） |
| `cooldown_applicable` 标记 | 04（Runtime 外层） |
| 候选贫乏降级协议 | 04（Runtime 外层） |
| FeasibilityFilter | 10（EV 子模块） |
| 五项打分 | 10（EV 子模块） |
| 动作排序 | 10（EV 子模块） |
| 推荐理由 | 10（EV 子模块） |
| EVReport 构造 | 10（EV 子模块） |
| GoalImpact 轻量重估 | 10（EV 子模块内部调用 02） |

冻结原则：

- Runtime 外层不得实现 EV 评分
- EV 子模块不得实现候选生成
- Runtime 是父层，EV 是子模块，不是并列顶层模块

### 10.2 本层与 Goal Solver（02）的边界

- 本层消费 `GoalSolverOutput` 与 `GoalSolverInput`
- 本层不调用完整 Goal Solver
- QUARTERLY 模式下完整 Goal Solver 重算由 Orchestrator 在本层调用前完成
- GoalImpact 所需的 lightweight 调用由 EV 子模块内部完成
- Runtime 层不得覆写 Goal Solver 的 lightweight 参数
- `RuntimeOptimizerParams` 的唯一来源是 05；04 不在本地维护第二套运行期参数口径

### 10.3 本层与 Orchestrator（07）的边界

- Orchestrator 负责触发、路由、阻断、升级、降级、状态写回
- Runtime 负责单轮运行期优化流程的纯函数执行
- Runtime 不判断是否“应该触发本轮”；它只处理“既然被触发，本轮怎么运行”

### 10.4 本层与 Decision Card（09）的边界

- 本层的终点是 `RuntimeOptimizerResult`
- Decision Card 消费本层输出，但不属于本层
- 本层不得输出 UI 成品文本，不得拼装卡片布局

---

## 11. 代码组织（文件树，冻结版）

```text
src/
└── runtime_optimizer/
    ├── types.py
    │   # LivePortfolioSnapshot
    │   # DeviationLevel
    │   # RuntimeOptimizerMode
    │   # RuntimeOptimizerParams
    │   # RuntimeOptimizerResult
    │
    ├── state_builder.py
    │   # validate_ev_state_inputs()
    │   # build_ev_state()
    │
    ├── candidates.py
    │   # generate_candidates()
    │   # _compute_*
    │   # _find_*
    │   # _make_action_*
    │   # _clip_amount_pct()
    │   # _trim_by_action_priority()
    │   # _deduplicate_candidates()
    │
    ├── optimizer.py
    │   # run_runtime_optimizer()
    │   # _apply_poverty_protocol()
    │
    └── ev_engine/
        ├── types.py
        ├── feasibility.py
        ├── scorer.py
        ├── report_builder.py
        ├── engine.py
        └── fixtures/
            └── sample_ev_state.py
```


### 文件职责约束

| 文件                            | 允许内容                                      | 禁止内容                               |
|-------------------------------|--------------------------------------------|------------------------------------|
| `runtime_optimizer/types.py`  | 类型定义、枚举、dataclass、默认值              | 业务逻辑、评分计算                       |
| `state_builder.py`            | 状态校验、EVState 组装                        | 候选生成、EV 打分                       |
| `candidates.py`               | 候选生成规则、amount_pct 计算与裁剪            | EV 打分、可行性过滤、EVReport 构造        |
| `optimizer.py`                | 主入口编排、贫乏降级协议                        | 评分细节、直接修改 EVState、持久化        |

### 11.1 外层目录负责的内容

runtime_optimizer/ 外层负责：

运行模式与子触发处理
输入校验
状态快照组装
候选动作生成
主入口编排
RuntimeOptimizerResult 汇总
### 11.2 EV 子目录负责的内容

runtime_optimizer/ev_engine/ 负责：

EV 正式类型
FeasibilityFilter
GoalImpact / Risk / Constraint / Behavior / Execution 五项评分
排序与推荐理由
EVReport
run_ev_engine(...)
### 11.3 禁止散落

禁止将 EV 核心评分实现散落到：

goal_solver/
orchestrator/
decision_card/
calibration/
shared/
runtime_optimizer/ 外层目录

同时禁止将 Runtime 外层逻辑反向塞入 runtime_optimizer/ev_engine/：

运行模式判定
输入校验
状态组装
候选动作生成
RuntimeOptimizerResult 汇总

### 11.4 历史版本兼容说明

历史设计中，EV 曾以独立顶层目录 `src/ev_engine/` 的方式描述。  
当前冻结版本不再采用该结构，统一改为：

- `Runtime Optimizer` 作为运行期层父目录
- `EV Engine` 作为 `runtime_optimizer/ev_engine/` 子目录

该调整不是单纯目录改名，而是为了反映真实职责边界：

- Runtime 是运行期流程编排者
- EV 是 Runtime 内部评分子模块

---

## 12. 当前版本范围说明

### 12.1 本文档包含

- Runtime 外层正式类型定义
- 输入校验规则
- 状态快照组装规则
- 候选动作生成规则
- amount_pct 预填与裁剪规则
- cooldown_applicable 标记规则
- 候选贫乏降级协议
- `run_runtime_optimizer()` 主入口
- Runtime 与 EV / Goal Solver / Orchestrator / Decision Card 的边界
- `runtime_optimizer/` 父目录与 `runtime_optimizer/ev_engine/` 子目录的工程组织规则

### 12.2 本文档不包含

- EV 五项评分细节
- FeasibilityFilter 具体实现
- EVReport 具体构造逻辑
- Goal Solver 完整求解细节
- Decision Card 展示层逻辑
- 持久化、日志写入、workflow 调度实现

---

## 13. 工程约束

| 约束                            | 说明                                                      | 处理方式                                  |
|-------------------------------|----------------------------------------------------------|------------------------------------------|
| `run_runtime_optimizer` 总耗时  | 目标 < 500ms                                             | 候选集控制 5~8 个；Goal Solver 轻量版 1000 路径 |
| `bucket_category` 必须显式提供   | 禁止字符串推断                                              | `validate_ev_state_inputs` 前置检查         |
| `amount_pct` 必须预填并裁剪      | 裁剪后 <= 0.0 不生成该候选；禁止 None 进入 EVScorer           | `_clip_amount_pct()` 统一处理               |
| 纯函数约束                       | 不写外部状态，不持久化，不产生副作用                            | 状态写入由 Orchestrator 负责                 |
| QUARTERLY 基线必须为本轮新基线    | 禁止读取上季度旧基线参与本轮比较                               | Orchestrator 负责传入正确参数（#16）           |
| 候选集去重                       | 去重键：ActionType + target_bucket + from_bucket + to_bucket；完全语义相同才视为重复 | `_deduplicate_candidates` 处理              |
| GoalImpact override 禁止       | 不得向轻量 Goal Solver 传入 override_n_paths 等覆盖参数      | scorer.py 内部统一处理，本层不传参（#7）         |
| trigger_type 必须区分 quarterly | 禁止 QUARTERLY 模式填 "monthly"                           | 主入口直接赋值 `mode.value`（#6）              |

---

## 14. 文件关联索引

| 文件                                   | 关系                                                                  |
|--------------------------------------|---------------------------------------------------------------------|
| `00_system_topology_and_main_flow.md` | 系统总拓扑参考（注意：00 有旧文件树差异，以 §16 裁决为准）                    |
| `01_governance_ips.md`               | 提供 IPS 边界、`bucket_category`、`bucket_to_theme` 映射                |
| `02_goal_solver.md`                  | 提供 `GoalSolverOutput`、`build_account_state_baseline()`；消费 `LivePortfolioSnapshot` |
| `08_allocation_engine.md`            | 提供候选战略配置集（`candidate_allocations`），用于 QUARTERLY 前置重算      |
| `05_constraint_and_calibration.md`   | 提供 canonical `EVParams`、`RuntimeOptimizerParams` 最新版本；更新 `MarketState / ConstraintState / BehaviorState` |
| `07_orchestrator_workflows.md`       | 触发本层的 workflow 定义；Orchestrator 是唯一合法调用方                    |
| `09_decision_card_spec.md`           | 消费 `EVReport`，构造决策卡（不属于本层）                                   |
| `10_ev_engine.md`                    | 本层下游子引擎；定义 `EVState`、`Action`、`EVReport`、`run_ev_engine()`    |

---

## 15. 实现约定

| 约定                 | 说明                                                                                       |
|--------------------|------------------------------------------------------------------------------------------|
| 百分比口径            | 全部使用 0~1 浮点，禁止 0~100                                                                  |
| 纯函数              | `run_runtime_optimizer` 不写状态，不持久化，不产生副作用                                            |
| 内部函数命名           | 所有辅助函数以下划线前缀（`_compute_*`、`_make_action_*`、`_find_*`、`_clip_*`）                    |
| `bucket_category`  | 必须由调用方显式提供并完整覆盖所有持仓桶，禁止字符串推断                                                 |
| `amount_pct` 预填  | CandidateGenerator 中所有动作必须预填并裁剪，不允许 None 传入 EVScorer                               |
| 候选集不做可行性判断     | CandidateGenerator 只生成，FeasibilityFilter（10）负责过滤，两层职责不混写                            |
| 高情绪候选集           | 高情绪时不自动清空候选集；通过 `cooldown_applicable` 标记，由 FeasibilityFilter 执行拦截                 |
| 模式差异集中处理        | 不同 mode 下的候选差异通过 `generate_candidates` 内的子触发分支统一处理，不散落在辅助函数中                |
| QUARTERLY 基线传入   | 本层不主动调用完整 Goal Solver，由 Orchestrator 在调用本层前完成                                      |
| Decision Card 边界  | 本层不构造任何 UI 文本；终点是 RuntimeOptimizerResult，下游 09 负责渲染                               |

---

## 16. 与 00_system_topology_and_main_flow.md 的实现层差异说明（冻结版）（#18）

> **本节是对 00_system_topology_and_main_flow.md 旧拓扑的正式裁决。**
> 实现时遇到以下差异，以本节为准，不以 00 为准。

| 差异项                                    | 00 旧内容                    | 正式裁决（04 / 10 为准）                                         |
|------------------------------------------|----------------------------|-----------------------------------------------------------------|
| `goal_impact_estimator.py`               | 00 文件树列出此文件            | **不创建**；GoalImpact 由 ev_engine/scorer.py 内部调用轻量 Goal Solver |
| `runtime_optimizer/` 目录               | 00 未列出                    | **需创建**；目录结构以 §11 文件树为准                                |
| `ev_engine/` 与 `runtime_optimizer/` 分工 | 00 描述较笼统               | **以 §10.1 边界表为准**，两目录职责强制隔离                           |
| `EVReport.trigger_type`                  | 00 无 "quarterly"           | **"quarterly" 是合法值**，QUARTERLY 模式必须填写                    |
| `EVReport.scored_actions` 字段名         | 00 旧名称 scored_actions     | **字段名为 ranked_actions**，以 10_ev_engine.md v1.1 为准          |

**实现原则**：
- `00_system_topology_and_main_flow.md` 仅作系统拓扑历史参考
- 所有具体实现边界以 `02_goal_solver.md`、`04_runtime_optimizer.md`（本文件）、`10_ev_engine.md` 最新版本为准
- 三者有冲突时，优先级：`10 > 04 > 02 > 00`（越具体的规格越优先）

---

## 统一边界说明

Runtime Optimizer 是运行期评估与动作优化层的父模块，负责运行模式判定、输入校验、状态快照组装、候选动作生成、调用 EV、执行降级协议并汇总运行期结果。

EV Engine 是 Runtime Optimizer 的内部证据引擎子模块，负责对候选动作执行可行性过滤、分项打分、排序、推荐理由生成与 EVReport 构造。

两者边界固定如下：

- Runtime 不实现 EV 的评分细节
- EV 不实现 Runtime 的模式控制、状态组装与候选生成
- Goal Solver 提供长期目标基线与 lightweight 概率重估能力
- Decision Card 消费结构化结果，不承担运行期优化逻辑

*文档版本：v2.1 | 状态：可交付实现*
*变更历史：v1.0 初版；v2.0 收口 18 项规则冲突与边界差异；v2.1 修复 4 处语义不一致（min_candidates 语义、dedup 键、重复版本字段、字段映射说明）*
*下次修订触发条件：CandidateGenerator 规则变更、新 ActionType 加入、EVState 类型变更、或首次模块联调完成后*


---

## 附录 A：04 ↔ 10 接口收口补丁（v2.2，追加说明，不替换上文原文）

> 本附录用于收口 `04_runtime_optimizer.md` 与 `10_ev_engine.md` 的联调接口。  
> **原则：不删除上文原文，只以本附录作为冻结版补丁。若与上文旧表述冲突，以本附录为准。**

### A.1 本轮裁决结论

1. `run_ev_engine()` 采用**单返回值 + 显式 trigger_type** 的正式签名。
2. `MarketState / ConstraintState / BehaviorState` 的 **canonical type source 统一为 `05_constraint_and_calibration.md`**。
3. `MarketState` 仍然保持“运行期状态”语义；**定量市场假设不回并到 `MarketState`**，仍从  
   `GoalSolverInput.solver_params.market_assumptions` 读取。
4. `EVReport.ranked_actions` 的元素类型以 `10` 为准，统一为 `list[EVResult]`，而不是 `list[Action]`。
5. `EVReport.goal_solver_baseline / goal_solver_after_recommended` 统一为**成功概率数值**，而不是 `GoalSolverOutput`。

### A.2 `run_ev_engine()` 正式签名（冻结版）

```python
def run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: Literal["monthly", "event", "quarterly"],
) -> EVReport:
    # EV Engine 对外唯一正式入口
    ...
```

### A.3 为什么不直接按 04 或 10 原文二选一

- **不直接按 04 原文**：因为 `run_ev_engine(ev_state=..., candidates=...)` 的参数名虽反映调用侧视角，但 `10` 已经把
  `candidate_actions` / `state` 作为更稳定的业务语义名写出来了，后者更适合做公开接口。
- **不直接按 10 原文**：因为 `trigger_type` 是 EVReport 的正式字段，且由 04 的 `mode` 决定；若不显式传入，10 就会在内部
  重新猜测上下文，边界会变差。

因此最终采用的是**04 的控制需求 + 10 的语义命名**的合成方案。

### A.4 本层对 `EVReport` 的正式消费口径（覆盖 §9.1 旧表）

| 字段                              | 正式类型                                   | 说明 |
|----------------------------------|--------------------------------------------|------|
| `ranked_actions`                 | `list[EVResult]`                           | 通过过滤并完成排序的动作结果列表 |
| `eliminated_actions`             | `list[tuple[Action, FeasibilityResult]]`   | 被可行性过滤淘汰的动作及原因 |
| `recommended_action`             | `Action \| None`                          | 推荐动作；若候选贫乏且无安全动作，可为 `None` |
| `recommended_score`              | `EVComponentScore \| None`                | 推荐动作的分项得分 |
| `confidence_flag`                | `str`                                      | `"high" / "medium" / "low"` |
| `confidence_reason`              | `str`                                      | 置信度说明 |
| `goal_solver_baseline`           | `float`                                    | 基线成功概率 |
| `goal_solver_after_recommended`  | `float \| None`                           | 推荐动作后的成功概率预测 |
| `trigger_type`                   | `str`                                      | `"monthly" / "event" / "quarterly"` |
| `state_snapshot_id`              | `str`                                      | EVState 对应快照 ID |
| `generated_at`                   | `str`                                      | 生成时间戳 |
| `params_version`                 | `str`                                      | EV 参数版本 |

### A.5 运行期主入口中的调用方式（覆盖 §8.2 / §8.3 的旧写法）

```python
ev_report = run_ev_engine(
    state=ev_state,
    candidate_actions=candidates,
    trigger_type=mode.value,
)
```

### A.6 `_apply_poverty_protocol()` 的正式读取方式

由于 `ranked_actions` 统一为 `list[EVResult]`，本层不得再把其当作 `list[Action]` 直接消费。  
正式读取方式如下：

```python
def _apply_poverty_protocol(ev_report: EVReport) -> tuple[EVReport, bool]:
    if len(ev_report.ranked_actions) >= 2:
        return ev_report, False

    safe_types = {ActionType.FREEZE, ActionType.OBSERVE}
    safe_results = [
        r for r in ev_report.ranked_actions
        if r.action.type in safe_types
    ]

    if safe_results:
        patched = replace(
            ev_report,
            recommended_action=safe_results[0].action,
            recommended_score=safe_results[0].score,
            confidence_flag="low",
            confidence_reason="候选通过过滤数量过少，已降级为安全动作优先",
        )
        return patched, True

    patched = replace(
        ev_report,
        recommended_action=None,
        recommended_score=None,
        confidence_flag="low",
        confidence_reason="候选通过过滤数量过少，且不存在安全动作可推荐",
    )
    return patched, True
```

### A.7 本层对 05 状态对象的正式依赖

本层继续直接消费 05 提供的：

- `MarketState`
- `ConstraintState`
- `BehaviorState`

但需要注意两个冻结规则：

1. **定量市场参数不从 `MarketState` 取。**  
   涉及 `expected_returns / volatility / correlation_matrix` 的逻辑，统一由 EV 子模块从  
   `solver_baseline_inp.solver_params.market_assumptions` 读取。

2. **约束与行为的运行期辅助字段，以 05 的扩展字段为准。**  
   包括但不限于：
   - `ConstraintState.qdii_available`
   - `ConstraintState.premium_discount`
   - `ConstraintState.transaction_fee_rate`
   - `ConstraintState.bucket_category`
   - `ConstraintState.bucket_to_theme`
   - `BehaviorState.high_emotion_flag`
   - `BehaviorState.panic_flag`
   - `BehaviorState.emotion_score`
   - `BehaviorState.action_frequency_30d`

### A.8 与 09 的衔接口径

09 在消费 `RuntimeOptimizerResult.ev_report` 时，应按以下事实读取，不得自行脑补：

- 主建议：`ev_report.recommended_action`
- 备选动作：`[r.action for r in ev_report.ranked_actions[1:]]`
- 推荐理由：来自 `ranked_actions[0].recommendation_reason` 与 `confidence_reason`
- 关键概率数字：`goal_solver_baseline / goal_solver_after_recommended`
