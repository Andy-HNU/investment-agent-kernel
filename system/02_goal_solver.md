# 02_goal_solver.md
# Goal Solver 设计规格 v2

> **文档定位**：本文件描述"目标求解与配置引擎层"中 Goal Solver 模块的职责、输入输出、求解流程和工程约束，可直接交付 Codex 实现。
>
> **版本变更（v1 → v2）**：
> - 回撤阈值改为真正的硬过滤（去掉 15% 容差）
> - 现金流事件模型（`CashFlowEvent`）正式进入 v1
> - 修正 `_ranking_score` 的 `complexity_score` 取值路径
> - 删除 `_handle_no_feasible_allocation` 中虚构的 `confidence` 字段引用
> - `remaining_budget` 语义收口为 theme-only，字段改名为 `theme_remaining_budget`
> - `theme_budgets` 负值语义补注释
> - 明确 02（Goal Solver）与 03（Allocation Engine）的分工边界
>
> **版本变更（v2 → v3）**：
> - 排序策略改为画像驱动：新增 `RankingMode` 枚举和自动推断逻辑
> - `GoalCard` 新增 `risk_preference` 字段
> - `_ranking_score` 改为按 `RankingMode` 分支执行，不再硬编码"够用优先"
> - 移除一句话定义中不带前提条件的"够用优先"表述
>
> **版本变更（v4 → v5，冻结版）**：
> - `GoalSolverInput` 新增 `snapshot_id` 字段，`account_profile_id` 保留；`GoalSolverOutput.input_snapshot_id` 改为读取 `snapshot_id`
> - `CashFlowEvent` 符号约定写绝：`event_type` 只是语义标签，符号完全由 `amount` 正负决定，注释与 `_build_cashflow_schedule` docstring 同步修正
> - `RiskBudget.drawdown_budget_used_pct` 补注兜底路径下可能 > 1.0 的语义
> - `GoalSolverParams.version` 默认值改为 `"v4.0.0"`，与文档版本对齐，并说明参数版本与文档版本独立演进

---

## 0. 一句话定义

**Goal Solver 是目标求解与配置引擎层的评估核心。**

它不预测市场，不生成候选配置，不拍板运行期动作。它只做一件事：

> 给定账户目标、现金流、资产规模、候选战略配置集合，估算每个候选配置的目标达成概率与风险指标，按画像驱动的排序策略选出推荐配置，并输出基线状态供 EV 引擎消费。

排序策略由目标优先级与风险偏好共同决定，支持三种模式：

| 模式 | 核心原则 | 适用场景 |
|------|---------|---------|
| `SUFFICIENCY_FIRST` | 先达概率阈值，再选回撤最低 | essential/important 目标 × 保守/中等风险偏好 |
| `PROBABILITY_MAX` | 在约束内最大化成功概率 | aspirational 目标，或高风险偏好 |
| `BALANCED` | 加权：0.6 × 成功概率 + 0.4 × (−回撤) | important 目标 × 激进风险偏好 |

模式由 `GoalCard.priority` × `GoalCard.risk_preference` 自动推断，也可由调用方在 `GoalSolverInput` 中显式覆盖。

---

## 1. 职责边界

### Goal Solver 负责

- 对每个候选战略配置运行参数化 Monte Carlo，估算目标达成概率
- 按可行性规则过滤不可行配置
- 在可行配置中按画像驱动的 `RankingMode` 排序并推荐
- 输出基线成功概率、风险摘要、结构预算、风险预算
- 向 EV 引擎提供 `AccountState.success_prob_baseline` 等基线字段

### Goal Solver 不负责

- **生成候选战略配置**：由 `08_allocation_engine.md`（Allocation Engine）独立负责
- **运行期动作选择**：由 `04_runtime_optimizer.md` 负责
- **日常巡检触发**：由 Orchestrator 负责
- **参数校准**：由 `05_constraint_and_calibration.md` 负责

> **02 与 08 的关系说明**：v1 中 `02_goal_solver.md` 负责候选配置评估与选择；候选空间生成由 `08_allocation_engine.md` 独立负责。二者共同构成总纲中的"目标求解与配置引擎层"。不要将本文件理解为完整配置引擎的单文件实现。

---

## 2. 上下游关系

```
AccountProfile ──┐
GoalCard       ──┼──► 08_allocation_engine ──► CandidateAllocations
CashFlowPlan   ──┤                                        │
AccountConstraints                                        ▼
                 └──────────────────────────► GoalSolver ──► GoalSolverOutput
                                                                    │
                                              ┌─────────────────────┘
                                              ▼
                                   RuntimeBaselineAdapter
                                              │
                                              ▼
                                   AccountState（注入 EV）
```

> **输入来源冻结说明**：
> - `candidate_allocations` 的唯一来源是 `08_allocation_engine.md`。
> - `GoalSolverParams / MarketAssumptions` 由 `05_constraint_and_calibration.md` 更新并注入。
> - 02 只消费上述对象，不反向修改、不自行重建。

---

## 3. 输入结构定义

### 3.1 输入合法性要求

| 字段 | 合法性要求 |
|------|-----------|
| `goal_amount` | > 0 |
| `horizon_months` | ≥ 6 |
| `current_portfolio_value` | ≥ 0 |
| `monthly_contribution` | ≥ 0 |
| `annual_step_up_rate` | `[0.0, 0.5]` |
| `cashflow_events[].amount` | 金额类事件（`lump_sum_in/out`, `bonus`, `expense`）：非零；状态类事件（`contribution_pause`, `contribution_resume`）：允许为 0 |
| `cashflow_events[].month_index` | `[0, horizon_months]` |
| `success_prob_threshold` | `(0.0, 1.0)`，建议 0.70~0.85 |
| `max_drawdown_tolerance` | `(0.0, 1.0)` |
| `goal.risk_preference` | `"conservative"` / `"moderate"` / `"aggressive"` 三选一 |
| `candidate_allocations` | 非空列表 |

### 3.2 现金流模型

```python
@dataclass
class CashFlowEvent:
    month_index: int                       # 从当前起算的第几个月，0 = 本月
    amount: float                          # 正数 = 流入，负数 = 流出
                                           # 重要：event_type 只提供语义标签，不自动决定符号。
                                           # 所有加减方向均以 amount 的正负为准。
                                           # 例：expense 事件应传入负数 amount（如 -50000.0）；
                                           # 若传入正数，将被视为流入，不会自动取反。
    event_type: Literal[
        "lump_sum_in",       # 一次性大额投入（年终奖、卖房款等）；amount 应为正数
        "lump_sum_out",      # 一次性大额提取（购房首付、子女学费等）；amount 应为负数
        "bonus",             # 年度奖金（语义同 lump_sum_in）；amount 应为正数
        "expense",           # 计划性支出（语义同 lump_sum_out）；amount 应为负数
        "contribution_pause",# 本月起暂停月投；amount 可为 0，由 month_index 标记时点
        "contribution_resume"# 本月起恢复月投；amount 可为 0，由 month_index 标记时点
    ]
    description: str = ""                  # 可选备注，用于决策卡展示

@dataclass
class CashFlowPlan:
    monthly_contribution: float            # 常规月投（元）
    annual_step_up_rate: float             # 年度递增率（0 = 不递增，0.05 = 每年增 5%）
    cashflow_events: list[CashFlowEvent] = field(default_factory=list)
    # 现金流构建规则：
    # - 常规月投按 monthly_contribution 和 annual_step_up_rate 逐月注入
    # - cashflow_events 在指定月份叠加单笔流入/流出或月投中断/恢复事件
    # - contribution_pause 生效后，常规月投暂停，直到 contribution_resume 出现
    # - 同一月份可有多个事件，按 list 顺序处理
```

### 3.3 其他输入结构

```python
class RankingMode(Enum):
    SUFFICIENCY_FIRST = "sufficiency_first"
    # 先达概率阈值，再选回撤最低，再看成功概率，再看复杂度
    # 理论依据：goals-based WM 中 essential/important 目标失败有真实生活后果；
    # 一旦达标，额外概率的边际效用远低于额外波动的边际损害（Kahneman 损失厌恶）

    PROBABILITY_MAX = "probability_max"
    # 在约束内最大化成功概率，不优先压回撤
    # 适用：aspirational 目标（"越多越好"，无硬阈值），或高风险偏好画像

    BALANCED = "balanced"
    # 加权得分 = 0.6 × success_probability + 0.4 × (1 − max_drawdown_90pct)
    # 适用：important 目标但用户风险偏好偏积极，不愿过度保守

# 画像 → RankingMode 自动推断表
# priority × risk_preference → RankingMode
RANKING_MODE_MATRIX: dict[tuple[str, str], RankingMode] = {
    ("essential",    "conservative"): RankingMode.SUFFICIENCY_FIRST,
    ("essential",    "moderate"):     RankingMode.SUFFICIENCY_FIRST,
    ("essential",    "aggressive"):   RankingMode.SUFFICIENCY_FIRST,  # essential 无论偏好均保守
    ("important",    "conservative"): RankingMode.SUFFICIENCY_FIRST,
    ("important",    "moderate"):     RankingMode.SUFFICIENCY_FIRST,
    ("important",    "aggressive"):   RankingMode.BALANCED,
    ("aspirational", "conservative"): RankingMode.BALANCED,
    ("aspirational", "moderate"):     RankingMode.PROBABILITY_MAX,
    ("aspirational", "aggressive"):   RankingMode.PROBABILITY_MAX,
}

def infer_ranking_mode(priority: str, risk_preference: str) -> RankingMode:
    """
    从目标优先级和风险偏好自动推断排序模式。
    如果组合不在矩阵中，fallback 到 SUFFICIENCY_FIRST（最保守）。
    """
    return RANKING_MODE_MATRIX.get((priority, risk_preference), RankingMode.SUFFICIENCY_FIRST)
```

```python
@dataclass
class GoalCard:
    goal_amount: float                     # 目标金额（元）
    horizon_months: int                    # 距目标月数
    goal_description: str                  # 目标描述（用于决策卡）
    success_prob_threshold: float          # 目标达成概率阈值（如 0.75）
    priority: Literal["essential", "important", "aspirational"] = "important"
    risk_preference: Literal["conservative", "moderate", "aggressive"] = "moderate"
    # risk_preference 来源：IPS / 账户宪法中的风险偏好评估结果
    # 与 priority 共同决定 RankingMode（见 RANKING_MODE_MATRIX）

@dataclass
class AccountConstraints:
    max_drawdown_tolerance: float          # 最大可承受回撤（硬约束，超出直接不可行）
    ips_bucket_boundaries: dict[str, tuple[float, float]]  # 桶 → (下限, 上限)
    satellite_cap: float
    theme_caps: dict[str, float]           # 主题名 → 上限比例
    qdii_cap: float
    liquidity_reserve_min: float           # 最低流动性储备比例

@dataclass
class StrategicAllocation:
    name: str                              # 配置名（用于日志和决策卡）
    weights: dict[str, float]              # 资产桶 → 占比，合计 = 1
    complexity_score: float                # 操作复杂度（0~1，越低越简单）
    description: str = ""

@dataclass
class GoalSolverInput:
    snapshot_id: str                       # 本次求解的输入快照 ID
                                           # 由 Orchestrator 在调用前生成，格式建议：
                                           # "{account_profile_id}_{ISO timestamp}"
                                           # 例：acc_001_20260322T143000
                                           # 用于精确回放本次求解；与 account_profile_id 职责不重叠
    account_profile_id: str                # 账户 ID，用于关联账户维度的历史查询
    goal: GoalCard
    cashflow_plan: CashFlowPlan
    current_portfolio_value: float
    candidate_allocations: list[StrategicAllocation]
    constraints: AccountConstraints
    solver_params: "GoalSolverParams"
    ranking_mode_override: RankingMode | None = None
    # 若为 None，自动从 goal.priority × goal.risk_preference 推断
    # 若显式传入，覆盖自动推断结果（用于测试或特殊场景）
    # 生产默认不得使用 override；仅测试、研究或人工复审允许显式覆盖。
```

---

## 4. 输出结构定义

```python
@dataclass
class RiskSummary:
    max_drawdown_90pct: float              # 90%分位最大回撤（路径级，跨整个投资期）
    terminal_value_tail_mean_95: float     # 终值分布最差 5% 路径的均值（元）
                                           # 注意：不是"单期 CVaR"，而是期末终值左尾均值
                                           # 算法：np.mean(terminal_values[terminal_values ≤ p5_threshold])
    shortfall_probability: float           # 终值不足目标金额的概率（= 1 - success_probability）
    terminal_shortfall_p5_vs_initial: float
                                           # 终值 5%分位相对初始本金的下行幅度
                                           # 算法：(initial_value - p5_terminal) / initial_value
                                           # 正值表示亏损比例，0 表示不亏，负值表示仍有盈余

@dataclass
class StructureBudget:
    core_weight: float                     # 推荐配置中核心桶占比
    defense_weight: float                  # 防御桶占比
    satellite_weight: float                # 卫星桶占比
    theme_remaining_budget: dict[str, float]
    # theme_remaining_budget = theme_cap - theme_used_in_recommended_allocation
    # 负值合法，表示该主题在推荐配置中已超配；
    # 运行期模块应将负值解释为"无剩余预算，且存在回收压力"，而非程序错误。
    satellite_remaining_cap: float         # satellite_cap - satellite_weight

@dataclass
class RiskBudget:
    drawdown_budget_used_pct: float        # 已用回撤预算 = max_drawdown_90pct / max_drawdown_tolerance
                                           # 1.0 表示恰好触及硬约束边界，< 1.0 表示有余量
                                           # 注意：当推荐配置来自"无可行配置兜底"路径时，
                                           # 该值可能 > 1.0，表示推荐项本身仍违反硬约束。
                                           # 消费方不应假设此字段一定 ≤ 1.0；
                                           # 应结合 solver_notes 判断是否处于兜底状态。
    # 注：v1 只输出回撤预算利用率。CVaR 预算（卫星/主题级别的风险分配）
    # 在 v1 中无足够来源定义，暂不输出，留待 v2 补充。

@dataclass
class SuccessProbabilityResult:
    allocation_name: str
    weights: dict[str, float]
    success_probability: float             # P(期末资产 ≥ goal_amount)
    expected_terminal_value: float         # 期望期末资产（元）
    risk_summary: RiskSummary
    is_feasible: bool
    infeasibility_reasons: list[str]       # 不可行原因列表（可行时为空）

@dataclass
class GoalSolverOutput:
    input_snapshot_id: str                 # 来自 GoalSolverInput.snapshot_id（本次求解的输入快照 ID）
                                           # 用于精确回放和复盘；不等于 account_profile_id
    generated_at: str                      # ISO 8601 时间戳

    recommended_allocation: StrategicAllocation
    recommended_result: SuccessProbabilityResult
    all_results: list[SuccessProbabilityResult]  # 全部候选结果，含不可行项
    ranking_mode_used: RankingMode               # 实际使用的排序模式（用于复盘）

    structure_budget: StructureBudget
    risk_budget: RiskBudget
    solver_notes: list[str]                # 警告/说明，供下游判断置信度用

    params_version: str
```

---

## 5. 求解流程

### 步骤 1：构建现金流路径

```python
def _build_cashflow_schedule(
    plan: CashFlowPlan,
    horizon_months: int
) -> list[float]:
    """
    返回长度为 horizon_months 的列表，每个元素为该月净现金流（元）。
    构建规则：
    1. 先按 monthly_contribution 和 annual_step_up_rate 填入常规月投
    2. 遍历 cashflow_events，按 month_index 叠加：
       - lump_sum_in / bonus / lump_sum_out / expense：直接将 amount 加到对应月
         （符号由 amount 自身决定，event_type 只是语义标签，不自动取反）
       - contribution_pause：将从该月起的常规月投置为 0，直到 contribution_resume
       - contribution_resume：恢复常规月投（按当时的 step-up 后金额）
    3. 同一月份可有多个事件，按 list 顺序依次处理
    """
    schedule = []
    contribution = plan.monthly_contribution
    paused = False

    for month in range(horizon_months):
        # 年度递增：每满 12 个月更新一次月投金额
        if month > 0 and month % 12 == 0:
            contribution *= (1 + plan.annual_step_up_rate)

        month_cf = 0.0 if paused else contribution

        for event in plan.cashflow_events:
            if event.month_index == month:
                if event.event_type == "contribution_pause":
                    paused = True
                    month_cf = 0.0
                elif event.event_type == "contribution_resume":
                    paused = False
                    month_cf = contribution
                else:
                    month_cf += event.amount  # lump_sum_in/out, bonus, expense

        schedule.append(month_cf)

    return schedule
```

### 步骤 2：参数化 Monte Carlo

```python
def _run_monte_carlo(
    weights: dict[str, float],
    cashflow_schedule: list[float],
    initial_value: float,
    goal_amount: float,
    market_state: MarketAssumptions,
    n_paths: int,
    seed: int
) -> tuple[float, float, RiskSummary]:
    """
    Goal Solver 的核心模拟函数，被两条调用路径共用：

    - run_goal_solver()：传入 n_paths = GoalSolverParams.n_paths（默认 5000）
      用于初始建档和季度复审，精度优先。

    - run_goal_solver_lightweight()：传入 n_paths = GoalSolverParams.n_paths_lightweight
      （默认 1000），用于 EV 引擎对每个候选动作的 GoalImpact 计算，性能优先。

    两条路径使用完全相同的算法，精度差异只来自路径数。
    路径数由 GoalSolverParams 统一管理，EV 引擎不单独持有此参数。

    性能要求：
    - n_paths=5000 时 < 2s
    - n_paths=1000 时 < 200ms
    - 固定 seed 保证同一版本参数下结果可复现
    - 不做完整 Black-Scholes 路径模拟，使用参数化正态分布
    """
    rng = np.random.default_rng(seed)
    horizon = len(cashflow_schedule)

    # 构建组合月度收益参数
    mu_monthly, sigma_monthly = _portfolio_params(weights, market_state)

    # 模拟 n_paths 条路径
    monthly_returns = rng.normal(
        mu_monthly, sigma_monthly,
        size=(n_paths, horizon)
    )

    # 逐月计算路径资产值
    values = np.zeros((n_paths, horizon + 1))
    values[:, 0] = initial_value

    for t in range(horizon):
        values[:, t + 1] = values[:, t] * (1 + monthly_returns[:, t]) + cashflow_schedule[t]

    terminal_values = values[:, -1]

    # 统计指标
    success_prob = float(np.mean(terminal_values >= goal_amount))
    expected_terminal = float(np.mean(terminal_values))

    # 回撤统计（路径级）
    drawdowns = _compute_path_drawdowns(values)
    max_dd_90pct = float(np.percentile(drawdowns, 90))

    # 终值左尾统计
    p5_threshold = float(np.percentile(terminal_values, 5))
    terminal_tail_mean = float(np.mean(terminal_values[terminal_values <= p5_threshold]))
    shortfall_prob = float(np.mean(terminal_values < goal_amount))
    terminal_shortfall_p5 = float((initial_value - p5_threshold) / initial_value) if initial_value > 0 else 0.0

    risk_summary = RiskSummary(
        max_drawdown_90pct=max_dd_90pct,
        terminal_value_tail_mean_95=terminal_tail_mean,
        shortfall_probability=shortfall_prob,
        terminal_shortfall_p5_vs_initial=terminal_shortfall_p5
    )

    return success_prob, expected_terminal, risk_summary
```

### 步骤 3：可行性过滤

```python
def _check_allocation_feasibility(
    allocation: StrategicAllocation,
    result: SuccessProbabilityResult,
    constraints: AccountConstraints
) -> tuple[bool, list[str]]:
    """
    硬约束过滤。所有规则均为硬约束，超出即不可行，无容差缓冲。
    """
    reasons = []
    w = allocation.weights

    # 1. IPS 桶边界
    for bucket, (lo, hi) in constraints.ips_bucket_boundaries.items():
        bw = w.get(bucket, 0.0)
        if bw < lo - 1e-4 or bw > hi + 1e-4:
            reasons.append(f"{bucket} 占比 {bw:.1%} 超出 IPS 边界 [{lo:.1%}, {hi:.1%}]")

    # 2. 卫星总仓上限
    # 使用 bucket_category 映射（由 AllocationEngine 在 StrategicAllocation 中标注）
    sat_weight = sum(w.get(b, 0.0) for b in w if _is_satellite(b, allocation))
    if sat_weight > constraints.satellite_cap + 1e-4:
        reasons.append(f"卫星总仓 {sat_weight:.1%} 超过上限 {constraints.satellite_cap:.1%}")

    # 3. 主题上限
    for theme, cap in constraints.theme_caps.items():
        tw = _theme_weight(w, theme, allocation)
        if tw > cap + 1e-4:
            reasons.append(f"主题 {theme} 占比 {tw:.1%} 超过上限 {cap:.1%}")

    # 4. 最大可承受回撤（硬约束，无容差）
    # 含义：90%分位最大回撤不得超过用户声明的最大承受回撤
    if result.risk_summary.max_drawdown_90pct > constraints.max_drawdown_tolerance:
        reasons.append(
            f"90%分位最大回撤 {result.risk_summary.max_drawdown_90pct:.1%} "
            f"超过最大可承受回撤 {constraints.max_drawdown_tolerance:.1%}"
        )

    # 5. 流动性储备
    liquid_weight = w.get("cash", 0.0) + w.get("money_market", 0.0)
    if liquid_weight < constraints.liquidity_reserve_min - 1e-4:
        reasons.append(f"流动性储备 {liquid_weight:.1%} 低于最低要求 {constraints.liquidity_reserve_min:.1%}")

    return len(reasons) == 0, reasons
```

### 步骤 4：排序与推荐

```python
def _ranking_score(
    result: SuccessProbabilityResult,
    allocation: StrategicAllocation,
    constraints: AccountConstraints,
    threshold: float,
    mode: RankingMode
) -> tuple:
    """
    排序键（降序），按 RankingMode 分支执行。
    complexity_score 从 allocation 参数获取，不从 result 中取。

    SUFFICIENCY_FIRST（essential/important × 保守/中等）：
      1. 是否达到成功概率阈值（True > False）
      2. 90%分位最大回撤（越小越好）
      3. 成功概率（达标后再看高低）
      4. 配置复杂度（越低越好）

    PROBABILITY_MAX（aspirational，或高风险偏好）：
      1. 成功概率（直接最大化）
      2. 90%分位最大回撤（次要）
      3. 配置复杂度

    BALANCED（important × 激进）：
      1. 加权得分 = 0.6 × success_prob + 0.4 × (1 - max_drawdown_90pct)
      2. 配置复杂度
    """
    p = result.success_probability
    dd = result.risk_summary.max_drawdown_90pct
    cx = -allocation.complexity_score  # 复杂度越低越好，取负值

    if mode == RankingMode.SUFFICIENCY_FIRST:
        meets = p >= threshold
        return (meets, -dd, p, cx)

    elif mode == RankingMode.PROBABILITY_MAX:
        return (p, -dd, cx)

    elif mode == RankingMode.BALANCED:
        weighted = 0.6 * p + 0.4 * (1.0 - dd)
        return (weighted, cx)

    # fallback（不应触发）
    return (p,)


def _find_allocation(
    candidates: list[StrategicAllocation],
    name: str
) -> StrategicAllocation:
    for a in candidates:
        if a.name == name:
            return a
    raise GoalSolverError(f"找不到配置 {name!r}，候选列表可能与结果不同步")
```

### 步骤 5：无可行配置的兜底处理

```python
def _handle_no_feasible_allocation(
    all_results: list[SuccessProbabilityResult],
    candidates: list[StrategicAllocation],
    constraints: AccountConstraints
) -> tuple[StrategicAllocation, SuccessProbabilityResult, list[str]]:
    """
    所有候选均因硬约束不可行时：
    1. 选"最接近可行"的配置（各类违规超标幅度的加权和最小者）
    2. 在 solver_notes 中写入强警告
    3. 不抛异常；由下游模块根据 solver_notes 和 all_results 自行下调决策置信度

    注意：本函数不输出也不修改任何 confidence 字段。
    决策置信度由 EV 引擎的 EVReport.confidence_flag 负责。

    超标幅度评分规则（各项归一化为 [0, ∞) 的无量纲超标幅度，越小越接近可行）：
    - drawdown_excess   = max(0, max_drawdown_90pct - max_drawdown_tolerance) / max_drawdown_tolerance
    - bucket_excess     = Σ max(0, w_i - hi) / hi + Σ max(0, lo - w_i) / lo （对所有违规桶求和）
    - satellite_excess  = max(0, sat_weight - satellite_cap) / satellite_cap
    - theme_excess      = Σ max(0, tw_t - theme_cap_t) / theme_cap_t （对所有违规主题求和）
    - liquidity_shortfall = max(0, liquidity_reserve_min - liquid_weight) / liquidity_reserve_min

    infeasibility_score = drawdown_excess * 2.0   # 回撤违规权重最高
                        + bucket_excess   * 1.5
                        + satellite_excess * 1.0
                        + theme_excess    * 1.0
                        + liquidity_shortfall * 0.5
    """
    notes = [
        "【强警告】所有候选配置均不满足硬约束（回撤或 IPS 边界），",
        "以下推荐为最接近可行的配置，不代表可直接执行。",
        "建议：重新评估目标金额（goal_amount）、期限（horizon_months）或"
        "最大可承受回撤（max_drawdown_tolerance），或由 AllocationEngine 补充新候选配置。"
    ]

    def _infeasibility_score(
        result: SuccessProbabilityResult,
        alloc: StrategicAllocation
    ) -> float:
        w = alloc.weights
        c = constraints
        score = 0.0

        # 回撤超标（权重 2.0）
        dd = result.risk_summary.max_drawdown_90pct
        if dd > c.max_drawdown_tolerance:
            score += 2.0 * (dd - c.max_drawdown_tolerance) / c.max_drawdown_tolerance

        # IPS 桶边界超标（权重 1.5）
        for bucket, (lo, hi) in c.ips_bucket_boundaries.items():
            bw = w.get(bucket, 0.0)
            if bw > hi:
                score += 1.5 * (bw - hi) / max(hi, 1e-6)
            elif bw < lo and lo > 0:
                score += 1.5 * (lo - bw) / lo

        # 卫星总仓超标（权重 1.0）
        sat_w = sum(w.get(b, 0.0) for b in w if _is_satellite(b, alloc))
        if sat_w > c.satellite_cap:
            score += 1.0 * (sat_w - c.satellite_cap) / max(c.satellite_cap, 1e-6)

        # 主题超标（权重 1.0）
        for theme, cap in c.theme_caps.items():
            tw = _theme_weight(w, theme, alloc)
            if tw > cap:
                score += 1.0 * (tw - cap) / max(cap, 1e-6)

        # 流动性不足（权重 0.5）
        liquid_w = w.get("cash", 0.0) + w.get("money_market", 0.0)
        if liquid_w < c.liquidity_reserve_min and c.liquidity_reserve_min > 0:
            score += 0.5 * (c.liquidity_reserve_min - liquid_w) / c.liquidity_reserve_min

        return score

    scored = [
        (r, _infeasibility_score(r, _find_allocation(candidates, r.allocation_name)))
        for r in all_results
    ]
    best_result, _ = min(scored, key=lambda x: x[1])
    best_alloc = _find_allocation(candidates, best_result.allocation_name)
    return best_alloc, best_result, notes
```

### 步骤 6：组合主流程

```python
def run_goal_solver(inp: GoalSolverInput) -> GoalSolverOutput:
    _validate_input(inp)  # 断言式输入校验，见第 3.1 节

    params = inp.solver_params
    cashflow_schedule = _build_cashflow_schedule(inp.cashflow_plan, inp.goal.horizon_months)
    market = params.market_assumptions
    notes: list[str] = []

    # 推断排序模式
    mode = inp.ranking_mode_override or infer_ranking_mode(
        inp.goal.priority, inp.goal.risk_preference
    )
    notes.append(f"排序模式：{mode.value}（目标优先级={inp.goal.priority}，风险偏好={inp.goal.risk_preference}）")

    # Step 1：对每个候选配置运行 Monte Carlo
    all_results: list[SuccessProbabilityResult] = []
    for alloc in inp.candidate_allocations:
        prob, expected, risk = _run_monte_carlo(
            weights=alloc.weights,
            cashflow_schedule=cashflow_schedule,
            initial_value=inp.current_portfolio_value,
            goal_amount=inp.goal.goal_amount,
            market_state=market,
            n_paths=params.n_paths,
            seed=params.seed
        )
        is_feasible, reasons = _check_allocation_feasibility(alloc, _make_interim_result(prob, expected, risk), inp.constraints)
        all_results.append(SuccessProbabilityResult(
            allocation_name=alloc.name,
            weights=alloc.weights,
            success_probability=prob,
            expected_terminal_value=expected,
            risk_summary=risk,
            is_feasible=is_feasible,
            infeasibility_reasons=reasons
        ))

    # Step 2：过滤可行配置
    feasible = [r for r in all_results if r.is_feasible]

    # Step 3：排序或兜底
    if feasible:
        ranked = sorted(
            feasible,
            key=lambda r: _ranking_score(
                r,
                _find_allocation(inp.candidate_allocations, r.allocation_name),
                inp.constraints,
                inp.goal.success_prob_threshold,
                mode
            ),
            reverse=True
        )
        best_result = ranked[0]
        best_alloc = _find_allocation(inp.candidate_allocations, best_result.allocation_name)

        if best_result.success_probability < inp.goal.success_prob_threshold:
            notes.append(
                f"无候选配置达到目标成功概率阈值 {inp.goal.success_prob_threshold:.0%}，"
                f"推荐配置成功概率为 {best_result.success_probability:.0%}。"
            )
    else:
        best_alloc, best_result, fallback_notes = _handle_no_feasible_allocation(
            all_results, inp.candidate_allocations, inp.constraints
        )
        notes.extend(fallback_notes)

    # Step 4：构建输出
    structure_budget = _build_structure_budget(best_alloc, inp.constraints)
    risk_budget = _build_risk_budget(best_result, inp.constraints)

    return GoalSolverOutput(
        input_snapshot_id=inp.snapshot_id,      # 来自输入快照 ID，不复用 account_profile_id
        generated_at=_now_iso(),
        recommended_allocation=best_alloc,
        recommended_result=best_result,
        all_results=all_results,
        ranking_mode_used=mode,
        structure_budget=structure_budget,
        risk_budget=risk_budget,
        solver_notes=notes,
        params_version=params.version
    )
```

---

## 6. StructureBudget 构建规则

```python
def _build_structure_budget(
    alloc: StrategicAllocation,
    constraints: AccountConstraints
) -> StructureBudget:
    w = alloc.weights

    core_w = sum(w.get(b, 0) for b in w if _is_core(b, alloc))
    defense_w = sum(w.get(b, 0) for b in w if _is_defense(b, alloc))
    satellite_w = sum(w.get(b, 0) for b in w if _is_satellite(b, alloc))

    # theme_remaining_budget = cap - used（可为负值，表示已超配）
    theme_remaining: dict[str, float] = {}
    for theme, cap in constraints.theme_caps.items():
        used = _theme_weight(w, theme, alloc)
        theme_remaining[theme] = cap - used
    # 负值语义：该主题在推荐配置中已超配，
    # 运行期模块应将其解释为"无剩余预算，且存在回收压力"，而非程序错误。

    return StructureBudget(
        core_weight=core_w,
        defense_weight=defense_w,
        satellite_weight=satellite_w,
        theme_remaining_budget=theme_remaining,
        satellite_remaining_cap=constraints.satellite_cap - satellite_w
    )
```

---

## 7. RuntimeBaselineAdapter（Goal Solver → EV 的状态传递）

EV 引擎消费的 `AccountState` 部分字段来自 Goal Solver 输出。此适配器负责转换，调用方（Orchestrator）在每次月度巡检前执行。

```python
def build_account_state_baseline(
    solver_output: GoalSolverOutput,
    live_portfolio: LivePortfolioSnapshot,    # 来自券商/托管账户的实时持仓
    current_portfolio_value: float
) -> AccountState:
    """
    将 Goal Solver 输出与实时持仓合并，构建 EV 消费的 AccountState。

    字段映射：
    - success_prob_baseline  ← recommended_result.success_probability
    - target_weights         ← recommended_allocation.weights
    - theme_remaining_budget ← structure_budget.theme_remaining_budget
      （语义：主题剩余预算，不含卫星总剩余额度）
    - current_weights        ← live_portfolio（实时持仓，非 Goal Solver 输出）
    - goal_gap               ← goal_amount - current_portfolio_value（调用方计算）
    """
    return AccountState(
        current_weights=live_portfolio.weights,
        target_weights=solver_output.recommended_allocation.weights,
        goal_gap=live_portfolio.goal_gap,
        success_prob_baseline=solver_output.recommended_result.success_probability,
        horizon_months=live_portfolio.remaining_horizon_months,
        available_cash=live_portfolio.available_cash,
        total_portfolio_value=current_portfolio_value,
        theme_remaining_budget=solver_output.structure_budget.theme_remaining_budget
        # 注意：theme_remaining_budget 专指主题剩余预算（theme-only），
        # 不包含卫星总剩余额度；卫星总预算由 satellite_cap 与 satellite_weight 另行表达。
    )
```

---

## 8. GoalSolverParams（可配置参数）

```python
@dataclass
class MarketAssumptions:
    expected_returns: dict[str, float]     # 资产桶级年化预期收益（Black-Litterman后验）
    volatility: dict[str, float]
    correlation_matrix: dict[str, dict[str, float]]

@dataclass
class GoalSolverParams:
    version: str = "v4.0.0"
    # 参数集版本，与文档版本号保持对齐（当前文档 v4.0）。
    # 两套版本独立演进：文档版本记录规格变更，参数版本记录运行时参数集变更。
    # 每次 CalibrationLayer 更新参数时应同步递增参数集版本号，便于复盘追踪。
    n_paths: int = 5000                    # 完整版路径数（初始建档用）
    n_paths_lightweight: int = 1000        # 轻量版路径数（EV 调用用）
    seed: int = 42
    # seed 固定的目的是保证同一版本参数下结果可复现，便于复盘和 A/B 对比。
    # 注意区分两种用途：
    # - 建档/复审：固定 seed 用于结果可复现
    # - 验证/回测：应在 CalibrationLayer 中以多个 seed 重复运行，
    #   检验结论对 seed 选择的敏感性，不可将单一 seed 结果视为统计稳定性的保证。
    market_assumptions: MarketAssumptions = field(default_factory=MarketAssumptions)
    # 注意：market_assumptions 由 CalibrationLayer 定期更新，GoalSolver 不修改
    shrinkage_factor: float = 0.85
    # 由 CalibrationLayer 设置的长期收益收缩因子。GoalSolver 只读取，不在 02 内重算。
```

---

## 9. v1 限定范围与已知约束

### v1 包含

- `RankingMode` 枚举（三种模式）
- `RANKING_MODE_MATRIX` 画像推断表
- `infer_ranking_mode()` 自动推断函数
- `GoalCard.risk_preference` 字段
- `GoalSolverInput.ranking_mode_override` 可选覆盖字段
- 画像驱动的 `_ranking_score`（SUFFICIENCY_FIRST / PROBABILITY_MAX / BALANCED）
- 全部输入/输出结构定义
- `CashFlowPlan`（含 `CashFlowEvent`，支持不规则现金流）
- 参数化 Monte Carlo（正态分布，n_paths 可配置）
- 可行性过滤（全部硬约束，无容差）
- 画像驱动排序逻辑（`RankingMode` 三模式）
- `RiskBudget`（v1 只含 `drawdown_budget_used_pct`，CVaR 预算留 v2）
- 超标幅度加权的兜底评分（`_handle_no_feasible_allocation`）
- `run_goal_solver_lightweight` 完整伪代码约定
- `RuntimeBaselineAdapter`（Goal Solver → EV 状态传递）
- `theme_remaining_budget` 负值语义定义
- `solver_notes` 警告机制

### v1 不包含

- 自动生成候选配置（由 `08_allocation_engine.md` 负责）
- 多目标联合优化（多个 GoalCard 同时求解）
- 跨账户联合分析
- 动态资产配置（v3 方向）
- 参数自动校准（由 `05_constraint_and_calibration.md` 负责）

### 已知工程约束

| 约束 | 说明 | 处理方式 |
|------|------|---------|
| Monte Carlo 计算时间 | 5000 路径完整版 < 2s；1000 路径轻量版 < 200ms | 两个版本独立参数；EV 只调用轻量版 |
| 市场假设更新频率 | MarketAssumptions 每月由 CalibrationLayer 更新一次 | GoalSolver 从 params 读取，不自行拉取市场数据 |
| 候选配置数量上限 | v1 建议 ≤ 10 个候选，超过后排序时间线性增长 | 由 AllocationEngine 控制候选集规模 |
| 回撤估计精度 | 参数化正态分布低估厚尾风险 | v2 可引入 t 分布或历史模拟；v1 接受此局限 |

---

## 10. 接口摘要

```python
# 主入口：完整求解（初始建档、季度复审）
def run_goal_solver(inp: GoalSolverInput) -> GoalSolverOutput: ...

# 轻量入口：EV 引擎调用（只替换 weights，其余参数沿用基线）
def run_goal_solver_lightweight(
    weights: dict[str, float],
    baseline_inp: GoalSolverInput
) -> tuple[float, RiskSummary]:
    """
    返回 (success_probability, risk_summary)。
    路径数固定使用 baseline_inp.solver_params.n_paths_lightweight，不接受外部覆盖。
    seed 固定使用 baseline_inp.solver_params.seed，保证同一轮 EV 评估的排序稳定性。
    不更新 GoalSolverOutput，不修改任何持久化状态。

    实现约定（Codex 必须遵守）：
    1. 以 baseline_inp 为基础，只替换 candidate_allocations 为单个 weights 的临时配置
    2. 复用 baseline_inp.cashflow_plan 和 baseline_inp.solver_params.market_assumptions
    3. 路径数取 baseline_inp.solver_params.n_paths_lightweight（不得硬编码 1000）
    4. 调用 _run_monte_carlo(weights, cashflow_schedule, ..., n_paths=n_paths_lightweight)
    5. 直接返回 (success_probability, risk_summary)，不执行可行性过滤和排序
    """
    params = baseline_inp.solver_params
    cashflow_schedule = _build_cashflow_schedule(
        baseline_inp.cashflow_plan, baseline_inp.goal.horizon_months
    )
    prob, _, risk = _run_monte_carlo(
        weights=weights,
        cashflow_schedule=cashflow_schedule,
        initial_value=baseline_inp.current_portfolio_value,
        goal_amount=baseline_inp.goal.goal_amount,
        market_state=params.market_assumptions,
        n_paths=params.n_paths_lightweight,   # 唯一来源，不接受外部覆盖
        seed=params.seed
    )
    return prob, risk

# 状态适配：Goal Solver 输出 → EV AccountState
def build_account_state_baseline(
    solver_output: GoalSolverOutput,
    live_portfolio: LivePortfolioSnapshot,
    current_portfolio_value: float
) -> AccountState: ...
```

---

## 11. 文件关联索引

| 文件 | 关系 |
|------|------|
| `01_governance_ips.md` | 提供 AccountConstraints 的来源（IPS / 账户宪法） |
| `08_allocation_engine.md` | 提供 `candidate_allocations`；与本文件共同构成目标求解与配置引擎层 |
| `04_runtime_optimizer.md` submodule: `10_ev_engine.md` | 消费 `GoalSolverOutput` 基线；调用 `run_goal_solver_lightweight` |
| `05_constraint_and_calibration.md` | 更新 `MarketAssumptions` 和 `GoalSolverParams` |
| `10_ev_engine.md` | 通过 `RuntimeBaselineAdapter` 接收 `AccountState` 基线字段 |

---

## 12. 实现约定

| 约定 | 说明 |
|------|------|
| 百分比统一用 0~1 | 不使用 0~100，所有比例字段均为浮点 0~1 |
| 回撤字段统一命名 | 正文描述用"90%分位最大回撤"；字段名用 `max_drawdown_90pct` |
| GoalSolver 是纯函数 | `run_goal_solver` 不写外部状态，不做持久化缓存 |
| 内部函数用下划线前缀 | `_run_monte_carlo`, `_build_cashflow_schedule` 等为模块私有 |
| seed 固定 | 同一版本 GoalSolverParams 内 seed 不变，保证结果可复现 |
| 无 confidence 字段 | GoalSolverOutput 不含置信度字段；决策置信度由 EV 的 EVReport 负责 |
| 输入校验前置 | `_validate_input()` 必须在任何计算前执行 |
| theme_remaining_budget 负值合法 | 负值表示超配，不是错误；消费方负责解释语义 |

---

*文档版本：v5.0（冻结版）| 状态：可交付实现 | 下次修订触发条件：v1 上线后第一次月度复盘，或 AllocationEngine 接口变更*

## 附录 A：v1.1 分布模拟模式升级补丁（追加说明，不替换上文原文）

### A.1 目标

`v1.1` 要把 Goal Solver 从单一 `static gaussian monte carlo` 升级成“可切换模拟模式”的求解器，同时保持 `v1` 的 backward compatibility。

新增目标不是推翻上文结构，而是在保持：

- `GoalSolverInput`
- `GoalSolverParams`
- `GoalSolverOutput`

这三层不失效的前提下，允许 02 消费更高阶的分布模型状态。

### A.2 新增 simulation mode

```python
class SimulationMode(str, Enum):
    STATIC_GAUSSIAN = "static_gaussian"
    GARCH_T = "garch_t"
    GARCH_T_DCC = "garch_t_dcc"
    GARCH_T_DCC_JUMP = "garch_t_dcc_jump"
```

`GoalSolverParams` 追加字段：

```python
simulation_mode: SimulationMode = SimulationMode.STATIC_GAUSSIAN
simulation_frequency: Literal["daily", "weekly", "monthly"] = "monthly"
regime_sensitive: bool = False
jump_overlay_enabled: bool = False
```

### A.3 新增 DistributionModelInput

```python
@dataclass
class DistributionModelInput:
    distribution_model_state: dict[str, Any] | None
    market_assumptions: MarketAssumptions
    simulation_mode: SimulationMode
```

约束：

1. `02` 不得直接回头访问原始历史数据源。
2. `02` 不得在本地重复拟合 GARCH / DCC / jump 参数。
3. `02` 只消费 `05` 已校准出的 `DistributionModelState`。

### A.4 各模式的正式含义

- `static_gaussian`
  - 维持 `v1` 语义
  - 使用静态 `expected_returns / volatility / correlation_matrix`
  - 月收益按 Gaussian 抽样

- `garch_t`
  - 每个桶使用条件波动与 `student_t` 创新分布
  - 不引入动态相关

- `garch_t_dcc`
  - 在 `garch_t` 基础上引入动态相关矩阵

- `garch_t_dcc_jump`
  - 在 `garch_t_dcc` 基础上叠加 bucket jump 与 systemic jump

### A.5 输出解释义务

`GoalSolverOutput.solver_notes` 必须新增披露：

- 当前 `simulation_mode`
- 是否使用历史数据
- 历史数据版本锚点
- 当前 regime 是否参与
- 是否启用 jump overlay
- 当前结果是否仍可视为 `static gaussian` 口径

### A.6 v1.1 对 success probability 的解释要求

前台与日志必须能解释：

1. 该概率是终值达标概率，不是平均年化收益率
2. 当前概率是在哪个 `simulation_mode` 下得到
3. 若模式不是 `static_gaussian`，必须能说明：
   - 条件波动是否开启
   - 动态相关是否开启
   - jump overlay 是否开启

### A.7 backward compatibility

- 若 `DistributionModelState` 缺失，必须回退到 `static_gaussian`
- 回退必须显式披露，不允许静默降级
- `run_goal_solver_lightweight(...)` 在 `v1.1` 仍可保留轻量路径，但必须沿用 baseline 的 `simulation_mode`
