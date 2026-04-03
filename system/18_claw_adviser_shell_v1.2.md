# 18_claw_adviser_shell_v1.2.md

> **文档定位**：本文件定义 `v1.2` 的 Claw adviser shell 边界、自然语言任务面和日级顾问职责。

---

## 0. 一句话定义

`v1.2` 的 Claw shell 不只是把用户话翻译成 frontdesk 命令。

它必须承担：

- 自然语言建档/复核/解释
- 日级监控与触发建议
- 计划变更解释
- 概率与数据依据解释
- 账户同步入口

但仍不自动下单。

---

## 1. 正式自然语言任务面

`v1.2` 至少覆盖以下 intents：

- `onboarding`
- `show_user`
- `status`
- `monthly`
- `quarterly`
- `event`
- `approve_plan`
- `feedback`
- `sync_portfolio_manual`
- `sync_portfolio_import`
- `sync_portfolio_ocr`
- `daily_monitor`
- `explain_probability`
- `explain_plan_change`
- `explain_data_basis`
- `explain_execution_policy`

---

## 2. 日级顾问职责

Claw 在 `v1.2` 默认做到：

- 每日监控产品和计划状态
- 根据触发规则给出具体买卖/止盈止损建议
- 但最终仍由用户确认执行

默认分工：

- 日：监控与建议
- 月：轻量复核
- 季：正式重估主计划

---

## 3. 解释义务

Claw 必须能用自然语言解释：

1. 目标达成率如何计算
2. 当前用了什么历史数据和分布模式
3. 为什么当前推荐方案不是最高概率方案
4. 为什么建议替换或保留 active plan
5. 当前产品维护规则是什么

---

## 4. 账户同步职责

Claw 必须支持把用户现实操作同步回系统：

- 手工录入具体产品
- 导入持仓/账单
- 截图/OCR 导入

并在同步后明确告诉用户：

- 当前真实持仓
- 与目标计划差异
- 是否还应继续执行原建议

---

## 5. 边界

`v1.2` 仍不包含：

- 自动下单
- 代用户确认交易
- 强依赖平台私有 API 的账户读取

但允许：

- 盘中估算
- 收盘后对账
- 次日动作确认
