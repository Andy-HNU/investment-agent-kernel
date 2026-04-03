# v1.2 Claw Natural-Language Acceptance

日期：2026-04-04

目的：提供 `v1.2` 的真实自然语言输入/输出证据，而不是只给测试文件。

## 说明

本次验收分成两层：

1. 仓库内 bridge JSONL
2. 真实 `openclaw agent --agent main --json` 日志

## 1. Bridge JSONL 验收

产物：

- [acceptance_summary.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_acceptance_2026-04-04/acceptance_summary.json)
- [openclaw-bridge-v12.jsonl](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_acceptance_2026-04-04/openclaw-bridge-v12.jsonl)

### 覆盖的自然语言任务

- onboarding
- explain probability
- explain data basis
- show user
- sync portfolio manual
- quarterly review
- event review
- daily monitor
- explain plan change
- explain execution policy
- approve plan
- status

### 这条日志证明了什么

- 自然语言已经不只是 onboarding/status 的 demo
- `quarterly / event / approve_plan / explain_* / daily_monitor` 都能被真实路由到 frontdesk/bridge
- 观测持仓同步也已经进入自然语言任务面

## 2. 真实 OpenClaw 说明性日志

产物：

- [openclaw_v12_actions_2026-04-04.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_v12_actions_2026-04-04.log)
- [openclaw_v12_data_basis_2026-04-04.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_v12_data_basis_2026-04-04.log)

### Case 1. 动作面说明

真实输出摘要：

```text
onboarding
monthly
quarterly
event
status
show_user
feedback
approve-plan
explain_probability
explain_plan_change
```

说明：

- 这条日志不是 bridge JSON，而是真实 `openclaw agent` 的文本输出
- 它证明当前 adviser shell 至少已经能对外暴露主动作面

### Case 2. 为什么不能再用 default/inline 假数据

真实输出摘要：

```text
因为 v1.2 的目标是把“能跑 demo”升级成“能做可信决策”：
default/inline 假数据只能验证流程，不具备市场真实性、时序连续性和可审计性；
真实外部源+本地缓存历史数据则能提供稳定可回放的时间序列，支持校准、回测、解释和复盘。
```

说明：

- 这条日志证明 Claw 层不只是能列动作，也能解释新的数据真实性边界

## 3. 本轮新暴露并已修复的问题

### 1. 英文 explainability 任务不命中

已修复：

- `explain probability`
- `explain data basis`
- `explain execution policy`

### 2. `approve_plan` 版本号误吸用户 id

已修复：

- 只接受独立 token 的 `vN`

### 3. `quarterly / event` bridge 输出未显式带 workflow

已修复：

- 现在 JSONL 摘要中可以直接看见 `quarterly / event`

## 4. 仍保留的边界

- 这次真实 `openclaw agent` 日志主要是说明性对话，不是直接驱动 bridge 调用
- 真正驱动 frontdesk 的仍以 bridge JSONL 为主
- memory / cron 自动闭环仍未接入
- `feedback` 在本轮 bridge 序列里没有形成有效 `run_id` 驱动，这条下一轮应再补一个完整场景

## 结论

`v1.2` 的 Claw 自然语言验收已经明显强于 `v1`：

- 不再只测说明文档
- 不再只测 onboarding/status
- 已经覆盖到：
  - 计划解释
  - 数据依据解释
  - 观测持仓同步
  - 季度复核
  - 事件复核
  - 日监控
  - plan approval

这说明 adviser shell 的动作面已经接近真实用户可测状态。
