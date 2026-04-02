# Investment Agent Kernel

这是当前投资系统的 `decision kernel` 仓库。

它提供：
- frontdesk workflow：`onboard / monthly / event / quarterly / status / feedback / approve-plan`
- bucket allocation、goal solver、runtime optimizer、decision card 主链
- execution plan 生成、审批、active/pending comparison
- provider abstraction、历史数据快照与 policy/news structured signal 入口
- 给 Claw 使用的 agent / integration 文档边界与 bridge runtime

它不提供：
- 自动下单
- scheduler / cron
- memory runtime
- 原始新闻正文直接驱动数学内核

## 权威顺序
1. `AGENTS.md`
2. `tests/`
3. `system/`
4. `handoff/README.md`
5. `docs/`

## 目录
```text
.
├─ AGENTS.md
├─ README.md
├─ frontdesk_app.py
├─ system/
├─ handoff/
├─ agent/
├─ integration/openclaw/
├─ scripts/
├─ tests/
└─ src/
```

## 快速开始
```bash
python3 -m pytest -q
python3 scripts/verify_provider_matrix.py
python3 scripts/run_sample_frontdesk_flow.py
```

一条最小前台体验链：
```bash
python3 frontdesk_app.py onboard \
  --profile-json '{"account_profile_id":"demo_user","display_name":"Demo","current_total_assets":50000,"monthly_contribution":6000,"goal_amount":300000,"goal_horizon_months":48,"risk_preference":"中等","max_drawdown_tolerance":0.12,"current_holdings":"cash","restrictions":[]}' \
  --non-interactive --json
```

## Frozen 样例
- provider fixture: [provider_snapshot_local.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/tests/fixtures/provider_snapshot_local.json)
- inline provider sample: [inline_snapshot.sample.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/examples/provider/inline_snapshot.sample.json)
- historical dataset sample: [historical_dataset.sample.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/examples/provider/historical_dataset.sample.json)

## 关键入口
- 前台：`frontdesk_app.py`
- demo：`demo.py`、`scripts/full_flow_demo.py`
- provider matrix：`scripts/verify_provider_matrix.py`
- sample flow：`scripts/run_sample_frontdesk_flow.py`
- Claw 文档入口：`agent/`、`integration/openclaw/`
- OpenClaw bridge：`scripts/openclaw_bridge_cli.py`、`scripts/accept_openclaw_bridge.py`
- v1 阶段报告：`handoff/CODEX_v1_phase_reports_2026-04-02.md`
- v1 测试报告：`handoff/CODEX_v1_system_test_report_2026-04-02.md`

## 当前已实现
- 用户画像解析与自然语言限制编译
- bucket 候选方案与具体产品执行计划
- execution plan 审批、回填、active/pending 差异化 guidance
- `http_json / inline_snapshot / local_json` provider config
- provider capability matrix 与 historical dataset cache
- policy/news structured signal -> `03/05`
- Claw 接入边界与 shell playbook 文档

## 已知边界
- 低频、单用户优先，不是高频交易系统
- provider 覆盖不是商用级全资产全券商
- OpenClaw 负责 memory / cron / policy-news 搜索分析 / 对话组织
- 本仓库继续作为 decision kernel，不作为完整 advisor shell

## 推荐验证
```bash
python3 -m pytest tests/contract/test_18_provider_data_contract.py -q
python3 -m pytest tests/contract/test_18_provider_registry_contract.py -q
python3 -m pytest tests/contract/test_18_frontdesk_execution_plan_guidance.py -q
python3 -m pytest tests/contract/test_18_claw_agent_docs_contract.py -q
```
