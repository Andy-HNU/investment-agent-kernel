# 11_product_mapping_and_execution_planner_v2.md
# 产品映射与执行计划层设计规格 v2

> 文档定位：本文件是 `08_allocation_engine.md`、`09_decision_card_spec_v1.1_patched.md` 与 frontdesk 产品化之间的补充规格。
>
> 它解决的问题不是“资金桶怎么求”，而是“资金桶结果如何下钻成具体 ETF / 基金 / 国债 / 黄金 / 现金管理产品，并形成可执行计划”。
>
> 本文件是 v2 补充规格，不替代 00-10 的 v1 主链文档。

---

## 0. 一句话定义

**Product Mapping / Execution Planner 是资金桶决策核与具体产品执行之间的桥接层。**

它把 `bucket allocation` 转成：

- 具体产品候选
- 替代品
- 执行理由
- 用户确认前的执行计划

它不改写 solver 数学结论，也不负责自动交易。

---

## 1. 角色边界

### 1.1 本层负责

- 消费 bucket-level 配置建议
- 为每个 bucket 匹配具体产品族与具体产品候选
- 输出一份用户可读的执行计划
- 管理产品池、替代品、停用策略与执行理由
- 为 frontdesk / advisor shell 提供“确认方案 -> 查看具体执行清单”的正式接口

### 1.2 本层不负责

- 重新计算成功概率
- 修改 Goal Solver / EV / Runtime Optimizer 结果
- 自动下单、代下单、交易路由、券商指令执行
- 把政策/新闻文本直接转换成具体产品买卖结论

### 1.3 与现有模块的关系

| 模块 | 关系 | 约束 |
|---|---|---|
| `08_allocation_engine.md` | 上游 | 08 只输出桶，不输出具体产品 |
| `02_goal_solver.md` | 上游 | 02 负责评估桶级候选，不直接评估产品清单 |
| `09_decision_card_spec_v1.1_patched.md` | 下游展示 | 09 可展示执行计划摘要，但不负责产品筛选逻辑 |
| `07_orchestrator_workflows_v1.1_patched.md` | 调用方 | 07 决定何时生成执行计划与是否要求确认 |

---

## 2. 第一版支持的产品族

第一版只要求做到“低频、可解释、可开源复用”的产品族，不追求覆盖所有交易品种。

### 2.1 资金桶到产品族

- `equity_cn`
  - 宽基 ETF
  - 红利 ETF
  - 行业 ETF
  - 风格 ETF
- `bond_cn`
  - 国债 ETF
  - 政金债 ETF
  - 纯债基金
- `gold`
  - 黄金 ETF
  - 黄金联接基金
- `cash / liquidity`
  - 货币基金
  - 短债基金
  - 现金管理类替代
- `qdii / overseas`
  - QDII 宽基
  - 海外指数 ETF

### 2.2 第一版不做

- 个股级选股
- 衍生品
- 高频轮动产品
- 复杂结构化产品

---

## 3. 产品池正式结构

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ProductCandidate:
    product_id: str
    product_name: str
    asset_bucket: str
    product_family: str
    wrapper_type: Literal["etf", "fund", "bond", "cash_mgmt", "other"]

    provider_source: str
    provider_symbol: str | None = None

    region: str = "CN"
    currency: str = "CNY"
    liquidity_tier: Literal["high", "medium", "low"] = "high"
    fee_tier: Literal["low", "medium", "high"] = "low"

    enabled: bool = True
    deprecated: bool = False
    deprecation_reason: str | None = None

    tags: list[str] = field(default_factory=list)
    risk_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
```

### 3.1 最低要求

- 每个产品必须属于且只属于一个 `asset_bucket`
- 每个产品必须声明来源与代码
- 每个产品必须有 `enabled / deprecated` 状态
- 每个产品必须可被替代

---

## 4. 产品映射规则

### 4.1 输入

- bucket allocation
- 用户限制条件
- 账户与地域约束
- 产品池
- provider capability matrix

### 4.2 输出

- 每个 bucket 的目标产品清单
- 每个产品的建议权重或建议金额
- 替代产品列表
- 执行理由
- 关键风险标签

### 4.3 映射原则

- 优先低复杂度
- 优先流动性更高
- 优先费用更低
- 优先更容易解释的产品
- 若多个产品等价，保留主推 + 替代品，而不是只给一个黑箱答案

### 4.4 用户限制必须生效

例如：

- `不碰股票`
  - 不得把权益 ETF 作为具体产品候选
- `只接受黄金和现金`
  - 只能映射到 `gold / cash`
- `不碰 QDII`
  - 不能下钻到海外基金或海外 ETF

---

## 5. 执行计划对象

```python
@dataclass
class ExecutionPlanItem:
    asset_bucket: str
    target_weight: float
    primary_product_id: str
    alternate_product_ids: list[str]
    rationale: list[str]
    risk_labels: list[str]

@dataclass
class ExecutionPlan:
    plan_id: str
    source_run_id: str
    source_allocation_id: str
    status: Literal["draft", "user_review", "approved", "superseded", "cancelled"]
    items: list[ExecutionPlanItem]
    warnings: list[str]
    confirmation_required: bool = True
```

### 5.1 状态机

- `draft`
- `user_review`
- `approved`
- `superseded`
- `cancelled`

### 5.2 确认边界

- 用户未确认前，只能视为“建议执行计划”
- 用户确认后，才能作为后续 `feedback / status / monthly` 的基线之一
- 仍然不等同于自动下单

---

## 6. 前台体验要求

前台至少应支持：

1. 展示资金桶建议
2. 展示每个资金桶对应的具体产品执行计划
3. 展示替代品与原因
4. 回答“为什么是这个产品，不是另一个”
5. 让用户确认或暂不确认执行计划

---

## 7. 测试要求

- 产品池 schema contract
- bucket -> product mapping contract
- 用户限制条件对产品层的语义测试
- 替代品回归
- 产品停用 / 替换回归
- 执行计划状态机测试
- 自然语言画像 + 执行计划 end-to-end 验收

---

## 8. v2 范围结论

v2 目标不是变成交易系统，而是让当前内核从：

- “给资金桶”

升级为：

- “给资金桶 + 给具体产品执行计划”

这是用户可执行性所必需的补充层。
