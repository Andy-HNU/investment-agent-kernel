# Investment Agent Kernel v1 Phase Reports

日期：2026-04-02

读者：产品负责人、项目 owner、后续接手机器人/工程师

## 总结

这次交付把 roadmap 的 5 个阶段都推进到了 `v1 可验收` 状态。

这里的 `v1` 不是“所有未来想做的都做完”，而是：

- kernel 主链已经能稳定跑通
- 用户结果不再停在抽象 bucket，而是有执行计划层
- provider / historical / policy-signal 已经有正式接口与测试
- 开源发布所需的 sample flow、fixture、边界说明、验证脚本已经齐
- Claw 已经有文档契约、bridge、CLI/harness，以及真实自然语言 I/O 日志

仍然刻意不做的，是自动交易、企业级多租户 SLA、完整券商/全资产商业接入、以及把 OpenClaw memory/cron runtime 复制进本仓库。

## Phase 1. Kernel Completion

### 实现了什么

- `02 goal_solver`：
  - 概率口径、`solver_notes`、fallback 解释链、infeasibility 语义收紧
  - `historical_dataset` 进入求解语义时会显式披露，不再暗含
- `10 ev_engine + 04 runtime_optimizer`：
  - `cooldown`、`forbidden_actions`、`candidate_poverty`、tie-break priority、mixed safe/active low-confidence 等语义已兑现
  - `ADD_DEFENSE` 回到事件型 drawdown 路径，不再乱入季度路径
  - amount sizing 不再靠固定 split，改为按 deficit / cash budget 裁剪
- `11 Product Mapping / Execution Planner`：
  - 资金桶之外新增具体产品执行计划层
  - frontdesk 已持久化 `plan_id + plan_version`
  - 用户侧能看到 `active_execution_plan / pending_execution_plan`
- `07/09/frontdesk`：
  - `approve-plan` 已经落地
  - active/pending 的 diff、comparison、guidance、next steps 已进入 decision card / CLI / user state
  - `replace_active / review_replace / keep_active` 已进入前台语义

### 用户能感受到的提升

- 不再只给一个“桶配置”，而是会告诉用户是否有新的待确认方案
- 用户能看见“当前执行方案”和“新候选方案”的差异，不用盲猜该不该切换
- 决策卡不再只是建议动作，还会附带执行计划、替换建议和确认入口

### 未做完但不阻塞 v1 的点

- orchestrator 还没有把 execution-plan approval/supersede 完全收成统一状态机
- 产品池仍是第一版，不是全市场全产品 universe
- solver / EV 的数学细节仍有继续拟合和校准空间

### 为什么这次没有继续往下打深

- v1 的优先级是把“用户可执行闭环”做出来，而不是把数学调参打到极限
- execution-plan 的确认、替换、反馈闭环一旦缺失，前台体验会明显失真；这个优先级高于继续微调公式

### 下一步建议

- 把 execution-plan state machine 上提到 orchestrator 统一管理
- 扩产品池和替代品策略
- 继续收紧 `02/04/10` 的公式与解释一致性

## Phase 2. Real-time and Historical Data Development

### 实现了什么

- `provider registry` 已加入：
  - 默认 `http_json`
  - `file_json`
  - 兼容 `inline_snapshot`
  - 兼容 `local_json`
- provider 能力矩阵与代码映射已经成型：
  - `src/snapshot_ingestion/provider_matrix.py`
  - `scripts/verify_provider_matrix.py`
- 历史数据底座第一版已加入：
  - `HistoricalDatasetSnapshot`
  - `HistoricalDatasetCache`
  - dataset version pinning / reload
  - timeseries dataset 类型和 CSV-style 输入工具
- policy/news 结构化信号第一版已加入：
  - `PolicyNewsSignal`
  - `signals_ingestion`
  - calibration 对 structured signal 的保守吸收

### 用户/系统层面的价值

- 外部输入不再只有一个“万能 JSON adapter”概念，而是已经有可扩展 provider surface
- 历史数据不再只是口头说“以后可以接”，而是已经有可落账、可 version pin、可回放的对象层
- policy/news 不会绕过风控直接篡改数学，而是先经过结构化和审计边界

### 未做完但不阻塞 v1 的点

- 还没有把 `AKShare / efinance / yfinance` 做成仓库内置、长期维护的专用 connector
- broker/account provider 仍以手工快照、JSON proxy、fixture 为主
- 历史数据目前是正式化的 dataset contract，不是完整的市场数据平台

### 为什么这样取舍

- v1 目标是“正式接口 + 样例 provider + 可测试历史数据底座”
- 如果一上来就把每个市场源都写死进主链，维护成本高，回放一致性反而更差
- 当前仓库的正确定位是 kernel，不是数据平台本身

### 下一步建议

- 按优先级补真实公开源 connector：先 `AKShare`，再 cross-check 源
- 补 broker/account provider 的适配层
- 增加 provider freshness / stale / drift 的长期观测数据

## Phase 3. Data and Provider Testing

### 实现了什么

- provider contract tests：
  - registry resolution
  - `file_json` / `http_json` / `local_json` / `inline_snapshot`
  - provenance / freshness / fallback
- historical data tests：
  - dataset cache roundtrip
  - version pinning
  - history 对 calibration / goal solver notes 的真实影响
- policy/news signal tests：
  - signal typing
  - manual review / quality flags / soft preferences
- end-to-end / acceptance：
  - frozen sample flow
  - frontdesk external snapshot flow
  - randomized natural-language profile acceptance 仍保留
  - plan guidance wiring smoke 已补
  - OpenClaw bridge integration tests 已补

### 用户/项目层面的价值

- 现在保护的是“语义有没有兑现”，不是只保护“程序别崩”
- provider 改坏、dataset 失真、signal 不生效，这些都更容易被测试拦住
- 未来继续接外部源时，不会只能靠人工肉眼回归

### 未做完但不阻塞 v1 的点

- 还没有 daemon 级、长时间运行的 drift 监控与自动告警
- 还没有对真实三方免费源做长期波动统计

### 为什么这样取舍

- 单用户开源 v1 更需要 contract/replay/fixture 的稳定性
- 长期在线监控更适合下一阶段和 Claw 的 cron/runtime 结合来做

### 下一步建议

- 增加 source-drift 日志与健康快照
- 对真实公开源建立周期回归
- 为高价值 provider 增加 fallback 切换演练

## Phase 4. Open-source Quality Hardening Before Claw

### 实现了什么

- 根 README 已经重写成当前仓库真实定位，不再是旧 seed 说明
- 开源级入口已经齐：
  - `scripts/verify_provider_matrix.py`
  - `scripts/run_sample_frontdesk_flow.py`
  - frozen fixtures / examples
- `system/11-14` 的 v2 补充规格已经落地，并和 handoff 入口打通
- handoff 现在新增：
  - 阶段报告
  - 系统测试报告
  - Claw 自然语言验收报告
- 关键日志已经固化到 repo：
  - provider matrix
  - sample frontdesk flow
  - OpenClaw NL logs
  - bridge JSONL artifacts

### 用户/开源读者会看到什么

- clone 下来后能知道这个仓库是干什么的、不是干什么的
- 能直接跑 sample flow，而不是只能看抽象文档
- 能看到 provider 边界、Claw 边界、风险边界
- 能沿着 handoff 入口直接找到 active 文档，不需要翻聊天记录

### 未做完但不阻塞 v1 的点

- 还没有守护进程式 monitoring / alerting
- 还没有完整的安装器/打包发布流程
- 还没有针对所有资产类别的真实联网 demo

### 为什么这样取舍

- v1 的目标是“开源不丢人、别人能跑通、边界透明”
- 不是把仓库先堆成一套运维系统

### 下一步建议

- 增加一键 healthcheck / readiness 脚本
- 增加 provider health snapshot 与 drift 诊断输出
- 整理成更正式的 release notes / CHANGELOG

## Phase 5. Advisor-Agent / Claw Integration

### 实现了什么

- agent/openclaw 文档契约层：
  - `agent/AGENT_GUIDE.md`
  - `agent/TOOL_CONTRACTS.md`
  - `agent/SKILL_ROUTING.md`
  - `agent/PLAYBOOK_ADVISOR_FULL.md`
  - `agent/NATURAL_LANGUAGE_TASK_SURFACE.md`
  - `integration/openclaw/*`
- machine-readable layer：
  - `agent/contracts/tool_contracts.json`
  - `agent/routing/skill_routing.json`
  - `integration/openclaw/config/schema.json`
- runtime bridge：
  - `src/agent/nli_router.py`
  - `src/integration/openclaw/bridge.py`
  - `scripts/openclaw_bridge_cli.py`
  - `scripts/accept_openclaw_bridge.py`
- 验证：
  - bridge unit/integration tests
  - bridge CLI/harness logs
  - 真实 `openclaw agent --agent main --json` 自然语言输入/输出日志

### 用户/Claw 运行时的价值

- Claw 不需要自己猜 frontdesk 工具面，已经有稳定的路由与桥接层
- 自然语言任务可以被落到 `onboarding / status / monthly / approve-plan / feedback`
- no-copy / patch-back 原则被显式文档化，不会把 OpenClaw 技能反向 fork 回本仓库

### 未做完但不阻塞 v1 的点

- 还没有把 Claw 的 cron / memory runtime 自动绑定到这个 bridge
- NLI router 仍是第一版规则路由，不是完整的多轮 advisor 对话编排器
- 真实 OpenClaw session 并发打同一 agent 时仍会遇到 session lock，因此验收采用串行 turn

### 为什么这样取舍

- 这是符合边界设计的：memory / cron / 对话组织继续留在 OpenClaw
- 本仓库只需要把 bridge、contract、runtime acceptance 做实

### 下一步建议

- 把 bridge task intent 和 OpenClaw cron/session 绑定起来
- 继续扩大 NLI router 识别面
- 补多轮 advisor 对话的 acceptance 场景

## 最终判断

这次 v1 已经完成了“第一次正式版本”应有的闭环：

- 有正式 kernel
- 有正式 provider / history / signal contract
- 有正式测试门
- 有开源级样例和说明
- 有 Claw bridge 与真实 NL 验证

如果要继续做 v1.1，最优先的不是推翻重来，而是：

1. 扩真实 provider
2. 增强 product universe
3. 把 orchestrator / bridge 的状态机继续收紧
4. 让 OpenClaw cron / memory 与本仓库 bridge 真正连起来
