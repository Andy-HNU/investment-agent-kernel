# 17_observed_portfolio_sync_and_reconciliation_v1.2.md

> **文档定位**：本文件定义 `v1.2` 的真实持仓同步与对账层，回答“用户现在到底持有什么，以及与系统计划差多少”。

---

## 0. 一句话定义

从 `v1.2` 开始，系统不再默认“建议 == 已执行”。

正式账户真相源改为：

- `observed_portfolio`

并与以下对象严格分离：

- `target_plan`
- `planned_actions`
- `reconciliation_state`

---

## 1. 现实约束

对于支付宝、京东金融等无官方个人投资账户 API 的平台，系统必须支持：

- 手工录入具体产品持仓
- 账单/交易记录导入
- 截图/OCR 导入

系统不得因为没有 API 就回退到“假定用户按建议执行”。

---

## 2. 同步方式

### 2.1 手工同步

输入至少到产品级：

- `product_id`
- `product_name`
- `market_value`
- 可选 `cost_basis`

### 2.2 账单导入

用于批量导入产品级持仓或交易记录。

### 2.3 OCR 导入

允许用截图/OCR 做初始同步，但必须：

- 保留置信度
- 标记需要人工确认

---

## 3. 标准结构

最少包含：

- `observed_portfolio`
  - 当前产品级持仓
- `reconciliation_state`
  - 与目标计划的桶级/产品级偏差

正式对账输出至少包含：

- `drift_by_bucket`
- `drift_by_product`
- `unexpected_products`
- `planned_action_status`

---

## 4. planned_action_status 语义

- `completed`
  - 观测持仓与目标计划基本一致
- `partial`
  - 只执行了一部分，或出现意外产品
- `stale`
  - 当前没有有效目标计划，或计划已失效

---

## 5. 前台行为要求

后续 monthly / quarterly / event 流程必须优先看：

1. 当前 `observed_portfolio`
2. 与 active/pending plan 的差异
3. 再决定：
   - keep active
   - review replace
   - replace active

不允许只根据上次建议直接生成下一次动作。

