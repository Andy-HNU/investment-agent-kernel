# CODEX v1.2 Dynamic-Data Remediation Patch Map

日期：2026-04-04

读者：开发、审阅、测试、产品 owner、后续接手机器人/工程师

## 总结

这份补丁地图用于落实
[CODEX_dynamic_data_hardline_audit_2026-04-04.md](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_dynamic_data_hardline_audit_2026-04-04.md)
中的三张清单，把“仓库级硬红线”从制度文件推进成真正可执行的修复计划。

目标不是继续堆解释，而是把当前系统从：

- `桶级求解器`
- `静态产品 catalog`
- `静态估值/政策标签排序`
- `事后 overlay penalty`
- `规则化执行模板`

推进到：

- `可审计的正式路径`
- `动态产品 universe`
- `真实估值与政策/新闻评分链`
- `诚实披露的产品层成功率`
- `可扩展的代理宇宙与正式数据状态标签`
- `可解释的 frontier 与约束绑定诊断`
- `不再 silently 回退的 degraded/fallback 路径`
- `可执行而非仅数学最优的账户层结果`

本补丁不单独作为新版本发布，定位为 `v1.2 patch`。但执行要求与主版本相同：

- 有明确功能边界
- 有实现顺序
- 有测试门
- 有验收标准
- 有不允许继续带入主干的静态化遗留

---

## 补丁目标

这轮补丁要解决 9 件事：

1. 建立正式路径与数据状态标签的代码级约束
2. 把产品 universe 从“静态 catalog 直接当结果来源”改成“注册表 + 动态筛选”
3. 补齐真实估值/低估区判定链，不再用静态 `valuation_percentile`
4. 补齐政策/新闻到产品评分的真实计算链
5. 把“产品级成功率”从事后 penalty 修正，升级到诚实的过渡态实现
6. 扩大真实历史代理宇宙，并明确何时只能宣称“代理宇宙求解”
7. 增加 frontier / 候选空间 / 绑定约束诊断，回答“是市场难，还是系统自己把可行解卡死了”
8. 隔离 degraded / fallback 回退路径，防止其 silently 压回保守模板
9. 增加执行层真实性约束，避免输出碎仓位、现金冲突、数学可行但账户不可执行的建议

---

## 非目标

本补丁不处理以下内容：

- 自动下单
- 券商个人资产 API 直连
- 完整的逐产品独立蒙特卡洛引擎
- Claw memory / cron runtime 自动闭环
- 全量替换所有先验与启发式参数
- 完整消灭所有静态注册表与人工元数据

这些不是不重要，而是不应和本轮“动态数据修复”混做一团。

---

## 硬边界

### 正式路径边界

满足任一条件，即视为正式路径：

1. 会对前台用户展示
2. 会进入验收结果、测试报告、阶段报告或对外说明
3. 会被用于推荐、排序、解释、成功率、回撤、执行建议、产品维护建议
4. 会被下游模块继续消费为“当前真实输入”

凡属正式路径：

- 不得 silent fallback
- 不得 demo/test 数据混入
- 必须显式或等价地携带 `data_status`
- 必须带来源与审计字段
- 若字段缺失，应直接降级或显式报缺
- degraded 模式下不得假装仍是完整正式结果

### 数据状态边界

关键字段必须区分：

- `observed`
- `computed_from_observed`
- `inferred`
- `prior_default`
- `synthetic_demo`
- `manual_annotation`

禁止行为：

- 用 `manual_annotation` 冒充 `observed`
- 用 `prior_default` 冒充真实市场快照
- 用 `synthetic_demo` 进入正式路径
- 用 `computed_from_observed` 包装一个没有可追溯输入的静态值

### 静态注册表边界

允许存在：

- 候选宇宙注册表
- 产品基础元数据
- 人工维护的映射层
- wrapper / market / style / asset-class 等参考标签

不允许：

- 单靠静态注册表直接决定正式候选池
- 把静态元数据当作实时估值、实时流动性、实时政策强度、实时执行成本

---

## 主执行主线

### 主线 1：Formal-Path Enforcement

目标：把“正式路径”和“数据状态标签”从文档要求变成代码和测试门。

#### Wave F1：数据状态字段入模

交付物：

- 正式定义通用 `data_status` 枚举
- 为关键输入与关键输出增加：
  - `data_status`
  - `source_ref`
  - `as_of`
  - `audit_window`

首批必须覆盖：

- market snapshot / historical dataset
- valuation snapshot / percentile result
- policy/news score
- product-level probability output
- frontdesk 展示卡片里的关键结论

建议结构：

```python
class DataStatus(str, Enum):
    OBSERVED = "observed"
    COMPUTED_FROM_OBSERVED = "computed_from_observed"
    INFERRED = "inferred"
    PRIOR_DEFAULT = "prior_default"
    SYNTHETIC_DEMO = "synthetic_demo"
    MANUAL_ANNOTATION = "manual_annotation"


@dataclass
class AuditWindow:
    start_date: str | None
    end_date: str | None
    trading_days: int | None
    observed_days: int | None
    inferred_days: int | None
```

#### Wave F2：正式路径 guard

交付物：

- 正式路径统一校验函数
- frontdesk / decision card / bridge 输出前的审计 guard

必须拦截：

- `synthetic_demo` 进入正式路径
- 缺少 `source_ref/as_of`
- 声称 `externally_fetched` 但没有窗口审计字段
- silent fallback 被当作正式结论返回

#### Wave F3：fallback 显式化

交付物：

- 把正式路径里的 silent fallback 改成显式状态

最低要求：

- `candidate_space_collapsed`
- `frontier_unavailable`
- `history_window_incomplete`
- `fallback_used_but_not_formal`

#### Wave F4：degraded 模式隔离

目标：防止 degraded 路径 silently 把结果压回保守模板。

交付物：

- degraded 影响范围标识
- degraded 模式下的推荐资格判断
- degraded 模式专用审计字段

最低要求：

- degraded 模式不得 silently 替换 candidate universe
- degraded 模式不得 silently 切换到保守模板
- degraded 模式必须暴露：
  - 哪个模块 degraded
  - 对候选空间/概率/排序/执行建议的影响范围
  - 是否仍允许生成 recommendation

验收 gate：

- 正式路径缺字段时必须显式降级
- `synthetic_demo` 不得通过 guard
- `externally_fetched` 必须伴随窗口审计字段
- degraded=true 且核心输入缺失时，应返回“不可执行”而不是继续输出完整配置单

---

### 主线 2：Dynamic Product Universe

目标：把 `catalog` 从“正式候选来源”降级成“注册表 + 元数据仓”，并叠加动态筛选。

#### Wave U1：注册表与动态池分离

交付物：

- 静态 catalog 继续保留，但明确定位为：
  - 候选宇宙注册表
  - 静态参考元数据仓
  - 人工映射层
- 新增动态候选池生成模块

动态候选池至少叠加：

- 可交易性
- 实时/缓存产品数据存在性
- wrapper / market / style 约束
- 用户画像约束

#### Wave U2：产品 universe 扩展接口

交付物：

- 可从真实源加载产品 universe 的 provider contract
- 产品注册项与运行时筛选结果分离

最低覆盖：

- ETF
- 场外基金
- 债券 ETF / 债基
- 黄金 ETF / 联接 / 积存金
- QDII / 海外宽基
- 个股

#### Wave U3：约束入层核对

交付物：

- 禁个股但允许 ETF/基金权益暴露的正式语义落地
- 允许 QDII / 场内 / 个股 等选项真正影响候选空间

#### Wave U4：候选筛选账单

目标：让系统能解释“候选空间为什么变大/没变大”。

交付物：

- 候选筛选分阶段日志
- 删除原因统计
- 前台/测试可读的候选空间变化摘要

建议结构：

```python
@dataclass
class CandidateFilterBreakdown:
    stage: str
    input_count: int
    output_count: int
    dropped_count: int
    top_drop_reasons: dict[str, int]
```

验收 gate：

- 放开个股/QDII/场内后，候选数应可见变化
- frontdesk/Claw 必须能解释“候选空间是否真的变大”
- 不得只报最终候选数，必须能说明各阶段删除原因

---

### 主线 3：Valuation and Low-Value Pipeline

目标：补齐 `PE<=40`、`低估 30 分位以下` 这类真实规则链。

#### Wave V1：原始估值观测输入

交付物：

- 产品/指数层的 PE/PB/估值原始观测 contract
- 统一来源与窗口元数据

最低要求：

- 原始估值数据标记为 `observed`
- 没有真实估值源时，不得再用静态分位值冒充实时估值

#### Wave V2：估值分位计算

交付物：

- 历史估值时间窗
- 分位计算模块
- 低估区间判定模块

建议结构：

```python
@dataclass
class ValuationSnapshot:
    product_id: str
    pe_ttm: float | None
    pb: float | None
    source_ref: str
    as_of: str
    data_status: DataStatus


@dataclass
class ValuationPercentileResult:
    product_id: str
    metric: str
    percentile: float
    window_start: str
    window_end: str
    trading_days: int
    data_status: DataStatus
```

#### Wave V3：正式筛选规则接线

交付物：

- `PE <= 40`
- `低估 30 分位以下`
- 若规则不适用于某类产品，需显式说明“不适用”

验收 gate：

- 不允许再直接使用静态 `valuation_percentile`
- 必须能展示：
  - 原始估值值
  - 分位窗口
  - 当前分位
  - 是否命中低估筛选

---

### 主线 4：Policy/News Scoring Pipeline

目标：把静态 `policy_news_score` 变成真实材料驱动的计算结果。

#### Wave N1：材料输入与状态标签

交付物：

- 原始政策/新闻材料输入 contract
- source / recency / confidence / decay metadata

#### Wave N2：产品相关性与评分

交付物：

- 从 signal 到产品的相关性映射
- 结构化评分模块

评分至少包含：

- 方向：利多 / 利空 / 中性
- 强度
- 时效衰减
- 适用资产与适用产品

#### Wave N3：排序链接线

交付物：

- 卫星排序改用动态评分
- 核心仓只允许温和影响，不允许被热点直接推翻

验收 gate：

- 无真实材料时，前台不得展示实时政策/新闻评分
- 有材料时，必须能展示来源与时间

---

### 主线 5：Product-Aware Probability Remediation

目标：把当前“桶级概率 - penalty”升级到诚实可披露的产品层过渡方案。

#### Wave P1：双层概率结构显式化

交付物：

- `bucket_success_probability`
- `product_proxy_adjusted_success_probability`
- `product_probability_method`

要求：

- 不再使用含混的 `product_adjusted_success_probability`
- 前台必须明确显示这是：
  - 真正产品级模拟
  - 还是代理映射估计

#### Wave P2：真实产品修正项入模

交付物：

- fee drag
- tracking error
- liquidity drag
- inferred history discount
- currency / duration / credit overlays

注意：

- 这一阶段仍允许以桶级主分布为底
- 但必须诚实披露“产品层是代理修正，不是逐产品独立重建”

#### Wave P3：frontier 诊断面板

交付物：

- raw candidate count
- filter 后 candidate count
- frontier 最高 expected return
- 各类 frontier 不可用原因

#### Wave P4：绑定约束诊断

目标：直接回答“是市场难，还是系统自己把可行解卡死了”。

交付物：

- 绑定约束识别
- 放松约束前后 frontier 变化摘要
- 约束放松无效时的结构化原因

建议结构：

```python
@dataclass
class FrontierConstraintDiagnostic:
    constraint_name: str
    is_binding: bool
    candidates_before: int
    candidates_after: int
    frontier_max_return_before: float | None
    frontier_max_return_after: float | None
    note: str | None
```

#### Wave P5：收益上限 sanity check

目标：确认 expected return 引擎没有把前沿上限压死。

交付物：

- 宽约束/近无约束场景下的 frontier max expected return
- 单资产或高进攻候选 expected return 上限对照
- 统一 cap / shrinkage / 风险惩罚重复计入检查

验收 gate：

- 放宽约束后，候选数与 frontier 上限必须可解释
- `target_return_priority_plan` 不可用时必须给出结构化原因
- 放开高风险资产或更高进攻资产后，收益上限若几乎不变，必须说明是：
  - universe 未扩进去
  - 参数过度收缩
  - 风险惩罚重复计入
  - degraded/fallback 回退
  - 其他结构性原因

---

### 主线 6：Proxy-Universe Expansion and Honest Disclosure

目标：解决“只有 4 条代理”的上限问题，并建立诚实的代理宇宙披露。

#### Wave X1：桶代理扩展

交付物：

- 不再只使用 `510300 / 511010 / 518880 / 159915`
- 为：
  - 个股
  - QDII
  - 海外宽基
  - 更丰富债券层
  - 不同黄金包装
    建立可审计代理来源

#### Wave X2：产品代理配置

交付物：

- 产品到代理/因子的映射 contract
- 映射来源和置信度

建议结构：

```python
@dataclass
class ProductProxySpec:
    product_id: str
    proxy_kind: str
    proxy_ref: str
    confidence: float
    source_ref: str
    data_status: DataStatus
```

#### Wave X3：诚实披露

正式前台必须能说明：

- 当前是“真实产品独立历史”
- 还是“代理宇宙求解”
- 代理覆盖了哪些资产类
- 没覆盖哪些资产类

验收 gate：

- 若仍处于“代理宇宙求解”，前台不得宣称已完成产品层放开
- 若仅 4 条或极少数代理在支撑分布建模，必须显式提示能力边界

---

### 主线 7：Execution Realism Patch

目标：避免输出“数学可行但账户不可执行”的正式建议。

#### Wave E1：交易粒度与现金闭合

交付物：

- 最小交易金额 / 最小份额约束
- 现金底仓目标与投资目标统一入层
- 调仓后账户金额闭合校验

最低要求：

- 不允许输出低于最小交易粒度的正式建议
- 不允许一边产品权重合计 100%，另一边又要求保留现金底仓
- 调仓建议必须回算到账户层金额闭合

#### Wave E2：执行成本最小纳入

交付物：

- fee / slippage / tax 的轻量执行成本模型
- 成本对分批与再平衡的影响

最低要求：

- 产品层正式建议不得假装零成本
- 若成本未知，应显式标记为 prior/default，不得伪装成 observed

#### Wave E3：分批与再平衡真实化

交付物：

- 基于账户层金额的分批买入计划
- 再平衡建议与现金流计划联动
- 已有持仓处理规则与真实买卖金额输出

验收 gate：

- 不允许生成大量几百元碎仓位作为正式建议
- 分批买入、止盈止损、再平衡建议必须能落到账户层金额
- 前台必须能解释：
  - 初始买多少
  - 现金留多少
  - 后续触发后买/卖多少
  - 为什么这些动作在账户层闭合

---

## 代码边界与文件落点

本补丁预计主要落在这些区域：

- `src/product_mapping/`
  - universe
  - selection
  - maintenance
  - valuation
  - policy_news_scoring
- `src/snapshot_ingestion/`
  - real_source_market
  - valuation ingestion
  - news/policy ingestion
  - product universe ingestion
- `src/goal_solver/`
  - probability output contract
  - frontier diagnostics
  - constraint diagnostics
  - return ceiling checks
- `src/orchestrator/`
  - 明确 bucket/product 双层概率
  - degraded/fallback 暴露
- `src/frontdesk/`
  - 审计字段展示
  - 正式路径 guard
  - proxy disclosure
  - execution realism display
- `src/shared/`
  - data_status / audit_window / proxy specs / diagnostics 等共用类型

---

## 静态字段迁移表

本补丁期间，必须明确哪些字段还能存在、但不能再冒充正式真值。

| 字段/模块 | 当前处理要求 | 正式路径允许性 | 替代来源/去向 |
| --- | --- | --- | --- |
| `catalog.py` 中静态产品注册信息 | 保留为注册表/元数据仓 | 允许，但不得单独决定正式候选 | 动态 universe 筛选结果 |
| `valuation_percentile` 静态字段 | 正式禁用 | 不允许 | 真实估值观测 + 动态分位计算 |
| `policy_news_score` 静态字段 | 正式禁用 | 不允许 | 原始材料 + 结构化评分链 |
| `expected_returns` 默认值 | 仅限 `prior_default` | 允许，但不得冒充真实市场快照 | 真实历史估计 / 动态计算 |
| `volatility` 默认值 | 仅限 `prior_default` | 允许，但不得冒充当前真实波动 | 真实历史估计 / 动态计算 |
| `correlation_matrix` 默认值 | 仅限 `prior_default` | 允许，但不得冒充当前真实相关矩阵 | 真实历史估计 / 动态计算 |
| `synthetic fallback allocation` | 正式禁用 | 不允许 | 显式错误状态 |
| `demo_flow.py` / `demo_scenarios.py` | 仅 demo/test | 不允许 | demo/test path 隔离 |
| `system_seed` | 仅初始种子/测试记录 | 不允许冒充真实反馈 | 真实用户行为/真实执行反馈 |
| `raw_volatility` / `liquidity_scores` / `valuation_z_scores` 等内置产品默认值 | 降级为 prior/default | 允许作为 fallback，但必须显式标注 | 真实产品数据或动态估计 |

---

## 测试计划

### 1. 正式路径与数据状态

- 正式路径 guard 测试
- `data_status` 标签测试
- 缺审计字段降级测试
- fallback 不得静默进入正式路径
- degraded 模式隔离测试

### 2. 产品 universe 与约束入层

- 动态候选数变化测试
- 禁个股但允许 ETF/基金权益暴露语义测试
- 放宽 QDII/场内/个股后候选空间变化测试
- 候选筛选账单测试
- 删除原因统计测试

### 3. 估值链

- 原始 PE/PB 抓取或缓存回放测试
- 估值分位计算测试
- `PE<=40` 与 `30 分位` 判定测试
- 无真实估值源时不允许伪装成低估筛选结果

### 4. 政策/新闻评分链

- 原始材料到结构化评分测试
- 评分衰减测试
- 卫星排序接线测试
- 无材料时不允许展示实时评分

### 5. 概率、frontier 与绑定约束

- 双层概率输出测试
- 代理修正方法披露测试
- 放宽约束后 frontier 诊断测试
- `target_return_priority_plan` 不可用原因测试
- 绑定约束诊断测试
- 收益上限 sanity check 测试

### 6. 代理宇宙与披露

- 新代理源接线测试
- 产品代理映射测试
- 前台“代理宇宙求解”披露测试
- 代理覆盖不足时能力边界提示测试

### 7. 执行层真实性

- 最小交易粒度测试
- 现金底仓与仓位闭合测试
- 分批计划账户层闭合测试
- 费率/滑点最小纳入测试
- 禁止输出碎仓位测试

### 8. 验收回放样本库

必须固化至少三类回放样本：

#### Sample A：原始失败验收样本回放

用途：

- 复现并回归验证：
  - frontier 是否仍塌成一个点
  - `target_return_priority_plan` 是否仍不可用且理由不透明
  - 放宽回撤后是否仍几乎不动

#### Sample B：放宽约束样本回放

用途：

- 验证：
  - 放开 QDII / 场内 / 个股 / 更高风险后，候选空间是否真的变大
  - frontier 上限是否显著变化
  - 若不变，是否给出绑定约束或收益上限结构化原因

#### Sample C：数据缺口样本回放

用途：

- 验证：
  - 缺窗口审计字段时是否显式降级
  - 缺估值源/缺新闻材料时是否拒绝伪装成正式结果
  - fallback 与 degraded 是否可见

---

## 验收标准

满足以下条件，才算本补丁通过：

1. 正式路径不再依赖静态动态真值
2. 关键正式字段带有可审计 `data_status`
3. `catalog` 不再单独决定正式候选结果
4. 静态 `valuation_percentile / policy_news_score` 不再冒充实时计算结果
5. 产品层成功率口径诚实，前台不再混淆“代理修正”和“真实产品级模拟”
6. 放宽约束时，系统能展示候选空间、绑定约束与 frontier 是否真的变化
7. 前台能明确说明当前是：
   - 真实产品独立历史
   - 还是代理宇宙求解
8. degraded / fallback 不再 silently 回退成保守模板并冒充正式建议
9. 正式建议在账户层可执行，不再输出碎仓位、现金冲突或金额不闭合结果

---

## 推荐执行顺序

建议按这个顺序推进：

1. 主线 1：Formal-Path Enforcement
2. 主线 2：Dynamic Product Universe
3. 主线 3：Valuation and Low-Value Pipeline
4. 主线 4：Policy/News Scoring Pipeline
5. 主线 5：Product-Aware Probability Remediation
6. 主线 6：Proxy-Universe Expansion and Honest Disclosure
7. 主线 7：Execution Realism Patch

原因：

- 不先立正式路径 guard，后面修再多动态链路也会继续被静态值污染
- 不先把 universe 从 catalog 中解耦，估值和政策/新闻评分即使算出来也没地方用
- 不先把口径改诚实，frontier 和概率修复很容易继续被包装成“已经完成”
- 不补绑定约束与收益上限诊断，就无法解释“为什么放宽约束也没用”
- 不补执行层真实性，最终仍可能输出数学可行但账户不可执行的正式建议

---

## 一句话结论

这份补丁地图的目标，不是“把静态值全删掉”，而是：

**把静态注册表、动态观测、动态计算、先验默认、代理推断这五类东西分清楚，并让正式路径只消费可审计、可披露、可回放、可执行的结果。**
