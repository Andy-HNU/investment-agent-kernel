# Investment Agent Kernel v1.1 Claw Natural-Language Acceptance

日期：2026-04-03

目的：提供 `v1.1` 的真实自然语言验收证据，而不是只给脚本或测试文件。

## 说明

本次 `v1.1` 的 Claw 验收分成两层：

1. 仓库内 OpenClaw bridge 的批量自然语言任务
2. 真实 `openclaw agent --agent main --json` 中文输入/输出日志

两层的意义不同：

- bridge batch：证明自然语言任务真能路由到正确 workflow
- real `openclaw agent`：证明真实 OpenClaw runtime 能给出人能读懂的中文解释

## Case A. OpenClaw bridge 批量自然语言任务

任务文件：

- [tasks.txt](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/integration/openclaw/examples/tasks.txt)

运行命令：

```bash
PYTHONPATH=src:. python3 scripts/accept_openclaw_bridge.py \
  --file integration/openclaw/examples/tasks.txt \
  --db handoff/logs/openclaw_acceptance_20260403T012108Z/frontdesk.sqlite \
  --artifacts handoff/logs/openclaw_acceptance_20260403T012108Z
```

最新 JSONL：

- [openclaw-bridge-20260403-104922.jsonl](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw-bridge-20260403-104922.jsonl)

当前已被真实任务覆盖的 intents：

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

这次重点不是“任务文件里写了”，而是 JSONL 已经真实记录了这些任务的：

- 原始自然语言输入
- intent 识别结果
- 结构化调用参数
- workflow 输出

## Case B. 真实 OpenClaw 中文输入/输出日志

### 1. onboarding 后用户会看到什么

日志：

- [openclaw_onboarding_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_onboarding_nl_2026-04-03.log)

输入主题：

- onboarding 后用户第一次会看到哪三类关键信息

输出摘要：

- Bucket 级资产配置建议
- 候选方案/产品选项
- 执行计划与 active/pending 差异

### 2. 为什么概率会变化

日志：

- [openclaw_probability_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_probability_nl_2026-04-03.log)

输入主题：

- simulation mode 和市场状态为什么会改变目标达成率

输出摘要：

- 解释了 `static_gaussian` 与 `garch_t / dcc / jump` 的区别
- 解释了市场状态如何改变参数与尾部压力
- 明确指出达成率是“分布假设 × 当前市场状态校准”的结果

### 3. 为什么建议替换 active plan

日志：

- [openclaw_plan_change_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_plan_change_nl_2026-04-03.log)

输入主题：

- `replace_active` 时用户到底应该比较什么

输出摘要：

- 桶级变化
- 产品级变化
- 风险/执行约束变化
- 计划版本与状态关系

### 说明

本次真实 `openclaw agent` 日志重点放在“解释层”，因为：

- 解释是用户第一眼能直接感知的 advisor shell 能力
- `approve_plan / feedback / show_user / quarterly / event` 的 workflow 触发正确性已由 batch JSONL 真正覆盖

## 结论

`v1.1` 的 Claw 验收不再只是：

- 有文档
- 有测试文件

而是已经有：

- 真实自然语言任务批量日志
- 真实 OpenClaw 中文输入/输出日志
- intent 到 workflow 的结构化映射结果

这满足了 `v1.1` 对 Claw 自然语言验收的要求。
