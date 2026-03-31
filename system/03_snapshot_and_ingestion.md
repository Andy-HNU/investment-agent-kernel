# 03_snapshot_and_ingestion.md
# 输入快照与采集层设计规格 v1.0

> **文档定位**：本文件是输入快照与采集层（Snapshot & Ingestion Layer）的正式实现规格，可直接交付 Codex 实现。
>
> 它是 `05_constraint_and_calibration.md` 的上游原始输入层，是 `07_orchestrator_workflows.md` 在每轮 workflow 触发前的数据准备层。
>
> **本层与 Allocation Engine 的边界说明**：本层编号 03 为 snapshot/ingestion；原设计中曾以 03 编号描述 Allocation Engine，该模块待独立编号为 `08_allocation_engine.md`，与本文件无直接交叉。
>
> **本层不参与任何投资决策、参数校准或动作评分。**

---

## 0. 一句话定义

**Snapshot & Ingestion Layer 是系统每轮运行的输入底座。**

它从外部数据源、账户侧、目标配置、约束规则、行为日志五个域中采集原始输入，完成统一化、快照化与版本化，向下游提供一个可复现的输入基线（SnapshotBundle）。

它只回答一件事：

> **当前这一轮系统运行，到底基于哪一份输入世界在工作。**

---

## 1. 职责边界

### 1.1 本层负责

- 按五域（市场 / 账户 / 目标 / 约束 / 行为）接收并整理原始输入
- 对原始输入执行字段统一化、单位归一、时间格式统一、缺失值标记
- 为每个域生成带有唯一标识和质量标记的快照对象
- 将五域快照组装成统一的 `SnapshotBundle`
- 为 bundle 分配可追踪的 `bundle_id`
- 标记数据质量、时效性、完整性
- 向 `05` 和 `07` 提供可消费的 bundle

### 1.2 本层不负责

- 计算 `MarketAssumptions`（由 `05` 负责）
- 识别 market regime（由 `05` 负责）
- 生成 `MarketState / ConstraintState / BehaviorState`（由 `05` 负责）
- 校准 `EVParams / GoalSolverParams / RuntimeOptimizerParams`（由 `05` 负责）
- 生成候选战略配置（由 `08_allocation_engine.md` 负责）
- 生成候选动作（由 `04_runtime_optimizer.md` 负责）
- EV 评分（由 `10_ev_engine.md` 负责）
- workflow 触发判断（由 `07_orchestrator_workflows.md` 负责）
- 原始数据持久化至数据仓库（由基础设施层负责）

### 1.3 与 05 的边界

| 本层（03）| 下游（05）|
|---------|---------|
| 把世界拿进来并冻结 | 解释这些输入在系统里意味着什么 |
| 生成原始快照对象 | 生成 MarketState / MarketAssumptions / ConstraintState / BehaviorState |
| 标记数据质量问题（打 flag）| 决定能否继续解释（降级还是阻断）|
| 不直接访问投资决策逻辑 | 不回头访问原始外部源 |

> **约束**：03 不直接生成 MarketState / MarketAssumptions；05 不直接回头访问原始外部源。

---

## 2. 上下游关系

```
外部数据源
   │
   ▼
03_snapshot_and_ingestion  ─── SnapshotBundle ──►  05_constraint_and_calibration
                                    │
                                    └──────────────►  07_orchestrator_workflows
                                                              │
                                            ┌─────────────────┴────────────┐
                                            ▼                              ▼
                                   02_goal_solver              04_runtime_optimizer
                                   （消费校准后参数）           （消费状态与校准后参数）
```

---

## 3. 核心类型定义

### 3.1 质量与完整性枚举

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class CompletenessLevel(Enum):
    FULL     = "full"      # 所有必需字段均完整
    PARTIAL  = "partial"   # 非关键字段缺失，可降级继续
    DEGRADED = "degraded"  # 关键字段缺失，需告知下游

class QualityCode(Enum):
    # 数据时效性
    STALE_MARKET_DATA        = "STALE_MARKET_DATA"        # 市场数据超过可接受更新窗口
    STALE_ACCOUNT_DATA       = "STALE_ACCOUNT_DATA"       # 持仓快照过旧
    # 完整性
    BEHAVIOR_DOMAIN_MISSING  = "BEHAVIOR_DOMAIN_MISSING"  # 行为域缺失（非阻断）
    SHORT_HISTORY_WINDOW     = "SHORT_HISTORY_WINDOW"     # 市场序列长度不足建议下限
    PARTIAL_BUCKET_COVERAGE  = "PARTIAL_BUCKET_COVERAGE"  # 持仓桶未完整覆盖 IPS 桶宇宙
    # 数据异常
    WEIGHT_SUM_MISMATCH      = "WEIGHT_SUM_MISMATCH"      # 权重合计偏离 1.0 超过容差
    CORRELATION_OUT_OF_RANGE = "CORRELATION_OUT_OF_RANGE" # 相关性矩阵含超范围值
    GOAL_HORIZON_TOO_SHORT   = "GOAL_HORIZON_TOO_SHORT"   # 目标期限 < 6 个月
    # 配置约束
    CONSTRAINT_BOUNDS_CONFLICT = "CONSTRAINT_BOUNDS_CONFLICT"  # 桶下限 > 上限
    COOLING_PERIOD_ACTIVE      = "COOLING_PERIOD_ACTIVE"       # 当前处于冷静期（信息性）

@dataclass
class QualityFlag:
    code: QualityCode
    severity: Literal["info", "warn", "error"]
    detail: str
    domain: Literal["market", "account", "goal", "constraint", "behavior", "bundle"]
```

### 3.2 快照元信息（所有域共用）

```python
@dataclass
class SnapshotMeta:
    snapshot_id: str
    # ID 格式建议："{domain}_{account_profile_id}_{ISO timestamp}"
    # 例：market_acc001_20260322T143000Z
    as_of_time: datetime          # 数据所代表的时间点（业务时间）
    ingest_time: datetime         # 本次采集完成的时间（系统时间）
    source_ref: str               # 数据来源标识（如 "broker_api_v2", "manual_upload"）
    schema_version: str = "v1.0" # 快照对象结构版本
    quality_flags: list[QualityFlag] = field(default_factory=list)
    completeness: CompletenessLevel = CompletenessLevel.FULL
```

### 3.3 市场域原始快照

```python
@dataclass
class MarketRawSnapshot:
    meta: SnapshotMeta

    # 价格与收益序列（按资产桶）
    # key: IPS 资产桶名称，与 ConstraintRawSnapshot.ips_bucket_boundaries 对齐
    price_series: dict[str, list[float]]      # 桶 → 价格序列（时间正序）
    return_series: dict[str, list[float]]     # 桶 → 月度收益率序列（时间正序）
    series_dates: list[str]                   # ISO 日期字符串列表，与序列长度对齐

    # 原始统计量（未经 05 校准）
    raw_volatility: dict[str, float]          # 桶 → 年化波动率估计
    raw_correlation: dict[str, dict[str, float]]  # 桶 → 桶 → 相关系数

    # 可选增益字段（缺失时 05 降级处理）
    valuation_z_scores: dict[str, float] = field(default_factory=dict)
    # 估值 Z-score：正值=偏贵，负值=偏便宜，|z| > 1.5 视为显著
    liquidity_scores: dict[str, float] = field(default_factory=dict)
    # 流动性评分：0.0（极差）~ 1.0（极佳）
    macro_tags: dict[str, str] = field(default_factory=dict)
    # 宏观标签，键值对，例 {"rate_env": "rising", "credit_spread": "widening"}

    # 质量约束参数
    min_recommended_history_months: int = 36
    # 序列建议最低历史月数；低于此值打 SHORT_HISTORY_WINDOW warn flag

    # 校验规则：
    # 1. price_series / return_series / series_dates 长度必须一致（同桶内）
    # 2. raw_correlation 对角线元素必须 = 1.0
    # 3. raw_correlation 所有值必须在 [-1.0, 1.0]，否则打 CORRELATION_OUT_OF_RANGE
    # 4. raw_volatility 所有值 > 0.0
```

### 3.4 账户域原始快照

```python
@dataclass
class AccountRawSnapshot:
    meta: SnapshotMeta
    account_profile_id: str

    # 持仓原始值
    holdings: dict[str, float]    # 桶 → 市值（元）
    total_value: float            # 账户总市值（元）
    available_cash: float         # 可用现金（元）
    last_rebalance_date: str      # ISO 日期，最近一次调仓日期

    # 盈亏摘要（信息性）
    realized_pnl_ytd: float       # 本年度已实现盈亏（元）
    unrealized_pnl: float         # 当前未实现盈亏（元）

    # 由采集层计算（非原始输入）
    weights: dict[str, float]
    # 计算规则：weights[bucket] = holdings[bucket] / total_value
    # 要求：sum(weights.values()) 应在 [0.99, 1.01]，超出打 WEIGHT_SUM_MISMATCH

    remaining_horizon_months: int
    # 由 Orchestrator 注入，表示账户当前剩余目标月数
    # 03 不主动计算，由调用方传入

    current_drawdown: float
    # 当前相对峰值回撤（0~1 正数）
    # 计算：1 - current_value / peak_value（峰值窗口统一为滚动 24 个月高点；若账户历史不足 24 个月，则使用账户成立以来高点）

    # 校验规则：
    # 1. total_value >= 0
    # 2. available_cash >= 0 且 <= total_value
    # 3. holdings 中所有值 >= 0
    # 4. holdings 桶名与 IPS 桶宇宙的覆盖关系（交集不为空）
```

### 3.5 目标域原始快照

```python
@dataclass
class GoalRawSnapshot:
    meta: SnapshotMeta
    account_profile_id: str

    # 目标定义（对应 GoalCard，但独立保存，不直接 import goal_solver 类型）
    goal_amount: float
    horizon_months: int
    goal_description: str
    priority: Literal["essential", "important", "aspirational"]
    risk_preference: Literal["conservative", "moderate", "aggressive"]
    success_prob_threshold: float   # (0.0, 1.0)

    # 现金流计划（原始结构，由 Orchestrator 适配为 CashFlowPlan）
    monthly_contribution: float     # 常规月投（元）
    annual_step_up_rate: float      # 年度递增率（0.0 ~ 0.5）
    cashflow_events_raw: list[dict]
    # 每条 dict 的必填字段：{month_index: int, amount: float, event_type: str, description: str}
    # 允许附加字段，但 03 v1 只依赖上述四个键做完整性检查；缺任一键即打 flag
    # 注意：amount 符号由调用方负责，正数=流入，负数=流出
    # 03 不验证 event_type 的业务语义，只验证字段存在、类型可解析、month_index 落在合法区间
    # 转换为 CashFlowEvent 列表由 Orchestrator 在调用 Goal Solver 前完成

    # 校验规则：
    # 1. goal_amount > 0
    # 2. horizon_months >= 6，否则打 GOAL_HORIZON_TOO_SHORT error
    # 3. success_prob_threshold in (0.0, 1.0)
    # 4. monthly_contribution >= 0
    # 5. annual_step_up_rate in [0.0, 0.5]
```

### 3.6 约束域原始快照

```python
@dataclass
class ConstraintRawSnapshot:
    meta: SnapshotMeta
    account_profile_id: str

    # IPS 硬约束（直接来自账户宪法）
    ips_bucket_boundaries: dict[str, tuple[float, float]]
    # {桶名: (下限, 上限)}，均为 0~1 浮点
    satellite_cap: float          # 卫星桶总上限（0~1）
    theme_caps: dict[str, float]  # 主题名 → 上限比例（0~1）
    qdii_cap: float               # QDII 总上限（0~1）
    liquidity_reserve_min: float  # 最低流动性储备比例（0~1）
    max_drawdown_tolerance: float # 最大可承受回撤（0~1，硬约束）

    # 再平衡规则
    rebalancing_band: float       # 再平衡触发偏离阈值（0~1）
    cooling_period_days: int      # 操作冷静期天数（>= 0）
    forbidden_actions: list[str]  # 当前被明确禁止的动作类型列表

    # 软偏好（建议性，不是硬约束）
    soft_preferences: dict[str, Any] = field(default_factory=dict)
    # 例：{"prefer_passive": True, "max_product_count": 8}

    # 校验规则：
    # 1. 所有 ips_bucket_boundaries 的下限 <= 上限，否则打 CONSTRAINT_BOUNDS_CONFLICT
    # 2. satellite_cap / qdii_cap / liquidity_reserve_min / max_drawdown_tolerance 在 [0, 1]
    # 3. rebalancing_band > 0
    # 4. cooling_period_days >= 0
```

### 3.7 行为域原始快照

```python
@dataclass
class BehaviorRawSnapshot:
    meta: SnapshotMeta
    account_profile_id: str

    # 交易频率统计
    trade_count_90d: int         # 过去 90 天操作次数
    trade_count_30d: int         # 过去 30 天操作次数

    # 行为信号（由行为分析层预标注，或由日志推断）
    detected_chase_events: list[str]   # 追涨事件描述列表
    detected_panic_events: list[str]   # 恐慌事件描述列表

    # override 记录
    override_count_90d: int            # 过去 90 天人工覆盖建议次数

    # 冷静期状态
    active_cooldown_until: str | None  # ISO 日期字符串，None = 无冷静期

    # 原始行为日志（保留供 05 更深入分析）
    behavior_log_raw: list[dict] = field(default_factory=list)
    # 每条 dict: {date, action_type, trigger, note}

    # 注意：行为域为可选域。若无行为日志，调用方传入 None 而非空对象。
```

### 3.8 快照 Bundle（系统核心交付对象）

```python
@dataclass
class SnapshotBundle:
    bundle_id: str
    # 格式建议："{account_profile_id}_{ISO timestamp}"
    # 例：acc001_20260322T143000Z
    # 这是系统内部追踪的核心 ID，GoalSolverInput.snapshot_id 应基于此派生

    account_profile_id: str
    created_at: datetime

    # 五域快照
    market: MarketRawSnapshot
    account: AccountRawSnapshot
    goal: GoalRawSnapshot
    constraint: ConstraintRawSnapshot
    behavior: BehaviorRawSnapshot | None  # 可选域，缺失不阻断

    # Bundle 整体质量
    bundle_quality: CompletenessLevel
    # 推断规则：
    # FULL     = 五域均 FULL（behavior 可为 None 但其余四域 FULL）
    # PARTIAL  = 非阻断性问题存在（如 SHORT_HISTORY_WINDOW, BEHAVIOR_DOMAIN_MISSING）
    # DEGRADED = 任意核心域（market/account/goal/constraint）出现 error 级 flag

    missing_domains: list[str]           # 完全缺失的域名列表
    quality_summary: list[QualityFlag]   # 所有域 flag 的汇总视图
```

---

## 4. 对外接口定义

### 4.1 主构建入口

```python
def build_snapshot_bundle(
    account_profile_id: str,
    as_of: datetime,
    market_raw: dict,                      # 来自市场数据适配器的原始 dict
    account_raw: dict,                     # 来自账户/持仓适配器的原始 dict
    goal_raw: dict,                        # 来自目标配置的原始 dict
    constraint_raw: dict,                  # 来自 IPS/规则配置的原始 dict
    behavior_raw: dict | None,             # 来自行为日志，可为 None
    remaining_horizon_months: int,         # 由 Orchestrator 注入
    schema_version: str = "v1.0"
) -> SnapshotBundle:
    """
    将五域原始输入构建为统一 SnapshotBundle。

    构建步骤：
    1. 依次解析各域原始 dict → 对应 RawSnapshot 对象
    2. 对每个快照执行域内校验，收集 QualityFlag
    3. 推断每个快照的 CompletenessLevel
    4. 组装 SnapshotBundle，派生 bundle_quality 与 quality_summary
    5. 生成 bundle_id

    注意：本函数不修改任何外部状态，不持久化，不调用 05/07/02/04/10。
    """
    ...
```

### 4.2 域内校验函数

```python
def validate_market_snapshot(snap: MarketRawSnapshot) -> list[QualityFlag]:
    """
    对市场快照执行校验，返回所有发现的 QualityFlag。
    不抛出异常，只返回 flag 列表，由调用方决定是否阻断。
    """
    ...

def validate_account_snapshot(snap: AccountRawSnapshot) -> list[QualityFlag]:
    """校验账户快照权重合计、持仓值非负、现金比例等。"""
    ...

def validate_goal_snapshot(snap: GoalRawSnapshot) -> list[QualityFlag]:
    """校验目标期限、概率阈值、现金流参数合法性，并检查 cashflow_events_raw 的必填字段结构。"""
    ...

def validate_constraint_snapshot(snap: ConstraintRawSnapshot) -> list[QualityFlag]:
    """校验桶边界（下限<=上限）、比例范围、冷静期参数。"""
    ...

def validate_behavior_snapshot(snap: BehaviorRawSnapshot) -> list[QualityFlag]:
    """校验行为快照（计数非负、日期格式等），行为域为可选。"""
    ...
```

### 4.3 Bundle 整体校验

```python
def validate_bundle(bundle: SnapshotBundle) -> list[QualityFlag]:
    """
    在各域快照已分别校验的基础上，执行跨域一致性校验：
    1. account.weights 的桶名是否覆盖 constraint.ips_bucket_boundaries 的桶宇宙
       （不覆盖 → 打 PARTIAL_BUCKET_COVERAGE warn）
    2. market.price_series 的桶集合是否与 constraint 桶宇宙兼容
    3. goal.horizon_months 与 account.remaining_horizon_months 是否接近（偏差 > 3 个月时 warn）
    4. constraint.cooling_period_days > 0 且 behavior 为 None 时，打 info flag 提示
    
    注：本函数不修改 bundle，只返回增量 flag 列表。
    """
    ...
```

---

## 5. bundle_id 与 GoalSolverInput.snapshot_id 的关系

`GoalSolverInput.snapshot_id` 由 Orchestrator 负责生成，格式应派生自 `SnapshotBundle.bundle_id`：

```
bundle_id:   acc001_20260322T143000Z
snapshot_id: acc001_20260322T143000Z_goalsolve
             └─── 由 Orchestrator 在调用 Goal Solver 前拼接后缀 ───┘
```

03 只负责生成 `bundle_id`；Orchestrator 读取 bundle 后，将 `bundle_id` 注入 `GoalSolverInput.snapshot_id`。
二者关系是一对一派生关系，不允许多个 bundle 对应同一 snapshot_id。

---

## 6. 降级与保守策略

### 6.1 可降级的情况（PARTIAL）

以下情况 03 打 warn flag，bundle 仍可继续向 05 传递：

| 情况 | Flag Code | 05 的处理方式 |
|------|-----------|-------------|
| 行为域缺失 | `BEHAVIOR_DOMAIN_MISSING` | 生成默认 BehaviorState（低惩罚系数）|
| 市场序列长度 < 36 月 | `SHORT_HISTORY_WINDOW` | 使用更保守的波动估计 |
| 持仓桶部分缺失 | `PARTIAL_BUCKET_COVERAGE` | 缺失桶权重补 0，打标 |
| 权重合计偏离 | `WEIGHT_SUM_MISMATCH` | 归一化后继续 |

### 6.2 不可降级的情况（DEGRADED）

以下情况 03 打 error flag，07 应评估是否阻断本轮 workflow：

| 情况 | Flag Code | 建议处理 |
|------|-----------|---------|
| 目标期限 < 6 个月 | `GOAL_HORIZON_TOO_SHORT` | 提示用户更新目标 |
| IPS 桶边界冲突 | `CONSTRAINT_BOUNDS_CONFLICT` | 人工确认后继续 |

> 即便出现上述 error flag，03 也只返回带 flag 的 bundle，不输出 workflow 阻断决定。

### 6.3 03 的降级原则

- 03 **只打 flag**，不自行决定是否继续
- 阻断决策由 `07_orchestrator_workflows.md` 根据 bundle_quality 判断
- 03 不静默糊过数据异常，必须显式打标

---

## 7. 代码组织

```text
src/
└── snapshot_ingestion/
    ├── types.py
    │   # CompletenessLevel / QualityCode / QualityFlag / SnapshotMeta
    │   # MarketRawSnapshot / AccountRawSnapshot / GoalRawSnapshot
    │   # ConstraintRawSnapshot / BehaviorRawSnapshot / SnapshotBundle
    │
    ├── validators.py
    │   # validate_market_snapshot()
    │   # validate_account_snapshot()
    │   # validate_goal_snapshot()
    │   # validate_constraint_snapshot()
    │   # validate_behavior_snapshot()
    │   # validate_bundle()
    │
    ├── builder.py
    │   # build_snapshot_bundle()
    │   # _parse_market_raw()
    │   # _parse_account_raw()
    │   # _parse_goal_raw()
    │   # _parse_constraint_raw()
    │   # _parse_behavior_raw()
    │   # _derive_bundle_quality()
    │   # _generate_bundle_id()
    │
    └── adapters/
        # 可选：各外部数据源的适配器
        # 不属于核心接口，按实际接入来源扩展
        ├── broker_adapter.py
        └── manual_upload_adapter.py
```

### 文件职责约束

| 文件 | 允许 | 禁止 |
|------|------|------|
| `types.py` | 类型定义、枚举、dataclass | 业务校验逻辑 |
| `validators.py` | 返回 flag 列表的纯校验函数 | 修改快照、持久化、调用 05/07 |
| `builder.py` | 解析 → 校验 → 组装 → 派生 bundle_id | EV 逻辑、参数校准、workflow 判断 |
| `adapters/` | 外部源格式转换为 raw dict | 业务解释、校准逻辑 |

---

## 8. v1 范围

### 8.1 v1 应做到

- 五域原始快照类型完整定义
- 各域独立校验函数（返回 flag 列表，纯函数）
- SnapshotBundle 组装
- bundle_id 生成
- bundle_quality 推断规则
- 跨域一致性校验（桶宇宙覆盖）
- 降级 flag 与 07 的降级契约说明
- bundle_id → GoalSolverInput.snapshot_id 的派生关系文档
- `cashflow_events_raw` 的四键结构校验（`month_index / amount / event_type / description`）

### 8.2 v1 不做

- 多数据源自动仲裁
- 复杂数据修复（05 负责更保守的估计，03 不做修复）
- 高级特征工程（如 PCA、regime 检测）
- 实时事件流平台
- 直接生成 MarketAssumptions 或 MarketState
- 大规模分布式数据采集管道

---

## 9. 验收标准

| 维度 | 标准 |
|------|------|
| **输入统一性** | 同一轮运行可明确引用同一 bundle_id 的输入基线 |
| **可回指性** | 05 / 02 / 04 / 10 均可通过 bundle_id 回指当时的输入世界 |
| **降级透明性** | 数据不完整时显式打 flag，不静默糊过 |
| **可复盘性** | 复盘时能完整还原当轮系统看见了哪一份输入 |
| **边界干净性** | 无投资决策逻辑、无参数校准公式、无 EV 评分进入本层 |

---

## 10. 文件关联索引

| 文件 | 关系 |
|------|------|
| `05_constraint_and_calibration.md` | 直接消费 SnapshotBundle；05 是 03 的第一消费者 |
| `07_orchestrator_workflows.md` | 触发 03 采集；根据 bundle_quality 决定是否阻断 workflow |
| `02_goal_solver.md` | 消费 03 产生的 GoalRawSnapshot（经 Orchestrator 适配为 GoalSolverInput）；`GoalSolverInput.snapshot_id` 派生自 `bundle_id` |
| `04_runtime_optimizer.md` | 消费 05 解释后的状态，状态上游来自 03 bundle |
| `08_allocation_engine.md` | 不直接依赖 03；候选配置由 Allocation Engine 独立生成 |
| `01_governance_ips.md` | 账户宪法是 ConstraintRawSnapshot 的来源文档 |

---

## 11. 实现约定

| 约定 | 说明 |
|------|------|
| 百分比口径 | 全部 0~1 浮点，禁止 0~100 |
| 纯函数约束 | `build_snapshot_bundle` 不写外部状态，不持久化 |
| 内部函数命名 | 下划线前缀：`_parse_*`, `_derive_*`, `_generate_*` |
| 行为域可选 | behavior 为 None 时不打 error，只打 BEHAVIOR_DOMAIN_MISSING warn |
| 类型不跨域导入 | `types.py` 不 import 来自 `goal_solver/`, `runtime_optimizer/`, `calibration/` 的类型 |
| datetime 时区 | 全部使用 UTC aware datetime，禁止 naive datetime |
| 字段名对齐 | 桶名必须与 IPS 桶宇宙保持一致，不允许别名推断 |

---

*文档版本：v1.0 | 状态：可交付实现*
*下次修订触发条件：新数据源接入、五域结构变更、与 05 接口调整*
