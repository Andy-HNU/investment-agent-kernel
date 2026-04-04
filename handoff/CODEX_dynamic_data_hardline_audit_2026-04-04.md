# CODEX Dynamic-Data Hardline Audit

日期：2026-04-04

读者：开发、审阅、测试、产品 owner

## 严重单

从现在开始，新增一条仓库级硬红线：

**凡是需要动态获取、动态计算、真实校准、真实抓取的数据，都不允许再写死在代码里充当正式结果来源。**

这条红线需要按下面的方式理解，避免执行时走偏：

- 静态参考元数据允许存在于代码或注册表中，但不能单独充当正式真值
- 动态观测值必须来自可审计的数据源或可回放的数据缓存
- 动态计算结果必须来自可追溯输入，而不是手填常量冒充计算结果
- prior/default 允许存在，但必须明确标注为 fallback，不得伪装成真实市场/真实产品/真实估值

允许存在的只有两类例外：

1. 明确标注为 `demo / example / fixture / test-only`
2. 明确标注为 `configurable default`，且只允许作为降级兜底，不允许伪装成真实来源

不允许再出现以下行为：

- 用内置常量冒充实时市场、实时产品、实时估值、实时政策/新闻信号
- 用静态标签冒充估值分位、PE/PB、政策评分、产品维护信号
- 用桶级概率事后减 penalty，冒充产品级成功率
- 用 fallback/synthetic 结果在正式路径中对外展示为真实结论

---

## 正式路径判定

满足任一条件，即视为正式路径：

1. 会对前台用户展示
2. 会进入验收结果、测试报告、阶段报告或对外说明
3. 会被用于推荐、排序、解释、成功率、回撤、执行建议、产品维护建议
4. 会被下游模块继续消费为“当前真实输入”

凡属正式路径，必须满足：

- 不得 silent fallback
- 不得 demo/test 数据混入
- 必须携带来源与审计字段
- 必须明确区分 `observed / computed_from_observed / inferred / prior_default / synthetic_demo / manual_annotation`
- 若字段缺失，应直接降级或显式报缺，不得包装为“真实依据”

---

## 数据分级标签规范

后续所有进入正式路径的关键字段，都应显式或等价地带有数据状态标签：

- `observed`
  - 真实观测数据
  - 例如价格、净值、成交额、基金规模、PE/PB 原始值、政策原文、新闻原文
- `computed_from_observed`
  - 由真实观测数据计算得到
  - 例如估值分位、波动率、相关矩阵、成功率、回撤分布、执行触发信号
- `inferred`
  - 基于代理或插补推算得到
  - 例如基金历史补段、盘中净值估算、代理指数回填
- `prior_default`
  - 模型先验或默认值
  - 允许作为 fallback 或初始化输入
- `synthetic_demo`
  - 仅限 demo/test/fixture 的人工构造数据
- `manual_annotation`
  - 人工录入或维护的静态标签、注册表映射、产品元数据

执行规则：

- `manual_annotation` 可以存在，但不得单独充当正式真值
- `prior_default` 可以进入模型，但必须明确标注，且不得冒充实时来源
- `inferred` 可以进入正式路径，但必须披露推算依据、区间和置信度
- `computed_from_observed` 必须能回溯到输入源和计算窗口

---

## 审计结论

本次审计的重点不是“代码能不能跑”，而是：

- 哪些数据本应实时抓取或动态计算
- 哪些逻辑本应由真实历史/真实市场驱动
- 哪些功能点仍然被写死在代码中

结论：

- 当前系统真实形态仍然更接近：
  - `桶级求解器`
  - `静态产品 catalog`
  - `静态估值/政策标签排序`
  - `事后 overlay penalty`
  - `规则化执行模板`
- 与任务地图承诺相比，产品层、估值层、产品级概率层仍未真正打通

---

## 清单 A：应动态获取/计算，却仍被写死的内容

这类问题优先级最高，后续必须改成真实查询或真实计算。

### A1. 产品 universe 与候选池

- `src/product_mapping/catalog.py`
  - 整个 `ProductCandidate` catalog 是内置常量
  - 当前候选产品池不是从真实市场/基金 universe 运行时筛出来的
  - `provider_symbol`、`market`、`style_tags`、`risk_labels` 都是静态录入

影响：

- 当前“选产品”不是实时筛选，只是在固定名单里排序

说明：

- `catalog` 本身不一定必须删除
- 但它应退化为：
  - 候选宇宙注册表
  - 静态参考元数据仓
  - 人工维护映射层
- 不得继续单独充当正式候选筛选依据
- 正式候选池必须叠加：
  - 实时/缓存市场数据
  - 可交易性筛选
  - 动态约束筛选
  - 可审计来源字段

### A2. 产品估值与低估区判定

- `src/product_mapping/types.py`
  - `ProductCandidate` 只有静态 `valuation_percentile`
- `src/product_mapping/selection.py`
  - 排序直接消费静态 `valuation_percentile`
  - 没有真实 `PE / PB / price_to_earnings / percentile history` 计算链

当前缺失：

- `PE <= 40`
- “低估区间 30 分位以下”
- 历史估值时间窗
- 实时或缓存估值数据来源
- observed / inferred 估值证据

影响：

- 任务地图中“按估值筛产品”当前没有真正实现

说明：

- 这类字段属于“动态获取 + 动态计算”混合链路
- 原始 PE/PB、估值原始值应视为 `observed`
- 分位、低估区判定应视为 `computed_from_observed`
- 不能继续用静态 `valuation_percentile` 冒充实时估值筛选结果

### A3. 政策/新闻评分

- `src/product_mapping/types.py`
  - `policy_news_score` 是静态字段
- `src/product_mapping/selection.py`
  - 卫星排序直接读静态 `policy_news_score`

当前缺失：

- 真实政策/新闻抓取后生成结构化产品评分
- 时效、来源、权重、衰减机制

影响：

- 当前“政策/新闻辅助选产品”仍是静态标签，不是实时信号

说明：

- 原始政策/新闻材料应是 `observed`
- 产品相关性、情绪/政策评分应是 `computed_from_observed`
- 若采用人工初始标签，应明确标注为 `manual_annotation`

### A4. 产品级成功率

- `src/goal_solver/engine.py`
  - 模拟核心仍按桶级 `weights -> expected_returns / volatility / correlation`
- `src/orchestrator/engine.py`
  - `product_adjusted_success_probability = bucket_success_probability - overlay_total_penalty`

影响：

- 现在没有真正的产品级成功率模拟
- 只是桶级概率事后扣一个 penalty

分层要求：

- 过渡阶段允许：
  - 桶级主分布
  - 产品层使用 fee drag / tracking error / liquidity drag / proxy mapping 做修正
- 但前台必须明确标注：
  - “产品层概率为代理映射估计，不是逐产品独立历史重建”
- 不允许再把当前实现包装成“真实产品级蒙特卡洛”

### A5. 真实市场代理宇宙

- `src/snapshot_ingestion/real_source_market.py`
  - 默认代理只有 4 条：
    - `sh510300`
    - `sh511010`
    - `sh518880`
    - `sz159915`

影响：

- 即使前台放开“个股/QDII/场内”，`02` 仍主要在 4 个桶代理上做历史分布建模

升级判定：

- 这是当前最高优先级问题之一，不是普通缺项
- 若历史分布建模长期仅依赖少量桶代理，则前台不得宣称：
  - 已完成产品层放开
  - 已完成个股/QDII/更广市场宇宙求解
- 必须明确标注为：
  - “代理宇宙求解”

### A6. 产品层 market/account/constraint 输入

- `src/shared/product_defaults.py`
  - `raw_volatility`
  - `liquidity_scores`
  - `valuation_z_scores`
  - `transaction_fee_rate`
  - `cooling_period_days`
  仍是代码内置值

影响：

- 产品层并未真正由真实产品数据/真实执行成本/真实流动性驱动

### A7. policy/news ingestion 只做 merge，不做真实计算

- `src/snapshot_ingestion/signals_ingestion.py`
  - 只是把 `SignalPack` 合并到 raw inputs
  - 没有从 signal 到产品评分、估值修正、执行触发的真实计算链

---

## 清单 B：可保留为可配置默认值，但不得充当正式真相源

这类内容可以暂存，但必须满足两条：

- 可配置
- 显式标注为 fallback/default，不得伪装成真实数据

### B1. 默认市场假设

- `src/shared/product_defaults.py`
  - `expected_returns`
  - `volatility`
  - `correlation_matrix`

要求：

- 只能作为 fallback prior 或初始化模型参数
- 不得在正式路径中冒充“当前真实市场快照”

说明：

- 这类量不一定是“实时抓取”的
- 更准确的要求是：
  - 必须由可追溯输入计算得到，或
  - 明确标注为 `prior_default`
- 不应被误解成“所有 expected return/vol/corr 都必须在线实时抓”

### B2. 风险画像到约束的映射公式

- `src/shared/profile_dimensions.py`
  - `satellite_cap`
  - `liquidity_reserve_min`
  - `equity_cap`
  - `success_prob_threshold`

要求：

- 可以作为第一版启发式默认值
- 必须逐步迁移到可校准参数，不应长期硬编码

说明：

- 这类内容更接近“动态计算的模型参数/策略参数”
- 允许先由规则驱动
- 但必须逐步从真实行为、真实账户、真实验收反馈中校准

### B3. 预算结构系数

- `src/product_mapping/maintenance.py`
  - `success_gap * 0.14`
  - `return_pressure * 0.60`
  - `risk_score * 0.06`
  - `short_horizon_pressure * 0.03`

要求：

- 若继续保留，必须外置成参数配置
- 不能宣称其为真实校准后的产品维护模型

### B4. 执行策略阈值模板

- `src/product_mapping/maintenance.py`
  - `10%` drawdown add
  - `12% / 15%` profit take
  - `5% / 4%` rebalance band

要求：

- 可以作为默认模板
- 不能冒充“已根据真实市场和产品历史自适应优化”

### B5. 复杂度/人工确认阈值

- `src/shared/profile_dimensions.py`
- `src/shared/product_defaults.py`

要求：

- 可以作为顾问前台默认值
- 应与真实用户行为数据逐步校准

---

## 清单 C：应隔离、删除或严格限制在 demo/test-only 的内容

这类内容不应继续混入正式路径，避免误导开发和验收。

### C1. synthetic fallback allocation

- `src/goal_solver/engine.py`
  - `warning=empty_candidate_allocations synthetic_fallback_used`
  - `fallback` allocation 直接给出固定权重

要求：

- 正式路径不允许 silent fallback
- 至少要改成明确报错：
  - `candidate_space_collapsed`
  - `frontier_unavailable`

### C2. demo_flow / demo_scenarios 遗留默认值

- `src/shared/demo_flow.py`
- `src/shared/demo_scenarios.py`

当前包含：

- `preferred_themes=["technology"]`
- 固定 `success_prob_threshold`
- 固定 `theme_caps`
- 固定 market assumptions

要求：

- 只能存在于 demo/test path
- 不得继续污染正式实现和验收口径

### C3. system_seed / seed feedback

- frontdesk / feedback 初始化路径里仍有 `system_seed`

要求：

- 只能作为测试/初始种子记录
- 不得在正式用户验收中充当真实执行反馈

### C4. “外部抓取”标签但无可审计窗口字段

当前问题：

- 前台可能显示 `externally_fetched`
- 但拿不出：
  - 起始日期
  - 结束日期
  - 交易日数
  - observed / inferred 拆分

要求：

- 没有窗口审计字段时，不允许把该结果包装成“完整真实依据”

---

## 总体整改要求

后续所有开发都必须遵守下面的替换顺序：

1. 本应动态获取的数据
   - 先接真实 provider
   - 再落缓存/版本化
   - 再进入建模/前台展示

2. 本应动态计算的数据
   - 先定义输入源
   - 再实现计算模块
   - 再输出可审计字段

3. 本应只是默认值的数据
   - 必须外置
   - 必须标注 fallback/default
   - 不得伪装成真实市场/真实产品/真实估值

4. 静态参考元数据
   - 可以保留
   - 但只能充当注册表、枚举、映射层、人工标签仓
   - 不得单独充当正式真值

5. demo/test-only 数据
   - 必须严格隔离
   - 不得进入正式路径

---

## 后续执行规则

从本文件创建之日起：

1. 任何新增代码若把动态数据直接写死进正式路径，视为严重缺陷
2. review 必须额外检查：
   - 是否存在内置真值
   - 是否存在静态标签冒充实时计算
   - 是否存在 demo/fallback 污染正式路径
   - 是否缺少正式路径判定
   - 是否缺少数据状态标签
   - 是否把 `manual_annotation` 误当成 `observed`
3. 测试必须增加：
   - 动态数据来源审计
   - observed/inferred 字段审计
   - data_status 标签审计
   - fallback 触发可见性审计
4. 所有后续任务地图都应默认引用本文件作为硬边界

---

## 一句话结论

当前系统最需要修的，不是再多写几层解释，而是：

**正式结果只能来自可审计的真实观测、由真实观测推导的动态计算、或被明确标注为 fallback/default 的模型先验；静态 catalog、人工标签、demo 数据、synthetic fallback 均不得伪装成正式真值。**
