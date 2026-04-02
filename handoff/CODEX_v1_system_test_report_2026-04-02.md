# Investment Agent Kernel v1 System Test Report

日期：2026-04-02

## 结论

本轮完成后的 `v1` 已通过：

- 新增功能 targeted tests
- 全量 `pytest -q`
- provider matrix 脚本
- sample frontdesk flow
- OpenClaw bridge harness
- 真实 `openclaw agent` 自然语言 I/O 记录

## 关键验证命令

### 1. 新增功能 targeted tests

```bash
python3 -m pytest tests/smoke/test_17_plan_guidance_wiring.py \
  tests/provider/test_dataset_cache_and_version_pinning.py \
  tests/provider/test_external_provider_registry_contract.py \
  tests/provider/test_signal_types_contract.py \
  tests/agent/test_agent_contracts.py \
  tests/integration/test_openclaw_bridge.py -q
```

结果：通过。

### 2. OpenClaw bridge integration fix 回归

```bash
python3 -m pytest tests/integration/test_openclaw_bridge.py -q
```

结果：通过。  
补抓到的问题是 `scripts/accept_openclaw_bridge.py` 缺少 `src/` bootstrap，已修复并补了真实脚本测例。

### 3. 全量测试

```bash
python3 -m pytest
```

结果：通过，`261 passed in 31.01s`。  
完整输出保存在：

- [pytest_full_2026-04-02.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/pytest_full_2026-04-02.log)

### 4. Provider capability matrix

```bash
python3 scripts/verify_provider_matrix.py
```

结果：通过。输出保存在：

- [provider_matrix_2026-04-02.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/provider_matrix_2026-04-02.json)

### 5. Sample frontdesk flow

```bash
python3 scripts/run_sample_frontdesk_flow.py
```

结果：通过。输出保存在：

- [sample_frontdesk_flow_2026-04-02.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/sample_frontdesk_flow_2026-04-02.json)

该 flow 覆盖了：

- onboarding
- approved active plan baseline
- quarterly follow-up
- execution plan comparison / guidance
- external snapshot provenance
- execution feedback summary

### 6. OpenClaw bridge harness

```bash
python3 scripts/accept_openclaw_bridge.py \
  --file handoff/logs/openclaw_bridge_tasks_2026-04-02.txt \
  --db handoff/logs/openclaw_bridge_2026-04-02.sqlite \
  --artifacts handoff/logs/openclaw_bridge_artifacts
```

结果：通过。  
自然语言输入/输出 JSONL 产物：

- [openclaw_bridge_tasks_2026-04-02.txt](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/openclaw_bridge_tasks_2026-04-02.txt)
- [openclaw-bridge-20260402-024333.jsonl](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/openclaw_bridge_artifacts/openclaw-bridge-20260402-024333.jsonl)

### 7. 真实 OpenClaw 自然语言 turn

使用命令：

```bash
openclaw agent --agent main --message '<natural language prompt>' --json
```

三组真实日志保存在：

- [openclaw_onboarding_nl_2026-04-02.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/openclaw_onboarding_nl_2026-04-02.log)
- [openclaw_execution_plan_nl_2026-04-02.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/openclaw_execution_plan_nl_2026-04-02.log)
- [openclaw_policy_signal_nl_2026-04-02.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/logs/openclaw_policy_signal_nl_2026-04-02.log)

阶段 5 的人工可读摘要见：

- [CODEX_phase5_claw_natural_language_acceptance_2026-04-02.md](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1/handoff/CODEX_phase5_claw_natural_language_acceptance_2026-04-02.md)

## 本轮发现并修复的问题

### 1. `accept_openclaw_bridge.py` 真实脚本入口失败

问题：

- 之前的 tests 只覆盖 bridge 函数和一个 CLI wrapper
- `accept_openclaw_bridge.py` 直接运行时没有把 `src/` 放进 `sys.path`

修复：

- 给脚本补了 `ROOT/SRC` bootstrap
- 给 `tests/integration/test_openclaw_bridge.py` 补了真实 harness 测例

### 2. 同一 OpenClaw session 并发打多条 prompt 会发生 session lock

问题：

- 对同一 `main` agent 并发发起多个 `openclaw agent` turn，会触发 session file lock

处理：

- Phase 5 的验收日志采用串行 turn 录制
- 这是当前 OpenClaw runtime 行为，不影响本仓库 bridge 正确性

## 当前剩余风险

- 专用市场 provider 仍以架构/fixture/registry 为主，未扩到全量真实公开源 connector
- OpenClaw memory/cron 还未和本仓库 bridge 自动绑定
- provider 还没有 daemon 级长期健康监控

## 对外可说的话

这次不是“代码看起来差不多了”，而是：

- 主链跑过了
- 新增功能跑过了
- bridge 跑过了
- Claw 自然语言 I/O 也跑过了

对 `v1` 来说，这已经满足正式验收要求。
