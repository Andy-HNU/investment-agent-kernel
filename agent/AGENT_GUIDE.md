# Advisor Agent Guide

## Role

本仓库对外提供的是 `investment advisor decision kernel`。

它负责：
- 目标求解
- 候选配置
- 运行时动作建议
- 决策卡
- 执行计划
- frontdesk 状态持久化

它不负责：
- 自动交易
- 调度器
- 长期记忆 runtime
- 新闻/政策原文检索 runtime
- 频道消息收发

## Audience

- OpenClaw advisor shell
- Codex/Codex-style developer agents
- 本地 CLI 用户

## Stable Runtime Surface

优先通过 `frontdesk_app.py` 进入：
- `onboard`
- `monthly`
- `event`
- `quarterly`
- `show-user`
- `status`
- `feedback`
- `approve-plan`

## Behavioral Rules

- 先构建或读取画像，再进入 workflow
- 先解释输入来源，再解释建议
- 若存在 `active_execution_plan` 与 `pending_execution_plan` 的差异，必须解释是否应替换
- 若外部数据 degraded/stale，必须披露 freshness/fallback
- 政策/新闻只能作为结构化信号 sidecar，不直接改写 solver 数学
- 用户若表达“目标年化收益率”，应传 `target_annual_return`，不要自行把它简化成只基于当前资产的期末目标金额

## Integration Rule

- OpenClaw 是 `advisor shell`
- 本仓库是 `decision kernel`
- 不复制 OpenClaw skill 正文到本仓库
- 修改外部 skill 时，只回 patch 到 OpenClaw 原路径
