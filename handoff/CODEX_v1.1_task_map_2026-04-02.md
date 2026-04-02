# CODEX v1.1 Task Map

日期：2026-04-02

读者：开发、审阅、测试、产品 owner、后续接手机器人/工程师

## 总结

`v1` 已经达到“可验收内核”状态，但仍遗留 3 类高价值问题：

- 模型正确性仍停留在 `static gaussian monte carlo`
- provider 真实源仍以架构/fixture 为主，未完成真实公开源闭环
- Claw adviser shell 只到 bridge-ready，不是完整自然语言壳层

`v1.1` 的目标不是推翻 `v1`，而是把这三类问题系统性补强，并把上一轮自然语言验收、年内模拟验收、provider 真实源闭环都拉进同一张执行地图。

本任务书从现在开始取代 `CODEX_kernel_first_roadmap_2026-04-01.md` 作为当前主执行地图；旧 roadmap 保留为 `v1` 历史路线，不再单独驱动下一轮开发。

## 协作约定

- 继续采用多角色协作：
  - `Lead / Integrator`
  - `Modeling Developer`
  - `Provider Developer`
  - `Product / Workflow Developer`
  - `Independent Reviewer`
  - `Independent Tester`
- review 要求：
  - 不只审代码
  - 还要查 `system/` 文档偏离、硬编码、隐藏降级、解释口径漂移
- 测试要求：
  - 不只跑 pytest
  - 必须保留真实自然语言日志、真实 provider smoke、随机画像回归和年度逻辑模拟
- 每条主线都必须形成：
  - 开发结果
  - 测试证据
  - 审阅结论
  - 剩余风险

## 当前遗留问题总表

### A. 模型正确性

- `02 goal_solver` 仍是 `parametric monte carlo + normal`
- `05 calibration` 会解释市场状态，但只改 `expected_returns / volatility / correlation`
- 市场状态不会改变分布形态
- 默认 `important + moderate`：
  - 成功阈值 = `70%`
  - ranking mode = `sufficiency_first`
  - moderate 候选集偏保守

### B. provider 与真实数据

- 已完成：
  - `http_json / file_json / inline_snapshot / local_json`
  - dataset cache / version pinning / replay contract
- 未完成：
  - 真实 `AKShare`
  - `efinance / baostock / yfinance / yahooquery` 真实验证
  - 真实 broker/account provider
  - 长期 drift / health 监控

### C. execution plan / 产品层

- `active / pending / approve-plan / comparison / guidance` 已完成
- 产品池仍是第一波 CN 核心桶
- `satellite / qdii / overseas` 等未完整映射
- 已发现真实缺陷：
  - 初始 execution plan 权重只覆盖 `95.24%`
  - 原因是 `satellite` 桶未映射到具体产品

### D. Claw adviser shell

- bridge-ready 已完成
- 未完成：
  - `quarterly`
  - `event`
  - `show-user`
  - 多轮 advisor shell
  - memory / cron 自动绑定
- 已发现真实问题：
  - `approve-plan` 对真实 `plan_id` 解析不稳
  - onboarding horizon phrase 解析存在误判
  - 文档承诺的 NL task surface 大于实际 bridge 能力

### E. 年内模拟与 acceptance 缺陷

- quarterly 缺 `live_portfolio` 会 blocked
- `cash_liquidity` 进入 live weights 时触发 bucket mapping 断言
- snapshot age guard 阻止真实 future-dated 年度回放
- policy/news structured signal 已进 kernel，但前台展示不完整
- Claw 自然语言验收仍不是“全功能全层覆盖”

### F. 概率解释与用户体验

- 缺“目标隐含所需年化”
- 缺“最高概率方案 vs 当前推荐方案”并列展示
- 当前推荐方案更偏低回撤，不够显式
- 用户仍容易把“目标期末总资产”误读成“收益目标”

## 主执行主线

### 主线 1：Modeling Upgrade

目标：把 `02/03/05` 从 `static gaussian` 升级到“分布可扩展、状态可解释、结果可回放”的内核。

#### Wave M1：03 原始输入扩展

交付物：

- `HistoricalReturnPanelRaw`
- `RegimeFeatureSnapshotRaw`
- `JumpEventHistoryRaw`
- `BucketProxyMappingRaw`

要求：

- 历史收益面板进入 `SnapshotBundle.market`
- 所有序列带：
  - `source_name`
  - `source_ref`
  - `version_id`
  - `lookback_months`
  - `frequency`
- regime 原料只做快照化，不做解释
- jump event 原始层只记录事实，不在 03 拟合参数

验收 gate：

- raw snapshot contract tests
- dataset version pinning / replay
- freshness / provenance / quality flags

#### Wave M2：05 分布模型校准

交付物：

- `GarchState`
- `DccState`
- `JumpOverlayState`
- `DistributionModelState`

要求：

- `05` 从 `03` 历史序列估计条件波动与动态相关
- regime 输入可以影响：
  - 波动水平
  - 相关性压力
  - jump 强度
- `05` 输出必须继续兼容现有：
  - `MarketState`
  - `MarketAssumptions`
  - `GoalSolverParams`

默认策略：

- `GARCH` 首版采用 `garch11`
- 创新分布默认 `student_t`
- `DCC` 首版采用 `dcc11`
- `JumpOverlay` 首版包含：
  - bucket jump
  - systemic jump

验收 gate：

- 单桶 `GARCH + t` 校准测试
- `DCC` 条件相关变化测试
- `JumpOverlay` 左尾加厚测试
- regime 改变时参数变化测试

#### Wave M3：02 模拟模式升级

交付物：

- `simulation_mode`
- `DistributionModelInput`
- solver explanations for mode / distribution / state

模式固定为：

- `static_gaussian`
- `garch_t`
- `garch_t_dcc`
- `garch_t_dcc_jump`

要求：

- 默认保留 `static_gaussian` 兼容
- 新模式通过 `GoalSolverParams` 显式选择
- `GoalSolverOutput.solver_notes` 必须披露：
  - 当前 mode
  - 是否使用历史数据
  - 当前 regime 是否参与
  - 是否启用 jump overlay

验收 gate：

- 同一输入下不同 `simulation_mode` 对照测试
- `static_gaussian` backward compatibility
- 不同 mode 的结果方向解释测试

#### Wave M4：概率解释升级

交付物：

- 隐含所需年化展示
- 推荐方案 vs 最高概率方案并列展示
- `important + moderate` 排序逻辑调整

要求：

- 用户能看见：
  - 目标本身隐含的所需年化
  - 当前推荐方案的达成率
  - 最高概率方案的达成率
  - 为什么两者不同

验收 gate：

- 决策卡 explanation regression
- 用户文案一致性检查
- 一年逻辑模拟口径回归

### 主线 2：Provider Real-Source Closure

目标：把“provider 架构已实现”升级到“至少核心真实公开源已验证”。

#### Wave P1：现有架构收口

确认并保留：

- `http_json`
- `file_json`
- `inline_snapshot`
- `local_json`
- dataset cache / version pinning

不重复开发：

- 已通过 fixture/local server 的 contract 测试路径

#### Wave P2：真实历史源

顺序固定：

1. `AKShare`
2. `efinance / baostock`
3. `yfinance / yahooquery`

要求：

- 先做历史序列获取
- 先通过 `market_history` adapter 把 bars 重采样成月频 return series
- 先落到 dataset cache
- 再进入 calibration / replay
- 历史数据不能绕过 version pinning

验收 gate：

- 真实 `AKShare` smoke
- 至少一条 cross-check 源 smoke
- replay consistency
- stale / drift regression

#### Wave P3：真实运行时快照

要求：

- 市场快照与 live portfolio 真实接入路径
- freshness / fail-open / fail-closed / fallback
- 手工快照仍保留为保底路径

边界：

- 券商真实 API 继续只预留接口，不作为 `v1.1` 必做验收项

### 主线 3：Execution Plan & Product Universe Closure

目标：让 execution plan 真正可执行，不再留下未映射桶和静默缺口。

任务：

- 扩产品池：
  - `satellite`
  - `qdii`
  - `overseas`
  - 必要现金类替代
- execution plan 权重必须达到 `1.0`
- unmapped bucket 不能只留 warning，必须：
  - 显式 blocked
  - 或提供降级产品方案
- orchestrator 接管 approval / supersede 状态机
- frontdesk / decision card 展示具体产品清单与替代品

验收 gate：

- execution plan weight sum regression
- active/pending/supersede state machine tests
- 产品层 acceptance flow

### 主线 4：Claw Adviser Shell Closure

目标：把当前 bridge-ready 提升到 `v1.1 adviser shell usable`。

任务：

- 扩 NL surface 到：
  - `quarterly`
  - `event`
  - `show-user`
- 修 `approve-plan` 真 `plan_id` 解析
- 修 onboarding horizon phrase 解析
- 补“为什么概率变了”
- 补“为什么建议替换 active plan”
- 文档承诺与实际 router/bridge 完全对齐

不做：

- OpenClaw memory runtime 自动注入
- cron 真运行时绑定
- 完整多轮超长 persona 编排器

验收 gate：

- 真实 `openclaw agent` NL 日志
- router/bridge contract tests
- docs drift tests

### 主线 5：Acceptance Defects from Year Simulation

目标：把这轮真实 1 年逻辑验收中抓到的问题全部闭环。

缺陷列表：

1. quarterly 缺 `live_portfolio` 时 blocked
2. `cash_liquidity` 进入 live weights 时断言失败
3. future-dated 年度回放被 snapshot age guard 卡住
4. policy/news signal 前台呈现不完整
5. execution plan 对 unmapped bucket 只 warning 不足以执行

每个缺陷必须写：

- 复现条件
- 影响层级
- 优先级
- 修复策略
- regression test

### 主线 6：Probability UX / Explanation Upgrade

目标：把“概率低但用户看不懂”改成“概率低且用户知道为什么低”。

任务：

- 显示目标隐含所需年化
- 显示目标口径：
  - 期末总资产
  - 不是收益目标
- 并列展示：
  - 当前推荐方案
  - 最高概率方案
- 显示：
  - 当前 simulation mode
  - 当前市场状态
  - 当前分布解释

验收 gate：

- 决策卡 explanation tests
- frontdesk CLI acceptance
- Claw 自然语言解释日志

## 测试与验收总规则

### 1. 数学与模型测试

- `GARCH + t` 单桶测试
- `DCC` 动态相关测试
- `JumpOverlay` 左尾测试
- `simulation_mode` 对照测试
- regime 变化 → 分布变化测试

### 2. provider 与数据测试

- fixture/local provider tests
- real-source smoke tests
- version pinning / replay
- stale / fallback / fail-open / fail-closed
- source drift regression

### 3. 工作流测试

- onboarding -> pending plan
- approve-plan -> active plan
- monthly / quarterly / event
- replace_active / keep_active / review_replace
- feedback summary
- execution plan weight sum = `1.0`

### 4. 自然语言与 Claw 测试

必须保留真实日志，不接受只留脚本：

- onboarding
- status
- monthly
- quarterly
- event
- approve-plan
- feedback
- “为什么概率变了”
- “为什么建议替换 active plan”

### 5. 版本结尾验收

每次版本结尾至少跑：

- 1 次完整 1 年逻辑模拟
- 1 次约束变化后的纠偏场景
- 1 次 Claw 自然语言用户验收
- 3 次差异化随机画像验收

### 6. 阶段纪律

- 每阶段最多 `15` loop
- 阶段内部允许切 `A/B` 波次
- 未收口不进入下一阶段
- 每完成一个大功能点，必须先过本功能点的 `3` 次随机画像验收

## 文档同步要求

`v1.1` 执行过程中，以下文档必须同步更新，禁止“代码改了但冻结文档没更新”：

- `system/02_goal_solver.md`
- `system/03_snapshot_and_ingestion.md`
- `system/05_constraint_and_calibration_v1.1_patched.md`
- `handoff/README.md`
- `handoff/CODEX_artifact_registry_2026-04-01.md`

更新原则：

- `system/` 负责正式业务语义
- `handoff/` 负责当前执行地图与验收材料
- `docs/superpowers/plans/` 只保留执行过程，不覆盖冻结规格

## 一句话判定

从现在开始：

- 看 `v1.1` 当前主线：先看本文件
- 看冻结主规格：回到 `system/02/03/05`
- 看上一轮 `v1` 已完成什么：看 `CODEX_v1_phase_reports_2026-04-02.md`
- 看当前遗留和真实验收缺陷：看本文件对应主线与 defect 列表
