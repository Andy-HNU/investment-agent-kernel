# EV 引擎设计规格 v1

> **文档定位**：本文件是 `04_runtime_optimizer.md`（运行期评估与动作优化层）的子规格，专门描述 EV 引擎的职责、输入输出、评分流程、工程约束和 v1 限定范围。可直接交付 Codex 实现。

---

## 0. 一句话定义

**EV（Expected Value）引擎是运行期动作优化层的证据引擎。**

EV（Expected Value）引擎是 Runtime Optimizer 的内部证据引擎子模块。
它在 Runtime 已完成状态构建与候选动作生成之后，对候选动作执行过滤、评分、排序与报告构造。

它不预测市场，不替代 Goal Solver，不输出投资建议。它只做一件事：

> 给定当前状态，对一组候选动作打分并排序，输出可解释的分解结果，供决策卡展示和 Orchestrator 路由使用。

核心公式：

```text
EV(action | state) = GoalImpact − RiskPenalty − SoftConstraintPenalty − BehaviorPenalty − ExecutionPenalty
```

EV 的职责是回答：

- 当前候选动作中，哪个更优
- 每个动作优劣体现在哪些维度
- 为什么推荐该动作而不是其他动作

EV 不负责回答：

- 当前属于哪一种运行模式
- 当前应生成哪些候选动作
- 是否需要触发某个工作流
- 用户界面如何展示最终结论

这些职责分别属于 Runtime Optimizer、Orchestrator 与 Decision Card。

---

## 1. 职责边界

### 1.1 EV 负责的内容

EV Engine 负责以下事项：

- 接收 Runtime Optimizer 传入的 `EVState`
- 接收 Runtime Optimizer 生成的 `candidate_actions`
- 对候选动作执行 Feasibility Filter
- 对通过过滤的动作执行五项评分：
  - GoalImpact
  - RiskPenalty
  - SoftConstraintPenalty
  - BehaviorPenalty
  - ExecutionPenalty
- 聚合动作总分并输出排序结果
- 生成推荐动作、次优动作、推荐理由
- 构造标准化 `EVReport`

### 1.2 EV 不负责的内容

EV Engine 不负责以下事项：

- 运行模式判定（MONTHLY / EVENT / QUARTERLY）
- 输入快照拼装
- 运行期状态构建
- 候选动作生成
- RuntimeOptimizerResult 汇总
- Orchestrator 工作流控制
- Goal Solver 完整求解
- 参数校准
- 状态持久化
- 决策卡 UI 文案与布局输出

### 1.3 Runtime 与 EV 的关系

Runtime Optimizer 是运行期动作优化层的父模块；EV Engine 是其内部评分子模块。

两者关系如下：

- Runtime 决定“评估什么”
- EV 决定“这些候选中哪个更优”
- Runtime 汇总 EV 输出，形成运行期结果
- Decision Card 消费运行期结果并生成展示内容

因此，EV 必须保持“只评分、不编排；只解释、不生成候选”的边界稳定。

### 关于 FeasibilityFilter 的边界说明

从**职责定义**上，`FeasibilityFilter` 属于评分前过滤，不属于 EV 的核心评分逻辑。
从**工程实现**上，可以与 EV Engine 放在同一模块目录中，作为 `run_ev_engine()` 的前置步骤调用。
也就是说：

* 职责上：**先过滤，再评分**
* 代码组织上：可以放在同一 EV 文件夹内，但不得与打分函数混写成一个不可拆分黑箱

---

## 2. 上下游关系

EV Engine 位于 Runtime Optimizer 内部，处于候选动作生成之后、结果汇总之前。

```text
Runtime Optimizer
   ├── build_ev_state(...)
   ├── generate_candidates(...)
   └── run_ev_engine(...)
            ├── FeasibilityFilter
            ├── EV Scorer
            ├── Ranking
            └── EVReport
                     │
                     └── consumed by Decision Card / Orchestrator
```
2.1 上游输入

EV 的上游输入由 Runtime Optimizer 提供，主要包括：

EVState
candidate_actions
EVParams（如适用）
运行模式与上下文元数据
2.2 下游输出

EV 的下游输出主要是：

ranked_actions
recommended_action
runner_up_action
EVReport

这些输出不会直接形成用户界面文本，而是作为结构化结果被 Runtime Optimizer、Orchestrator 和 Decision Card 消费。

---

## 3. 状态结构定义

EV 引擎消费以下四组状态。**状态由调用方在每次触发前构建，EV 本身不持久化状态。**

> 定义权说明：`AccountState / EVState` 是 EV 本地组合类型；`MarketState / ConstraintState / BehaviorState / EVParams` 的 canonical source 以 `05_constraint_and_calibration.md` 为准。本节展示的是 EV 侧消费字段视图。

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class AccountState:
    current_weights: dict[str, float]        # 资产桶 → 当前占比，合计≈1
    target_weights: dict[str, float]         # 战略配置基线，合计≈1
    goal_gap: float                          # 目标缺口（正=缺，负=超）
    success_prob_baseline: float             # Goal Solver 当前基线成功概率（0~1）
    horizon_months: int                      # 距目标剩余月数
    available_cash: float                    # 可用资金（绝对值，人民币）
    total_portfolio_value: float             # 总组合市值
    theme_remaining_budget: dict[str, float] # 各主题的剩余预算占比（theme-only）

    @property
    def deviation(self) -> dict[str, float]:
        # 派生字段，不存储，避免状态失真
        return {
            k: self.current_weights.get(k, 0.0) - self.target_weights.get(k, 0.0)
            for k in self.target_weights
        }

@dataclass
class MarketState:
    expected_returns: dict[str, float]       # 资产桶级年化预期收益（建议使用收缩后的长期假设）
    volatility: dict[str, float]             # 资产桶年化波动率
    correlation_matrix: dict[str, dict[str, float]]  # 桶间相关性矩阵
    valuation_percentile: dict[str, float]   # 估值历史分位（0=便宜, 1=贵）
    liquidity_flag: dict[str, bool]          # True=流动性受限
    correlation_spike_alert: bool = False    # 来自 05 的高相关预警；True 时提高集中度惩罚

@dataclass
class ConstraintState:
    ips_boundaries: dict[str, tuple[float, float]]   # 桶 → (下限, 上限)，IPS 硬边界
    satellite_cap: float                              # 卫星总仓上限
    theme_caps: dict[str, float]                      # 主题上限（如 technology: 0.15）
    effective_drawdown_threshold: float              # 来自 05 的有效回撤阈值（统一消费口径）
    qdii_available: float                             # 剩余 QDII 配额（元）
    premium_discount: dict[str, float]                # 场内 ETF 折溢价（正=溢, 负=折）
    transaction_fee_rate: dict[str, float]            # 各资产桶交易费率

    # 资产桶分类映射（必须由调用方显式提供，禁止通过字符串匹配推断）
    bucket_category: dict[str, Literal["core", "defense", "satellite"]]
    # 示例：{"equity_cn": "core", "bond_cn": "defense", "gold": "satellite"}

    bucket_to_theme: dict[str, str | None]
    # 示例：{"tech_etf": "technology", "pharma_etf": "healthcare", "equity_cn": None}

@dataclass
class BehaviorState:
    high_emotion_flag: bool                   # 当前处于高情绪状态
    recent_chasing_flag: bool                 # 近期有追涨记录（30天内）
    panic_flag: bool                          # 近期有恐慌性操作记录
    action_frequency_30d: int                 # 近30天实际操作次数
    emotion_score: float                      # 情绪评分（0=平静, 1=极端）
    behavior_penalty_coeff: float = 0.0       # 来自 05 的行为风险强度系数（0~1）

@dataclass
class EVState:
    account: AccountState
    market: MarketState
    constraints: ConstraintState
    behavior: BehaviorState
    ev_params: "EVParams"                     # 来自校准层的可调参数
    goal_solver_baseline_inp: "GoalSolverInput"    # Orchestrator 注入的 Goal Solver 基线输入快照
```

---

## 4. 动作结构定义

候选动作必须使用以下枚举类型，不接受自由文本。枚举由 `CandidateGenerator` 产出，EV 不修改。

```python
from enum import Enum
from dataclasses import dataclass

class ActionType(Enum):
    FREEZE           = "freeze"               # 不操作，维持现状
    OBSERVE          = "observe"              # 冻结并设置观察条件
    ADD_CASH_TO_CORE = "add_cash_core"        # 新增资金补核心桶
    ADD_CASH_TO_DEF  = "add_cash_defense"     # 新增资金补防御桶
    ADD_CASH_TO_SAT  = "add_cash_satellite"   # 新增资金补卫星桶
    REBALANCE_LIGHT  = "rebalance_light"      # 轻量再平衡（不超过阈值）
    REBALANCE_FULL   = "rebalance_full"       # 完整再平衡
    REDUCE_SATELLITE = "reduce_satellite"     # 降低卫星仓位
    ADD_DEFENSE      = "add_defense"          # 增加防御性资产

@dataclass
class Action:
    type: ActionType
    target_bucket: str | None
    amount: float | None                      # 金额（绝对值，元）
    amount_pct: float | None                  # 占组合比例（0~1）
    from_bucket: str | None
    to_bucket: str | None
    cash_source: str                          # "new_cash" / "sell_rebalance" / "dividend"
    requires_sell: bool
    expected_turnover: float
    policy_tag: str                           # "monthly_fix" / "rebalance" / "risk_reduce" / "observe"
    cooldown_applicable: bool
    rationale: str                            # 给决策卡用的文字说明（中文，50字以内）
    explanation_facts: list[str]

    # 金额口径约定：
    # 1. amount 和 amount_pct 不能同时为空；
    # 2. EV Scorer 只消费 amount_pct（0~1 浮点）；
    # 3. 若 amount_pct 为空，调用方必须按 amount / total_portfolio_value 预先换算后填入；
    # 4. 若 amount 与 amount_pct 同时存在，以 amount_pct 为评分主口径，amount 仅用于展示与校验。
```

---

## 5. 评分流程：四层架构

### 第 0 层：候选动作生成（EV 不负责，但需了解）

由 `CandidateGenerator` 按当前状态和权限规则生成候选动作集合。v1 候选动作数量建议控制在 **5~8 个**，避免打分结果稀释。

生成逻辑简述：

* 如果偏离 < 阈值 且无风险线触发 → 候选集必须包含 `FREEZE`
* 如果有新增资金 → 候选集包含各桶的 `ADD_CASH_*` 变体
* 如果偏离 > 阈值 → 候选集包含 `REBALANCE_LIGHT` 和 `REBALANCE_FULL`
* 如果卫星超上限 → 候选集包含 `REDUCE_SATELLITE`
* 如果高情绪 → 强制加入 `OBSERVE`

---

### 第 1 层：可行性过滤（`FeasibilityFilter`）

**进入 EV 打分前**，先用硬约束过滤。违反任何硬约束的动作直接淘汰，不进入打分。

> 回撤阈值口径冻结：若 FeasibilityFilter 或 RiskPenalty 需要消费回撤阈值，统一读取 `ConstraintState.effective_drawdown_threshold`，不得在 10 内部再维护第二套阈值名。

```python
from dataclasses import dataclass

@dataclass
class FeasibilityResult:
    is_feasible: bool
    fail_reasons: list[str]   # 淘汰原因，用于决策卡展示

def check_feasibility(action: Action, state: EVState) -> FeasibilityResult:
    reasons: list[str] = []
    new_weights = _apply_action(action, state.account)

    # 规则 1：IPS 桶边界（硬约束）
    for bucket, (lo, hi) in state.constraints.ips_boundaries.items():
        w = new_weights.get(bucket, 0.0)
        if w < lo - 1e-4 or w > hi + 1e-4:
            reasons.append(f"{bucket} 仓位 {w:.1%} 超出 IPS 边界 [{lo:.1%}, {hi:.1%}]")

    # 规则 2：QDII 额度
    qdii_usage = _estimate_qdii_usage(action)
    if qdii_usage > state.constraints.qdii_available:
        reasons.append(
            f"QDII 配额不足，需要 {qdii_usage:.0f} 元，剩余 {state.constraints.qdii_available:.0f} 元"
        )

    # 规则 3：可用资金
    if action.amount and action.cash_source == "new_cash" and action.amount > state.account.available_cash:
        reasons.append(f"资金不足：需要 {action.amount:.0f} 元，可用 {state.account.available_cash:.0f} 元")

    # 规则 4：卫星总上限（硬上限）
    sat_weight = sum(
        w for b, w in new_weights.items()
        if state.constraints.bucket_category.get(b) == "satellite"
    )
    if sat_weight > state.constraints.satellite_cap + 1e-4:
        reasons.append(f"卫星总仓 {sat_weight:.1%} 超过上限 {state.constraints.satellite_cap:.1%}")

    # 规则 5：冷静期
    if state.behavior.high_emotion_flag and action.cooldown_applicable:
        if action.type not in [ActionType.FREEZE, ActionType.OBSERVE]:
            reasons.append("当前处于高情绪冷静期，非观察/冻结动作不可执行")

    return FeasibilityResult(
        is_feasible=(len(reasons) == 0),
        fail_reasons=reasons
    )
```

---

### 第 2 层：EV 打分（`EVScorer`）

说明：EV 不再单独维护 Monte Carlo 路径数。GoalImpact 统一通过 `run_goal_solver_lightweight()` 调用 Goal Solver 的轻量入口，路径数由 `GoalSolverParams.n_paths_lightweight` 统一管理。

对通过可行性过滤的动作计算各分项。**所有分项统一量纲：成功概率差值（Δp），范围约 `[-0.15, +0.15]`。**

#### 2.1 量纲统一原则

| 分项                    | 原始单位           | 转换方法                         |
| --------------------- | -------------- | ---------------------------- |
| GoalImpact            | Δp（已是目标单位）     | 直接使用                         |
| RiskPenalty           | CVaR差值 / 风险原始分 | × `risk_to_prob_coeff`       |
| SoftConstraintPenalty | 二次惩罚 / 原始分     | × `constraint_to_prob_coeff` |
| BehaviorPenalty       | 原始行为分          | × `behavior_to_prob_coeff`   |
| ExecutionPenalty      | 交易成本（%资产）      | × `execution_to_prob_coeff`  |

> **v1 注意**：所有 penalty 函数内部先形成 `raw_penalty`（无量纲或本项原始量纲），再在函数末尾统一映射为 Δp。系数不允许硬编码在函数逻辑内。

---
#### 2.2 GoalImpact（目标影响）

GoalImpact 用于估计：

> **某个候选动作执行后，对目标达成概率带来的边际变化（Δp）。**

其核心不是重新做一次全局目标求解，而是在**当前 Goal Solver 已给定基线成功概率**的前提下，估计某个动作是否会使成功概率上升、下降或近似不变。

因此，EV 文档中不再把这部分描述为另一套“轻量版算法”。
这里调用的是 **Goal Solver 的公开轻量入口**：

> **`run_goal_solver_lightweight()`**

它与完整入口共用同一个 Monte Carlo 内核，差异仅在于路径数和输出范围。

##### 2.2.1 职责边界

###### `run_goal_solver_lightweight()` 在 EV 路径中负责

* 在 EV 子系统内部，估计某个动作执行后的 `p_after`
* 返回 `Δp` 计算所需的 `p_after` 与 `RiskSummary`
* 为 EV 的 `GoalImpact` 分项提供可比较、低延迟、稳定的近似值

###### 它不负责

* 不负责完整 `GoalSolverOutput` 构建
* 不负责候选战略配置排序
* 不负责结构预算、风险预算和 `solver_notes` 输出
* 不跨轮持久化缓存

##### 2.2.2 与 Goal Solver 的关系

EV 不再维护独立的 GoalImpact 模拟器规格。
当前设计改为：**直接调用 Goal Solver 暴露的轻量入口 `run_goal_solver_lightweight()`**。

| 模块 | 职责 | 典型输出 |
| --- | --- | --- |
| `run_goal_solver()` | 全局目标求解，回答“够不够” | `GoalSolverOutput` |
| `run_goal_solver_lightweight()` | 局部权重变动的快速概率重估，供 EV 比较动作优劣 | `(success_probability, RiskSummary)` |

两条调用路径使用相同的 Monte Carlo 算法，差异只在于：

* `n_paths`：完整版默认 5000，轻量版默认 1000
* 输出范围：轻量版不构建 `GoalSolverOutput`，不做排序，不输出结构预算
* 调用频率：EV 每轮会对多个候选动作重复调用，性能要求更高

路径数属于 Goal Solver 的职责，EV 只调用公开接口，不单独持有路径数参数。

##### 2.2.3 工程组织约定

EV 不再单独维护 `goal_impact_estimator.py` 作为一套并行算法。
工程上应直接从 Goal Solver 模块导入公开轻量入口，例如：

```text id="q4s4eh"
run_goal_solver / run_goal_solver_lightweight
```

如需复用更底层的概率模拟能力，仍可通过 shared 层实现，但 EV 不应再定义一套与 Goal Solver 平行的业务语义接口。

---

##### 2.2.4 输入输出定义

```python id="v0jn3k"
def compute_goal_impact(action: Action, state: EVState) -> float:
    """
    返回 Δp = p_after - p_baseline

    含义：
    - 正值：该动作提升目标达成概率
    - 负值：该动作削弱目标达成概率
    - 0：改善不足以穿透噪声阈值，视为近似无差异
    """
```

内部调用 Goal Solver 公开轻量入口：

```python id="wh44s6"
def run_goal_solver_lightweight(
    weights: dict[str, float],
    baseline_inp: GoalSolverInput
) -> tuple[float, RiskSummary]:
    """
    返回 (success_probability, risk_summary)。

    说明：
    - `baseline_inp` 由 Orchestrator 注入到 EVState.goal_solver_baseline_inp
    - `override_n_paths` 默认为 None；路径数由 GoalSolverParams.n_paths_lightweight 决定
    - EV 不构建 GoalSolverOutput，也不修改任何持久化状态
    """
```

##### 2.2.5 v1 实现原则

v1 中，GoalImpact 直接复用 Goal Solver 的参数化 Monte Carlo 内核。
它的目标不是重新做一遍完整的全局求解，而是：

> **在与 Goal Solver 相同的概率模型下，为候选动作之间的相对比较提供稳定、低延迟、可解释的概率差估计。**

因此，v1 采用以下工程原则：

* 使用资产桶级别，而不是产品级别
* 使用 Goal Solver 当前版本的市场假设与现金流路径
* 使用与 `run_goal_solver()` 相同的 Monte Carlo 算法
* 轻量化仅来自路径数较少，不来自另一套近似公式
* 固定 seed，优先保证候选动作间排序稳定性

---

##### 2.2.6 注释版实现思路

EV 中的 GoalImpact 计算建议分为 4 步。

###### Step 1：把动作应用到当前状态，得到动作后的权重

```python id="e47psk"
new_weights = _apply_action(action, state.account)
```

###### Step 2：读取 Goal Solver 基线输入

该输入由 Orchestrator 在进入 EV 前注入到 `EVState.goal_solver_baseline_inp`，其中包含：

* 目标金额与期限
* 现金流计划
* 当前资产规模
* AccountConstraints
* GoalSolverParams（含 `n_paths_lightweight`、`seed`、`market_assumptions`）

###### Step 3：调用 `run_goal_solver_lightweight()`

```python id="sq8vqm"
p_after, risk_summary = run_goal_solver_lightweight(
    weights=new_weights,
    baseline_inp=state.goal_solver_baseline_inp
)
```

###### Step 4：计算 `Δp` 并做噪声过滤

```python id="hajqj8"
delta = p_after - state.account.success_prob_baseline
if abs(delta) < state.ev_params.goal_solver_min_delta:
    delta = 0.0
```

##### 2.2.7 参考实现（注释版）

```python id="d842ay"
def compute_goal_impact(action: Action, state: EVState) -> float:
    """
    返回 Δp = p_after - p_baseline。
    Goal Solver 轻量入口与完整版共用相同 Monte Carlo 内核；
    EV 不单独决定路径数。
    """
    params = state.ev_params
    new_weights = _apply_action(action, state.account)

    p_after, _risk_summary = run_goal_solver_lightweight(
        weights=new_weights,
        baseline_inp=state.goal_solver_baseline_inp,
    )

    delta = p_after - state.account.success_prob_baseline

    if abs(delta) < params.goal_solver_min_delta:
        delta = 0.0

    return delta
```

##### 2.2.8 EV 中的调用方式

`GoalImpact` 建议写成：

```python id="yd4xga"
def compute_goal_impact(action: Action, state: EVState) -> float:
    """
    返回 Δp = p_after - p_baseline
    """
    params = state.ev_params
    new_weights = _apply_action(action, state.account)

    p_after, _risk_summary = run_goal_solver_lightweight(
        weights=new_weights,
        baseline_inp=state.goal_solver_baseline_inp,
    )

    delta = p_after - state.account.success_prob_baseline

    # 最小可分辨阈值
    if abs(delta) < params.goal_solver_min_delta:
        delta = 0.0

    return delta
```

---

##### 2.2.9 与 shared 层的关系

共享关系现在收口为两层：

* `goal_solver/`：系统级业务入口，暴露 `run_goal_solver()` 与 `run_goal_solver_lightweight()`
* `shared/probability_engine.py`：若有需要，仅承载更底层的通用数值工具

EV 不再单独维护一套与 Goal Solver 平行的 GoalImpact 业务接口；它只消费 Goal Solver 的轻量公开入口。

---



#### 2.3 RiskPenalty（风险惩罚）

```python
def compute_risk_penalty(action: Action, state: EVState, params: EVParams) -> float:
    new_weights = _apply_action(action, state.account)

    # 1. 参数化 CVaR（95%，单期）
    cvar_after = _parametric_cvar(new_weights, state.market, confidence=0.95)
    cvar_before = _parametric_cvar(state.account.current_weights, state.market, confidence=0.95)
    cvar_delta = cvar_after - cvar_before

    # 2. 集中度惩罚：单桶占比超过 IPS 上限的 70% 时触发
    concentration_penalty = 0.0
    for bucket, (lo, hi) in state.constraints.ips_boundaries.items():
        w = new_weights.get(bucket, 0.0)
        headroom = (hi - w) / (hi - lo + 1e-6)
        if headroom < params.concentration_headroom_threshold:
            concentration_penalty += (params.concentration_headroom_threshold - headroom) ** 2

    # 3. 高相关环境下提高集中度惩罚（来自 05 的 correlation_spike_alert）
    if state.market.correlation_spike_alert:
        concentration_penalty *= 1.5

    # 4. 流动性压力
    liquidity_penalty = 0.0
    if action.target_bucket and state.market.liquidity_flag.get(action.target_bucket, False):
        liquidity_penalty = 0.01

    raw_penalty = cvar_delta * params.drawdown_penalty_coeff \
        + concentration_penalty * params.volatility_penalty_coeff \
        + liquidity_penalty
    return raw_penalty * params.risk_penalty_weight
```

---

#### 2.4 SoftConstraintPenalty（软约束惩罚）

注意：硬约束已在 `FeasibilityFilter` 中处理，此处只处理接近边界、预算挤占等软惩罚。

```python
def compute_soft_constraint_penalty(action: Action, state: EVState, params: EVParams) -> float:
    new_weights = _apply_action(action, state.account)
    penalty = 0.0

    # 1. 接近 IPS 边界惩罚
    for bucket, (lo, hi) in state.constraints.ips_boundaries.items():
        w = new_weights.get(bucket, 0.0)
        headroom = min(w - lo, hi - w) / max(hi - lo, 1e-6)
        if headroom < params.ips_headroom_warning_threshold:
            penalty += (params.ips_headroom_warning_threshold - headroom) ** 2

    # 2. 主题预算挤占惩罚（显式映射，禁止字符串匹配）
    for theme, cap in state.constraints.theme_caps.items():
        theme_weight = sum(
            w for b, w in new_weights.items()
            if state.constraints.bucket_to_theme.get(b) == theme
        )
        if theme_weight > cap * params.theme_budget_warning_pct:
            overage = theme_weight - cap * params.theme_budget_warning_pct
            penalty += overage ** 2 * 2

    return penalty * params.soft_constraint_weight
```

---

#### 2.5 BehaviorPenalty（行为惩罚）

注意：高情绪下**不允许**的动作已在 `FeasibilityFilter` 拦截。这里只处理“允许但不优雅”的行为风险。

> 口径冻结：`behavior_penalty_coeff` 来自 05 的 `BehaviorState`，表示行为风险强度；`behavior_penalty_weight` 来自 05 的 `EVParams`，表示该项在 EV 总分中的占比。二者不是同一概念。

```python
def compute_behavior_penalty(action: Action, state: EVState, params: EVParams) -> float:
    """
    返回行为惩罚，量纲为 Δp。
    内部 raw_penalty 为无量纲累加分，最终统一乘 behavior_to_prob_coeff 转为 Δp。
    """
    raw_penalty = 0.0
    b = state.behavior

    # 1. 情绪评分加权
    if (
        b.emotion_score > params.emotion_score_threshold
        and action.type not in [ActionType.FREEZE, ActionType.OBSERVE]
    ):
        emotion_multiplier = (b.emotion_score - params.emotion_score_threshold) * 2
        raw_penalty += emotion_multiplier * 1.0

    # 2. 追涨惩罚
    if b.recent_chasing_flag and _is_momentum_chase(action, state.market):
        raw_penalty += 0.6

    # 3. 频率惩罚
    if b.action_frequency_30d >= params.action_frequency_threshold:
        excess = b.action_frequency_30d - (params.action_frequency_threshold - 1)
        raw_penalty += min(excess * 0.3, 1.2)

    # 4. 恐慌性卖出惩罚
    if b.panic_flag and action.requires_sell:
        raw_penalty += 0.8

    scaled_penalty = raw_penalty * max(0.0, state.behavior.behavior_penalty_coeff)
    return scaled_penalty * params.behavior_penalty_weight
```

---

#### 2.6 ExecutionPenalty（执行成本）

```python
def compute_execution_penalty(action: Action, state: EVState, params: EVParams) -> float:
    amount_pct = action.amount_pct or 0.0

    # 1. 显性成本
    fee_bucket = action.target_bucket or action.to_bucket or ""
    fee_rate = state.constraints.transaction_fee_rate.get(fee_bucket, 0.001)
    fee_cost = amount_pct * fee_rate

    # 2. 折溢价成本
    premium_bucket = action.target_bucket or action.to_bucket or ""
    premium = state.constraints.premium_discount.get(premium_bucket, 0.0)
    premium_cost = abs(premium) * amount_pct

    # 3. 操作复杂度
    complexity_cost = 0.003 if action.requires_sell else 0.0

    raw_cost = fee_cost + premium_cost + complexity_cost
    return raw_cost * params.execution_penalty_weight
```

---

### 第 3 层：汇总打分与排序

```python
from dataclasses import dataclass

@dataclass
class EVComponentScore:
    goal_impact: float
    risk_penalty: float
    soft_constraint_penalty: float
    behavior_penalty: float
    execution_penalty: float
    total: float

@dataclass
class EVResult:
    action: Action
    score: EVComponentScore
    rank: int
    is_recommended: bool
    recommendation_reason: str

def score_action(action: Action, state: EVState) -> EVComponentScore:
    params = state.ev_params

    gi = compute_goal_impact(action, state)
    rp = compute_risk_penalty(action, state, params)
    cp = compute_soft_constraint_penalty(action, state, params)
    bp = compute_behavior_penalty(action, state, params)
    ep = compute_execution_penalty(action, state, params)

    total = gi - rp - cp - bp - ep

    return EVComponentScore(
        goal_impact=gi,
        risk_penalty=rp,
        soft_constraint_penalty=cp,
        behavior_penalty=bp,
        execution_penalty=ep,
        total=total,
    )

def rank_actions(
    candidate_actions: list[Action],
    state: EVState
) -> tuple[list[EVResult], list[tuple[Action, FeasibilityResult]]]:
    """
    返回：
    - ranked_results：通过可行性过滤的动作，按 EV 分数降序排列
    - eliminated：被硬约束淘汰的动作及原因
    """
    passed: list[tuple[Action, EVComponentScore, int]] = []
    eliminated: list[tuple[Action, FeasibilityResult]] = []

    for idx, action in enumerate(candidate_actions):
        feasibility = check_feasibility(action, state)
        if feasibility.is_feasible:
            score = score_action(action, state)
            passed.append((action, score, idx))
        else:
            eliminated.append((action, feasibility))

    # 稳定排序：先按 total 降序，再按动作优先级，再按原输入顺序
    passed.sort(
        key=lambda x: (
            -x[1].total,
            _action_priority(x[0].type),
            x[2],
        )
    )

    results: list[EVResult] = []
    for i, (action, score, _) in enumerate(passed):
        results.append(
            EVResult(
                action=action,
                score=score,
                rank=i + 1,
                is_recommended=(i == 0),
                recommendation_reason=_generate_reason(action, score, i),
            )
        )

    return results, eliminated
```

---

## 6. 输出：EVReport（决策卡数据源）

```python
from dataclasses import dataclass

@dataclass
class EVReport:
    trigger_type: str                         # "monthly" / "event" / "quarterly"
    generated_at: str                         # ISO 8601 时间戳
    state_snapshot_id: str                    # 状态快照 ID，用于复盘

    ranked_actions: list[EVResult]
    eliminated_actions: list[tuple[Action, FeasibilityResult]]

    recommended_action: Action
    recommended_score: EVComponentScore
    confidence_flag: str                      # "high" / "medium" / "low"
    confidence_reason: str

    goal_solver_baseline: float
    goal_solver_after_recommended: float

    params_version: str
```

### 置信度规则（v1 简化版）

置信度由以下因素决定，**不由推荐动作类型直接决定**：

| 置信度      | 触发条件                                                                                       |
| -------- | ------------------------------------------------------------------------------------------ |
| `high`   | 通过过滤的动作 ≥ 3 个，且 top1-top2 分差 > `high_confidence_min_diff`                                  |
| `medium` | 通过过滤的动作 ≥ 2 个，且分差在 `medium_confidence_min_diff ~ high_confidence_min_diff`                 |
| `low`    | 以下任一：通过过滤动作仅 1 个；分差 < `medium_confidence_min_diff`；情绪标志触发；GoalImpact 近似全为 0；大多数候选动作因硬约束被淘汰 |

> 注：`FREEZE` 可以是高置信度推荐动作；若当前状态本就没有明显改善空间，维持现状可能是确定性最优。

---

## 7. EVParams（可校准参数）

`EVParams` 的唯一正式定义位于 `05_constraint_and_calibration.md` / `calibration.types`。
10_ev_engine 只 import 使用，不在本地重复定义。

```python
from calibration.types import EVParams
```

本层直接消费的关键字段包括：

- 五项权重：`goal_impact_weight / risk_penalty_weight / soft_constraint_weight / behavior_penalty_weight / execution_penalty_weight`
- 风险与执行系数：`volatility_penalty_coeff / drawdown_penalty_coeff / qdii_premium_cost_rate / transaction_cost_rate`
- Goal Solver 轻量调用阈值：`goal_solver_seed / goal_solver_min_delta`
- 评分阈值：`ips_headroom_warning_threshold / theme_budget_warning_pct / concentration_headroom_threshold`
- 行为阈值：`emotion_score_threshold / action_frequency_threshold / momentum_lookback_days / momentum_threshold_pct`
- 置信度阈值：`high_confidence_min_diff / medium_confidence_min_diff`

---

## 8. v1 限定范围与已知约束

### v1 包含

* 全部状态结构定义
* CandidateGenerator（枚举模板，5~8 个动作）
* FeasibilityFilter（全部硬约束规则）
* EVScorer（五项分量，统一量纲）
* GoalImpact 通过 `run_goal_solver_lightweight()` 调用 Goal Solver 轻量入口
* EVReport 结构（供决策卡消费）
* EVParams（可配置，初始值拍定）

### v1 不包含

* RL / 动态策略优化（v3）
* 跨账户联合 EV
* 产品级 EV 打分（v1 只到资产桶级）
* GoalImpact 的完整路径模拟（保留给 v2）
* 自动校准（v1 系数手动更新）

### 已知工程风险

| 风险               | 说明                    | 缓解措施                                        |
| ---------------- | --------------------- | ------------------------------------------- |
| Goal Solver 调用成本 | 每个候选动作都要计算 GoalImpact | 通过 `run_goal_solver_lightweight()` 复用同一内核；基线由外部预先给定 |
| 排序噪声             | 接近动作的 Δp 可能只是采样噪声     | 固定参数 + 最小可分辨阈值                              |
| 量纲未统一风险          | 初始 coeff 未经真实校准       | coeff 独立存储，首轮复盘后手工调整                        |
| 候选动作贫瘠           | 打分再精确，候选集贫乏也无意义       | CandidateGenerator 保证 `FREEZE` + 至少 3 个有效动作 |
| 行为惩罚过软           | 只做软罚可能无法阻断危险动作        | 部分行为必须在 FeasibilityFilter 层直接拦截             |

---

## 9. 推荐理由生成规则

```python
def _generate_reason(action: Action, score: EVComponentScore, rank: int) -> str:
    """
    根据分项分解生成推荐/不推荐理由文本（中文，用于决策卡展示）。

    规则（按优先级）：
    1. 若 goal_impact 是最大正贡献项：
       -> "该动作在提升目标成功概率方面最优，风险与成本可控"
    2. 若 goal_impact 近似为 0 且 risk_penalty 明显较低：
       -> "该动作主要通过降低风险暴露提升整体配置稳健性"
    3. 若推荐动作为 FREEZE 或 OBSERVE，且 total 为正或接近 0：
       -> "当前可执行动作改善空间有限，维持现状或观察更优"
    4. 若 behavior_penalty 是主要扣分项：
       -> "该动作在行为约束下优先级受限，但仍优于其他候选"
    5. 其他情况：
       -> 拼接主要贡献与主要成本，例如：
          "目标影响 +X.X%，风险成本 -Y.Y%，执行成本较低"
    """
    ...
```

---

## 10. 接口摘要（供 Orchestrator 调用）

```python
def run_ev_engine(
    candidate_actions: list[Action],
    state: EVState
) -> EVReport:
    """
    输入：候选动作列表 + 当前状态快照
    输出：EVReport（含排序、分解、推荐动作、决策卡数据）
    """
    _validate_state(state)
    for action in candidate_actions:
        _validate_action(action)

    ranked, eliminated = rank_actions(candidate_actions, state)
    return _build_ev_report(ranked, eliminated, state)

def explain_action(
    action: Action,
    state: EVState
) -> EVComponentScore:
    _validate_state(state)
    _validate_action(action)

    feasibility = check_feasibility(action, state)
    if not feasibility.is_feasible:
        raise ValueError(f"动作不可行：{feasibility.fail_reasons}")

    return score_action(action, state)
```

---

## 11. 输入合法性约定

调用方必须保证以下约束在调用 `run_ev_engine()` 前成立。EV 对关键字段做断言式校验，不做静默修正。

```python
def _validate_state(state: EVState) -> None:
    assert abs(sum(state.account.current_weights.values()) - 1.0) < 1e-3, \
        "current_weights 合计必须为 1"
    assert abs(sum(state.account.target_weights.values()) - 1.0) < 1e-3, \
        "target_weights 合计必须为 1"

    assert 0.0 <= state.account.success_prob_baseline <= 1.0, \
        "success_prob_baseline 必须在 [0, 1]"
    assert 0.0 <= state.behavior.emotion_score <= 1.0, \
        "emotion_score 必须在 [0, 1]"

    corr = state.market.correlation_matrix

    # 对角必须为 1
    for a in corr:
        assert abs(corr[a].get(a, 0.0) - 1.0) < 1e-4, \
            f"correlation_matrix 对角元素必须为 1，违反桶：{a}"

    # 必须对称
    for a in corr:
        for b in corr[a]:
            assert abs(corr[a][b] - corr.get(b, {}).get(a, corr[a][b])) < 1e-4, \
                f"correlation_matrix 必须对称，违反桶对：{a}, {b}"

def _validate_action(action: Action) -> None:
    assert not (action.amount is None and action.amount_pct is None), \
        "amount 和 amount_pct 不能同时为空"
    assert action.amount_pct is not None, \
        "进入 EV scorer 前，amount_pct 必须由调用方预先换算填入"
    assert 0.0 <= action.amount_pct <= 1.0, \
        "amount_pct 必须在 [0, 1]"
```

---

## 12. 实现约定

以下约定适用于所有实现此规格的代码，不可在实现中覆盖。

| 约定         | 说明                                                                                                                                            |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 百分比口径      | 全部使用 `0~1` 浮点，禁止使用 `0~100`                                                                                                                    |
| Penalty 量纲 | 各 penalty 内部先形成 raw 值，再在函数末尾统一乘 coeff 映射为 Δp                                                                                                  |
| 纯函数        | EV 引擎不写状态、不做持久化缓存、不产生副作用                                                                                                                      |
| 内部函数命名     | 模块内部辅助函数以下划线前缀（如 `_apply_action`）                                                                                                             |
| 参数一致性      | 同一轮 `run_ev_engine()` 内，所有候选动作使用相同 `EVParams` 与 market assumptions                                                                            |
| 排序稳定性      | 总分相同先看动作优先级，再按原输入顺序                                                                                                                           |
| 动作优先级      | `FREEZE > OBSERVE > ADD_CASH_TO_CORE > ADD_CASH_TO_DEF > REBALANCE_LIGHT > REBALANCE_FULL > REDUCE_SATELLITE > ADD_CASH_TO_SAT > ADD_DEFENSE` |
| 分值范围       | 各分项目标范围约为 `Δp ∈ [-0.15, +0.15]`；超出时记录警告日志，但 v1 不截断                                                                                            |
| 调试输出       | 生产环境默认关闭；测试/复盘模式可输出完整分项分解                                                                                                                     |

---

## 13. 文件关联索引

| 文件                                 | 关系                                |
| ---------------------------------- | --------------------------------- |
| `02_goal_solver.md`                | 提供 `run_goal_solver_lightweight()` 与 Goal Solver 基线输入规格 |
| `04_runtime_optimizer.md`          | EV 所在上层模块，定义触发条件和 Orchestrator 路由 |
| `05_constraint_and_calibration.md` | EVParams 的来源，定义校准频率和更新规则          |
| `09_decision_card_spec.md`         | EVReport 的消费方，定义决策卡字段映射           |
| `07_orchestrator_workflows.md`     | 触发 EV 引擎的 workflow 定义             |

---

*文档版本：v1.1 | 状态：可交付实现 | 下次修订触发条件：Goal Solver 轻量接口或 AllocationEngine 接口变更*

---

## 文件树约束

下面这部分我建议你直接作为**开发约束**附在文档后面，或者单独落成 `ev_engine_folder_contract.md`。

### 约束原则

**所有 EV 相关实现必须单独放在大项目里的一个独立文件夹中，不允许散落到 Goal Solver、Runtime Optimizer、Decision Card、Calibration 等其他模块目录。**

目的只有一个：

> **避免 Codex 在跨模块补代码时发生上下文交叉，把 EV 的评分逻辑、过滤逻辑、报告逻辑和外层 workflow 混写。**

这也符合你前面已经确定的边界：Goal Solver 是中枢，EV 是运行期动作优化层里的证据引擎，两者要强连接，但不能代码互相污染。 

---

## 建议目录

EV 相关核心实现必须统一放在：src/runtime_optimizer/ev_engine/

推荐结构如下：

```text
project_root/
├── system/
│   ├── 02_goal_solver.md
│   ├── 04_runtime_optimizer.md
│   ├── 05_constraint_and_calibration.md
│   ├── 09_decision_card_spec.md
│   └── 10_ev_engine.md
│
├── src/runtime_optimizer/
│   └── ev_engine/
│       ├── types.py              # EV 的核心数据结构定义：EVState / Action / EVParams / EVReport 等
│       ├── feasibility.py        # 硬约束过滤：IPS/QDII/冷静期/卫星上限/可用资金等
│       ├── scorer.py             # 五项评分核心：GoalImpact / Risk / Constraint / Behavior / Execution
│       ├── report_builder.py     # EVResult / EVReport 构造、排序、置信度、推荐理由生成
│       ├── engine.py             # 对外主入口：run_ev_engine / explain_action，负责编排而不持久化
│       └── fixtures/
│           └── sample_ev_state.py  # 最小可运行样例状态与动作夹具，供本地联调和 Codex 回归使用
│
└── tests/
    └── test_ev_engine.py         # 可选：项目级测试文件，不属于 EV 文件夹内的 5 个开发件
```

### EV 子目录负责的内容

runtime_optimizer/ev_engine/ 负责：

EV 正式类型定义
Feasibility Filter
五项评分实现
分数聚合与排序
推荐理由
EVReport
run_ev_engine(...)

### 禁止散落的目录

禁止将 EV 核心评分实现散落到以下目录：

goal_solver/
orchestrator/
decision_card/
calibration/
shared/
runtime_optimizer/ 外层目录

### Runtime 外层与 EV 子目录的分工

runtime_optimizer/ 外层负责：

运行模式判定
输入校验
状态快照组装
候选动作生成
调用 run_ev_engine(...)
汇总 RuntimeOptimizerResult

runtime_optimizer/ev_engine/ 负责：

候选动作过滤
动作评分
动作排序
推荐理由
EVReport

---

## 这 5 个开发文件分别做什么

### `types.py`

只放**类型定义**，不放业务逻辑。

内容包括：

* `AccountState`
* `MarketState`
* `ConstraintState`
* `BehaviorState`
* `EVState`
* `ActionType`
* `Action`
* `FeasibilityResult`
* `EVComponentScore`
* `EVResult`
* `EVReport`
* `EVParams`

约束：

* 不允许在这个文件里写评分逻辑
* 不允许在这个文件里写 workflow
* 只负责类型、默认值、枚举、简单属性

---

### `feasibility.py`

只放**硬约束过滤**。

内容包括：

* `_apply_action`
* `_estimate_qdii_usage`
* `check_feasibility`

职责：

* 判断动作是否可执行
* 给出淘汰原因
* 不参与总分计算

约束：

* 不允许在这里写 `goal_impact`
* 不允许在这里写 EV 总分
* 不允许生成决策卡文案

---

### `scorer.py`

只放**打分函数**。

内容包括：

* `compute_goal_impact`
* `compute_risk_penalty`
* `compute_soft_constraint_penalty`
* `compute_behavior_penalty`
* `compute_execution_penalty`
* `score_action`

职责：

* 接受已合法的 `Action + EVState`
* 返回结构化分项分数
* 不负责淘汰动作
* 不负责拼装最终报告

约束：

* 不允许在这里做持久化缓存
* 不允许在这里读写外部数据库
* 不允许把候选动作生成逻辑塞进来

---

### `report_builder.py`

只放**排序、解释、报告构造**。

内容包括：

* `_action_priority`
* `_generate_reason`
* `_build_confidence_flag`
* `rank_actions`
* `_build_ev_report`

职责：

* 对通过过滤的动作做稳定排序
* 生成推荐理由
* 生成置信度和最终 EVReport

约束：

* 不允许在这里实现五项 score 细节
* 不允许在这里改写状态
* 只消费 `feasibility.py` 和 `scorer.py` 的结果

---

### `engine.py`

只放**对外主入口**，是 EV 文件夹唯一允许暴露给外层 workflow 的模块。

内容包括：

* `_validate_state`
* `_validate_action`
* `run_ev_engine`
* `explain_action`

职责：

* 做输入校验
* 按顺序调用：

  * validate
  * feasibility
  * scoring
  * ranking
  * report building
* 向外返回稳定接口

约束：

* 外层模块不得绕过 `engine.py` 直接调用 `scorer.py` 作为正式业务入口
* `engine.py` 不负责存储、不负责调度其他大模块、不负责网络请求

---

## `fixtures/` 做什么

### `fixtures/sample_ev_state.py`

这是**最小可运行夹具**，只做一件事：

> 给 Codex 和开发者提供一套固定的 `EVState + candidate_actions` 样例，用来跑通 `run_ev_engine()`。

建议内容：

* 一个标准 `EVState`
* 一组 `candidate_actions`
* 一组高情绪状态样例
* 一组越界状态样例
* 一组再平衡样例

作用：

* 防止 Codex 写代码时只能靠空想补类型
* 防止不同文件对字段理解不一致
* 给后面的单测和回归测试提供统一输入

---

## 额外约束：禁止跨模块散写

这条建议你可以直接写给 Codex：

```text
实现 EV 时，禁止把以下逻辑写到 ev_engine 文件夹之外：
- Action / EVState / EVParams / EVReport 的正式定义
- FeasibilityFilter 的正式实现
- EV 五项分量打分
- EV 排序与推荐理由生成
- run_ev_engine / explain_action 主入口

Goal Solver、Orchestrator、Decision Card、Calibration 只能通过 engine.py 暴露的接口消费 EV，不得反向内嵌 EV 逻辑。
```

---

EV 文件夹约束（更新版）
所有 EV 核心评分实现必须统一放在 src/runtime_optimizer/ev_engine/，不得散落到 Goal Solver、Orchestrator、Decision Card、Calibration、shared 或 Runtime 外层目录。

同时，Runtime 外层逻辑必须统一放在 src/runtime_optimizer/，不得反向塞入 ev_engine/。

其中分工如下：

runtime_optimizer/：模式判定、状态组装、候选生成、主入口编排、RuntimeOptimizerResult
runtime_optimizer/ev_engine/：过滤、五项打分、排序、推荐理由、EVReport、run_ev_engine


---

## GoalImpact / Goal Solver 边界说明

如果 10 中有 “GoalImpact”“GoalImpact Estimator”“与 Goal Solver 关系” 章节，用下面这段替换对应部分：

```md
## GoalImpact 的实现边界

GoalImpact 是 EV 五项评分中的正向收益维度，用于评估某一候选动作相对当前基线状态对目标达成概率的边际影响。

### 唯一实现来源

GoalImpact 必须通过 Goal Solver 提供的 lightweight 接口计算获取。  
EV 不允许维护独立的第二套目标求解逻辑，也不允许在 EV 内部复制长期求解器。

标准实现方式为：

- 基于 Runtime 提供的当前状态构造动作后的权重方案
- 调用 Goal Solver 的 `run_goal_solver_lightweight(...)`
- 计算动作前后目标达成概率差值
- 将差值映射为 GoalImpact 分数

### 禁止事项

以下做法一律禁止：

- 在 EV 内部维护独立 `goal_impact_estimator.py` 业务模块
- 在 EV 内部另写一套 Monte Carlo 求解器
- 直接覆盖 Goal Solver 的 lightweight 路径数配置
- 在 Runtime 或 EV 中维护第二套长期目标评估口径

### 历史版本说明

历史版本中曾出现“独立 GoalImpact Estimator”设想。  
当前冻结版本已经取消这一设计：

- GoalImpact 不再作为独立业务模块存在
- GoalImpact 的唯一正式来源是 Goal Solver lightweight 接口
- 相关调用逻辑应放在 `runtime_optimizer/ev_engine/scorer.py` 内部

---

补充说明

统一边界说明
Runtime Optimizer 是运行期评估与动作优化层的父模块，负责运行模式判定、状态快照组装、候选动作生成、调用 EV、汇总结果并向下游提供结构化输出。
EV Engine 是 Runtime Optimizer 的内部证据引擎子模块，负责对候选动作执行可行性过滤、分项打分、排序、推荐理由生成与 EVReport 构造。
Runtime 不实现 EV 评分细节；EV 不实现 Runtime 的模式控制、状态组装与候选生成。
Decision Card 消费 EVReport；Orchestrator 消费 RuntimeOptimizerResult；Goal Solver 提供基线与轻量概率重估能力。

---

## 附录 A：10 ↔ 04 / 05 接口收口补丁（v1.2，追加说明，不替换上文原文）

> 本附录用于收口 `10_ev_engine.md` 与 `04_runtime_optimizer.md` / `05_constraint_and_calibration.md`
> 的正式接口。  
> **原则：不删除上文原文；若旧表述与本附录冲突，以本附录为准。**

### A.1 本轮裁决结论

1. `run_ev_engine()` 的正式签名采用：

```python
def run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: Literal["monthly", "event", "quarterly"],
) -> EVReport:
    ...
```

2. `run_ev_engine()` 的**唯一返回值**是 `EVReport`。  
   `ranked_actions / recommended_action / confidence_reason` 等都属于 `EVReport` 内部字段，不再作为并列主返回值表述。

3. `MarketState / ConstraintState / BehaviorState` 的正式定义权归 05；  
   本文 §3 中的同名 dataclass 视为**历史消费视图**，不再作为正式类型来源。

4. EV 涉及的长期定量市场参数，统一从：

```python
state.goal_solver_baseline_inp.solver_params.market_assumptions
```

读取，而不是从 `MarketState` 读取。

### A.2 为什么类型口径按 05 收口，而不是按 10 回推

- 05 本来就承担“解释层 + 参数治理层”的定义权；
- 04 已经直接消费 05 的状态对象；
- 若按 10 回推，会让 EV 的消费视图反过来定义系统正式状态，边界会倒置。

因此本轮不是“缩 10 的能力”，而是把 10 真正需要的运行字段**上收到 05**，避免丢功能。

### A.3 `EVState` 的正式类型来源

`EVState` 仍由 10 定义为组合对象，但其中三组状态必须按以下来源 import：

```python
from calibration.types import MarketState, ConstraintState, BehaviorState
```

> 注意：这里的 `calibration.types` 指代 05 对应的正式类型文件位置。

### A.4 EV 对市场参数的正式读取方式

#### A.4.1 允许读取

- `state.market.risk_environment`
- `state.market.volatility_regime`
- `state.market.liquidity_status`
- `state.market.valuation_positions`
- `state.market.correlation_spike_alert`
- `state.market.quality_flags / is_degraded`

#### A.4.2 不再直接要求 `MarketState` 自带

- `expected_returns`
- `volatility`
- `correlation_matrix`

#### A.4.3 风险与概率相关计算的正式来源

```python
market_assumptions = state.goal_solver_baseline_inp.solver_params.market_assumptions
```

其中读取：

- `market_assumptions.expected_returns`
- `market_assumptions.volatility`
- `market_assumptions.correlation_matrix`

### A.5 `ConstraintState` 的正式消费字段（以 05 v1.1 扩展为准）

EV 可正式消费以下字段：

- `ips_bucket_boundaries`
- `satellite_cap`
- `theme_caps`
- `effective_drawdown_threshold`
- `qdii_available`
- `premium_discount`
- `transaction_fee_rate`
- `bucket_category`
- `bucket_to_theme`

若伪代码中出现 `ips_boundaries` 等旧缩写，视为本地临时变量名，不代表正式字段名变更。例如：

```python
ips_boundaries = state.constraints.ips_bucket_boundaries
```

### A.6 `BehaviorState` 的正式消费字段（以 05 v1.1 扩展为准）

EV 可正式消费以下字段：

- `high_emotion_flag`
- `recent_chasing_flag`
- `panic_flag`
- `action_frequency_30d`
- `emotion_score`
- `behavior_penalty_coeff`

解释层字段如：

- `recent_chase_risk`
- `recent_panic_risk`
- `cooldown_active`
- `cooldown_until`

继续保留，但 EV 的运行期判定应优先读取上述规范化字段。

### A.7 `EVReport` 的正式口径补丁

为与 04 / 09 对齐，`EVReport` 补充以下约定：

```python
@dataclass
class EVReport:
    trigger_type: str
    generated_at: str
    state_snapshot_id: str

    ranked_actions: list[EVResult]
    eliminated_actions: list[tuple[Action, FeasibilityResult]]

    recommended_action: Action | None
    recommended_score: EVComponentScore | None
    confidence_flag: str                  # "high" / "medium" / "low"
    confidence_reason: str

    goal_solver_baseline: float
    goal_solver_after_recommended: float | None

    params_version: str
```

### A.8 `runner_up_action` 的口径收束

上文“下游输出”中提到的 `runner_up_action`，应理解为**可从 `ranked_actions` 派生的展示概念**，而不是主入口的并列返回值。  
正式推导方式：

```python
runner_up_action = (
    report.ranked_actions[1].action
    if len(report.ranked_actions) >= 2
    else None
)
```

### A.9 `run_ev_engine()` 的正式接口摘要（覆盖 §10 旧签名）

```python
def run_ev_engine(
    state: EVState,
    candidate_actions: list[Action],
    trigger_type: Literal["monthly", "event", "quarterly"],
) -> EVReport:
    # 输入：
    # - state: 由 04 构建的 EVState
    # - candidate_actions: 由 04 生成的候选动作
    # - trigger_type: 由 04.mode.value 显式传入
    #
    # 输出：
    # - EVReport（唯一返回值）
    _validate_state(state)
    for action in candidate_actions:
        _validate_action(action)

    ranked, eliminated = rank_actions(candidate_actions, state)
    return _build_ev_report(
        ranked=ranked,
        eliminated=eliminated,
        state=state,
        trigger_type=trigger_type,
    )
```

### A.10 对 09 的消费承诺

EV 向 09 保证：

- 决策卡层永远可以从 `EVReport` 本体拿到完整展示事实；
- 不要求 09 依赖额外 side-channel 拿 `runner_up_action`；
- 不要求 09 消费完整 `GoalSolverOutput` 作为运行期动作卡的概率依据。
