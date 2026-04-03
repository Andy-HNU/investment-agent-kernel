# CODEX v1.2 Task Map

日期：2026-04-03

读者：开发、审阅、测试、产品 owner、后续接手机器人/工程师

## 总结

`v1.1` 已经达到“真实 provider 架构 + adviser shell 基线可验收”的状态，但最近一轮 Claw 对话验收说明，系统离“可信、能执行、能解释、能持续跟踪”的投资顾问内核还有一层关键升级：

- 当前达成率仍主要是`桶级成功率`，不是`产品级执行成功率`
- 当前产品层仍偏薄，缺少`选产品`和`管产品`的独立逻辑
- 当前无 API 账户同步仍不完善，真实账户变动会让系统逐步偏离
- 当前解释层还不够让用户相信：
  - 用了什么历史数据
  - 多长窗口
  - 如何跨周期
  - 当前分布长什么样
  - 为什么推荐方案不是最高概率方案

`v1.2` 的目标不是单点修补，而是把系统升级成一个更接近真实顾问工作的三层结构：

1. `真实数据与分布建模内核`
2. `产品选择与产品维护内核`
3. `Claw 顾问壳层与日级监控/解释/建议能力`

从本任务书开始：

- 不再允许使用系统生成的 default / inline / synthetic 假数据驱动正式路径
- 正式历史数据必须来自真实外部源抓取，并进入版本化缓存
- 自动化测试默认使用“真实源抓取后缓存的数据”，只保留少量 live smoke
- `v1.2` 的最终目标是：**更好的投资建议，更准的投资建议**

本任务书从现在开始取代 `CODEX_v1.1_task_map_2026-04-02.md` 作为当前主执行地图；旧文档保留作 `v1.1` 历史记录。

## 协作约定

- 继续采用多角色协作：
  - `Lead / Integrator`
  - `Modeling Developer`
  - `Provider Developer`
  - `Product / Execution Developer`
  - `Sync / Reconciliation Developer`
  - `Claw Shell Developer`
  - `Independent Reviewer`
  - `Independent Tester`
- review 要求：
  - 不只审代码
  - 还要查冻结文档偏离、低级硬编码、解释口径漂移、数据真伪边界
- 测试要求：
  - 不只跑 `pytest`
  - 必须有：
    - 真实源缓存数据回归
    - live smoke
    - 随机画像回归
    - 年度逻辑模拟
    - Claw 真实自然语言日志
- 每条主线都必须形成：
  - 开发结果
  - 测试证据
  - 审阅结论
  - 剩余风险

## v1.2 的硬边界

### 数据真相边界

- 正式路径只允许两类数据：
  - 真实外部源实时抓取的数据
  - 真实外部源抓取后版本化缓存的数据
- 不再允许：
  - `product_default_market_snapshot`
  - `inline_snapshot`
  - synthetic fixture
  - 任意系统自造历史数据
- 测试默认使用真实源缓存数据，不要求每次都联网重抓
- live smoke 保留少量样本验证真实 provider 仍然可用

### 账户同步边界

- 真实持仓以 `observed_portfolio` 为准
- 不允许再假设“系统建议 == 用户已执行”
- 无官方个人资产 API 平台（如支付宝、京东金融）默认走：
  - 具体产品持仓手工录入
  - 交易记录/账单导入
  - 截图/OCR 识别

### 顾问壳边界

- `v1.2` 中 Claw 默认做到：
  - 日级监控
  - 触发信号判断
  - 具体买卖 / 止盈止损建议
  - 但最终仍由用户确认执行
- 不在 `v1.2` 内实现自动下单

## 当前验收反馈总表

### A. Claw 对话验收直接暴露的问题

- `不买股票` 被错误解释成“禁整个权益桶”，而不是“禁个股”
- 产品映射太薄：每桶只有极少数产品，缺少真实的核心 + 卫星内部结构
- 债券、黄金、现金都没有做内部结构化管理
- 没有显式现金仓与低位补仓预算
- 只给一次性建议，没有季度执行计划
- 止盈止损、分批买卖、产品维护规则缺位
- 用户看不到：
  - 用了多长历史
  - 用了哪些源
  - 当前模拟分布是什么
  - 为什么合理
- “延长到 4 年即可到 80%”这类建议在本金已覆盖目标时仍被展示，缺少常识性拦截

### B. 建模层面的新问题

- 当前达成率仍主要按桶级建模，不是产品级建模
- 当前真实历史窗口没有强约束跨周期
- 当前短样本只会被打保守因子，不会被识别为“周期不充分”
- 当前分布解释仍不足以支持用户判断合理性

### C. 账户现实约束

- 支付宝、京东金融场景下，公开官方个人投资账户读取 API 不可依赖
- 用户可能在系统建议之前自行操作
- 系统必须支持“建议、执行、真实持仓、对账状态”分离

## 主执行主线

### 主线 1：Real-Source Market Data and Cycle Coverage

目标：把 `03` 从“可接历史数据”升级到“历史数据足以支撑跨周期建模”。

#### Wave D1：真实源历史数据管道

交付物：

- 真实 provider 历史抓取器
  - `akshare`
  - `baostock`
  - `yfinance`
  - 其他 cross-check 源可后续扩展
- 统一历史数据缓存与版本化
- source metadata / cache metadata / as-of metadata

要求：

- 正式历史数据必须来自真实源抓取
- 抓取后必须落到版本化缓存
- 任一建模 run 都必须能回溯：
  - source
  - as_of
  - dataset_version
  - lookback_days

#### Wave D2：跨周期窗口规则

交付物：

- 长期结构窗口规则
- 短期 regime 窗口规则
- 周期覆盖检查

默认规则：

- 长期结构窗口：`日频 10 年`
- 短期 regime 窗口：`日频 1-2 年`
- 不再只看“月数 >= 36”
- 新增周期覆盖判定：
  - 是否覆盖至少一个明显上行阶段
  - 是否覆盖至少一个明显下行阶段
  - 是否覆盖至少一个高波动阶段

新增质量标记：

- `CYCLE_COVERAGE_INSUFFICIENT`
- `SHORT_OBSERVED_HISTORY`
- `INFERRED_HISTORY_ATTACHED`

#### Wave D3：产品历史与推算历史规则

交付物：

- 产品真实历史结构
- 基金类推算历史结构
- 历史段落化元数据

默认规则：

- 产品真实历史不足 `10` 年时，不强行补齐
- 基金类允许通过下列方式推算历史：
  - 跟踪指数
  - 联接 ETF
  - 主要持仓 / 重仓股
  - 所属板块 / 风格指数
- 推算历史可进入主模型，但必须降权
- 其他不能可靠推算的品类，不强补

新增数据结构：

```python
@dataclass
class ProductHistorySegment:
    start_date: str
    end_date: str
    source_kind: Literal["observed", "inferred"]
    source_ref: str
    confidence: float
    return_series: list[float]


@dataclass
class ProductHistoryProfile:
    product_id: str
    observed_history_days: int
    inferred_history_days: int
    inference_method: str | None
    inference_weight: float
    segments: list[ProductHistorySegment]
```

验收 gate：

- 真实源抓取 smoke
- dataset cache/replay
- 周期覆盖检查回归
- 推算历史标记与降权测试

### 主线 2：Distribution Modeling Upgrade

目标：把 `02/05` 从“桶级静态/半动态分布”升级到“产品感知 + regime 感知 + 尾部感知”。

#### Wave M1：产品级与桶级双层建模

交付物：

- `bucket_success_probability`
- `product_adjusted_success_probability`
- 产品 overlay 风险修正

原则：

- 桶级概率继续保留，回答“战略配置是否合理”
- 产品级修正概率回答“按这个具体产品计划执行后是否合理”
- 产品差异至少纳入：
  - 费率
  - 跟踪误差
  - 折溢价/流动性
  - 久期/信用/汇率
  - 推算历史折扣

#### Wave M2：日频主建模与 regime 敏感

交付物：

- 日频主建模输入
- 长期结构分布
- 短期 regime 调节

默认策略：

- 主建模频率：日频
- 前台展示：可聚合成周/月视角
- regime 不只改均值/波动/相关性，还可影响：
  - jump 强度
  - 产品维护带宽
  - 执行节奏

#### Wave M3：用户解释升级

交付物：

- 历史窗口展示
- 数据源展示
- 当前分布模式展示
- 分布图/摘要指标

用户应能看到：

- 用了哪些数据
- 观察历史多少天
- 推算历史多少天
- 当前 `simulation_mode`
- 当前 regime
- 为什么推荐不是最高概率方案

验收 gate：

- 同一画像在桶级与产品级概率上的差异解释测试
- 历史窗口/推算历史披露测试
- Brier / calibration style regression（若当前版本可用）

### 主线 3：Product Selection Engine

目标：把“桶映射到 1 个产品”升级成“有独立逻辑的产品选择层”。

#### Wave P1：约束语义重构

默认语义固定为：

- `不买股票` = 禁个股，不等于禁 ETF / 指数基金 / 场外基金形式的权益暴露
- 约束分三层：
  - 资产暴露层
  - 工具包装层
  - 风格/主题层

新增数据结构：

```python
@dataclass
class ProductConstraintProfile:
    forbidden_exposures: set[str]
    forbidden_wrappers: set[str]
    forbidden_styles: set[str]
    allowed_wrappers: set[str]
    allowed_markets: set[str]
```

#### Wave P2：产品筛选逻辑

每个资产类别都要有独立逻辑，不再统一套一句“选指数基金”。

默认逻辑：

- 权益核心：
  - 优先低成本指数产品
  - 用估值、流动性、费率、规模、跟踪误差排序
- 权益卫星：
  - 引入政策/新闻/热点，但有硬预算
- 债券：
  - 区分短债 / 中长债 / 国债 / 政金债 / 纯债 / 可转债（如纳入）
- 黄金：
  - 区分 ETF / 联接 / 积存金
- 现金：
  - 货基 / 现金管理 / 活期替代
- QDII / 海外：
  - 单独管理汇率与市场时区暴露
- 个股：
  - 仅在用户允许时进入候选，且不能默认替代指数核心

#### Wave P3：产品池与证据层

交付物：

- 产品池注册表
- 每个产品的结构化证据
- 候选排序理由

产品证据至少包含：

- `asset_type`
- `wrapper_type`
- `market`
- `expense_level`
- `liquidity_level`
- `tracking_quality`
- `valuation_percentile`
- `policy_news_score`
- `core_or_satellite`

验收 gate：

- 禁个股但允许 ETF/基金的语义回归
- 各大资产类都有 2+ 候选
- 排序理由回归

### 主线 4：Product Maintenance Policy

目标：把一次性建议升级成“季度执行计划 + 日监控规则 + 触发式动作”。

#### Wave X1：预算结构重构

从固定桶预算升级成：

- `core_budget`
- `defense_budget`
- `satellite_budget`
- `cash_reserve_budget`

其中：

- 核心仓也允许管理，不再完全静态
- 卫星仓上限不固定写死，而由：
  - 目标隐含所需收益率
  - 当前达成率缺口
  - 剩余期限
  - 风险承受能力
 共同推导

#### Wave X2：季度执行计划

交付物：

- 初始建仓计划
- 分批买入计划
- 低位补仓规则
- 止盈减仓规则
- 再平衡带

新增数据结构：

```python
@dataclass
class TriggerRule:
    rule_id: str
    scope: Literal["core", "satellite", "bond", "gold", "cash"]
    trigger_type: Literal["drawdown", "valuation", "profit_take", "rebalance_band", "regime_shift"]
    threshold: float
    action: str
    size_rule: str
    note: str


@dataclass
class QuarterlyExecutionPolicy:
    plan_id: str
    quarter_start_date: str
    initial_actions: list[dict[str, Any]]
    trigger_rules: list[TriggerRule]
    cash_reserve_target: float
    review_date: str
```

#### Wave X3：高频监控与 T+1 市场规则

默认策略：

- 监控频率：高频/周内可触发
- 但最终执行建议必须区分：
  - `intraday_estimated`
  - `close_confirmed`

对于场外基金 / 联接基金：

- 允许盘中估算净值
- 估算可直接触发买卖建议
- 但必须同时输出：
  - `estimated_intraday=true`
  - `confidence`
  - `close_reconcile_required=true`

对于 ETF：

- 直接用盘中价格与参考净值

验收 gate：

- 核心仓也能触发管理动作
- 卫星预算随目标收益变化测试
- 季度计划生成回归
- 盘中估算与收盘确认对账测试

### 主线 5：Observed Portfolio Sync and Reconciliation

目标：把系统从“假设用户照做”升级成“以真实观测持仓为真相”。

#### Wave S1：账户真相对象

新增四个正式对象：

- `target_plan`
- `planned_actions`
- `observed_portfolio`
- `reconciliation_state`

新增数据结构：

```python
@dataclass
class ObservedHolding:
    product_id: str
    product_name: str
    quantity: float | None
    market_value: float
    cost_basis: float | None
    account_source: str
    observed_at: str
    source_kind: Literal["manual", "statement_import", "ocr", "broker_api"]
    confidence: float


@dataclass
class ReconciliationState:
    account_profile_id: str
    observed_portfolio_version: str
    target_plan_id: str | None
    planned_action_status: Literal["none", "pending", "partial", "completed", "stale"]
    drift_by_bucket: dict[str, float]
    drift_by_product: dict[str, float]
    missing_products: list[str]
    unexpected_products: list[str]
```

#### Wave S2：多来源同步

`v1.2` 默认支持：

- 手工录入具体产品持仓
- 交易记录/账单导入
- 截图/OCR 导入

OCR 参考 OpenClaw 现有能力：

- `snapshot_importer`
- `portfolio_editor`
- `ocr_importer`

但当前仓库不复制其正文，只做：

- 桥接
- 结构化输出 contract
- patch-back 规则延续

#### Wave S3：用户先行动作的处理

系统必须能识别：

- 用户在建议前已自行买卖
- 用户只执行了部分建议
- 用户执行了不同于建议的操作

后续所有复核默认以 `observed_portfolio` 为准，而不是 `planned_actions`。

验收 gate：

- OCR/导入/手工录入三路径回归
- 用户提前自行操作场景回归
- 对账结果驱动后续建议的回归

### 主线 6：Claw Adviser Shell and Evidence UX

目标：把 Claw 从“能触发 workflow”升级成“能监控、能解释、能下具体建议”的顾问壳。

#### Wave C1：任务面升级

Claw 默认支持：

- onboarding
- status
- show_user
- monthly
- quarterly
- event
- approve_plan
- feedback
- explain_probability
- explain_plan_change
- explain_data_basis
- explain_execution_policy
- sync_portfolio_manual
- sync_portfolio_import
- sync_portfolio_ocr
- daily_monitor

#### Wave C2：日级顾问监控

Claw 默认做到：

- 按天监控产品和组合
- 给出：
  - 止跌/补仓提示
  - 止盈/减仓提示
  - 风险偏离提醒
  - 计划替换建议
- 仍由用户确认执行

#### Wave C3：证据面板与说服力

用户界面/自然语言回答必须能说清：

- 当前用了哪些历史数据
- 当前数据源与缓存版本
- 观察历史 vs 推算历史
- 当前分布与 regime
- 当前推荐方案为何成立
- 最高概率方案为何不同
- 当前是桶级结论还是产品级修正结论

验收 gate：

- Claw 真实自然语言日志
- “为什么概率变了”日志
- “为什么建议替换/不替换”日志
- “为什么这个产品而不是那个产品”日志

## 冻结文档更新要求

`v1.2` 实现时，以下冻结文档必须实时更新，不能再只留在任务地图里：

- `system/02_goal_solver.md`
  - 产品级成功率
  - 日频建模
  - 观察历史/推算历史
- `system/03_snapshot_and_ingestion.md`
  - 真实源历史缓存
  - 周期覆盖
  - 产品历史段
  - OCR/导入后的 observed portfolio raw contract
- `system/05_constraint_and_calibration_v1.1_patched.md`
  - 分层预算
  - 产品 overlay
  - regime 如何影响产品维护带宽
- 新增 `system/16_product_selection_and_maintenance_v1.2.md`
- 新增 `system/17_observed_portfolio_sync_and_reconciliation_v1.2.md`
- 新增 `system/18_claw_adviser_shell_v1.2.md`

## 测试计划

### 1. 数据与 provider

- 真实源历史抓取 smoke
- 历史缓存 replay
- 周期覆盖检查
- 推算历史标记/降权测试
- live smoke 与 cached test 分离

### 2. 建模

- 桶级 vs 产品级成功率对照
- 日频建模回归
- 产品 overlay 风险修正测试
- regime / jump / DCC 变化测试
- 历史窗口变化敏感性测试

### 3. 产品选择与维护

- 约束语义测试：
  - 禁个股但允许 ETF/基金
- 产品排序测试
- 核心仓管理动作测试
- 卫星预算随目标收益变化测试
- 季度执行策略回归

### 4. 账户同步与对账

- 手工录入
- 交易记录导入
- OCR 导入
- 用户自行操作先于建议的对账测试
- `observed_portfolio` 优先级回归

### 5. Claw 自然语言

必须有真实日志，不接受只留测试脚本：

- onboarding
- status
- monthly
- quarterly
- event
- approve_plan
- feedback
- explain_probability
- explain_data_basis
- explain_execution_policy
- daily_monitor
- OCR/导入同步对话

### 6. 版本收口验收

版本结尾至少跑：

- 1 次完整 1 年逻辑模拟
- 1 次用户提前自行操作的纠偏场景
- 1 次无 API 多账户同步场景
- 1 次 Claw 全流程自然语言验收
- 3 次差异化随机画像验收

## 一句话判定

`v1.2` 的目标不是让系统“说得更像顾问”，而是让它真正升级成：

- 用真实数据建模
- 能选产品
- 能管产品
- 能同步真实账户
- 能持续监控
- 能把理由讲清楚

做到这一层后，用户看到的将不再只是“一个桶级概率系统”，而是一套更接近真实投资顾问工作的产品级内核。
