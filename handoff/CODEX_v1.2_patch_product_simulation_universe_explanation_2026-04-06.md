# CODEX v1.2 Patch Map: Product Simulation, Full Universe, Valuation/Signals, Probability Explanation

日期：2026-04-06

读者：开发、审阅、测试、产品 owner、Claw 验收操作者

## 总结

这份补丁地图用于解决当前 investment kernel 剩余的 4 个高优先级缺口：

1. `逐产品独立模拟` 仍未实现
2. `全市场产品宇宙` 仍未完整实现
3. `估值链 / 政策新闻链` 仍未完全入 kernel 主链
4. `成功率解释` 仍缺少可审计拆解与反事实解释能力

这 4 项不再视为边角优化，而是 `v1.2` 后续继续可用、可解释、可验收的核心升级。

本补丁定位：

- `v1.2` 的后续核心能力补丁
- 不单独升大版本
- 但交付要求等同于主版本：
  - 有明确范围
  - 有数据结构
  - 有测试门
  - 有 Claw 迭代验收闭环

---

## 补丁目标

本补丁完成后，系统应达到：

1. `02/04` 不再只做桶级/代理级主分布，而能做逐产品或逐产品代理路径模拟
2. 产品候选池不再以本地静态注册表为主要上限，而是以真实市场 universe snapshot 为主
3. 股票/基金/ETF 的估值和政策新闻证据进入 kernel 主链，真正影响筛选、排序和维护
4. 成功率解释不再只报结果和几个结构性标签，而能回答：
   - 为什么低/高
   - 是市场难还是系统边界
   - 哪个约束在绑定
   - 哪个产品/哪类产品拉高或拉低了概率
   - 如果改目标/风险/期限/月投，变化多少

---

## 非目标

本补丁不处理：

- 自动交易
- 券商个人账户 API 直连
- 高频/日内策略
- OpenClaw memory / cron runtime 自动绑定
- 全商业级 SLA / 多租户

---

## 四条主线

### 主线 A：逐产品独立模拟

目标：让 `goal_solver` 不再只吃桶级分布，而能对产品层 return path 做正式建模。

#### A1. 产品模拟输入正式入模

必须新增：

- `product_simulation_inputs`
- `product_return_series`
- `product_proxy_specs`
- `product_simulation_method`
- `product_simulation_coverage`

建议结构：

```python
@dataclass
class ProductSimulationSeries:
    product_id: str
    source_ref: str
    data_status: str
    frequency: str
    observed_start_date: str | None
    observed_end_date: str | None
    observed_points: int
    inferred_points: int
    return_series: list[float]
    proxy_ref: str | None = None
    proxy_kind: str | None = None
```

```python
@dataclass
class ProductSimulationInput:
    products: list[ProductSimulationSeries]
    frequency: str
    simulation_method: str
    audit_window: dict[str, Any]
    coverage_summary: dict[str, Any]
```

#### A2. 模拟层升级

`goal_solver` 要支持三档方法：

1. `bucket_only`
2. `product_proxy_path`
3. `product_independent_path`

要求：

- 正式输出中必须显式标注当前方法
- 不允许再把过渡态包装成“已是逐产品独立模拟”

#### A3. 产品路径 overlay 正式入路径计算

必须把下面这些因子真正并入 path，而不是只做事后 penalty：

- fee drag
- tracking error
- liquidity drag
- duration overlay
- credit overlay
- currency overlay
- inferred history discount

#### A4. 输出口径升级

必须同时输出：

- `bucket_success_probability`
- `product_proxy_adjusted_success_probability`
- `product_independent_success_probability`
- `product_probability_method`
- `simulation_coverage_summary`

---

### 主线 B：全市场产品宇宙

目标：把 Layer 2 的产品宇宙正式升级成“真实市场 snapshot + runtime 筛选”，不再由本地 catalog 决定上限。

#### B1. Universe provider 正式化

主源组合：

- `tinyshare/Tushare`
  - `stock_basic`
  - `fund_basic`
  - `trade_cal`
  - `daily`
  - `fund_daily`
  - `daily_basic`
- `yfinance`
  - 海外 / QDII / cross-market fallback
- `baostock`
  - A 股历史备用
- `SSE/SZSE 官方列表`
  - 场内基金/ETF universe 基底

#### B2. Universe snapshot 数据结构

建议结构：

```python
@dataclass
class ProductUniverseItem:
    product_id: str
    ts_code: str | None
    wrapper: str
    asset_bucket: str
    market: str
    region: str | None
    theme_tags: list[str]
    risk_labels: list[str]
    source_ref: str
    data_status: str
    as_of: str
```

```python
@dataclass
class ProductUniverseSnapshot:
    snapshot_id: str
    as_of: str
    source_name: str
    source_ref: str
    data_status: str
    item_count: int
    items: list[ProductUniverseItem]
    audit_window: dict[str, Any] | None
```

#### B3. Universe filter breakdown 正式化

必须保留并前台可解释：

- raw candidate count
- filtered candidate count
- removed by wrapper
- removed by theme
- removed by risk
- removed by valuation
- removed by liquidity
- removed by region

#### B4. 本地 catalog 降级

要求：

- `catalog.py` 只保留：
  - fallback registry
  - 静态参考元数据
  - wrapper/theme/asset bucket baseline mapping
- 不得再单独决定正式结果上限

---

### 主线 C：估值链与政策新闻链入 kernel

目标：把估值和 signals 从“可展示、可注入”升级成“主链筛选与维护依据”。

#### C1. 股票估值链

主源：

- `tinyshare.daily_basic`

必须支持：

- `PE <= 40`
- `PB`
- 历史分位
- 窗口审计

建议结构：

```python
@dataclass
class ValuationObservation:
    product_id: str
    metric: str
    value: float | None
    as_of: str
    source_ref: str
    data_status: str
```

```python
@dataclass
class ValuationPercentile:
    product_id: str
    metric: str
    percentile: float | None
    window_start: str | None
    window_end: str | None
    trading_days: int | None
    data_status: str
```

#### C2. 基金/ETF 估值链

要求：

- 不把基金本身强行当作直接有 PE
- 通过以下路径之一映射：
  - 跟踪指数
  - 持仓行业/主题
  - bucket underlying proxy

输出必须说明：

- `valuation_mode = direct_observed | index_proxy | holdings_proxy | not_applicable`

#### C3. 政策新闻链

主输入：

- Claw skill 结构化输出
- 可选补充：Tushare 可用公告/新闻接口

建议结构：

```python
@dataclass
class PolicyNewsSignal:
    signal_id: str
    source_ref: str
    published_at: str
    direction: str
    strength: float
    recency_days: float
    decay_weight: float
    target_assets: list[str]
    target_themes: list[str]
    data_status: str
```

#### C4. 排序与维护入链

要求：

- 卫星仓：signals 直接参与排序
- 核心仓：signals 只允许温和影响，不得被热点直接推翻
- maintenance policy 必须保留：
  - 哪条 signal 触发了什么建议
  - 置信度
  - data_status

---

### 主线 D：成功率解释重构

目标：把成功率解释升级成可审计、可分解、可做反事实分析的顾问面板。

#### D1. 结果层

必须同时展示：

- 当前推荐方案
- 最高概率方案
- 目标收益优先方案
- 回撤约束优先方案
- 成功率
- 方案自身预期年化
- 隐含所需年化
- 90% 回撤

#### D2. 约束层

必须解释：

- 当前哪个约束在绑定
- 放宽后候选数是否变化
- 放宽后 frontier 上限是否变化
- 是 `市场难` 还是 `系统边界/约束/宇宙` 在卡住

建议结构：

```python
@dataclass
class ProbabilityConstraintContribution:
    name: str
    is_binding: bool
    before_candidates: int
    after_candidates: int
    before_frontier_ceiling: float | None
    after_frontier_ceiling: float | None
    explanation: str
```

#### D3. 证据层

必须展示：

- 当前 `product_probability_method`
- observed / inferred / prior_default 占比
- 历史窗口
- calibration / forward validation 摘要
- formal_path 状态

#### D4. 反事实层

必须生成标准化 what-if：

- 若坚持目标收益，回撤需放到多少
- 若坚持回撤，收益会降到多少
- 若增加月投，成功率变化多少
- 若延长期限，成功率变化多少
- 若放开科技/个股/高风险约束，候选与 frontier 如何变化

#### D5. 产品贡献层

必须解释：

- 哪些产品/产品类拉高了成功率
- 哪些拉高了回撤
- 哪些因 fee/tracking/liquidity 降低了产品层成功率

---

## 推荐开发顺序

必须按顺序做，不并行主线：

1. 主线 B：全市场产品宇宙
2. 主线 C：估值链与政策新闻链入 kernel
3. 主线 A：逐产品独立模拟
4. 主线 D：成功率解释重构

原因：

- 不先把 universe 和估值链做实，逐产品模拟没有足够产品输入
- 不先把 signals 做实，产品维护和解释层仍然会空
- 解释层必须建立在真实建模和真实 universe 之上，否则只是在包装半成品

---

## 测试方案

### 1. 单元 / 合同测试

必须新增或扩展：

- `tests/contract/test_23_product_universe_snapshot_contract.py`
- `tests/contract/test_24_product_simulation_contract.py`
- `tests/contract/test_25_valuation_signal_contract.py`
- `tests/contract/test_26_probability_explanation_v2_contract.py`

覆盖：

- universe snapshot 结构
- valuation percentile 结构
- policy news signal 结构
- product simulation input/output 结构
- explanation v2 字段完整性

### 2. 数据源集成测试

必须覆盖：

- `tinyshare`
  - `stock_basic`
  - `fund_basic`
  - `daily`
  - `fund_daily`
  - `daily_basic`
- `yfinance` fallback
- `baostock` fallback

要求：

- 不允许 silent fallback
- fallback 必须保留 source_ref / degraded note

### 3. 筛选与排序测试

必须覆盖：

- `PE<=40`
- `30分位`
- forbidden_theme
- forbidden_risk_labels
- policy/news A/B 对照
- 去掉限制后 runtime candidate count 和 frontier 变化

### 4. 产品模拟测试

必须覆盖：

- bucket_only
- product_proxy_path
- product_independent_path

比较：

- success_probability
- expected_annual_return
- max_drawdown_90pct
- product contribution deltas

### 5. Claw 自然语言测试

必须至少做两轮：

#### Claw Round 1

目的：

- 暴露缺口
- 识别字段缺失、解释不清、约束无效、runtime 未接入等问题

#### Claw Round 2+

目的：

- 逐轮修复后回归
- 直到满足验收标准

---

## Claw 迭代验收流程

每轮都必须覆盖：

1. onboarding
2. runtime universe 审计
3. valuation 审计
4. policy/news 审计
5. success probability 解释
6. 放宽约束 A/B/C 比较
7. quarterly review
8. sync observed_portfolio
9. daily_monitor
10. explain_probability / explain_plan_change

Claw 每轮追问必须强制要求系统回答：

- 当前是不是逐产品独立模拟
- 当前是不是全市场 universe
- valuation 是 direct 还是 proxy
- 哪些数据是 observed
- 哪些只是 inferred / prior_default / manual_annotation
- 成功率为什么是这个数
- 如果坚持目标/回撤，系统怎么反推

---

## 验收标准

满足以下条件，才算本补丁通过：

1. `02/04` 至少能在部分产品上跑 `product_independent_path`
2. 正式前台不再把 `product_proxy_adjustment_estimate` 冒充成逐产品独立模拟
3. runtime product universe 不再由本地静态 catalog 决定上限
4. 股票估值链 observed 生效，`PE<=40 / 30分位` 可被审计
5. 基金/ETF 估值模式明确区分 `direct_observed / proxy / not_applicable`
6. policy/news 能真实改变卫星排序，并保留审计
7. success probability explanation 能回答：
   - 为什么
   - 卡在哪
   - 放宽后怎样
   - 哪些产品在贡献
8. Claw 至少完成两轮闭环验收，且第二轮无 blocker

---

## 一句话结论

这份补丁不是“再补几条字段”，而是把系统从：

- 桶级主模拟
- 局部动态产品筛选
- 半静态解释

推进到：

- 真正产品层可模拟
- 全市场可筛选
- 估值与政策新闻真正入核
- 成功率解释可审计、可追问、可反事实推演

