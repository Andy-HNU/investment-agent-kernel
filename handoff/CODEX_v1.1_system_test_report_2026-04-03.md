# Investment Agent Kernel v1.1 System Test Report

日期：2026-04-03

## 结论

本轮 `v1.1` 验证不再只靠模块单测，而是同时覆盖：

- 模型与 provider contract
- 真实公开源 smoke
- 年度逻辑验收
- OpenClaw bridge 自然语言批量验收
- 真实 `openclaw agent` 中文输入/输出日志

当前阶段的总体判断是：

- 代码层：可通过
- workflow 层：可通过
- 自然语言桥接层：可通过
- 真实 provider 层：核心路径可通过，`yfinance` 保留环境性 skip 边界

## 关键验证命令与结果

### 1. Review 问题针对性回归

```bash
PYTHONPATH=src:. python3 -m pytest \
  tests/agent/test_agent_contracts.py \
  tests/agent/test_nli_router_contract.py \
  tests/integration/test_openclaw_bridge.py \
  tests/contract/test_05_to_02_contract.py \
  tests/contract/test_18_provider_registry_contract.py -q
```

结果：通过。

这轮重点锁住了：

- `simulation_mode requested/used/auto_selected` 的诚实披露
- quarterly/event 沿用 baseline distribution context 时的 refresh summary 语义
- OpenClaw bridge 的 `approve_plan / feedback / show_user`
- bridge 文档和 runtime 能力的一致性

### 2. 真实 provider smoke

```bash
PYTHONPATH=src:. python3 -m pytest tests/smoke/test_18_live_timeseries_provider_smoke.py -q
```

结果：

```text
.s..
SKIPPED [1] tests/smoke/test_18_live_timeseries_provider_smoke.py:55: yfinance live provider returned empty rows
```

解释：

- `AKShare` live smoke：通过
- `BaoStock` live smoke：通过
- `market_history` live smoke：通过
- `yfinance`：本次外部源返回空行，因此被显式 `skip`

这说明真实 provider 层不是“只存在于设计图里”，已经跑到了公网源；同时也诚实保留了外部源不稳定边界。

保留摘要：

- [live_provider_smoke_summary_2026-04-03.txt](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/live_provider_smoke_summary_2026-04-03.txt)

### 3. 年度逻辑验收

```bash
PYTHONPATH=src:. python3 scripts/run_v11_year_acceptance.py \
  --db handoff/logs/v11_year_acceptance.sqlite \
  --output handoff/logs/v11_year_acceptance_2026-04-03.json
```

结果：退出码 `0`。

核心产物：

- [v11_year_acceptance_2026-04-03.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/v11_year_acceptance_2026-04-03.json)

本轮最关键的验收点：

- onboarding / quarterly / event / month_12 全程都保持 `garch_t_dcc_jump`
- restrictions change 会触发 `replace_active`
- 年度逻辑链路覆盖：
  - onboarding
  - approve-plan
  - feedback
  - monthly
  - quarterly
  - event
  - restrictions change
  - year-end review

### 4. OpenClaw bridge 批量自然语言验收

```bash
PYTHONPATH=src:. python3 scripts/accept_openclaw_bridge.py \
  --file integration/openclaw/examples/tasks.txt \
  --db handoff/logs/openclaw_acceptance_20260403T012108Z/frontdesk.sqlite \
  --artifacts handoff/logs/openclaw_acceptance_20260403T012108Z
```

结果：退出码 `0`。

核心产物：

- [acceptance_summary.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/acceptance_summary.json)
- [openclaw-bridge-20260403-104922.jsonl](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw-bridge-20260403-104922.jsonl)
- [tasks.txt](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/integration/openclaw/examples/tasks.txt)

当前真实覆盖到的 bridge intents：

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

### 5. 真实 `openclaw agent` 中文日志

真实命令形态：

```bash
openclaw agent --agent main --message "<中文提示词>" --json
```

已保留的真实输入/输出日志：

- [openclaw_onboarding_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_onboarding_nl_2026-04-03.log)
- [openclaw_probability_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_probability_nl_2026-04-03.log)
- [openclaw_plan_change_nl_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/openclaw_acceptance_20260403T012108Z/openclaw_plan_change_nl_2026-04-03.log)

这些日志不是脚本 mock，而是真实 OpenClaw runtime 输出。

### 6. 核心全量回归

```bash
PYTHONPATH=src:. python3 -m pytest -q --ignore=tests/smoke/test_18_live_timeseries_provider_smoke.py
```

结果：通过，退出码 `0`。保留产物：

- [pytest_v11_core_2026-04-03.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/pytest_v11_core_2026-04-03.log)
- [pytest_v11_core_summary_2026-04-03.txt](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/pytest_v11_core_summary_2026-04-03.txt)

说明：

- 核心回归与 live provider smoke 分开留痕
- 这样可以避免外部网络等待把整个内核回归套件拖住，同时又不掩盖真实源边界

## 本轮修掉的关键问题

### 1. `simulation_mode` 诚实度

问题：

- 自动从 `static_gaussian` 升级到 advanced mode 时，旧 notes 仍把它写成 `downgrade=true`

修复：

- 现在区分 `change=upgrade / unchanged / downgrade`
- 只在真实降级时才写 `downgrade=true`

### 2. quarterly / event 会丢失 baseline distribution context

问题：

- follow-up 会回退成 `static_gaussian`

修复：

- quarterly / event 现在沿用最近 baseline 的 `historical_return_panel / regime_feature_snapshot / jump_event_history / bucket_proxy_mapping`

### 3. quarterly refresh summary 对市场上下文来源的误报

问题：

- 实际复用了 provider-backed baseline context，但 quarterly 的 `market_raw` domain 和刷新建议仍按“默认市场输入”处理

修复：

- 现在 quarterly 的市场输入 domain 会标成基线复用，并给出正确的下一步刷新建议

### 4. OpenClaw 文档与 runtime drift

问题：

- 文档把 richer follow-up inputs 说成 NL bridge 已支持，实际没有

修复：

- 现在明确区分：
  - direct tool 输入面
  - NL bridge 当前支持输入面

### 5. OpenClaw `feedback` 必须显式写 `run_id`

问题：

- 这会让自然语言反馈任务不够实用，也导致 batch acceptance 证据难写

修复：

- 现在缺失 `run_id` 时会自动 fallback 到 latest run

## 当前剩余风险

1. `yfinance` 这类外部源仍受公网返回质量影响，本轮保留 `skip` 边界而不是假装稳定。
2. 年度逻辑验收使用的是 replay-friendly 模式，不等于把未来日期 live snapshot 真放开。
3. Claw shell 目前已“可用”，但还不是 memory/cron 自动闭环的长期顾问 runtime。

## 对外可说的话

这次 `v1.1` 不是“又加了一些代码”，而是：

- 真实源跑过了
- 年内逻辑跑过了
- Claw 自然语言桥跑过了
- 真实 OpenClaw 中文输出也留痕了

对第一次正式升级版本来说，这已经达到“可以拿来做系统自然语言验收”的标准。
