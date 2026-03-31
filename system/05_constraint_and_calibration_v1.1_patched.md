# 05_constraint_and_calibration.md
# 约束与校准层设计规格 v1.0

> **文档定位**：本文件是约束与校准层（Constraint & Calibration Layer）的正式实现规格，可直接交付 Codex 实现。
>
> 它是 `03_snapshot_and_ingestion.md` 的直接下游解释层，是 `02_goal_solver.md`、`04_runtime_optimizer.md`、`10_ev_engine.md` 的参数治理层。
>
> **本层不参与 workflow 编排，不生成候选动作，不执行 EV 评分，不向用户直接展示任何内容。**

---

## 0. 一句话定义

**Constraint & Calibration Layer 是系统的输入解释与参数治理中枢。**

它基于 03 提供的 SnapshotBundle：

1. 将原始市场输入解释为系统内部状态
2. 将原始约束与行为输入解释为可执行的约束与行为状态
3. 校准长期求解参数（供 Goal Solver 消费）
4. 校准运行期参数（供 Runtime Optimizer 与 EV 消费）
5. 管理参数的版本、更新来源与回写策略

它不直接回答"动作选哪个"，但它决定：

> **系统应当以什么样的市场理解、什么样的约束口径、什么样的参数版本来做后续判断。**

---

## 1. 职责边界

### 1.1 本层负责

- 消费 `SnapshotBundle`，对各域原始快照执行系统层面的解释
- 从市场原始快照构造 `MarketState`（运行期视角）
- 从市场原始快照与历史反馈校准 `MarketAssumptions`（长期求解视角）
- 从约束原始快照构造并更新 `ConstraintState`
- 从行为原始快照构造并更新 `BehaviorState`
- 更新 `GoalSolverParams`（含 `MarketAssumptions`）
- 更新 `RuntimeOptimizerParams`
- 更新 `EVParams`
- 管理参数的版本化、来源记录与受控回写
- 支持降级（输入不完整时的保守兜底）
- 生成 `CalibrationResult`，供 07 注入下游模块

### 1.2 本层不负责

- 外部市场数据采集（由 `03` 负责）
- 账户系统直连与持仓数据拉取（由 `03` 负责）
- workflow 触发与路由（由 `07` 负责）
- 候选战略配置生成（由 `08_allocation_engine.md` 负责）
- 候选动作生成（由 `04_runtime_optimizer.md` 负责）
- EV 打分（由 `10_ev_engine.md` 负责）
- Goal Solver 求解执行（由 `02_goal_solver.md` 负责）
- 决策卡展示文案生成（由 `09_decision_card_spec.md` 负责）
- 持久化与日志写入（由基础设施层负责）
- `RuntimeOptimizerParams / EVParams` 的并行重复定义（唯一类型定义权归 05，04/10 只 import 使用）

### 1.3 与 03 的边界

| 上游（03）| 本层（05）|
|---------|---------|
| 提供原始快照与 SnapshotBundle | 解释这些原始输入的系统含义 |
| 打数据质量 flag（warn/error）| 决定能否继续解释，如何降级 |
| 不直接访问投资逻辑 | 不回头访问原始外部源 |

> **约束**：05 不直接访问原始外部数据源；03 不直接生成 MarketState 或 MarketAssumptions。

### 1.4 与 02/04/10 的边界

| 下游模块 | 消费内容 | 约束 |
|---------|---------|------|
| `02_goal_solver` | `GoalSolverParams / MarketAssumptions` | 02 只消费，不修改 MarketAssumptions，不反向回写 GoalSolverParams |
| `04_runtime_optimizer` | `MarketState / ConstraintState / BehaviorState / RuntimeOptimizerParams` | 04 不内嵌校准逻辑；`RuntimeOptimizerParams` 由 `calibration.types` 唯一定义，04 仅 import 使用 |
| `10_ev_engine` | `EVParams`（由 04 传入 EVState） | 10 不自行维护另一套阈值体系；`EVParams` 由 `calibration.types` 唯一定义，10 仅 import 使用 |

---

## 2. 上下游关系

```
03_snapshot_and_ingestion（SnapshotBundle）
    │
    ▼
05_constraint_and_calibration
    │
    ├── CalibrationResult ──► 07_orchestrator_workflows
    │                                  │
    │              ┌────────────────────┼──────────────────────┐
    │              ▼                    ▼                      ▼
    │    02_goal_solver        04_runtime_optimizer    10_ev_engine
    │    （GoalSolverParams）   （MarketState /         （EVParams）
    │                          ConstraintState /
    │                          BehaviorState /
    │                          RuntimeOptimizerParams）
    │
    └── 回写参数版本 ──► 参数版本存储（由基础设施层负责持久化）
```

---

## 3. 核心类型定义

### 3.1 MarketState（运行期市场视角）

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any


@dataclass
class MarketState:
    """
    运行期市场状态。
    服务对象：04_runtime_optimizer / 10_ev_engine（通过 EVState）
    更新频率：每次 CalibrationLayer 被调用时更新（月度或事件触发）

    与 MarketAssumptions 的区别：
    - MarketState 是运行期标签与定性描述，给 Runtime/EV 用
    - MarketAssumptions 是定量参数（均值/波动/相关性），给 Goal Solver 用
    """
    as_of: datetime
    source_bundle_id: str          # 来源 SnapshotBundle.bundle_id
    version: str                   # 本次状态版本 ID

    # 环境定性标签
    risk_environment: Literal["low", "moderate", "elevated", "high"]
    # 推断规则：基于 raw_volatility 均值与历史分位
    # low: < 25th pct | moderate: 25~75th | elevated: 75~90th | high: > 90th

    volatility_regime: Literal["low", "normal", "high"]
    # 基于全桶等权平均波动率的历史分位

    # 桶级别状态
    liquidity_status: dict[str, Literal["normal", "tight", "stressed"]]
    # key = IPS 桶名，来源：MarketRawSnapshot.liquidity_scores
    # normal: score > 0.6 | tight: 0.3~0.6 | stressed: < 0.3
    # 若 liquidity_scores 缺失，降级为全桶 "normal"，并打 quality flag

    valuation_positions: dict[str, Literal["cheap", "fair", "rich", "extreme"]]
    # key = IPS 桶名，来源：MarketRawSnapshot.valuation_z_scores
    # cheap: z < -1.5 | fair: -1.5~1.5 | rich: 1.5~2.5 | extreme: > 2.5
    # 若 valuation_z_scores 缺失，降级为全桶 "fair"

    # 相关性预警
    correlation_spike_alert: bool
    # True = 当前时期相关性显著高于历史均值（> 历史 85th pct）
    # 触发含义：分散化效果下降，EV 可能需要对集中度提高惩罚

    # 质量
    quality_flags: list[str]       # 降级标记列表（code 字符串）
    is_degraded: bool              # True = 存在任意 error 级 flag
```

### 3.2 MarketAssumptions（长期求解视角）

```python
# 注意：MarketAssumptions 类型定义在 02_goal_solver.md（goal_solver/types.py）
# 05 负责产生并更新该对象，02 只消费。
# 此处仅注明 05 对 MarketAssumptions 的构造责任与更新规则。

# from goal_solver.types import MarketAssumptions
# MarketAssumptions 字段：
#   expected_returns: dict[str, float]  # 桶 → 年化预期收益（Black-Litterman 后验）
#   volatility: dict[str, float]        # 桶 → 年化波动率
#   correlation_matrix: dict[str, dict[str, float]]  # 桶 → 桶 → 相关系数

# 05 的构造责任：
# 1. 以历史均值为先验（Prior）
# 2. 应用收缩估计（Ledoit-Wolf 或固定收缩系数）降低极端权重风险
# 3. 融合主观看法时可选 Black-Litterman（v1 可简化为保守先验，v2 引入 BL）
# 4. 每次更新生成新版本 ID，旧版本保留用于复盘
# 5. GoalSolver 从 GoalSolverParams.market_assumptions 读取，不自行拉取

# MarketAssumptions 保守构造约束（v1）：
# - expected_returns 上限不超过各桶资产类别的历史长期均值 + 1 个标准差
# - volatility 不低于各桶历史最低波动率的 80%（防止过度乐观的平静期输入）
# - correlation_matrix 必须为正半定矩阵（实现时需检验并修正）
```

### 3.3 ConstraintState（运行期约束状态）

```python
@dataclass
class ConstraintState:
    """
    校准后的运行期约束状态。
    服务对象：04_runtime_optimizer（通过 EVState.ips_constraints / BehaviorState）
    更新频率：每次 CalibrationLayer 被调用时更新
    """
    as_of: datetime
    source_bundle_id: str
    version: str

    # 从 ConstraintRawSnapshot 直接透传的硬约束
    ips_bucket_boundaries: dict[str, tuple[float, float]]  # (下限, 上限)
    satellite_cap: float
    theme_caps: dict[str, float]
    qdii_cap: float
    liquidity_reserve_min: float
    max_drawdown_tolerance: float      # 来自 IPS，为硬约束上限
    rebalancing_band: float
    forbidden_actions: list[str]
    cooling_period_days: int
    soft_preferences: dict[str, Any]

    # 校准后的有效阈值（可能比 IPS 原始值更严格）
    effective_drawdown_threshold: float
    # <= max_drawdown_tolerance
    # 校准逻辑：当 MarketState.risk_environment == "high" 时，
    # effective_drawdown_threshold = max_drawdown_tolerance * 0.85（提前收紧）
    # 其他情况等于 max_drawdown_tolerance

    # 是否当前处于冷静期（由 BehaviorState 触发）
    cooldown_currently_active: bool

    # 校验规则：effective_drawdown_threshold <= max_drawdown_tolerance
```

### 3.4 BehaviorState（行为状态与惩罚参数）

```python
@dataclass
class BehaviorState:
    """
    校准后的行为状态与惩罚参数。
    服务对象：04_runtime_optimizer / 10_ev_engine（BehaviorPenalty 项）
    更新频率：每次 CalibrationLayer 被调用时更新
    """
    as_of: datetime
    source_bundle_id: str
    version: str

    # 行为信号（从 BehaviorRawSnapshot 解释而来）
    recent_chase_risk: Literal["none", "low", "moderate", "high"]
    # 推断规则：
    # none: detected_chase_events 为空 且 trade_count_30d <= 正常阈值
    # low: 有 1 个追涨事件 或 轻度高频
    # moderate: 2~3 个追涨事件 或 trade_count_30d > 3x 均值
    # high: 3+ 追涨事件 或 trade_count_30d > 5x 均值

    recent_panic_risk: Literal["none", "low", "moderate", "high"]
    # 同类推断逻辑，基于 detected_panic_events

    trade_frequency_30d: float         # 过去 30 天月均操作次数（直接来自 raw）
    override_count_90d: int            # 过去 90 天人工覆盖次数

    cooldown_active: bool              # 当前是否处于冷静期
    cooldown_until: datetime | None    # 冷静期结束时间，None = 无冷静期

    # EV 消费字段
    behavior_penalty_coeff: float
    # 0.0 ~ 1.0，用于 EV BehaviorPenalty 项的放大系数
    # 推断规则（v1 保守版）：
    # chase_risk == "none" 且 panic_risk == "none": 0.0
    # chase_risk == "low" 或 panic_risk == "low":   0.2
    # chase_risk == "moderate" 或 panic_risk == "moderate": 0.5
    # chase_risk == "high" 或 panic_risk == "high": 1.0
    # 多项叠加取最大值，不累加
    # 注意：该系数不是 EV 中的权重；10_ev_engine 按
    # BehaviorPenalty_score = behavior_penalty_weight × f(behavior_penalty_coeff, action)
    # 消费本字段，其中 coeff 表示行为风险强度，weight 表示该项在总分中的占比。

    recent_chasing_flag: bool
    # True = recent_chase_risk in ["moderate", "high"]
    # 供 04_runtime_optimizer 候选生成时标记 cooldown_applicable
```

### 3.5 RuntimeOptimizerParams（运行期参数）

```python
@dataclass
class RuntimeOptimizerParams:
    """
    运行期优化器参数，由 05 负责维护版本并更新。
    04_runtime_optimizer 从此结构读取配置，不自行修改，也不得在本地重复定义同名 dataclass。
    """
    version: str = "v1.0.0"

    # 偏离与事件触发阈值（canonical names）
    deviation_soft_threshold: float = 0.03
    deviation_hard_threshold: float = 0.10
    satellite_overweight_threshold: float = 0.02
    drawdown_event_threshold: float = 0.10

    # 候选动作生成参数
    min_candidates: int = 2            # 最低候选数量（兜底 FREEZE + OBSERVE）
    max_candidates: int = 8            # 最高候选数量
    min_cash_for_action: float = 1000.0
    new_cash_split_buckets: int = 2
    new_cash_use_pct: float = 0.80
    defense_add_pct: float = 0.05

    # 运行期约束与校验辅助参数
    rebalance_full_allowed_monthly: bool = False
    cooldown_trade_frequency_limit: float = 4.0
    amount_pct_min: float = 0.02
    amount_pct_max: float = 0.30
    max_portfolio_snapshot_age_days: int = 3

    # 说明：旧命名 `deviation_trigger_threshold / hard_deviation_threshold` 在冻结版中退役，
    # 统一使用 `deviation_soft_threshold / deviation_hard_threshold`。
```

### 3.6 EVParams（EV 引擎参数）

```python
@dataclass
class EVParams:
    """
    EV 引擎参数，由 05 负责维护版本并更新。
    10_ev_engine 从此结构读取权重、系数与阈值，不自行修改，也不得在本地重复定义 `EVParams`。
    """
    version: str = "v1.0.0"

    # 五项总分权重
    goal_impact_weight: float = 0.40
    risk_penalty_weight: float = 0.25
    soft_constraint_weight: float = 0.15
    behavior_penalty_weight: float = 0.10
    execution_penalty_weight: float = 0.10

    # RiskPenalty / ExecutionPenalty 系数
    volatility_penalty_coeff: float = 1.0
    drawdown_penalty_coeff: float = 1.5
    qdii_premium_cost_rate: float = 0.015
    transaction_cost_rate: float = 0.003

    # Goal Solver 轻量调用参数（EV 只读，不覆盖）
    goal_solver_seed: int = 42
    goal_solver_min_delta: float = 0.003

    # EV 评分阈值与映射参数
    ips_headroom_warning_threshold: float = 0.20
    theme_budget_warning_pct: float = 0.85
    concentration_headroom_threshold: float = 0.30
    emotion_score_threshold: float = 0.50
    action_frequency_threshold: int = 2
    momentum_lookback_days: int = 30
    momentum_threshold_pct: float = 0.20
    high_confidence_min_diff: float = 0.020
    medium_confidence_min_diff: float = 0.005

    # 总分归一化
    total_weight_sum: float = 1.00
    # 校验规则：
    # goal_impact_weight + risk_penalty_weight + soft_constraint_weight
    # + behavior_penalty_weight + execution_penalty_weight == total_weight_sum
```

### 3.7 参数版本元信息

```python
@dataclass
class ParamVersionMeta:
    """
    参数版本治理对象。所有可校准参数对象均应携带版本元信息。
    不可静默覆盖，不可无版本回写。
    """
    version_id: str
    # 格式建议："{module}_{timestamp}"，例 "ev_params_20260322T143000Z"

    source_bundle_id: str          # 触发本次更新的 bundle
    created_at: datetime
    updated_reason: str            # 更新原因（如 "monthly_calibration", "manual_review"）
    quality: Literal["full", "degraded", "manual"]
    # full: 正常校准结果
    # degraded: 输入不完整，部分参数使用兜底/先验值
    # manual: 人工确认覆盖

    is_temporary: bool
    # True = 降级模式下生成，不应持久化为默认参数
    # False = 正常校准结果，可持久化
```

### 3.8 CalibrationResult（本层唯一交付对象）

```python
from goal_solver.types import MarketAssumptions, GoalSolverParams
# 注：goal_solver/types.py 中已定义 MarketAssumptions 和 GoalSolverParams
# 05 从该模块 import，不重复定义


@dataclass
class CalibrationResult:
    """
    约束与校准层的唯一交付对象。
    由 07_orchestrator_workflows 接收，注入 02/04/10 各模块。
    """
    calibration_id: str            # 格式："{account_profile_id}_{ISO timestamp}"
    source_bundle_id: str          # 来源 SnapshotBundle.bundle_id
    created_at: datetime
    account_profile_id: str

    # 状态类输出（主要给 04/10 用）
    market_state: MarketState
    constraint_state: ConstraintState
    behavior_state: BehaviorState

    # 参数类输出（给 02/04/10 用）
    market_assumptions: MarketAssumptions
    goal_solver_params: GoalSolverParams
    # 包含已更新的 market_assumptions；02 消费此完整对象
    runtime_optimizer_params: RuntimeOptimizerParams
    ev_params: EVParams

    # 质量与治理
    calibration_quality: Literal["full", "partial", "degraded"]
    degraded_domains: list[str]    # 降级处理的域名列表
    notes: list[str]               # 校准说明（如"行为域缺失，BehaviorState 使用默认值"）
    param_version_meta: ParamVersionMeta
```

---

## 4. 对外接口定义

### 4.1 主校准入口

```python
def run_calibration(
    bundle: SnapshotBundle,
    prior_calibration: CalibrationResult | None,
    default_goal_solver_params: GoalSolverParams | None = None,
    default_runtime_params: RuntimeOptimizerParams | None = None,
    default_ev_params: EVParams | None = None,
) -> CalibrationResult:
    """
    从 SnapshotBundle 生成完整 CalibrationResult。

    执行顺序：
    1. interpret_market_state()
    2. calibrate_market_assumptions()（依赖 MarketState 中的 regime 标签）
    3. interpret_behavior_state()
    4. interpret_constraint_state()（依赖 BehaviorState.cooldown_active）
    5. update_goal_solver_params()
    6. update_runtime_optimizer_params()
    7. update_ev_params()
    8. 组装 CalibrationResult，推断整体 calibration_quality

    若 prior_calibration 为 None（首次运行），则使用 default_* 参数作为先验。
    若 default_* 均为 None 且 prior 为 None，使用模块内硬编码的初始默认值。

    注意：本函数为纯函数，不写外部状态，不持久化。
    持久化由 07_orchestrator_workflows 在接收 CalibrationResult 后负责。
    """
    ...
```

### 4.2 子职责函数

```python
# ─── Market 解释 ────────────────────────────────────────────────
def interpret_market_state(
    market_raw: MarketRawSnapshot
) -> MarketState:
    """
    将市场原始快照转换为运行期 MarketState。
    降级规则：
    - liquidity_scores 缺失 → 全桶 "normal" + quality_flag
    - valuation_z_scores 缺失 → 全桶 "fair" + quality_flag
    - raw_volatility 完全缺失 → is_degraded=True，不允许继续
    """
    ...

def calibrate_market_assumptions(
    market_raw: MarketRawSnapshot,
    market_state: MarketState,
    prior_assumptions: MarketAssumptions | None,
) -> MarketAssumptions:
    """
    从原始市场序列校准 MarketAssumptions（long-term parameters）。

    校准逻辑（v1 保守版）：
    1. expected_returns：使用收缩后的历史均值（Ledoit-Wolf 方向，但 v1 可简化为
       使用 `GoalSolverParams.shrinkage_factor` 做固定因子收缩，默认 0.85）
    2. volatility：取历史样本标准差，下限不低于历史最低波动的 80%
    3. correlation_matrix：对历史相关性矩阵做正半定修正（eigenvalue clipping）
    4. 若序列长度 < 36 月（SHORT_HISTORY_WINDOW），额外增大波动估计（乘以 1.2 保守因子）
    5. 若 prior_assumptions 存在且当前数据质量为 degraded，沿用 prior，不重算

    不引入 Black-Litterman 主观看法（v2 方向）。
    """
    ...

# ─── Behavior 解释 ──────────────────────────────────────────────
def interpret_behavior_state(
    behavior_raw: BehaviorRawSnapshot | None,
    prior_behavior: BehaviorState | None = None,
) -> BehaviorState:
    """
    将行为原始快照解释为 BehaviorState。
    若 behavior_raw 为 None，使用默认低惩罚状态（behavior_penalty_coeff=0.0）。
    若 prior_behavior 存在且 behavior_raw 为 None，沿用 prior。
    """
    ...

# ─── Constraint 解释 ────────────────────────────────────────────
def interpret_constraint_state(
    constraint_raw: ConstraintRawSnapshot,
    market_state: MarketState,
    behavior_state: BehaviorState,
    prior_constraint: ConstraintState | None = None,
) -> ConstraintState:
    """
    将约束原始快照解释为 ConstraintState。
    同时将 behavior_state.cooldown_active 注入 ConstraintState.cooldown_currently_active。
    根据 market_state.risk_environment 校准 effective_drawdown_threshold。
    """
    ...

# ─── 参数更新 ───────────────────────────────────────────────────
def update_goal_solver_params(
    market_assumptions: MarketAssumptions,
    prior_params: GoalSolverParams | None,
) -> GoalSolverParams:
    """
    将最新 MarketAssumptions 注入 GoalSolverParams 并更新版本号。
    其他 GoalSolverParams 字段（n_paths, seed, shrinkage_factor 等）在 prior 存在时保持不变，
    除非有显式人工更新指令。
    """
    ...

def update_runtime_optimizer_params(
    market_state: MarketState,
    constraint_state: ConstraintState,
    prior_params: RuntimeOptimizerParams | None,
) -> RuntimeOptimizerParams:
    """
    根据市场状态与约束状态更新 RuntimeOptimizerParams。
    v1 更新逻辑简单：大部分参数保持先验值，仅在高风险环境下收紧 deviation 阈值。
    """
    ...

def update_ev_params(
    market_state: MarketState,
    behavior_state: BehaviorState,
    prior_params: EVParams | None,
) -> EVParams:
    """
    根据市场与行为状态更新 EVParams。
    v1 更新逻辑：behavior_penalty_weight 在高行为风险时提升（上限 0.20）。
    """
    ...
```

---

## 5. MarketState 与 MarketAssumptions 的区别（核心约定）

本节为下游模块消费时的参考说明，必须被 04 / 02 / 10 遵守：

```text
MarketState（运行期）:
  - 描述"当前市场输入在运行期下的定性解释结果"
  - 用于 04（Runtime）识别偏离、触发阈值、生成候选动作
  - 用于 10（EV）的 RiskPenalty、ExecutionPenalty 等项
  - 更短周期、更偏"当前轮次视角"
  - 不包含定量均值/波动参数

MarketAssumptions（长期求解）:
  - 描述"Goal Solver Monte Carlo 中所采用的定量参数"
  - 用于 02（Goal Solver）的路径模拟
  - 包含 expected_returns / volatility / correlation_matrix
  - 更长周期、更偏"长期稳定估计视角"

使用约束：
  - MarketState 服务运行期（04/10）
  - MarketAssumptions 服务长期求解（02）
  - 两者不得混用：04 不得直接读取 MarketAssumptions 参与候选打分；
    02 不得读取 MarketState 参与路径模拟
  - 两者均由 05 生成，下游模块不得自行构造
```

---

## 6. 参数回写与版本治理

### 6.1 回写对象

| 对象 | 更新频率 | 触发条件 |
|------|---------|---------|
| `MarketAssumptions` | 月度（或季度） | 月度/季度 calibration 触发 |
| `GoalSolverParams` | 月度 | 同上（含 MarketAssumptions） |
| `RuntimeOptimizerParams` | 月度，或高风险事件触发 | 月度 / EVENT 触发 |
| `EVParams` | 月度，或行为异常事件触发 | 月度 / 行为 EVENT |
| `ConstraintState` | 月度，或 IPS 人工更新 | 月度 / 人工确认 |
| `BehaviorState` | 月度，或事件触发 | 月度 / 行为 EVENT |

### 6.2 版本治理硬约束

以下约束不可违反：

- **不允许无版本回写**：每次参数更新必须生成新 `version_id`
- **不允许静默覆盖**：新版本必须保留旧版本引用，供复盘使用
- **不允许下游模块自行写回**：只有 05 可以生成新版本参数；02/04/10 只消费
- **临时降级参数不可持久化为默认**：`is_temporary=True` 的参数仅用于当轮运行
- **参数更新必须携带来源**：`source_bundle_id` + `updated_reason` + `created_at` 必须完整

### 6.3 版本 ID 格式建议

```
goal_solver_params_20260322T143000Z
ev_params_20260322T143000Z
runtime_params_20260322T143000Z
market_assumptions_20260322T143000Z
```

---

## 7. 降级与保守策略

### 7.1 可降级情况（calibration_quality = "partial"）

| 情况 | 处理方式 |
|------|---------|
| 行为域缺失（BEHAVIOR_DOMAIN_MISSING）| 使用默认 BehaviorState（penalty_coeff=0.0，cooldown=False）|
| 序列长度 < 36 月（SHORT_HISTORY_WINDOW）| 使用保守波动率估计（原始值 × 1.2）|
| 估值/流动性数据缺失 | 降级为 "fair" / "normal" 标签 |
| 部分桶无市场数据 | 使用先验参数中对应桶的假设，打 warn flag |

### 7.2 不可降级情况（calibration_quality = "degraded"）

| 情况 | 处理方式 |
|------|---------|
| 核心市场序列（price/return）完全缺失 | 阻断，返回 degraded CalibrationResult，07 决定是否暂停 workflow |
| GoalSolverParams 核心参数无法构造且无先验 | 同上 |
| ConstraintRawSnapshot 存在 CONSTRAINT_BOUNDS_CONFLICT | 阻断，等待人工确认后重跑 |

### 7.3 降级原则

- 降级优先于静默伪造
- 沿用先验优先于临时拍脑袋重建
- 强约束优先于激进优化
- `CalibrationResult.calibration_quality` 必须如实反映降级状态，不允许伪报 "full"

校准质量推断表（冻结版）：

| `calibration_quality` | 判定规则 |
|---|---|
| `"full"` | 无 warn / error 级降级标记，全部核心域正常 |
| `"partial"` | 存在 warn 级降级，但无阻断级 error |
| `"degraded"` | 存在任一阻断级 error，或核心参数只能沿用先验无法正常重算 |

---

## 8. 代码组织

```text
src/
└── calibration/
    ├── types.py
    │   # MarketState / ConstraintState / BehaviorState
    │   # RuntimeOptimizerParams / EVParams（04/10 仅 import 使用，禁止重复定义）
    │   # ParamVersionMeta / CalibrationResult
    │   # （MarketAssumptions / GoalSolverParams 从 goal_solver.types import）
    │
    ├── market_interpreter.py
    │   # interpret_market_state()
    │   # calibrate_market_assumptions()
    │   # _infer_risk_environment()
    │   # _infer_volatility_regime()
    │   # _classify_liquidity()
    │   # _classify_valuation()
    │   # _check_correlation_spike()
    │   # _shrink_returns()
    │   # _clip_correlation_to_psd()
    │
    ├── behavior_interpreter.py
    │   # interpret_behavior_state()
    │   # _infer_chase_risk()
    │   # _infer_panic_risk()
    │   # _compute_penalty_coeff()
    │
    ├── constraint_interpreter.py
    │   # interpret_constraint_state()
    │   # _calibrate_effective_drawdown_threshold()
    │
    ├── params_updater.py
    │   # update_goal_solver_params()
    │   # update_runtime_optimizer_params()
    │   # update_ev_params()
    │   # _generate_version_id()
    │
    └── calibrator.py
        # run_calibration()（主入口）
        # _derive_calibration_quality()
        # _assemble_calibration_result()
```

### 文件职责约束

| 文件 | 允许 | 禁止 |
|------|------|------|
| `types.py` | 类型定义、枚举、dataclass | 业务推断逻辑 |
| `market_interpreter.py` | 市场解释、MarketAssumptions 校准 | 行为解释、约束解释、EV 打分 |
| `behavior_interpreter.py` | 行为信号解释、惩罚系数推断 | 市场解释、候选动作生成 |
| `constraint_interpreter.py` | 约束状态构造、阈值校准 | 参数版本管理、EV 逻辑 |
| `params_updater.py` | 参数对象版本更新 | 状态解释、候选生成 |
| `calibrator.py` | 主入口编排与质量推断 | 持久化、workflow 触发、UI 文本 |

---

## 9. v1 范围

### 9.1 v1 应做到

- 五个核心类型完整定义：MarketState / ConstraintState / BehaviorState / RuntimeOptimizerParams / EVParams
- CalibrationResult 完整定义与 ParamVersionMeta 治理
- market_interpreter：基于 raw 序列的保守校准（收缩均值、下限波动、PSD 修正）
- behavior_interpreter：基于计数与事件列表的简单规则推断
- constraint_interpreter：硬约束透传 + effective_drawdown 校准 + cooldown 注入
- params_updater：版本 ID 生成 + 参数封装
- run_calibration 主入口：编排顺序固定、降级路径清晰
- 与 03 接口对齐（SnapshotBundle 消费）
- 与 02 接口对齐（MarketAssumptions / GoalSolverParams 产出）
- 与 04 接口对齐（MarketState / ConstraintState / BehaviorState 产出）
- 与 10 接口对齐（EVParams 产出）

### 9.2 v1 不做

- Black-Litterman 主观看法融合（v2 方向）
- 全自动复杂自学习校准（黑盒 ML 参数调节）
- 跨账户联合风险分析
- 高度自适应的动态 regime 模型
- 将 05 做成"万能策略中枢"
- 直接触发 workflow 或拍板动作

---

## 10. 验收标准

| 维度 | 标准 |
|------|------|
| **口径统一性** | 长期求解（02）与运行期优化（04/10）基于同一套 05 解释体系 |
| **边界清晰性** | 05 未越界执行采集、编排、求解、评分 |
| **参数可追踪性** | 每个参数对象有清晰 version_id、source_bundle_id、updated_reason |
| **降级可解释性** | 输入不完整时给出受控、保守、透明的降级结果 |
| **回写受控性** | 参数更新可审计、可回放、can_be_replayed=True when is_temporary=False |
| **类型导入方向** | 05 从 goal_solver.types import MarketAssumptions / GoalSolverParams；反向不允许 |
| **参数定义唯一性** | `RuntimeOptimizerParams / EVParams` 仅在 05 定义；04/10 不重复声明 |

---

## 11. 文件关联索引

| 文件 | 关系 |
|------|------|
| `03_snapshot_and_ingestion.md` | 提供 SnapshotBundle；05 是 03 的第一消费者 |
| `02_goal_solver.md` | 提供 MarketAssumptions / GoalSolverParams 类型定义；05 更新并返回这些对象 |
| `04_runtime_optimizer.md` | 消费 MarketState / ConstraintState / BehaviorState / RuntimeOptimizerParams |
| `10_ev_engine.md` | 消费 EVParams（通过 04 传入 EVState）|
| `07_orchestrator_workflows.md` | 触发 05 校准；接收 CalibrationResult 并注入下游 |
| `01_governance_ips.md` | 账户宪法是 ConstraintRawSnapshot 的来源；ips_bucket_boundaries 定义于此 |
| `08_allocation_engine.md` | 独立生成 `candidate_allocations`；05 不生成、不筛选、不改写战略候选集 |

---

## 12. 实现约定

| 约定 | 说明 |
|------|------|
| 百分比口径 | 全部 0~1 浮点，禁止 0~100 |
| 纯函数约束 | `run_calibration` 不写外部状态，不持久化，不产生副作用 |
| 内部函数命名 | 下划线前缀：`_infer_*`, `_classify_*`, `_shrink_*`, `_compute_*` |
| MarketAssumptions 不在 05 重新定义 | 类型从 `goal_solver.types` 导入，禁止重定义 |
| 参数不允许下游修改 | 02/04/10 对 params 对象只读，修改必须经过 05 |
| 降级不静默 | `CalibrationResult.degraded_domains` 必须完整列出，不允许为空但 quality != "full" |
| datetime 时区 | 全部使用 UTC aware datetime |
| 版本 ID 全局唯一 | 格式 "{param_type}_{ISO timestamp}"，同一毫秒内若有多次更新需加自增后缀 |

---

*文档版本：v1.0 | 状态：可交付实现*
*下次修订触发条件：MarketAssumptions 类型变更（02）、EVParams 字段变更（10）、新行为信号类型加入、或与 07 接口调整*


---

## 附录 A：05 作为 04 / 10 状态类型唯一来源的补丁（v1.1，追加说明，不替换上文原文）

> 本附录用于收口 `05_constraint_and_calibration.md` 与 `04_runtime_optimizer.md` / `10_ev_engine.md`
> 之间的状态类型口径。  
> **原则：05 保持 canonical source 地位；不删除上文原文，只通过追加字段与适配约定补足运行期能力。**

### A.1 裁决结论

1. `MarketState / ConstraintState / BehaviorState` 的**唯一正式定义权**仍归 05。
2. 10 中出现的同名 dataclass 视为**历史消费视图**，不再作为正式类型定义。
3. 若 04 / 10 需要更多运行期字段，优先**补到 05 的 canonical type**，而不是在 04 / 10 中重复定义同名结构。
4. `MarketAssumptions` 仍保持在 `GoalSolverParams.market_assumptions` 中；**不并回 `MarketState`**。

### A.2 `MarketState` 的冻结语义

`MarketState` 继续表示“运行期定性市场状态”，其职责不变：

- 风险环境标签
- 波动状态标签
- 流动性状态
- 估值位置
- 相关性预警
- 质量与降级标记

**明确禁止**以下字段并入 `MarketState` 正式定义：

- `expected_returns`
- `volatility`
- `correlation_matrix`

这些字段属于长期求解参数，应继续由：

```python
GoalSolverInput.solver_params.market_assumptions
```

提供，供 EV 的 GoalImpact / RiskPenalty 读取。

### A.3 `ConstraintState` 追加字段（不替换原字段）

为满足 04 / 10 的运行期执行需要，`ConstraintState` 在保持上文原字段不变的前提下，追加以下字段：

```python
@dataclass
class ConstraintState:
    # ...上文原字段保持不变...

    # ---- 运行期 / EV 消费扩展字段（v1.1 追加）----
    qdii_available: float = 0.0
    # 剩余 QDII 可用额度（元）；若不适用，置 0 或由 Orchestrator 注入保守值

    premium_discount: dict[str, float] = field(default_factory=dict)
    # 各资产桶或产品映射的折溢价信息；正=溢价，负=折价

    transaction_fee_rate: dict[str, float] = field(default_factory=dict)
    # 各资产桶交易费率；无专门费率时由下游退化到 EVParams.transaction_cost_rate

    bucket_category: dict[str, Literal["core", "defense", "satellite"]] = field(default_factory=dict)
    # 资产桶分类映射；04 与 10 均应消费本字段，禁止通过字符串推断

    bucket_to_theme: dict[str, str | None] = field(default_factory=dict)
    # 资产桶到主题映射；主题无归属时置 None
```

### A.4 为什么 `ConstraintState` 需要这样扩展

如果不把这些字段并入 05，会出现两个问题：

- 04 / 10 将再次各自维护一套 `ConstraintState` 变体；
- `bucket_category / bucket_to_theme` 已经被 04 的校验与候选生成正式依赖，不上收回 05 会导致定义权漂移。

因此此处追加字段是**补功能，不改边界**。

### A.5 `BehaviorState` 追加字段（不替换原字段）

为满足冷静期阻断、行为惩罚和决策卡展示，`BehaviorState` 在保持上文原字段不变的前提下，追加以下规范化运行字段：

```python
@dataclass
class BehaviorState:
    # ...上文原字段保持不变...

    # ---- 运行期 / EV 消费扩展字段（v1.1 追加）----
    high_emotion_flag: bool = False
    # 当前是否处于高情绪状态；建议由 recent_chase_risk / recent_panic_risk / 行为事件综合推断

    panic_flag: bool = False
    # 当前是否存在恐慌性行为信号；可由 recent_panic_risk >= moderate 映射

    emotion_score: float = 0.0
    # 标准化情绪分值（0~1）；供 EV 行为惩罚与 09 展示使用

    action_frequency_30d: int = 0
    # 近 30 天动作次数的整数口径；若原始值来自 trade_frequency_30d（float），
    # 允许在发布 CalibrationResult 前做 round / floor 固化

    recent_chasing_flag: bool = False
    # 与 04 既有消费口径保持一致；建议定义为 recent_chase_risk in ["moderate", "high"]
```

### A.6 这些追加字段如何与原字段共存

- `recent_chase_risk / recent_panic_risk` 仍是**解释层主口径**；
- `high_emotion_flag / panic_flag / emotion_score / recent_chasing_flag` 是**运行期消费口径**；
- 二者不是冲突关系，而是“解释结果 → 运行标志”的上下游关系。

### A.7 对 04 / 10 的正式约束

04 / 10 在引用 05 状态对象时，必须遵守：

1. **不得在本地重复定义同名 dataclass 作为正式类型。**
2. **不得把长期定量参数塞回 `MarketState`。**
3. **若需要局部别名，应使用 adapter / helper，而不是再造一份类型。**

### A.8 推荐的适配辅助函数（可选，不强制）

```python
def build_ev_inputs_from_calibration(
    calibration: CalibrationResult,
) -> tuple[MarketState, ConstraintState, BehaviorState]:
    # 直接返回 05 的 canonical 状态对象
    return (
        calibration.market_state,
        calibration.constraint_state,
        calibration.behavior_state,
    )
```
