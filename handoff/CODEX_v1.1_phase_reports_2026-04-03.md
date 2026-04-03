# Investment Agent Kernel v1.1 Phase Reports

日期：2026-04-03

读者：产品 owner、项目负责人、后续接手机器人/工程师、非技术验收人

## 总结

`v1.1` 这轮不是重写系统，而是在 `v1` 基线之上把 6 条主线真正拉通：

- 目标达成率模型不再只停在静态高斯世界
- 真实公开源 provider 不再只停在 fixture 和架构图
- execution plan 不再停在核心桶，已经覆盖 `satellite / qdii / overseas / cash`
- Claw shell 不再只到 `bridge-ready`，而是把关键工作流和解释链打到了自然语言任务面
- 一年逻辑验收从“只能手动猜”提升到“有正式脚本和结果文件”
- 概率解释从“只给一个百分比”提升到“解释目标难度、模式、市场状态和最高概率方案”

这次交付的关键价值不是“看起来功能多了”，而是两件事：

1. 投资建议更可执行
2. 目标达成率口径更诚实、更稳定、更接近真实市场假设

仍然刻意不做的，是自动交易、真实券商 API 下单、多租户商用 SLA、以及把 OpenClaw memory/cron runtime 复制进本仓库。

## 主线 1. Modeling Upgrade

### 实现了什么

- `03 -> 05 -> 02` 的分层建模链已经成型：
  - 历史收益面板
  - regime feature snapshot
  - jump history
  - bucket proxy mapping
- `02 goal_solver` 现在支持并披露：
  - `static_gaussian`
  - `garch_t`
  - `garch_t_dcc`
  - `garch_t_dcc_jump`
- `simulation_mode` 不再只报一个值，而是区分：
  - `simulation_mode_requested`
  - `simulation_mode_used`
  - `simulation_mode_auto_selected`
- follow-up workflow 不再把 advanced distribution context 静默冲掉：
  - quarterly / event 会沿用最近基线的历史收益、regime 和 jump 上下文
  - 不再因为 workflow 切换而悄悄退回 `static_gaussian`

### 用户能感受到的提升

- 目标达成率不再只由“一个静态均值和波动”决定
- 同一个用户在 onboarding、quarterly、event 之间，概率口径保持一致，不会因为流程切换出现“看起来莫名其妙变了”
- 系统现在能告诉用户：
  - 目标本身隐含所需年化是多少
  - 当前用的是什么 simulation mode
  - 为什么最高概率方案和当前推荐方案不一样

### 还没完全做到的地方

- 当前 `GARCH / DCC / Jump` 仍是第一代 kernel 实现，不是完整机构级风险引擎
- 分布形态已经可切换，但参数估计仍保留保守 heuristic
- 没有把更复杂的 regime transition / hidden-state 模型也一并拉进来

### 为什么先做到这里

- `v1.1` 的核心是把概率口径“做对、讲清、跑稳”
- 如果不先把 requested/used mode 讲明白，不先把 quarterly/event 的 distribution context 保住，后面再加更复杂模型也只会继续制造解释债务

### 下一步建议

- 继续强化参数估计而不是再加新 mode 名字
- 把 market regime 对 distribution state 的影响从“override 为主”推进到“估计 + override 并存”
- 补更严格的校准回放与对照测试

## 主线 2. Provider Real-Source Closure

### 实现了什么

- timeseries provider 已经从“规划”变成真实代码：
  - `akshare`
  - `efinance`
  - `baostock`
  - `yfinance`
- `market_history` adapter 已能把真实 bars 变成月频 return series 并进入 solver
- dataset cache / version pinning / replay 已经跟真实源打通
- 本轮真实 smoke 结果是：
  - `AKShare` live smoke：通过
  - `BaoStock` live smoke：通过
  - `market_history` live smoke：通过
  - `yfinance` live smoke：本次因返回空行被 `skip`

### 用户/系统价值

- 目标达成率开始有真实历史序列支撑，而不是只靠默认市场快照
- provider 的成功/失败/陈旧/降级都有正式语义
- 回放时能明确知道：当时用的是哪一版数据、来自哪个 provider

### 还没完全做到的地方

- `efinance / yfinance / yahooquery` 还不是“长期稳定保证通过”的状态
- 真实券商/账户 provider 仍只保留接口边界
- 还没有 daemon 级 provider health monitoring

### 为什么先做到这里

- `v1.1` 先要把“真实公开源闭环”做出来，而不是一步跳到完整数据平台
- 对单用户开源系统来说，真实公开源 smoke + cache/replay 比空喊“商用级接入”更有价值

### 下一步建议

- 增加 provider drift / health snapshot
- 为高价值源做定期回归
- 再决定是否引入更重的外部源和账户接入

## 主线 3. Execution Plan & Product Universe Closure

### 实现了什么

- 产品层不再只有 `equity_cn / bond_cn / gold / cash`
- 已加入：
  - `satellite`
  - `qdii_global`
  - `overseas`
  - `cash_liquidity`
- execution plan 现在要求：
  - 要么 `coverage_ratio = 1.0`
  - 要么显式 `blocked / degraded`
  - 不再允许“静默丢失一个桶”
- active / pending / approve-plan / comparison / guidance 已经和产品计划层打通

### 用户能感受到的提升

- 不只是看到“该配什么桶”，而是能看到：
  - 具体 ETF / 基金 / 黄金 / 现金类方案
  - 替代产品
  - 这次是否该替换当前 active plan
- 当用户限制条件变化时，系统能给出真正的 replace/keep 结论，而不是只换个名字

### 还没完全做到的地方

- 产品池还是第一版，不是全市场 universe
- 账户税务、交易成本、账户封装差异还没有进入产品层
- orchestrator 对 plan approval/supersede 的统一状态机还可继续上提

### 为什么先做到这里

- 用户看不到具体产品，前台体验就永远像研究 demo
- `v1.1` 的目标是让建议至少“可以执行”，不是先把产品池扩到无限大

### 下一步建议

- 扩产品池
- 引入更细的 suitability / account wrapper 规则
- 把 approval/supersede 完全并到 orchestrator

## 主线 4. Claw Adviser Shell Closure

### 实现了什么

- OpenClaw bridge 现在已经覆盖 10 个 intent：
  - `onboarding`
  - `status`
  - `show_user`
  - `monthly`
  - `quarterly`
  - `event`
  - `approve_plan`
  - `feedback`
  - `explain_probability`
  - `explain_plan_change`
- `approve_plan` 支持：
  - 只给 `account_profile_id`
  - 只给 `plan_version`
  - 自动 fallback 到唯一 pending plan
- `feedback` 支持：
  - 显式 `run_id`
  - 缺失 `run_id` 时自动 fallback 到 latest run
- bridge contract 和 tool contract 现在显式区分：
  - direct tool 支持什么
  - NL bridge 当前真能吃什么

### 用户/Claw 运行时价值

- 自然语言已经不只是“讲讲说明书”，而是真能触发前台工作流
- 对用户来说，解释链已经像 advisor shell，而不是“再让我去查一遍 JSON”
- 对 Claw runtime 来说，doc/runtime drift 已经明显收紧

### 还没完全做到的地方

- 还没有把 memory / cron runtime 自动挂进来
- 还不是完整的多轮长期 advisor persona
- richer follow-up inputs（如 `profile_json`、provider override）仍主要走 direct tool/CLI，不走 NL bridge

### 为什么先做到这里

- v1.1 的重点是把“常用关键动作”先做实
- 如果桥接层连 approve / feedback / quarterly / event 都不稳，继续做多轮 persona 只会把问题藏起来

### 下一步建议

- 补 memory / cron 绑定
- 扩 NL bridge 对 richer overrides 的解析
- 做更长链路的多轮 adviser conversation acceptance

## 主线 5. Acceptance Defects from Year Simulation

### 实现了什么

- 年度逻辑验收现在有正式脚本：
  - `scripts/run_v11_year_acceptance.py`
- 本轮把关键 defect 真修掉了：
  - quarterly / event 不再掉回 `static_gaussian`
  - quarterly 的市场输入 domain 不再把沿用的 baseline market context 误报成“默认市场假设”，刷新建议也不再错误提示“先去配置 provider”
  - 年度脚本里已经能把 execution plan approval / feedback / restrictions change 串起来

### 真实验收结论

在这轮 1 年逻辑模拟里：

- onboarding 就明确给出：
  - `simulation_mode_used = garch_t_dcc_jump`
  - 隐含所需年化 `15.09%`
  - 最高概率只有 `0.26%`
- Q1 和 drawdown event 都没有乱动 active plan
- Q2 用户转成“更保守限制”后，系统明确给出 `replace_active`
- 到年末，plan comparison 和 feedback 闭环仍然保持一致

### 还没完全做到的地方

- 这轮“1 年模拟”是逻辑回放，不是未来真实日期环境中的在线运行
- future-dated live snapshot 仍然受 age guard 保护；验收脚本通过 `allow_historical_replay=True` 进入回放模式

### 为什么先做到这里

- 先把年度逻辑链路跑通，比空谈“以后能做年度复盘”更重要
- 对用户来说，最重要的是系统在 12 步里是否保持语义一致，而不是日期是否真穿越

### 下一步建议

- 如果后续要做更真实的时序回放，再把 age-guard / replay-mode 继续细化
- 增加更多约束变化场景和极端市场场景

## 主线 6. Probability UX / Explanation Upgrade

### 实现了什么

- 决策结果里已经能展示：
  - 隐含所需年化
  - 当前推荐方案达成率
  - 最高概率方案达成率
  - simulation mode
  - market regime / volatility regime
- OpenClaw bridge 新增：
  - `explain_probability`
  - `explain_plan_change`
- 前台解释不再只说“系统推荐”，而是能说：
  - 目标为什么难
  - 当前模式是什么
  - 为什么推荐方案不是最高概率方案

### 用户能感受到的提升

- 目标达成率低时，用户不再只能猜“系统是不是算错了”
- 当系统推荐更稳但概率稍低的方案时，用户能直接看到“最高概率方案”作为对照
- 这让“建议更好”与“建议更准”第一次被分开解释了

### 还没完全做到的地方

- 还没有完整的对话式教育层，把这些解释拆成更自然的多轮问答
- 当前 explanation 仍主要由 decision card / bridge 构造，不是独立的 narrative engine

### 为什么先做到这里

- 先把核心口径讲清，优先级高于追求更花哨的前台说法
- 如果连“当前概率为什么是这个数”都讲不清，其他体验都是表面工作

### 下一步建议

- 补更自然的 explanation templates
- 把“目标太激进”与“约束太强”拆成更清晰的前台话术
- 结合后续 Claw 多轮壳层做连续解释

## 最终判断

`v1.1` 已经达到“第一次正式升级版本”的交付线：

- 建议更可执行了
- 概率口径更诚实了
- 真实数据路径更像真系统了
- Claw 自然语言层不再只会说说明书

但它仍然不是最终体。最重要的残余边界有 3 条：

1. 真实券商/账户 provider 仍未接入
2. `yfinance` 这类可选 live 源仍存在环境性不稳定
3. Claw shell 还没有 memory/cron 自动闭环

如果接下来继续做 `v1.2`，最值得的方向不是再堆功能，而是：

- 继续提高真实数据稳定性
- 继续提高概率模型可解释性与参数可靠性
- 继续把 adviser shell 做成长期对话系统
