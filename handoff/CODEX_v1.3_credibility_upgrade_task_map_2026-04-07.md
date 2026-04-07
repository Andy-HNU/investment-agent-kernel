# CODEX v1.3 Credibility Upgrade Task Map

日期：2026-04-07

读者：开发、审阅、测试、产品 owner、Claw/OpenClaw 验收操作者

## 文档定位

`v1.3` 不是单一“功能升级版本”，而是一个以可信输出为核心的分阶段治理计划。

它分成两类里程碑：

- `Gate`：必须先落地的语义、状态、正式路径治理
- `Package`：在 gate 之上推进的模型、运行时、验收体系升级

`v1.3` 的 umbrella 目标不变，但内部推进顺序必须固定：

1. `Gate 1`：结果语义与证据治理
2. `Gate 2`：正式计算路径硬化
3. `Package 3`：概率引擎与可信度升级
4. `Package 4`：运行时优化与 Claw 闭环

任何 package 都不得绕过前置 gate。

---

## 总目标

把 investment kernel 从：

- 能跑
- 能给建议
- 能做部分解释

推进到：

- 结果类别清晰
- 证据等级可审计
- 正式路径无 silent fallback
- 收益率与成功率披露遵守统一 policy
- Claw 可以复验路径，不只是复述文本

`v1.3` 最终不是追求“数字更高”，而是追求三件事：

1. 同一场景重跑，结果稳定
2. 历史回放里，概率与真实命中率大体一致
3. 用户和 operator 能看懂“为什么是这个收益率/成功率”

---

## 一阶原则

### Principle 1

**结果类别先于模型实现。**

任何输出必须先判定其结果类别，再决定允许使用哪些模型、哪些证据、哪些披露形式。

### Principle 2

**证据等级先于数值精度。**

没有足够证据等级的结果，不得以高精度形式披露。

### Principle 3

**失败必须结构化且可恢复。**

禁止 silent fallback；失败必须指出失败阶段、缺失证据与下一步恢复路径。

### Principle 4

**性能优化不得隐式改变结果语义。**

任何缓存、复用、粗筛与 top-K 策略，都不得在未声明的情况下改变结果类别、证据等级或披露资格。

---

## 非目标

本版本不处理：

- 自动下单
- 券商个人资产 API 直连
- 高频 / 日内交易
- 完整 OpenClaw memory / cron runtime 自动化
- 商业级 SLA / 多租户 / 配额治理

---

## 当前问题陈述

`v1.2` 已完成：

- runtime product universe
- tinyshare/Tushare 主数据链
- observed valuation
- `product_independent_path`
- Layer 1 / Layer 2 / Layer 3 闭环

但当前仍存在：

- 正式路径 fallback 污染
- 结果类别与失败语义未固定
- 成功率仍主要是模型单点输出
- 主 Monte Carlo 仍以静态参数正态为主
- 概率缺少校准体系
- Claw 能验文本，但不够验语义路径
- A/B/C/D 与无约束扫描仍有较高重复计算成本

因此 `v1.3` 的首要任务不是“先上更复杂模型”，而是先把语义、证据、失败和披露钉死。

---

## Gate 1：结果语义与证据治理

目标：先定义系统如何判定、如何分类、如何披露、如何审计。没有通过 `Gate 1`，后续一切模型升级都不得进入正式路径。

### Gate 1 输出物

必须形成 3 个正式产物：

1. `结果状态迁移图`
2. `概率/收益率披露判定表`
3. `Evidence Bundle schema`

### 结果状态迁移图

状态迁移必须按下图理解，不允许实现时自由发挥：

```text
exploratory_result
  -> degraded_formal_result
  -> formal_estimated_result
  -> formal_independent_result
```

附加约束：

- 主结果类别只能单向晋升，不能在同一次 formal run 中先晋升再回落并混合输出
- `formal_independent_result` 若失去独立覆盖资格，不得静默回退为 proxy 正式结果；必须重新判定类别
- `heuristic diagnostics` 不参与状态迁移，只是附加层

### Gate 1 判定顺序

所有正式 run 必须按下面顺序判定，不允许跳步或后验补标签：

1. **输入资格判定**
2. **执行资格判定**
3. **证据完备度判定**
4. **结果类别判定**
5. **披露资格判定**
6. **诊断层附加**

任何模块都不得自行改写这个顺序。

### 1. 输入资格判定

判断内容：

- 是否具备 formal execution 所需最小输入
- 输入来源是否允许进入 formal path
- 是否仍混入 synthetic / builtin substitute / debug fixture

输出：

- `input_eligibility = eligible | ineligible`
- `input_blocking_predicates`

### 2. 执行资格判定

判断内容：

- 当前请求的结果类别是否允许执行
- 当前 execution policy 是否允许使用所需输入与模型
- 是否满足进入独立模拟、估计模拟、解释模拟的最小条件

输出：

- `execution_eligibility`
- `requested_result_category`
- `eligible_result_categories`

### 3. 证据完备度判定

判断内容：

- coverage
- calibration
- distribution readiness
- explanation readiness
- data completeness

输出：

- `coverage_summary`
- `calibration_summary`
- `distribution_readiness`
- `explanation_readiness`
- `data_completeness`
- `confidence_level`

建议统一闭集：

- `data_completeness = complete | partial | sparse`
- `calibration_quality = strong | acceptable | weak | insufficient_sample`
- `confidence_level = high | medium | low`
- `distribution_readiness = ready | partial | not_ready`
- `explanation_readiness = ready | partial | not_ready`

### 4. 结果类别判定

同一次 run 的**主输出只能属于一个主结果类别**。结果类别互斥，不允许 recommendation、frontier、解释面板各自偷偷落在不同主类别后再拼成一张卡。

先切清两个不同概念：

- `run_outcome_status`
- `resolved_result_category`

`run_outcome_status` 是这次 formal run 的状态：

- `completed`
- `degraded`
- `unavailable`
- `blocked`

`resolved_result_category` 只在**存在主结果输出**时才赋值。

兼容说明：

- 对外现有字段 `formal_path_status` 在 `v1.3` 迁移期内保留
- 但其语义必须与 `run_outcome_status` 一一对应
- 新代码一律以 `run_outcome_status` 为内部规范字段

对应关系：

| run_outcome_status | resolved_result_category |
| --- | --- |
| `completed` | `formal_independent_result` / `formal_estimated_result` / `exploratory_result` |
| `degraded` | `degraded_formal_result` |
| `unavailable` | `null` |
| `blocked` | `null` |

也就是说：

- `unavailable` 和 `blocked` 是运行结果状态，不是主结果类别
- 失败 formal run 可以没有 `resolved_result_category`
- 失败时必须转向 `FailureArtifact`，而不是硬凑一个主结果类别

主结果类别定义：

- `formal_independent_result`
- `formal_estimated_result`
- `degraded_formal_result`
- `exploratory_result`

#### 类别定义

`formal_independent_result`

- 推荐方案与正式展示的 frontier 均满足独立模拟资格
- 不依赖 proxy 顶替
- 证据等级足以进入正式披露

`formal_estimated_result`

- 正式路径允许给出估计结果
- 但核心结果基于 formal estimate，而非完全独立模拟
- 必须显式说明其不是 independent result

`degraded_formal_result`

- 仍然属于正式路径
- 但证据或覆盖不足以支持高精度披露
- 允许给区间、限制性解释与恢复建议

`exploratory_result`

- 仅用于探索、演示、调试
- 不得冒充正式建议
- 只能来自 `execution_policy = EXPLORATORY`
- 不得作为 formal run 失败后的主结果类别

formal run 的主结果只允许是：

- `formal_independent_result`
- `formal_estimated_result`
- `degraded_formal_result`
- `null`

如果 formal run 失败后仍希望提供探索性内容：

- 只能作为 `secondary_companion_artifact`
- 不得写入同一次 formal run 的 `resolved_result_category`

#### Entry Criteria

每个类别都必须有 `entry criteria`：

- `formal_independent_result`
  - `input_eligibility = eligible`
  - 推荐方案 `distribution_ready_coverage = 1.0`
  - 推荐方案 `independent_weight_adjusted_coverage = 1.0`
  - 推荐方案 `independent_horizon_complete_coverage = 1.0`
  - 所需 simulation mode 资格满足
  - formal execution policy 不触发 blocked predicate

- `formal_estimated_result`
  - formal path 允许 estimated 结果
  - 推荐方案 `independent_weight_adjusted_coverage < 1.0`
  - 但 estimated coverage 与解释证据达到正式估计结果要求

- `degraded_formal_result`
  - formal path 仍可给有限正式输出
  - 至少能生成可信区间或可信结构化失败

- `exploratory_result`
  - `execution_policy = EXPLORATORY`
  - relaxed/exploratory 输入与披露条件成立

#### Promotion Criteria

必须显式定义晋升条件：

- `exploratory_result -> degraded_formal_result`
  - 输入脱离 test/demo substitute
  - formal evidence refs 可追踪
  - 输出满足最小正式失败/诊断格式

- `degraded_formal_result -> formal_estimated_result`
  - estimated 结果的 coverage 与 evidence 达标
  - disclosure policy 允许区间或有限点值

- `formal_estimated_result -> formal_independent_result`
  - 推荐方案 `independent_weight_adjusted_coverage = 1.0`
  - 推荐方案 `independent_horizon_complete_coverage = 1.0`
  - `distribution_ready_coverage = 1.0`
  - simulation eligibility 达标

### 5. 披露资格判定

披露不是结果类别的别名，必须单独判定。

披露粒度：

- `point_and_range`
- `range_only`
- `diagnostic_only`
- `unavailable`

#### Probability Disclosure Policy

系统必须输出并遵守统一的 disclosure policy。

最小输入字段：

- `result_category`
- `confidence_level`
- `data_completeness`
- `calibration_quality`
- `distribution_readiness`
- `coverage_summary`

判定所用闭集：

- `confidence_level = high | medium | low`
- `data_completeness = complete | partial | sparse`
- `calibration_quality = strong | acceptable | weak | insufficient_sample`
- `distribution_readiness = ready | partial | not_ready`

披露判定表：

| 条件 | 允许披露 |
| --- | --- |
| `formal_independent_result` 且 `confidence_level=high` 且 `calibration_quality in {strong, acceptable}` 且 `distribution_readiness=ready` | `point_and_range` |
| `formal_estimated_result` 且 `confidence_level in {high, medium}` 且 `calibration_quality != weak` | `range_only` |
| `degraded_formal_result` 且 `trustworthy_partial_diagnostics=true` 且 `distribution_readiness != not_ready` 且 `explanation_readiness != not_ready` | `range_only` |
| `degraded_formal_result` 且不满足上行条件 | `diagnostic_only` |
| `exploratory_result` | `diagnostic_only` |
| 输入或执行资格不满足 | `unavailable` |

建议输出对象：

```python
@dataclass
class DisclosureDecision:
    result_category: str
    disclosure_level: str
    confidence_level: str
    data_completeness: str
    calibration_quality: str
    point_value_allowed: bool
    range_required: bool
    diagnostic_only: bool
    precision_cap: str
    reasons: list[str]
```

稳定推导规则：

- `confidence_level = high`
  - `data_completeness = complete`
  - `distribution_readiness = ready`
  - `calibration_quality in {strong, acceptable}`
- `confidence_level = medium`
  - 不满足 high，但仍满足 formal disclosure 最低条件
- `confidence_level = low`
  - 仅满足 degraded 或 diagnostic disclosure

禁止各模块自行定义另一套 `confidence_level` 规则。

### Confidence Derivation Policy

`confidence_level` 不是自由字段，必须由以下输入联合推导：

- `resolved_result_category`
- `coverage_summary`
- `data_completeness`
- `calibration_quality`
- `distribution_readiness`
- `explanation_readiness`

建议结构：

```python
@dataclass
class ConfidenceDerivationPolicy:
    result_category: str | None
    minimum_independent_weight_adjusted_coverage_for_high: float
    minimum_distribution_ready_coverage_for_high: float
    minimum_calibration_quality_for_high: str
    maximum_confidence_by_result_category: dict[str, str]
```

强约束：

- `formal_independent_result` 才允许 `confidence_level = high`
- `formal_estimated_result` 最高只能到 `medium`
- `degraded_formal_result` 最高只能到 `low`
- `run_outcome_status in {unavailable, blocked}` 时不生成 `confidence_level`

附加约束：

- `degraded` 不得显示超过证据等级的精度
- `formal_estimated_result` 不得伪装成 independent point estimate
- calibration 差时必须自动放宽区间
- evidence 不足时不得显示高精度单点

### 6. 诊断层附加

以下字段降级为 `heuristic diagnostics`，不作为 formal truth：

- `market_ceiling`
- `model_ceiling`
- `constraint_gap`
- `coverage_gap`
- `difficulty_source`

它们只能在主结果类别确定、披露资格确定之后附加，不得反向决定主结果类别。

### Coverage Ontology

必须先定义 coverage ontology，再谈 `100%` 或 `95%`。

最小覆盖维度：

- `security_level_coverage`
- `weight_adjusted_coverage`
- `horizon_complete_coverage`
- `distribution_ready_coverage`
- `explanation_ready_coverage`

建议结构：

```python
@dataclass
class CoverageSummary:
    security_level_coverage: float
    weight_adjusted_coverage: float
    independent_weight_adjusted_coverage: float
    horizon_complete_coverage: float
    independent_horizon_complete_coverage: float
    distribution_ready_coverage: float
    explanation_ready_coverage: float
    selected_product_count: int
    observed_product_count: int
    missing_product_count: int
    blocking_products: list[str]
```

所有 coverage 数值字段统一采用 `0.0-1.0` 闭区间，不允许混入 `full/partial` 这类另一套值域。

推荐方案的 `100%` independent coverage，必须按：

- `independent_weight_adjusted_coverage`
- `independent_horizon_complete_coverage`
- `distribution_ready_coverage`

联合判定，不允许仅按产品数量判定。

### Evidence Bundle Schema

每次 run 必须生成最小审计对象 `EvidenceBundle`。

```python
@dataclass
class EvidenceBundle:
    bundle_schema_version: str
    execution_policy_version: str
    disclosure_policy_version: str
    mapping_signature: str
    history_revision: str
    distribution_revision: str
    solver_revision: str
    code_revision: str
    calibration_revision: str
    request_id: str
    account_profile_id: str
    as_of: str
    requested_result_category: str
    resolved_result_category: str | None
    run_outcome_status: str
    execution_policy: str
    disclosure_policy: str
    simulation_mode: str | None
    input_refs: dict[str, str]
    evidence_refs: dict[str, str]
    coverage_summary: dict[str, Any]
    calibration_summary: dict[str, Any] | None
    formal_path_status: str
    failed_stage: str | None
    blocking_predicates: list[str]
    degradation_reasons: list[str]
    next_recoverable_actions: list[str]
    diagnostics_trustworthy: bool
```

要求：

- `formal_path_status` 仅作为对外兼容别名保留
- `formal_path_status` 必须与 `run_outcome_status` 值完全一致
- 没有版本/签名字段的 bundle 不得视为可复验正式证据

### Contract Migration Window

`Gate 1` contract 采用三阶段迁移：

- `phase_0_detect_only`
- `phase_1_warn_with_artifact`
- `phase_2_hard_fail`

禁止一开始就把所有新 contract 直接切成 hard fail。

### Gate 1 验收标准

- 所有正式 run 都能映射到固定判定顺序
- 每次 run 只有一个主结果类别
- 所有主结果类别都有 `entry criteria` 与 `promotion criteria`
- 披露资格可由 policy 稳定推导
- `EvidenceBundle` 最小对象固定
- `market_ceiling/model_ceiling/...` 明确标为 heuristic diagnostics

---

## Gate 2：正式计算路径硬化

目标：删除正式路径 fallback，但同时固定“结构化失败”和“最小失败产物”，防止系统从假成功直接跳到高频硬失败。

### Gate 2 核心原则

- 正式路径删除 silent fallback
- 删除 fallback 不等于允许随意硬崩
- 失败必须结构化、可恢复、可审计

### Execution Policy 与 Disclosure Policy

不再使用单一 `strict_formal_mode` 作为万能开关。

改为两个正交维度：

- `execution_policy`
- `disclosure_policy`

建议结构：

```python
class ExecutionPolicy(str, Enum):
    FORMAL_STRICT = "formal_strict"
    FORMAL_ESTIMATION_ALLOWED = "formal_estimation_allowed"
    EXPLORATORY = "exploratory"


class DisclosurePolicy(str, Enum):
    FORMAL_DISCLOSURE = "formal_disclosure"
    DEGRADED_DISCLOSURE = "degraded_disclosure"
    DIAGNOSTIC_ONLY = "diagnostic_only"
```

### 正式路径必须删除的 fallback

必须删除或改成显式失败：

- `synthetic fallback allocation`
- runtime universe 拿不到时静默退 builtin catalog
- `product_independent_path -> product_proxy_path` 静默回退
- advanced distribution mode 失败时静默退 `static_gaussian`

测试、回放、debug 允许保留：

- cache
- replay bundle
- test fixture

但它们不得进入 formal result。

### Failure Taxonomy

`degraded`、`unavailable`、`blocked` 必须定义为工程 contract，而不是产品文案。

建议统一闭集：

```python
class RunOutcomeStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
```

- `degraded`
  - 可以给有限正式结果
  - 但精度、披露或范围受限

- `unavailable`
  - 当前请求的结果类别不可生成
  - 但系统仍可能给其他更低等级结果

- `blocked`
  - formal execution 的前置条件不成立
  - 不允许继续生成该正式结果

### 失败最小产物

失败时最少必须产出：

`failed_stage` 必须使用固定词表，并且与 `Gate 1` 判定顺序对齐：

- `input_eligibility`
- `execution_eligibility`
- `evidence_completeness`
- `result_category_resolution`
- `disclosure_resolution`
- `solver_preflight`
- `formal_compute`
- `artifact_persistence`

```python
@dataclass
class FailureArtifact:
    request_identity: dict[str, Any]
    requested_result_category: str
    execution_policy: str
    disclosure_policy: str
    failed_stage: str
    blocking_predicates: list[str]
    available_evidence_refs: dict[str, str]
    missing_evidence_refs: dict[str, str]
    next_recoverable_actions: list[str]
    trustworthy_partial_diagnostics: bool
```

特别要求：

- 必须有 `failed_stage`
- 必须有 `next_recoverable_actions`
- 不得只给自由文本 reason
- `failed_stage` 不允许使用开放文本

`trustworthy_partial_diagnostics` 不是自由布尔值，至少要求：

- `available_evidence_refs` 可追踪
- `explanation_readiness != not_ready`
- 关键诊断字段不依赖 forbidden substitute
- `failed_stage` 已知且落在固定词表

### Preflight Validation

正式 run 进入 solver 之前必须经过 preflight：

- 是否请求 formal result
- 是否存在被禁止 substitute
- 是否满足 requested result category 的最低覆盖条件
- 是否满足 requested simulation mode 的 eligibility

不满足时：

- 不进入正式求解
- 直接生成 `FailureArtifact`

### Gate 2 验收标准

- 正式路径无 silent fallback
- 失败都有标准最小产物
- `degraded/unavailable/blocked` 语义可稳定测试
- preflight 能在求解前挡掉不合格请求
- 正式路径与测试/回放路径分离

---

## Package 3：概率引擎与可信度升级

目标：在 Gate 1/2 固定后，升级模型，但模型升级必须服从结果类别、证据等级和披露 policy，而不是反过来主导语义。

### Package 3 核心原则

- 不是 mode 越多越好
- 而是 mode eligibility contract 必须先于 mode 扩充
- 成功率可信靠校准，不靠更高级的 mode 名称

### Mode Eligibility Contract

必须先定义：

- 什么证据条件下允许使用哪种 `simulation_mode`
- 样本长度不足时怎么降级
- regime segmentation 不稳定时如何处理
- jump overlay 校准失败如何影响输出资格
- mode selection 是规则决定、不是 operator 任意选择

建议结构：

```python
@dataclass
class SimulationModeEligibility:
    simulation_mode: str
    minimum_sample_months: int
    minimum_weight_adjusted_coverage: float
    requires_regime_stability: bool
    requires_jump_calibration: bool
    allowed_result_categories: list[str]
    downgrade_target: str | None
    ineligibility_action: str
```

还必须定义 mode resolution：

```python
@dataclass
class ModeResolutionDecision:
    requested_mode: str
    selected_mode: str | None
    eligible_modes_in_order: list[str]
    ineligibility_action: str
    downgraded: bool
    downgrade_reason: str | None
```

约束：

- 不允许“因为想用某个 mode，就发明宽松资格”
- 必须先由结果类别与披露需求定义资格，再由资格允许 mode
- `ineligibility_action` 只能是：
  - `select_lower_eligible_mode`
  - `degrade_result`
  - `mark_unavailable`
  - `block_formal_run`

补充约束：

- 在 `execution_policy = FORMAL_STRICT` 下，`select_lower_eligible_mode` 不得成为新版 fallback
- 若 lower mode 会改变：
  - `resolved_result_category`
  - `disclosure_level`
  - `confidence_level`
  - `distribution_readiness`
  则不得只做 mode 选择，必须重新走：
  - 结果类别判定
  - 披露资格判定
  - EvidenceBundle 写入

### 优先实现顺序

1. `student_t`
2. `historical_block_bootstrap`
3. `regime_switching_bootstrap`
4. `garch_t_dcc_jump`

理由：

- 先解决“正态假设过强”
- 再解决 regime
- 最后再引入更重的参数化动态波动模型

### 分布模型状态

```python
@dataclass
class DistributionModelState:
    simulation_mode: str
    tail_model: str | None
    regime_sensitive: bool
    jump_overlay_enabled: bool
    eligibility_decision: dict[str, Any]
    calibration_summary: dict[str, Any] | None
    source_ref: str
    as_of: str
    data_status: str
```

### 独立产品路径升级

当前缺陷：

- `product_independent_path` 先压成 `mean/std`
- 再喂回静态正态 MC

必须升级为：

- 产品路径直接参与 bootstrap / tail-aware path generation
- 不再把路径形状压平

### 收益率分解模型

收益率分解要服务解释，但不能伪装成严格因果归因。

新增：

- `residual_component`
- 每个 component 的 `estimation_confidence`

```python
@dataclass
class ExpectedReturnDecomposition:
    decomposition_basis: str
    additivity_convention: str
    base_return_component: float
    risk_premium_component: float
    valuation_component: float
    income_component: float
    fee_drag_component: float
    tracking_drag_component: float
    liquidity_drag_component: float
    constraint_loss_component: float
    residual_component: float
    net_expected_return: float
    estimation_confidence: dict[str, str]
```

要求：

- 允许 residual
- 不强行把所有误差分摊进“看起来好听”的 component
- 必须明确 `decomposition_basis`
  - `ex_ante_model_based`
  - `scenario_attribution`
  - `heuristic_mix`
- 必须明确 `additivity_convention`
  - `arithmetic`
  - `geometric`
  - `approximate`

### Success Event Contract

成功率必须明确绑定到统一的成功事件，禁止不同模块各算各的 success。

```python
@dataclass
class SuccessEventSpec:
    horizon_months: int
    target_type: str
    target_value: float
    drawdown_constraint: float | None
    benchmark_ref: str | None
    contribution_policy: str
    rebalancing_policy: str
    return_basis: str
    fee_basis: str
```

最小要求：

- Monte Carlo
- calibration
- decision card
- Claw explain

都必须引用同一份 `SuccessEventSpec`。

默认 formal success 定义必须写死：

- horizon 由 goal/profile 决定
- contribution policy 明确是否继续定投
- rebalancing policy 明确是否再平衡
- return basis 明确 `nominal` 或 `real`
- fee basis 明确 `gross` 或 `net`

### Formal Estimated Result Contract

`formal_estimated_result` 不能只是“independent 不够时的剩余桶”，必须有正向定义。

```python
@dataclass
class FormalEstimatedResultSpec:
    estimation_basis: str
    minimum_estimated_weight_adjusted_coverage: float
    minimum_explanation_ready_coverage: float
    point_estimate_allowed: bool
    required_range_disclosure: bool
```

允许的 `estimation_basis` 仅限：

- `proxy_path`
- `factor_model`
- `bucket_estimate`
- `hybrid_independent_estimate`

要求：

- `formal_estimated_result` 必须显式写出 `estimation_basis`
- 默认只允许 `range_only`
- 不得因 independent coverage 不足而自动“滑落”到 estimated；必须满足 estimated 自身 entry criteria

### 成功率披露从单点升级为 policy 驱动

输出结构至少包含：

- `expected_annual_return_point`
- `expected_annual_return_range`
- `success_probability_point`
- `success_probability_range`
- `confidence_level`
- `data_completeness`
- `calibration_quality`

但最终显示什么，必须由 `disclosure_policy` 决定，不由单一模块自由决定。

### 概率校准体系

新增：

- rolling out-of-sample replay
- Brier score
- reliability curve
- probability bucket calibration
- regime-sliced calibration
- realized vs predicted tracking

```python
@dataclass
class CalibrationSummary:
    sample_count: int
    brier_score: float | None
    reliability_buckets: list[dict[str, Any]]
    regime_breakdown: list[dict[str, Any]]
    calibration_quality: str
    source_ref: str
```

验收线：

- 不得只验证单一 `40%-50%` 区间，必须做分桶校准
- 至少覆盖：
  - `0%-20%`
  - `20%-40%`
  - `40%-60%`
  - `60%-80%`
  - `80%-100%`
- 每桶都要看：
  - 预测区间
  - 实际命中率
  - 样本数
- 样本不足必须标记 `insufficient_sample`
- 明显偏离时必须：
  - 下调 `confidence_level`
  - 放宽概率区间
  - 必要时降为 `diagnostic_only`

### Coverage 目标

必须基于 ontology，而不是漂亮数字。

正式目标：

- 推荐方案：
  - `independent_weight_adjusted_coverage = 100%`
  - `independent_horizon_complete_coverage = 100%`
  - `distribution_ready_coverage = 100%`
- `frontier_top_20`：
  - `independent_weight_adjusted_coverage >= 95%`
  - `independent_horizon_complete_coverage >= 95%`
  - `distribution_ready_coverage >= 95%`

### Heuristic Diagnostics

`market_ceiling`、`model_ceiling`、`constraint_gap`、`coverage_gap` 在本 package 中继续保持 heuristic 属性。

它们的用途是：

- 解释
- operator 诊断
- Claw 追问入口

不是 formal truth。

### Package 3 验收标准

- simulation mode 使用受 eligibility contract 约束
- 推荐方案 independent coverage 满足 formal independent 要求
- probability output 有 calibration summary
- 收益率分解带 residual 与 component confidence
- point/range 展示遵守 disclosure policy

---

## Package 4：运行时优化与 Claw 闭环

目标：降低重复计算成本，但性能优化不得改变证据语义；Claw 负责验路径与结果，不负责定义语义。

### Package 4 核心原则

- 性能优化必须绑定证据不变性
- Claw 是验收入口，不是 semantic truth owner

### Evidence Invariance

任何缓存、复用、粗筛、top-K 精算优化都必须证明：

- `result_category` 不变
- `run_outcome_status` 不变
- `disclosure_eligibility` 不变
- `coverage_summary` 关键判定不变
- heuristic diagnostics 不越级
- `EvidenceBundle` 核心 refs 不失真

若无法证明不变，则必须把变化写入输出 contract，不能静默改变。

这里的“关键判定不变”必须至少覆盖：

- `requested_result_category`
- `resolved_result_category`
- `run_outcome_status`
- `disclosure_level`
- `simulation_mode`
- `input_refs`
- `evidence_refs`
- `blocking_predicates`
- `independent_weight_adjusted_coverage`
- `independent_horizon_complete_coverage`
- `distribution_ready_coverage`

并新增证明产物：

```python
@dataclass
class EvidenceInvarianceReport:
    baseline_run_ref: str
    optimized_run_ref: str
    semantic_refs: dict[str, str]
    artifact_refs: dict[str, str]
    invariant_fields: list[str]
    exact_match_fields: list[str]
    tolerated_numeric_diffs: dict[str, float]
    drift_fields: list[str]
    verdict: str
```

性能优化默认要求：

- 结果类别和披露资格必须完全一致
- `semantic_refs` 必须完全一致
- `artifact_refs` 可以变化，但不得影响语义判定
- 数值容差只能用于非类别字段，并且必须显式登记

### 共享状态从“缓存”升级为“状态依赖图”

不得只按简单输入签名做复用。

必须显式管理：

- `product_universe_snapshot`
- `valuation_result`
- `historical_dataset`
- `distribution_model_state`

以及它们的派生关系和失效关系。

共享快照 key 至少应包含：

- `as_of`
- `provider_signature`
- `universe_signature`
- `mapping_signature`
- `history_revision`
- `distribution_revision`

### Counterfactual 复用

A/B/C/D 不得每场景重建全部市场输入。

应复用：

- 市场快照
- universe snapshot
- valuation result
- distribution state

只变化：

- 约束
- 风险预算
- 目标
- 披露政策

### 两阶段求解与误杀控制

允许：

1. recall-biased 粗筛
2. top-K 精算

但必须补这 4 个保护：

- `false_negative_budget`
- `challenger_set`
- `adversarial_candidates`
- recommendation correctness regression

要求：

- 粗筛可以多保留、不准高置信误杀
- 被 coverage 困难或高尾部行为影响的候选，必须有保底进入精算的机制

### 性能遥测

每次 run 记录：

- `universe_build_ms`
- `valuation_build_ms`
- `history_fetch_ms`
- `solver_screen_ms`
- `independent_simulation_ms`
- `explanation_build_ms`

并进入 `EvidenceBundle` 关联的 debug artifact。

### Claw 的角色

Claw 负责：

- 跑正式 prompt
- 回答结构化问题
- 触发固定追问

Claw 不负责：

- 定义结果类别
- 决定 heuristic 是否为 formal truth
- 充当唯一真值裁判

Claw 的任何结论都必须能追溯到：

- `EvidenceBundle`
- `FailureArtifact`
- `DisclosureDecision`

不能依赖纯自由文本推断。

### 固定 Claw 验收集

每轮版本必须跑：

1. 基线 onboarding
2. A/B/C/D 对照
3. 无约束最高收益
4. observed_portfolio sync + daily/explain

### Claw 必输字段

- `run_outcome_status`
- `resolved_result_category`
- `requested_result_category`
- `simulation_mode`
- `product_probability_method`
- `coverage_summary`
- `formal_path_status`
- `runtime_candidate_count`
- `registry_candidate_count`
- `frontier_max_expected_annual_return`
- `difficulty_source`
- `market_ceiling`
- `model_ceiling`
- `constraint_gap`
- `coverage_gap`

兼容说明：

- `result_category` 只允许作为 `resolved_result_category` 的 legacy alias 出现在旧接口
- 当 `run_outcome_status in {unavailable, blocked}` 时：
  - `resolved_result_category = null`
  - `result_category` 也必须为 `null`
  - 不允许为了兼容而伪造类别值

### Package 4 验收标准

- A/B/C/D 支持共享市场状态复用
- 性能优化不改变证据语义
- Claw 能区分 independent ceiling 与 proxy ceiling
- Claw 能输出固定证据字段

---

## 关键文件边界

### 结果语义与 Evidence Bundle

- `src/frontdesk/service.py`
- `src/frontdesk/storage.py`
- `src/decision_card/builder.py`
- `src/orchestrator/engine.py`

### 正式路径与执行策略

- `src/goal_solver/engine.py`
- `src/goal_solver/types.py`
- `src/product_mapping/engine.py`
- `src/product_mapping/runtime_inputs.py`

### 分布模型与校准

- `src/calibration/engine.py`
- `src/calibration/types.py`
- `src/shared/providers/tinyshare.py`

### 性能、缓存、复用

- `src/frontdesk/service.py`
- `src/frontdesk/storage.py`
- `src/orchestrator/engine.py`

### Claw/OpenClaw 验收

- `integration/openclaw/contracts/bridge_contract.md`
- `tests/integration/test_openclaw_bridge.py`
- `tests/smoke/test_frontdesk_cli_smoke.py`

---

## 测试策略

### Gate 1 测试

- 结果类别互斥性测试
- 结果类别晋升条件测试
- disclosure policy 判定表测试
- EvidenceBundle schema 完整性测试
- heuristic diagnostics 不得冒充 formal truth 测试

### Gate 2 测试

- strict formal path 无 fallback
- builtin catalog 不得静默接管 formal 路径
- independent coverage 不足时必须 degraded / unavailable / blocked
- failure artifact 最小产物完整性
- preflight validation 先于求解

### Package 3 测试

- mode eligibility contract
- `static_gaussian` vs `student_t` vs `historical_block_bootstrap`
- recommended plan independent coverage 合格性
- calibration summary 生成与区间放宽逻辑
- decomposition residual 与 confidence 字段完整性

### Package 4 测试

- snapshot reuse 语义不变性
- A/B/C/D 共享市场快照
- top-K 精算不改变结果类别
- Claw 固定 prompt regression

---

## 最终验收标准

`v1.3` 可判完成，必须同时满足：

1. `Gate 1` 完成
   - 状态迁移图、披露判定表、Evidence Bundle schema 固定

2. `Gate 2` 完成
   - 正式路径无 silent fallback
   - 失败结构化且可恢复

3. `Package 3` 达标
   - 推荐方案满足 formal independent 要求
   - success probability 有 calibration summary
   - 收益率/成功率披露遵守 policy

4. `Package 4` 达标
   - 性能优化不改变证据语义
   - Claw 能复验路径与类别，不再只验文本

---

## 执行建议

开发顺序固定：

1. `Gate 1`
2. `Gate 2`
3. `Package 3`
4. `Package 4`

实施阶段可拆 worker，但设计和集成必须由主线 owner 统一收口。

推荐拆法：

- Worker 1：Gate 1 + Gate 2 contract
- Worker 2：Package 3 distribution / calibration
- Worker 3：Package 4 runtime reuse / telemetry / Claw regression

主线 owner 负责：

- 结果语义统一
- policy 与 contract 统一
- 最终验收

---

## 结论

`v1.3` 不是“再加几个高级算法”的版本。

它首先是：

- 结果类别治理
- 证据等级治理
- 正式路径治理

然后才是：

- 概率引擎升级
- 性能优化
- Claw 闭环固化

只有这样，investment kernel 才能从“会回答”升级成“可信地回答”。
