# 16_product_selection_and_maintenance_v1.2.md

> **文档定位**：本文件定义 `v1.2` 的产品选择与产品维护层。它位于资产桶策略之下、用户执行层之上，负责回答“买什么、怎么配、怎么管”。

---

## 0. 一句话定义

`v1.2` 不再把“资产桶 -> 单产品名”视为充分建议。

系统必须提供：

- 产品选择逻辑
- 核心/防守/卫星/现金预算
- 季度执行政策
- 止盈止损与分批执行规则

---

## 1. 约束解释

产品层必须区分三类约束：

1. 资产暴露
   - equity / bond / gold / cash / qdii / satellite
2. 包装工具
   - 个股 / ETF / 场外基金 / 债券 / 积存金 / 现金管理
3. 风格与市场
   - 宽基 / 红利 / 行业 / 海外 / 主题 / 科技 等

默认语义：

- `不买股票` = 禁个股，不等于禁 ETF/基金形式的权益暴露

---

## 2. 核心数据结构

产品层的正式结构包括：

- `ProductCandidate`
- `ProductConstraintProfile`
- `ExecutionPlanItem`
- `ExecutionPlan`
- `BudgetStructure`
- `QuarterlyExecutionPolicy`
- `TriggerRule`

这些类型的实现位于：

- `src/product_mapping/types.py`
- `src/product_mapping/selection.py`
- `src/product_mapping/maintenance.py`

---

## 3. 产品选择规则

### 3.1 核心仓

默认优先：

- 指数化
- 低费率
- 高流动性
- 高跟踪质量

### 3.2 卫星仓

允许吸收：

- 政策/新闻信号
- 估值分位
- 风格/主题偏好

但必须：

- 有预算约束
- 与核心仓区分角色
- 收益兑现后优先回流核心/现金

### 3.3 债券、黄金、现金

不得再把这三类写成单产品占位符。

最低要求：

- 债券：按久期/信用/国债/政金债做内部结构
- 黄金：区分 ETF / 联接 / 积存金
- 现金：显式存在，承担补仓与机动资金角色

---

## 4. 预算结构

正式预算拆为四类：

- `core_budget`
- `defense_budget`
- `satellite_budget`
- `cash_reserve_budget`

默认原则：

- 核心仓也管理，不再完全静态
- 卫星预算不写死，按目标缺口、隐含所需年化、期限和风险承受动态推导
- 现金仓必须显式保留

---

## 5. 季度执行政策

季度执行政策至少包含：

- 初始建仓动作
- 触发规则
- 现金缓冲目标
- 下次 review 日期

默认触发类型：

- `drawdown`
- `profit_take`
- `rebalance_band`
- `regime_shift`

默认执行哲学：

- 日级监控
- 阈值触发建议
- 季度重估主计划

---

## 6. 产品维护原则

### 6.1 核心仓

- 跟行情，但不允许粗暴追涨杀跌
- 大涨分段止盈
- 大跌分批补仓
- regime 恶化时可转向更防守核心

### 6.2 卫星仓

- 允许更积极的分批买入与分段止盈
- 但收益兑现优先回流核心/现金

### 6.3 场外基金日监控

场外基金/联接基金允许盘中估算净值，但必须区分：

- `estimated_intraday`
- `close_reconcile_required`

盘中信号可以触发建议，但收盘后/次日必须对账确认。

