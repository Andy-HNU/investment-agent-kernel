# Phase 5 Claw Natural-Language Acceptance

日期：2026-04-02

目的：提供 `Phase 5` 的真实自然语言输入/输出证据，而不是只给测试文件或脚本。

## 说明

本次验收分成两层：

1. 真实 `openclaw agent --agent main --json` turn
2. 仓库内 OpenClaw bridge harness 产生的 JSONL 输入/输出日志

注意：

- 对同一 `main` agent 并发打多个 turn 会遇到 OpenClaw session lock
- 因此本次真实 agent turn 采用串行录制

## Case 1. 新用户 onboarding 后会看到什么

输入：

```text
你现在扮演 advisor shell。请读取 /root/AndyFtp/investment_system_codex_ready_repo/agent/PLAYBOOK_ADVISOR_FULL.md 和 /root/AndyFtp/investment_system_codex_ready_repo/README.md，然后用中文告诉一个新用户：第一次 onboarding 后他会看到哪三类关键信息。不要改代码，只给简洁结果。
```

输出摘要：

```text
第一次 onboarding 后，你会看到三类关键信息：
1) Bucket 级别配置建议
2) 候选方案/产品选项
3) 执行计划（若已有旧计划，还会展示 active vs pending 差异）
```

原始日志已在主干清理阶段移除；本节保留输入与输出摘要。

## Case 2. active vs pending execution plan

输入：

```text
请读取 /root/AndyFtp/investment_system_codex_ready_repo/agent/TOOL_CONTRACTS.md 和 /root/AndyFtp/investment_system_codex_ready_repo/src/frontdesk/service.py，用中文解释 active_execution_plan 和 pending_execution_plan 的区别，以及用户什么时候应该 approve-plan。不要改代码。
```

输出摘要：

```text
active_execution_plan 是已经审批通过、当前正在执行的计划。
pending_execution_plan 是新生成但尚未审批的候选计划。
首次 onboarding、后续出现新 pending 且决定采用时，或者 comparison 显示 replace_active / review_replace 时，应进入 approve-plan 流程。
```

原始日志已在主干清理阶段移除；本节保留输入与输出摘要。

## Case 3. policy/news 为什么不能直接改 solver

输入：

```text
请读取 /root/AndyFtp/investment_system_codex_ready_repo/system/13_policy_news_structured_signal_contract_v2.md 和 /root/AndyFtp/investment_system_codex_ready_repo/src/calibration/engine.py，用中文解释：政策/新闻为什么不能直接改写 solver 数学，而要先变成 structured signal。不要改代码。
```

输出摘要：

```text
政策/新闻是高噪声、非结构化输入，直接改 solver 数学会把内核变成不可审计黑箱。
所以必须先变成带来源、时间、置信度、人工复核标记的 structured signal，再由 calibration 保守吸收，只影响 review gate、risk penalty、约束边界和解释层。
```

原始日志已在主干清理阶段移除；本节保留输入与输出摘要。

## Case 4. 仓库内 bridge harness 的自然语言日志

输入任务文件原件已在主干清理阶段移除；保留其任务摘要如下。

内容包括：

```text
onboard user bridge_demo assets 50000 monthly 5000 goal 200000 in 36 months risk moderate
show status for user bridge_demo
monthly follow-up for user bridge_demo
```

输出 JSONL 原件已在主干清理阶段移除；保留其“自然语言任务被 bridge 路由到 frontdesk 并生成结构化输入/输出对”的验收结论。

这个 JSONL 不是模型解释文本，而是 bridge 真正把自然语言任务路由到 frontdesk 后写出来的结构化输入/输出对。

## 结论

Phase 5 不再只是“有文档”：

- 有真实 `openclaw agent` 的自然语言输入/输出
- 有本仓库 bridge 的自然语言任务 JSONL 落盘
- 有对应 bridge tests 与 CLI/harness 验证

这已经满足 `v1` 对 Claw 接入验收的最低要求。
