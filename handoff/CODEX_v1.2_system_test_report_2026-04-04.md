# Investment Agent Kernel v1.2 System Test Report

日期：2026-04-04

## 结论

本轮 `v1.2` 的系统测试分成 5 类：

1. 回归与修复测试
2. 前瞻验证
3. 真实 provider smoke
4. Claw/bridge 自然语言验收
5. 全量 pytest

5 类测试均已落下真实证据。  
其中 fresh 全量 `pytest -q` 已在本轮收口完成，进度日志见 `handoff/logs/pytest_v12_full_2026-04-04.log`，最终退出码为 `0`。

## 1. 回归与修复测试

### 1.1 空权重集合高级分布模式回归

命令：

```bash
python3 -m pytest tests/contract/test_02_goal_solver_contract.py::test_run_monte_carlo_handles_empty_weight_set_in_advanced_mode -q
```

结果：通过。

意义：

- `garch_t` 路径下空权重集合不再崩溃
- 这对高约束、低风险、现金主导场景是必须的

### 1.2 Claw shell explainability 路由与 approve_plan 解析回归

命令：

```bash
python3 -m pytest tests/agent/test_19_claw_shell_contract.py -q
```

结果：通过。

覆盖点：

- 英文 `explain probability`
- 英文 `explain data basis`
- 英文 `explain execution policy`
- `approve_plan` 不再误吸用户 id 中的 `v12`

## 2. 前瞻验证

### 2.1 固定锚点验证

产物：

- [forward_validation_anchor_2026-04-04.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/forward_validation_anchor_2026-04-04.json)

结论：

- 锚点：`2021-01-01`
- horizon：`60` 个月
- goal：`450000`
- mode：`garch_t`
- 预测成功率：`0.4636`
- 实际终值：`425767.88`
- 实际未达标：`false`
- bucket/product-adjusted 的 Brier 风格误差：`0.2149`

判断：

- 该锚点下，模型给出中等成功率，实际结果未达标
- 这说明验证链条是通的
- 也说明系统已经具备“用真实未来打脸自己”的能力

### 2.2 滚动锚点验证

产物：

- [forward_validation_rolling_2026-04-04.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/forward_validation_rolling_2026-04-04.json)

结论：

- anchors：`2021-01-01 / 2022-01-03 / 2023-01-03`
- hit_rate：`0.3333`
- 平均预测成功率：`0.4741`
- 平均 Brier 风格误差：`0.4599`

判断：

- 当前校准质量还不够好
- 但这不是坏消息：因为系统已经从“只会报一个概率”升级到了“概率是否合理可以被真实未来检验”

## 3. 真实 Provider Smoke

产物：

- [live_provider_smoke_2026-04-04.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/live_provider_smoke_2026-04-04.json)

本轮结果：

- `akshare`：成功，`56` 行
- `baostock`：成功，`56` 行
- `yfinance`：rate limit

判断：

- 中国市场免费源的真实路径已经打通
- 海外免费源在当前环境下仍有稳定性边界

## 4. Claw / Bridge 自然语言验收

### 4.1 Bridge JSONL

产物：

- [acceptance_summary.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_acceptance_2026-04-04/acceptance_summary.json)
- [openclaw-bridge-v12.jsonl](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_acceptance_2026-04-04/openclaw-bridge-v12.jsonl)

本轮实际覆盖的 workflow：

- `onboard`
- `explain_probability`
- `explain_data_basis`
- `show_user`
- `sync_observed_portfolio`
- `quarterly`
- `event`
- `daily_monitor`
- `explain_plan_change`
- `explain_execution_policy`
- `approve_plan`
- `status`

### 4.2 真实 `openclaw agent` 日志

产物：

- [openclaw_v12_actions_2026-04-04.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_v12_actions_2026-04-04.log)
- [openclaw_v12_data_basis_2026-04-04.log](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1-2-delivery/handoff/logs/openclaw_v12_data_basis_2026-04-04.log)

其中一条真实解释输出明确说明：

- 为什么 `v1.2` 必须使用真实外部源缓存历史数据
- 为什么 default/inline 假数据只适合测流程，不适合测正式路径

## 5. 全量 pytest

本轮 fresh 全量已完成：

```bash
python3 -m pytest -q
```

结果：

- 退出码：`0`
- 进度日志：`handoff/logs/pytest_v12_full_2026-04-04.log`
- 该日志显示全套用例跑到 `[100%]` 后正常结束

因此本轮报告中的系统级结论已经由 fresh 全量回归覆盖。

## 本轮发现并修复的问题

### 1. `garch_t` 在空权重集合场景下崩溃

已修复，并补 contract test。

### 2. 英文 explainability 意图不命中

已修复，并补 agent contract test。

### 3. `approve_plan` 版本号解析误吸用户 id

已修复，并补 agent contract test。

## 剩余风险

- 概率校准质量还不够强，前瞻验证已经说明这一点
- `yfinance` 这类免费源仍有环境限频风险
- 真实券商/账户 API 仍未接入
- memory / cron runtime 仍未自动绑定到 Claw adviser shell

## 判断

如果评价标准是：

- 路径是否真实
- 测试是否诚实
- 能否被自然语言验收

那么 `v1.2` 已经明显比上一版更硬。  
如果评价标准是：

- 概率是否已经完全可信

那么答案仍然是：**还需要继续校准**。
