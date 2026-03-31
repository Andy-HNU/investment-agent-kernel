# 01_governance_ips.md
# 治理与账户定义层设计规格 v1.0

> **文档定位**：本文件描述治理与账户定义层（Governance & IPS Layer）的职责、输入输出、核心类型与工程边界，可直接交付 Codex 实现。
>
> 它是 `08_allocation_engine.md` 与 `02_goal_solver.md` 的长期稳定上游，用于定义账户画像、IPS、桶映射、可投资宇宙与账户宪法。
>
> **本层不做数据采集、不做市场解释、不做参数校准、不做运行期动作优化。**

---

## 0. 一句话定义

**治理与账户定义层是系统的长期规则底座。**

它负责把“这个账户是谁、允许投什么、不能投什么、长期约束是什么、战略配置世界如何被切分”这些长期稳定规则显式定义出来，供 `08_allocation_engine.md` 生成候选战略配置、供 `02_goal_solver.md` 执行长期目标求解。

它只回答一件事：

> **这个账户在长期制度层面允许系统在什么边界内工作。**

---

## 1. 职责边界

### 1.1 本层负责

- 定义账户长期画像（风险偏好、复杂度容忍度、白名单/黑名单）
- 定义 IPS（Investment Policy Statement）硬边界
- 定义资产桶宇宙、桶分类、桶到主题映射
- 定义 QDII / 流动性桶等特殊语义桶
- 定义账户级投资禁投 / 限投规则
- 定义战略配置基线与治理字典版本
- 向 `08` 提供 `AllocationProfile / AllocationUniverse`
- 向 `02` 提供 `AccountConstraints` 的正式来源
- 向 `03` 提供可被快照化的约束与目标配置底稿

### 1.2 本层不负责

- 外部市场数据采集（由 `03_snapshot_and_ingestion.md` 负责）
- 持仓、收益、行为日志等运行时输入冻结（由 `03` 负责）
- `MarketState / ConstraintState / BehaviorState` 解释（由 `05_constraint_and_calibration.md` 负责）
- 候选战略配置生成（由 `08_allocation_engine.md` 负责）
- 成功概率求解、Monte Carlo 仿真（由 `02_goal_solver.md` 负责）
- 运行期候选动作生成与 EV 打分（由 `04_runtime_optimizer.md` / `10_ev_engine.md` 负责）
- workflow 触发、阻断与路由（由 `07_orchestrator_workflows.md` 负责）

### 1.3 与 03 的边界

| 本层（01） | 下游/旁路（03） |
|---|---|
| 定义长期规则与账户宪法 | 在每轮运行时把规则快照化 |
| 提供账户画像、IPS、桶映射底稿 | 生成 `ConstraintRawSnapshot / GoalRawSnapshot` |
| 不关心本轮市场与行为状态 | 关心“本轮系统到底基于哪份输入世界运行” |
| 不携带运行时时效性语义 | 负责打 `quality_flags` 与 `bundle_id` |

> **约束**：01 负责“定义规则”，03 负责“冻结规则的本轮副本”；03 不重新定义 IPS 语义，01 不参与本轮数据采集。

### 1.4 与 08 的边界

| 本层（01） | 下游（08） |
|---|---|
| 提供账户画像、桶宇宙、主题映射、白名单/黑名单 | 基于这些规则生成 `candidate_allocations` |
| 定义 IPS 硬边界 | 投影并校验候选配置是否满足 IPS |
| 不生成候选配置 | 只生成候选配置，不发明治理字典 |

> **约束**：`bucket_category`、`bucket_to_theme`、QDII 标记、流动性桶标记必须由 01 显式维护；08 不允许通过字符串猜测这些映射。

### 1.5 与 02 的边界

| 本层（01） | 下游（02） |
|---|---|
| 提供 `AccountConstraints` 的来源与解释 | 消费 `AccountConstraints` 做硬约束过滤 |
| 提供风险偏好评估底稿 | 消费 `GoalCard.risk_preference` 执行排序模式推断 |
| 不参与 Monte Carlo 求解 | 负责成功概率评估与候选排序 |

---

## 2. 上下游关系

```text
账户建档 / 用户访谈 / 治理配置输入
   ├── 风险偏好评估
   ├── 账户约束录入
   ├── IPS 桶边界设定
   ├── 主题与可投宇宙设定
   └── 白名单 / 黑名单设定
                    │
                    ▼
             01_governance_ips
               ├── AllocationProfile
               ├── AllocationUniverse
               ├── AccountConstraints
               └── GovernanceBaseline
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
08_allocation_engine      03_snapshot_and_ingestion
        │                       │
        ▼                       ▼
02_goal_solver       05_constraint_and_calibration
```

补充说明：

- `01 -> 08 -> 02` 是长期战略链路。
- `01 -> 03 -> 05` 是“规则被本轮运行快照化”的并行链路。
- 01 不直接下沉到 04/10；运行期模块只消费 03/05 解释后的结果。

---

## 3. 核心类型定义

### 3.1 类型策略

为避免跨模块重复定义，本层采用以下策略：

- **01 正式拥有的类型**：`AccountProfile`、`AllocationUniverse`、`GovernanceBaseline`
- **01 派生/适配输出**：`AccountConstraints`（供 02 使用）
- **01 不重复定义的类型**：`GoalCard`、`CashFlowPlan`、`StrategicAllocation`、`MarketState`、`BehaviorState`

> **约束**：02/08 若需要账户画像或桶宇宙，应从 01 import 或由 Orchestrator 适配后传入，不得各自再定义一套长期治理语义。

### 3.2 AccountProfile（长期账户画像）

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Any


@dataclass
class AccountProfile:
    """
    账户长期画像。
    由建档流程或治理层维护，变化频率低。
    """
    account_profile_id: str

    risk_preference: Literal["conservative", "moderate", "aggressive"]
    complexity_tolerance: Literal["low", "medium", "high"] = "medium"

    # 账户可投白名单 / 黑名单
    allowed_buckets: list[str] = field(default_factory=list)
    forbidden_buckets: list[str] = field(default_factory=list)

    # 主题级偏好
    preferred_themes: list[str] = field(default_factory=list)
    forbidden_themes: list[str] = field(default_factory=list)

    # 产品与市场侧限制
    qdii_allowed: bool = True

    # 预留扩展：税务、账户权限、交易限制等
    profile_flags: dict[str, Any] = field(default_factory=dict)
```

说明：

- `risk_preference` 是长期账户画像字段，运行时不应在 03/05 中被静默改写。
- `allowed_buckets / forbidden_buckets` 是治理层的显式边界，不等价于运行时持仓状态。

### 3.3 AllocationUniverse（桶宇宙与映射字典）

```python
@dataclass
class AllocationUniverse:
    """
    长期可投资桶宇宙，由治理层正式维护。
    08 只能消费，不能猜测。
    """
    buckets: list[str]

    # 三大类：core / defense / satellite
    bucket_category: dict[str, Literal["core", "defense", "satellite"]]

    # 桶到主题映射；无主题归属时可为 None
    bucket_to_theme: dict[str, str | None]

    # 特殊语义桶
    qdii_buckets: list[str] = field(default_factory=list)
    liquidity_buckets: list[str] = field(default_factory=list)

    # 可选展示与排序信息
    bucket_alias: dict[str, str] = field(default_factory=dict)
    bucket_order: list[str] = field(default_factory=list)
```

校验要求：

- `bucket_category.keys()` 必须完整覆盖 `buckets`
- `bucket_to_theme.keys()` 必须完整覆盖 `buckets`
- `qdii_buckets / liquidity_buckets` 必须是 `buckets` 子集
- 不允许依赖字符串规则自动推断 category / theme

### 3.4 IPSPolicy（长期硬约束政策）

```python
@dataclass
class IPSPolicy:
    """
    Investment Policy Statement 的正式结构。
    是 AccountConstraints 的长期治理来源。
    """
    ips_bucket_boundaries: dict[str, tuple[float, float]]
    satellite_cap: float
    theme_caps: dict[str, float]
    qdii_cap: float
    liquidity_reserve_min: float
    max_drawdown_tolerance: float
```

说明：

- `IPSPolicy` 是治理层语义；`AccountConstraints` 是 02 的求解消费视图。
- 两者字段允许一一对应，但所有权在 01。

### 3.5 AccountConstraints（向 02 导出的正式求解视图）

```python
@dataclass
class AccountConstraints:
    max_drawdown_tolerance: float
    ips_bucket_boundaries: dict[str, tuple[float, float]]
    satellite_cap: float
    theme_caps: dict[str, float]
    qdii_cap: float
    liquidity_reserve_min: float
```

导出规则：

- 默认由 `IPSPolicy` 一对一投影生成
- 若账户画像存在额外限制（例如 `qdii_allowed=False`），应在导出时显式收紧约束，而不是在 02/08 隐式处理

### 3.6 GovernanceBaseline（治理基线聚合对象）

```python
@dataclass
class GovernanceBaseline:
    """
    01 对外输出的长期治理聚合对象。
    可由 Orchestrator、建档流、03 快照化流程统一消费。
    """
    account_profile: AccountProfile
    universe: AllocationUniverse
    ips_policy: IPSPolicy
    constraints: AccountConstraints

    version: str = "v1.0.0"
    baseline_notes: list[str] = field(default_factory=list)
```

---

## 4. 主流程与实现思路

### 4.1 建档/更新主流程

```text
用户建档输入 / 治理配置
   │
   ├── 风险偏好评估
   ├── IPS 桶边界配置
   ├── bucket_category / bucket_to_theme 维护
   ├── 白名单 / 黑名单维护
   └── QDII / 流动性桶标记维护
   │
   ▼
validate_governance_inputs()
   │
   ▼
build_account_profile()
   │
   ▼
build_allocation_universe()
   │
   ▼
build_ips_policy()
   │
   ▼
derive_account_constraints()
   │
   ▼
assemble_governance_baseline()
```

### 4.2 核心实现原则

1. **长期稳定优先**  
   01 的对象变化频率低，不能混入运行时随机状态。

2. **显式字典优先**  
   `bucket_category`、`bucket_to_theme` 必须显式维护，不允许字符串猜测。

3. **治理收紧优先**  
   若画像限制比 IPS 更严格，以更严格者为准；但必须显式写入 `constraints`。

4. **可快照化**  
   01 产出的对象必须可被 03 直接引用并快照化，保证运行回放。

---

## 5. 对外接口

### 5.1 建议主入口

```python
def build_governance_baseline(
    account_profile_id: str,
    risk_preference: str,
    complexity_tolerance: str,
    allowed_buckets: list[str],
    forbidden_buckets: list[str],
    preferred_themes: list[str],
    forbidden_themes: list[str],
    qdii_allowed: bool,
    ips_bucket_boundaries: dict[str, tuple[float, float]],
    satellite_cap: float,
    theme_caps: dict[str, float],
    qdii_cap: float,
    liquidity_reserve_min: float,
    max_drawdown_tolerance: float,
    bucket_category: dict[str, str],
    bucket_to_theme: dict[str, str | None],
    qdii_buckets: list[str],
    liquidity_buckets: list[str],
) -> GovernanceBaseline:
    ...
```

### 5.2 对 08 的输出

- `account_profile`
- `universe`
- `constraints`

### 5.3 对 03 的输出

- `ips_policy`
- `account_profile`
- `constraints`
- 可被快照化的治理字典版本号

### 5.4 对 02 的输出

- `constraints`
- 风险偏好来源说明（供 `GoalCard.risk_preference` 对齐）

---

## 6. 代码组织建议

```text
src/governance_ips/
├── types.py
├── validators.py
├── profile_builder.py
├── universe_builder.py
├── ips_builder.py
├── constraints_adapter.py
└── main.py
```

职责建议：

- `types.py`：正式类型定义
- `validators.py`：字段合法性与覆盖率检查
- `profile_builder.py`：构造 `AccountProfile`
- `universe_builder.py`：构造 `AllocationUniverse`
- `ips_builder.py`：构造 `IPSPolicy`
- `constraints_adapter.py`：从 `IPSPolicy + AccountProfile` 派生 `AccountConstraints`
- `main.py`：主入口 `build_governance_baseline()`

---

## 7. v1 应做到

- `AccountProfile / AllocationUniverse / IPSPolicy / AccountConstraints / GovernanceBaseline` 正式类型齐备
- bucket/category/theme/QDII/liquidity 规则可校验
- 画像限制可显式收紧约束
- 可直接供 08 / 02 / 03 消费
- 版本号与基线说明可追踪

## 8. v1 不要求

- 自动风险测评问卷系统
- 自动推荐 IPS 边界
- 基于历史回测的画像自动学习
- 多账户继承与模板管理
- UI 配置台

---

## 9. 验收标准

| 验收项 | 标准 |
|---|---|
| 类型完整性 | 01 正式给出账户画像、宇宙、IPS、约束四类核心对象 |
| 边界清晰性 | 01 不碰 03 采集、不碰 05 校准、不碰 08 生成、不碰 02 求解 |
| 字典显式性 | `bucket_category / bucket_to_theme` 明确维护，不依赖字符串猜测 |
| 可导出性 | 可稳定导出 `AccountConstraints` 给 02，导出画像/宇宙给 08 |
| 可快照化 | 产出对象能被 03 无损快照化 |
| 可追踪性 | `GovernanceBaseline.version` 与 `baseline_notes` 可用于回放 |

---

## 10. 文件关联索引

| 关联文件 | 关系 |
|---|---|
| `00_system_topology_and_main_flow.md` | 定义 01 位于“治理与账户定义层” |
| `02_goal_solver.md` | `AccountConstraints` 的正式来源；`GoalCard.risk_preference` 来源于账户宪法评估 |
| `03_snapshot_and_ingestion.md` | 03 快照化 01 的治理规则与约束底稿 |
| `08_allocation_engine.md` | 08 依赖 01 提供 `AllocationProfile / AllocationUniverse / AccountConstraints` |
| `04_runtime_optimizer.md` | 04 文档中使用的 `bucket_category / bucket_to_theme` 应由 01 维护 |

---

## 11. 自检（简版）

### 11.1 功能完整性

- 已定义 01 的最小闭环：账户画像、IPS、宇宙、约束、治理基线
- 能支撑 08 候选生成所需的长期字典输入
- 能支撑 02 求解所需的约束来源
- 能支撑 03 对规则做本轮快照化

### 11.2 内部冲突

- 无明显内部职责冲突
- `IPSPolicy` 与 `AccountConstraints` 语义相近，但文档已明确：前者是治理语义，后者是 02 消费视图，不冲突

### 11.3 外部冲突

- 与 03 不重复：01 定义长期规则，03 冻结本轮输入世界
- 与 08 不重复：01 定义边界和字典，08 生成候选配置
- 与 05 不重复：01 不做解释与校准

### 11.4 接口接洽

- 对 08：接口闭合
- 对 02：接口闭合
- 对 03：可快照化，接口闭合
- 对 04：通过治理字典间接接洽，不直接耦合运行期逻辑
