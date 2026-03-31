# 08_allocation_engine.md
# 候选战略配置生成层设计规格 v1.0

> **文档定位**：本文件描述“目标求解与配置引擎层”中的 Allocation Engine 模块职责、输入输出、候选生成流程、工程约束与自检结果，可直接交付 Codex 实现。
>
> 它是 `00_system_topology_and_main_flow.md` 中 `candidate_allocations` 的唯一来源模块，是 `02_goal_solver.md` 的直接上游候选空间生成层。
>
> **本层不做市场解释、不做参数校准、不做 Monte Carlo 求解、不做运行期动作优化。**
>
> **本层的唯一任务是：在治理边界内，生成一组合法、可解释、结构多样、可直接送入 Goal Solver 的战略候选配置。**

---

## 0. 一句话定义

**Allocation Engine 是系统的战略候选配置生成中枢。**

它基于账户治理边界、目标画像、现金流路径与资产桶宇宙，构造一组 `candidate_allocations`，供 `02_goal_solver.md` 做全局目标求解与推荐。

它不直接回答“最终选哪个”，但它决定：

> **Goal Solver 到底在什么样的战略候选空间中做评估。**

---

## 1. 职责边界

### 1.1 本层负责

- 消费治理层提供的账户画像视图、IPS 约束、桶映射与可投资宇宙
- 消费目标与现金流信息，生成与目标画像相匹配的战略候选模板
- 基于模板生成 bucket-level 权重草案
- 将草案投影到 IPS 可行域，保证满足硬约束
- 计算主题暴露、卫星占比、QDII 占比、流动性占比等结构指标
- 对候选配置执行静态合法性校验、去重、裁剪与稳定排序
- 为每个候选配置补充可解释元信息（名称、描述、复杂度、来源模板）
- 输出 `candidate_allocations: list[StrategicAllocation]`
- 输出候选集元信息，供 Orchestrator / 日志 / 复盘使用

### 1.2 本层不负责

- 外部市场数据采集（由 `03_snapshot_and_ingestion.md` 负责）
- 市场状态解释与参数校准（由 `05_constraint_and_calibration.md` 负责）
- Goal Solver 完整求解、成功概率估算、Monte Carlo 仿真（由 `02_goal_solver.md` 负责）
- 运行期候选动作生成（由 `04_runtime_optimizer.md` 负责）
- EV 打分与动作排序（由 `10_ev_engine.md` 负责）
- workflow 触发、阻断、降级与路由（由 `07_orchestrator_workflows.md` 负责）
- 用户界面展示与文案输出（由 `09_decision_card_spec.md` 负责）
- 直接持久化与日志写入（由基础设施层负责）
- 读取 `SnapshotBundle`、`MarketState`、`BehaviorState`、`ConstraintState`、`EVParams` 等运行期对象

### 1.3 与 02 的边界

| 本层（08） | 下游（02） |
|---|---|
| 生成 `candidate_allocations` | 评估 `candidate_allocations` |
| 保证候选结构合法、可解释、多样 | 运行 Monte Carlo、做硬约束过滤、排序与推荐 |
| 不计算成功概率 | 计算成功概率与风险摘要 |
| 不决定最终推荐 | 负责推荐候选选择 |

> **约束**：08 不内嵌 Goal Solver 的概率求解逻辑；02 不反向生成或修改候选配置集合。

### 1.4 与 03 / 05 / 04 / 10 的边界

| 模块 | 关系 | 约束 |
|---|---|---|
| `03_snapshot_and_ingestion.md` | 无直接依赖 | 08 不直接读取 `SnapshotBundle` |
| `05_constraint_and_calibration.md` | 无直接依赖 | 08 不读取 `MarketState / ConstraintState / BehaviorState / EVParams` |
| `04_runtime_optimizer.md` | 间接关系 | 04 只在 QUARTERLY 前置重算链路中间接受益于 08 输出；正常运行期不直接调用 08 |
| `10_ev_engine.md` | 无直接依赖 | EV 不使用战略候选集做评分输入；EV 只处理运行期候选动作 |

### 1.5 与 01 的边界（治理与 IPS）

`01_governance_ips.md` 尚未上传，但根据 `02_goal_solver.md`、`04_runtime_optimizer.md` 与 `00_system_topology_and_main_flow.md`，治理层应负责以下长期稳定输入的定义与维护：

- IPS 桶边界（`ips_bucket_boundaries`）
- `bucket_category`（`core / defense / satellite`）
- `bucket_to_theme`（桶 → 主题）
- QDII 标识、流动性桶标识、账户可投白名单
- 风险偏好、复杂度偏好、主题禁投/限投规则

> **约束**：08 不自己发明 bucket 分类或主题映射；这些映射必须来自治理层或由 Orchestrator 显式注入。

---

## 2. 上下游关系

```text
治理与账户定义层（01）
   ├── 账户画像 / 风险偏好 / 复杂度偏好
   ├── IPS 桶边界
   ├── bucket_category / bucket_to_theme
   ├── 主题与 QDII 规则
   └── 可投资桶宇宙
                    │
                    ▼
               08_allocation_engine
                    │
                    ▼
     candidate_allocations: list[StrategicAllocation]
                    │
                    ▼
               02_goal_solver
                    │
                    ├── GoalSolverOutput
                    └── baseline / structure_budget / risk_budget
                              │
                              ▼
                     04_runtime_optimizer（季度链路间接受益）
```

补充说明：

- `03_snapshot_and_ingestion.md` 与 `05_constraint_and_calibration.md` 走的是另一条“输入快照 / 参数治理”并行链路，不是 08 的直接上游。
- `07_orchestrator_workflows.md` 是 08 的唯一合法调用方；08 本身不做 workflow 判定。
- `02_goal_solver.md` 的 `GoalSolverInput.candidate_allocations` 必须由 08 产出，不能由 02 自己补造。

---

## 3. 核心类型定义

### 3.1 说明：哪些类型复用，哪些类型由 08 独有

为避免跨模块重复定义，08 的类型策略如下：

- **复用 02 的正式类型**：`GoalCard`、`CashFlowPlan`、`AccountConstraints`、`StrategicAllocation`
- **由 08 独有定义**：`AllocationProfile`、`AllocationUniverse`、`AllocationTemplate`、`AllocationEngineParams`、`AllocationEngineInput`、`AllocationEngineResult`

> **约束**：08 不重新定义 `StrategicAllocation`，直接复用 02 的正式输出结构，保证接口直连。

### 3.2 AllocationProfile（08 消费的账户画像视图）

`02_goal_solver.md` 在上下游关系图中使用了 `AccountProfile` 一词，但未给出正式类型定义。
为避免与未来的 `01_governance_ips.md` 抢占类型所有权，08 在内部使用一个**归一化消费视图**：`AllocationProfile`。

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Any


@dataclass
class AllocationProfile:
    """
    08 内部消费的账户画像视图。
    由 Orchestrator 根据 01_governance_ips / 账户配置适配后传入。
    """
    account_profile_id: str

    risk_preference: Literal["conservative", "moderate", "aggressive"]
    complexity_tolerance: Literal["low", "medium", "high"] = "medium"

    # 产品与桶白名单/黑名单
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)

    # 主题侧偏好
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)

    # 境内外限制
    qdii_allowed: bool = True

    # 额外策略标记（预留）
    profile_flags: dict[str, Any] = field(default_factory=dict)
```

说明：

- `risk_preference` 与 `GoalCard.risk_preference` 应保持一致；若两者不一致，以 `GoalCard` 为最终目标偏好，以 `AllocationProfile` 作为治理/账户允许边界。
- `allowed_buckets / forbidden_buckets` 用于治理层的显式白名单/黑名单控制。

### 3.3 AllocationUniverse（资产桶宇宙与映射）

```python
@dataclass
class AllocationUniverse:
    """
    Allocation Engine 的候选生成宇宙。
    必须由治理层或 Orchestrator 显式提供，不允许字符串猜测。
    """
    buckets: list[str]

    # 必须完整覆盖 buckets
    bucket_category: dict[str, Literal["core", "defense", "satellite"]]
    bucket_to_theme: dict[str, str | None]

    # 特殊语义桶集合
    qdii_buckets: list[str] = field(default_factory=list)
    liquidity_buckets: list[str] = field(default_factory=list)

    # 可选元信息
    bucket_alias: dict[str, str] = field(default_factory=dict)   # 桶展示名
    bucket_order: list[str] = field(default_factory=list)        # 稳定排序顺序
```

校验要求：

- `bucket_category.keys()` 必须完整覆盖 `buckets`
- `bucket_to_theme.keys()` 必须完整覆盖 `buckets`
- `qdii_buckets` / `liquidity_buckets` 必须是 `buckets` 的子集
- 不允许通过桶名称字符串推断 category / theme

### 3.4 AllocationTemplate（内部模板）

```python
@dataclass
class AllocationTemplate:
    """
    候选战略配置模板。
    不是最终输出对象，而是内部生成规则的承载体。
    """
    template_name: str
    template_family: Literal[
        "defense_heavy",
        "balanced_core",
        "growth_tilt",
        "liquidity_buffered",
        "theme_tilt",
        "satellite_light",
    ]

    # 三大类目标总权重；最终仍需投影到 IPS 约束
    target_core_weight: float
    target_defense_weight: float
    target_satellite_weight: float

    # 可选主题倾斜
    preferred_theme: str | None = None
    theme_tilt_strength: float = 0.0      # 0~1

    # 可选流动性增强
    liquidity_buffer_bonus: float = 0.0   # 在 liquidity_buckets 上的额外权重需求
```

模板说明：

- 模板只表达“结构倾向”，不是最终合法权重。
- 最终输出必须经过投影、裁剪与合法性校验。

### 3.5 AllocationEngineParams（08 内部生成参数）

```python
@dataclass
class AllocationEngineParams:
    version: str = "v1.0.0"

    min_candidates: int = 4
    max_candidates: int = 8

    # 去重阈值：两组权重 L1 距离低于此值，视为同一候选
    dedup_l1_threshold: float = 0.08

    # 权重清理与数值稳定
    zero_clip_threshold: float = 1e-4
    weight_round_digits: int = 4

    # 复杂度评分权重
    complexity_bucket_count_weight: float = 0.35
    complexity_satellite_weight: float = 0.35
    complexity_theme_count_weight: float = 0.20
    complexity_special_rule_weight: float = 0.10

    # 主题倾斜与流动性增强的 v1 步长
    theme_tilt_step: float = 0.05
    liquidity_buffer_step: float = 0.05
```

### 3.6 AllocationEngineInput（主入口输入）

```python
# 由 02 定义的正式类型
from goal_solver.types import GoalCard, CashFlowPlan, AccountConstraints, StrategicAllocation

@dataclass
class AllocationEngineInput:
    account_profile: AllocationProfile
    goal: GoalCard
    cashflow_plan: CashFlowPlan
    constraints: AccountConstraints
    universe: AllocationUniverse
    params: AllocationEngineParams = field(default_factory=AllocationEngineParams)
```

### 3.7 AllocationEngineResult（本层唯一交付对象）

```python
@dataclass
class CandidateDiagnostics:
    allocation_name: str
    template_name: str
    theme_exposure: dict[str, float]
    satellite_weight: float
    qdii_weight: float
    liquidity_weight: float
    notes: list[str] = field(default_factory=list)


@dataclass
class AllocationEngineResult:
    candidate_set_id: str
    account_profile_id: str
    engine_version: str

    candidate_allocations: list[StrategicAllocation]
    diagnostics: list[CandidateDiagnostics]

    generation_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```

> **唯一交付约束**：下游真正消费的核心字段只有 `candidate_allocations`；其余字段仅供日志、调试、复盘、Orchestrator 记录使用。

---

## 4. 对外接口定义

### 4.1 主入口

```python
def run_allocation_engine(inp: AllocationEngineInput) -> AllocationEngineResult:
    """
    生成一组可直接送入 Goal Solver 的 candidate_allocations。

    纯函数约束：
    - 不写状态
    - 不持久化
    - 不访问外部市场数据
    - 同一输入应返回稳定一致的候选集
    """
```

### 4.2 子职责函数

```python
# ─── 输入校验 ────────────────────────────────────────────────

def validate_allocation_input(inp: AllocationEngineInput) -> list[str]:
    ...

# ─── 模板构造 ────────────────────────────────────────────────

def build_template_family(inp: AllocationEngineInput) -> list[AllocationTemplate]:
    ...

# ─── 草案生成 ────────────────────────────────────────────────

def instantiate_template(
    template: AllocationTemplate,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> dict[str, float]:
    ...

# ─── 约束投影 ────────────────────────────────────────────────

def project_to_constraints(
    draft_weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
    params: AllocationEngineParams,
) -> dict[str, float]:
    ...

# ─── 结构校验与元信息 ─────────────────────────────────────────

def validate_candidate(
    weights: dict[str, float],
    constraints: AccountConstraints,
    universe: AllocationUniverse,
    profile: AllocationProfile,
) -> list[str]:
    ...


def build_strategic_allocation(
    name: str,
    weights: dict[str, float],
    universe: AllocationUniverse,
    params: AllocationEngineParams,
    description: str,
) -> StrategicAllocation:
    ...

# ─── 去重与裁剪 ──────────────────────────────────────────────

def deduplicate_candidates(
    allocations: list[StrategicAllocation],
    params: AllocationEngineParams,
) -> list[StrategicAllocation]:
    ...


def trim_candidates(
    allocations: list[StrategicAllocation],
    min_candidates: int,
    max_candidates: int,
) -> list[StrategicAllocation]:
    ...
```

### 4.3 主入口执行顺序（冻结版）

`run_allocation_engine()` 的执行顺序固定如下：

1. 输入合法性校验
2. 构造模板家族
3. 逐模板生成 bucket-level 草案权重
4. 将草案投影到约束可行域
5. 执行候选静态合法性校验
6. 构造 `StrategicAllocation` 与诊断信息
7. 去重、裁剪、稳定排序
8. 生成 `AllocationEngineResult`

> **约束**：08 不允许在步骤 4 之后再引入随机扰动；同一输入必须保持候选集稳定可复现。

---

## 5. 候选生成主逻辑

### 5.1 生成原则

08 的生成路线固定为：

> **模板生成 → 约束投影 → 静态校验 → 去重裁剪 → 输出候选集**

v1 不采用黑盒优化器寻找全局最优，不在 08 内运行 Monte Carlo，不做对未来收益分布的主观假设。

### 5.2 为什么采用模板驱动而不是黑盒搜索

原因如下：

- 02 已负责“候选评估”；08 只需负责“候选生成”
- 模板更易解释、易复盘、易控边界
- 与 04 的“候选动作生成器”保持架构一致：**先生成候选，再交由下游评分/评估**
- 模板驱动下，同一输入结果稳定，便于 A/B 对比与审计

### 5.3 模板家族（v1）

v1 固定包含以下模板家族：

1. `DEFENSE_HEAVY`
   - 适用：保守偏好 / 近端目标 / 现金流不稳定 / 即将有大额流出
   - 目标：提升 `defense` 与 `liquidity` 权重，降低 `satellite`

2. `BALANCED_CORE`
   - 适用：中性目标 / 中性偏好
   - 目标：核心桶居中，防御适度，卫星受限

3. `GROWTH_TILT`
   - 适用：长期目标 / 激进偏好 / 现金流稳定
   - 目标：提高 `core` 中成长暴露，保留合理防御底盘

4. `LIQUIDITY_BUFFERED`
   - 适用：未来 12 个月存在明确流出计划
   - 目标：显式提高流动性桶占比，满足 `liquidity_reserve_min`

5. `THEME_TILT_<theme>`
   - 适用：主题未被禁止，且 `theme_caps` 留有空间
   - 目标：在主题上限内做轻度倾斜，不突破 theme cap

6. `SATELLITE_LIGHT`
   - 适用：复杂度偏好低 / 风险偏好保守
   - 目标：保留小比例卫星仓，但不完全归零

> **v1 原则**：模板只要求覆盖“结构差异”，不追求全排列枚举。

### 5.4 目标画像如何影响模板选择

模板选择与参数修正逻辑建议如下：

- `goal.priority == "essential"`
  - 强制包含 `DEFENSE_HEAVY`、`BALANCED_CORE`、`LIQUIDITY_BUFFERED`
  - 非必要情况下不生成高卫星占比模板

- `goal.risk_preference == "conservative"`
  - 下调 `target_satellite_weight`
  - 上调 `target_defense_weight`

- `goal.risk_preference == "aggressive"`
  - 允许 `GROWTH_TILT`
  - `theme_tilt_strength` 可上调，但仍受 `theme_caps` 约束

- `cashflow_plan` 在未来 12 个月有负向大额流出
  - 强制启用 `LIQUIDITY_BUFFERED`
  - `liquidity_buffer_bonus` 提升

- `account_profile.complexity_tolerance == "low"`
  - 模板数量减一
  - 禁止多主题倾斜模板并降低卫星仓

### 5.5 草案生成：先按 category，再分配到 bucket

建议分两层生成：

1. **category 层**：先确定 `core / defense / satellite` 总权重
2. **bucket 层**：再把 category 权重分配到具体 bucket

v1 的 bucket 分配原则：

- 同 category 内，优先分配到治理层允许且不被 profile 禁止的 bucket
- 若 category 内多个 bucket 可选，优先顺序为：
  1. `bucket_order`（若提供）
  2. 非主题专属桶优先于主题专属桶（防止主题过度集中）
  3. 桶名字典序（稳定打破平局）

### 5.6 约束投影（核心实现点）

`project_to_constraints()` 是 08 的关键函数。它负责把草案权重修正为可行解。

投影时必须满足以下规则：

1. 权重总和 = 1.0
2. 所有 bucket 权重 >= 0
3. 每个 bucket 权重落在 `ips_bucket_boundaries[bucket]` 内
4. `satellite` 总权重 <= `satellite_cap`
5. 各主题暴露 <= `theme_caps[theme]`
6. `QDII` 总权重 <= `qdii_cap`
7. `liquidity` 总权重 >= `liquidity_reserve_min`
8. `forbidden_buckets` 权重必须为 0
9. 若 `qdii_allowed == False`，所有 `qdii_buckets` 权重必须为 0

推荐的投影顺序：

1. 裁掉 profile 禁投桶
2. 应用 bucket 上下限
3. 修正 category 总权重
4. 修正 satellite cap
5. 修正 theme caps
6. 修正 qdii cap
7. 补齐 liquidity reserve
8. 重新归一化并 round
9. 复检所有硬约束

> **约束**：投影只允许做“保守修正”，不允许突破任何硬边界来换取模板完整性。

### 5.7 静态校验（进入 02 之前）

每个候选进入 Goal Solver 前，08 应先执行一轮静态校验。

`validate_candidate()` 至少检查：

- 权重和是否为 1.0（允许极小数值误差）
- 是否存在负权重
- 是否越过任一 bucket 边界
- 是否违反 `satellite_cap`
- 是否违反 `theme_caps`
- 是否违反 `qdii_cap`
- 是否低于 `liquidity_reserve_min`
- 是否使用了 profile 禁止桶 / 禁止主题
- 是否存在未映射 bucket

校验失败的候选：

- **不得进入 `candidate_allocations`**
- 可在 `warnings` 中记录原因，供调试与复盘使用

### 5.8 去重、裁剪与稳定排序

去重规则建议：

- 去重距离：两组 `weights` 的 L1 距离 < `dedup_l1_threshold`
- 同模板生成的多个近似结果，只保留第一个
- 结构上明显不同（如防守型 vs 成长型）的候选必须保留

裁剪规则建议：

- 目标范围：`min_candidates <= N <= max_candidates`
- 若候选过多，优先保留不同模板家族的代表
- 若候选不足，至少保留：
  - 一个防守型
  - 一个均衡型
  - 一个偏成长或偏主题型（若 profile 允许）
  - 一个高流动性缓冲型（若未来有负向现金流）

稳定排序键建议：

1. 模板家族优先级（防守 / 均衡 / 成长 / 主题 / 流动性缓冲）
2. complexity_score 升序（简单优先）
3. 候选名称字典序升序

> **说明**：08 的排序不是最终推荐排序，只是为了输出稳定、便于日志和复盘。

---

## 6. 复杂度评分与候选命名规则

### 6.1 complexity_score 计算原则

08 必须为每个候选计算 `complexity_score`，供 02 排序时使用。

v1 建议公式：

```python
complexity_score = (
    bucket_count_component * 0.35 +
    satellite_component * 0.35 +
    theme_count_component * 0.20 +
    special_rule_component * 0.10
)
```

其中：

- `bucket_count_component`：使用桶数量越多，复杂度越高
- `satellite_component`：卫星仓越高，复杂度越高
- `theme_count_component`：主题暴露越多，复杂度越高
- `special_rule_component`：若需额外流动性缓冲 / QDII 限制 / 特殊约束修正，则略增复杂度

要求：

- 范围归一到 `[0, 1]`
- 不得依赖随机项
- 同一输入下保持稳定

### 6.2 候选命名规则

建议统一命名格式：

`<family>__<risk_pref>__<index>`

例如：

- `balanced_core__moderate__01`
- `defense_heavy__conservative__01`
- `theme_tilt_ai__aggressive__01`

`description` 建议包含：

- 结构倾向说明（核心 / 防御 / 卫星）
- 是否包含流动性增强
- 是否存在主题倾斜
- 主要约束特征（如 QDII 受限、卫星仓压缩）

---

## 7. 与 Goal Solver 的接口对齐（核心约定）

### 7.1 输出必须直接可放入 GoalSolverInput

08 的输出主对象应直接满足 02 的这一段输入要求：

```python
GoalSolverInput(
    ...,
    candidate_allocations=alloc_result.candidate_allocations,
    ...,
)
```

因此：

- 08 不再包一层“自定义 allocation 类型”给 02 去转换
- 08 不输出 bucket category 之外的基金级细节给 02
- 08 输出的是 `StrategicAllocation`，而不是 08 自己的私有配置结构

### 7.2 08 不承担 02 的硬过滤职责

虽然 08 会先做静态校验，但 02 仍然保留自己的硬约束过滤，原因如下：

- 08 负责“候选生成阶段的显式非法过滤”
- 02 负责“求解阶段的最终可行性裁决”

两层不冲突：

- 08 先拦住明显非法候选
- 02 再在求解与排序上下文中执行最终裁决

### 7.3 08 不使用 GoalSolverParams / MarketAssumptions

这条必须写死：

- 08 不读取 `GoalSolverParams`
- 不读取 `MarketAssumptions`
- 不根据市场预期收益去主动偏置候选

否则 08 会与 05 / 02 的职责重叠。

---

## 8. 代码组织

```text
src/allocation_engine/
├── __init__.py
├── types.py                    # AllocationProfile / AllocationUniverse / AllocationTemplate / Params / Result
├── validator.py                # 输入校验、候选合法性校验
├── templates.py                # 模板家族定义与画像映射
├── generator.py                # 草案权重生成
├── projection.py               # 约束投影（IPS / theme / qdii / liquidity）
├── complexity.py               # complexity_score 计算
├── dedup.py                    # 去重、裁剪、稳定排序
├── engine.py                   # run_allocation_engine 主入口
└── fixtures/
    └── sample_allocation_input.py
```

### 文件职责约束

| 文件 | 职责 |
|---|---|
| `types.py` | 只放 08 自有类型；复用 02 类型时只 import，不重复定义 |
| `validator.py` | 只做校验，不生成候选 |
| `templates.py` | 只定义模板，不做投影 |
| `generator.py` | 只做草案生成，不做最终合法性判决 |
| `projection.py` | 只做可行域投影，不写模板逻辑 |
| `complexity.py` | 只做复杂度分，不做排序推荐 |
| `dedup.py` | 只做去重/裁剪/稳定排序 |
| `engine.py` | 只做主流程编排，不内联复杂业务细节 |

> **约束**：08 不应将“模板、投影、合法性校验、复杂度计算、主流程编排”混写在一个大函数中。

---

## 9. v1 范围

### 9.1 v1 应做到

- `AllocationEngineInput / Result` 完整定义
- `AllocationProfile / AllocationUniverse / AllocationTemplate / Params` 完整定义
- 至少 4 类模板家族
- bucket-level 候选生成
- 约束投影（bucket 边界 / satellite cap / theme caps / qdii cap / liquidity reserve）
- 候选合法性校验
- complexity_score 计算
- 去重与稳定排序
- 输出 `candidate_allocations: list[StrategicAllocation]`
- 与 02 的直接接口对齐说明
- 与 01 / 03 / 05 / 04 / 10 的边界说明

### 9.2 v1 不做

- 基于市场预期收益的动态偏置生成
- 资产/基金级细粒度选择（v1 只做到 bucket 级）
- 用户偏好在线学习
- 黑盒优化器或遗传算法全局搜索
- 多目标联合候选生成（多个 GoalCard 同时求解）
- 与 03 / 05 的直接链路耦合
- 自动修复治理层缺失的 `bucket_category / bucket_to_theme`

---

## 10. 验收标准

| 维度 | 标准 |
|---|---|
| **唯一来源** | `candidate_allocations` 只由 08 生成 |
| **接口直连性** | 输出结果可直接放入 `GoalSolverInput.candidate_allocations` |
| **合法性** | 所有输出候选通过静态校验，无显式违反 bucket / theme / qdii / liquidity 约束 |
| **多样性** | 至少包含 3 种结构明显不同的候选家族 |
| **可解释性** | 每个候选均有 `name / description / complexity_score` |
| **稳定性** | 同一输入多次运行候选集顺序与内容保持一致 |
| **边界干净性** | 无 Monte Carlo、无 MarketState、无 Runtime Action、无 EV 打分逻辑进入本层 |
| **工程可维护性** | 模板、投影、校验、去重、复杂度计算分文件隔离 |

---

## 11. 文件关联索引

| 文件 | 关系 |
|---|---|
| `00_system_topology_and_main_flow.md` | 顶层总拓扑；08 是 `candidate_allocations` 的唯一来源 |
| `01_governance_ips.md` | 提供 IPS 边界、账户画像、`bucket_category`、`bucket_to_theme`、白名单/黑名单等长期稳定输入 |
| `02_goal_solver.md` | 直接消费 `candidate_allocations`；08 与 02 共同构成“目标求解与配置引擎层” |
| `03_snapshot_and_ingestion.md` | 明确 08 不直接依赖 03；两者是并行上游链路 |
| `04_runtime_optimizer.md` | 仅在 QUARTERLY 前置重算链路中间接受益于 08 输出 |
| `05_constraint_and_calibration.md` | 明确 08 不依赖 05 产出；05 不生成、不筛选、不改写战略候选集 |
| `07_orchestrator_workflows.md` | Orchestrator 是 08 的唯一合法调用方 |
| `10_ev_engine.md` | 无直接依赖；EV 只处理运行期候选动作，不处理战略候选配置 |

---

## 12. 实现约定

| 约定 | 说明 |
|---|---|
| 百分比口径 | 全部使用 0~1 浮点，禁止 0~100 |
| 纯函数约束 | `run_allocation_engine` 不写外部状态、不持久化、不发网络请求 |
| 稳定输出 | 同一输入应输出同一候选集与排序 |
| 不读市场态 | 不读取 `SnapshotBundle / MarketState / BehaviorState / EVParams` |
| 类型归属 | `StrategicAllocation / GoalCard / CashFlowPlan / AccountConstraints` 只从 02 import，不在 08 重复定义 |
| 映射来源 | `bucket_category / bucket_to_theme` 必须显式提供，禁止字符串推断 |
| 非法候选处理 | 非法候选直接丢弃并记录 warning，不得进入 `candidate_allocations` |
| 复杂度分 | 必须 deterministic，禁止随机扰动 |
| 内部函数命名 | 下划线前缀：`_build_*`, `_project_*`, `_validate_*`, `_compute_*`, `_dedup_*` |

---

## 13. 自检报告

### 13.1 功能完整度

| 检查项 | 状态 | 说明 |
|---|---|---|
| 上下游定位明确 | ✅ | 已明确 08 位于治理层之后、02 之前；不依赖 03/05 |
| 核心输入完整 | ✅ | 已定义 `AllocationProfile / GoalCard / CashFlowPlan / AccountConstraints / AllocationUniverse` |
| 核心输出完整 | ✅ | 已定义 `AllocationEngineResult`，主交付对象为 `candidate_allocations` |
| 候选生成流程完整 | ✅ | 模板生成 → 投影 → 校验 → 去重 → 输出 |
| 静态合法性校验完整 | ✅ | bucket / satellite / theme / qdii / liquidity / whitelist-blacklist 全覆盖 |
| 与 02 接口可落地 | ✅ | 直接复用 `StrategicAllocation`，无需额外适配层 |
| 复杂度评分定义 | ✅ | 已给出 deterministic 规则 |
| 代码组织可落地 | ✅ | 已拆分 types / templates / generator / projection / validator / dedup / engine |

**结论**：从实现规格角度看，08 已具备直接交付 Codex 开发的完整度。

### 13.2 内部冲突检查

| 检查项 | 状态 | 说明 |
|---|---|---|
| 候选生成与候选评估混淆 | ✅ 无冲突 | 已明确 08 只生成，02 只评估 |
| 模板逻辑与投影逻辑混写 | ✅ 已隔离 | 代码组织中已拆分模板/投影文件 |
| 类型重复定义风险 | ✅ 已规避 | `StrategicAllocation / GoalCard / CashFlowPlan / AccountConstraints` 直接从 02 import |
| 随机性导致不可复盘 | ✅ 已规避 | 文档要求 deterministic，不引入随机扰动 |
| 主题倾斜与 theme cap 冲突 | ✅ 已约束 | 明确 theme tilt 必须在 cap 内完成 |
| 画像偏好与目标偏好冲突 | ⚠️ 可控 | 文档已规定：`GoalCard` 是最终目标偏好，`AllocationProfile` 只表达账户允许边界 |

**内部评估**：无阻断级内部冲突；唯一需要实现时注意的是 `GoalCard.risk_preference` 与 `AllocationProfile.risk_preference` 的冲突裁决顺序，本文已给出裁决口径。

### 13.3 外部冲突检查

| 检查项 | 状态 | 说明 |
|---|---|---|
| 与 03 的编号/职责冲突 | ✅ 无冲突 | 已明确 08 独立编号，且不依赖 03 |
| 与 05 的参数治理冲突 | ✅ 无冲突 | 08 不读取 05 的状态与参数 |
| 与 04 的候选动作生成冲突 | ✅ 无冲突 | 08 生成战略候选；04 生成运行期动作候选 |
| 与 10 的评分职责冲突 | ✅ 无冲突 | 08 不做 EV 评分 |
| 与 02 的类型归属冲突 | ✅ 无冲突 | 08 复用 02 的正式类型，不重复定义 |
| 与 01 的类型所有权冲突 | ⚠️ 可控 | 01 尚未上传；本文通过 `AllocationProfile` 作为“08 内部消费视图”规避抢占 `AccountProfile` 正式所有权 |

**外部评估**：当前无阻断级外部冲突；未来当 `01_governance_ips.md` 落地时，应把 `AllocationProfile` 的上游来源在 01/07/08 三份文档中同步收口，但不影响本版 08 的实现。

### 13.4 接口接洽检查

#### 08 → 02

- 已对齐 `candidate_allocations: list[StrategicAllocation]`
- 已对齐 `complexity_score / name / description`
- 不需要额外 adapter

#### 01 / 07 → 08

- 要求 Orchestrator 显式注入：`bucket_category / bucket_to_theme / profile whitelist-blacklist`
- 若 01 未能提供完整映射，08 必须报错或 warning，不得猜测

#### 08 → 04（季度链路）

- 04 不直接消费 08 主结果
- 正确链路应为：`07 -> 08 -> 02 -> 04`
- 因此不存在 08 直接向 04 提供运行期状态的接口需求

#### 08 → 05 / 10

- 无直接接口
- 本文已明确禁止 08 消费 05 或 10 的对象

**接口评估**：08 与现有 00/02/03/04/05/10 的接口关系整体自洽。

### 13.5 一句话结论

**08 的实现规格已经完整，内部边界干净，外部冲突可控，与现有 00/02/03/04/05/10 的接口能够闭环。**

当前唯一需要后续文档联动确认的，不是 08 本身的职责，而是 `01_governance_ips.md` 对账户画像与桶映射正式类型的所有权定义。

---

*文档版本：v1.0 | 状态：可交付实现*
*下次修订触发条件：01_governance_ips.md 落地、AllocationUniverse 字段变更、或 02 的 StrategicAllocation 结构发生调整*
