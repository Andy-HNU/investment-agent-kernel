# Investment Agent Kernel v1.1 年度验收对话报告

日期：2026-04-03

目的：用“对话”的方式说明这套系统在一整年逻辑推进里的真实表现，而不是只给测试文件。

对应原始结果：

- [v11_year_acceptance_2026-04-03.json](/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/v1.1-delivery/handoff/logs/v11_year_acceptance_2026-04-03.json)

## 场景设定

- 初始总资产：`12 万`
- 每月投入：`6000`
- 目标：`3 年达到 45 万`
- 风险偏好：`中等`
- 初始持仓：`55% 沪深300 / 30% 债券 / 15% 黄金`
- 中途会发生：
  - 季度复盘
  - 一次 drawdown 事件
  - 一次明显的限制条件变化

## 对话式验收

验收官：先给我一句话结论，这套系统到了 `v1.1` 后最重要的变化是什么？

系统负责人：它现在不只是会给一个建议，而是能把“目标为什么难、当前用什么模型、当前计划是否该替换、具体换成什么产品”讲清楚，而且这条解释在 onboarding、quarterly、event 之间是一致的。

验收官：建档之后第一眼看到什么？

系统负责人：系统先给出一份正式 baseline。  
这次 onboarding 的关键信息是：

- `simulation_mode_used = garch_t_dcc_jump`
- 隐含所需年化：`15.09%`
- 最高概率成功率：`0.26%`
- 90% 情况最大回撤：`2.73%`

验收官：这个成功率看起来很低，系统有没有可能算错？

系统负责人：这次低不是算错，而是目标本身太激进。  
从当前资产和每月投入倒推，`3 年到 45 万` 隐含要求大约 `15.09%` 年化，这本来就不是一个低风险、中等约束下容易达成的目标。  
`v1.1` 比以前好的地方，是它不再只给你一个低概率数字，而是明确告诉你“目标隐含需要多高年化”，这样用户能看懂“到底是目标太难，还是系统太保守”。

验收官：这次给的还是抽象桶吗？

系统负责人：不是。  
execution plan 已经下钻到具体产品层，比如：

- `equity_cn -> 沪深300ETF`
- `bond_cn -> 国债ETF`
- `gold -> 黄金ETF`
- `satellite -> 创业板ETF / 科创50ETF`

同时也保留替代品，不再只给一个桶权重。

验收官：第一个月过去之后，系统会不会立刻折腾用户？

系统负责人：没有。  
第 1 个月的 monthly 结果是：

- 状态：`degraded`
- comparison：`keep_active`
- 核心含义：当前信号还不足以推翻 active plan

也就是说，系统没有为了显得“智能”就强行让用户改方案。

验收官：到了季度复盘呢？

系统负责人：季度复盘的核心是两点：

1. 这次没有再掉回 `static_gaussian`
2. 系统会把 quarterly baseline 和当前 active plan 的差异说清楚

Q1 的结果是：

- 状态：`escalated`
- `simulation_mode_used = garch_t_dcc_jump`
- 隐含所需年化从 `15.09%` 下降到 `14.02%`
- comparison 仍然是 `keep_active`

验收官：也就是说，quarterly 虽然重新评估了，但没有乱换计划？

系统负责人：对。  
这就是 `v1.1` 想达到的效果：不是更频繁地换计划，而是在“该不该换”这件事上更稳。

验收官：那 drawdown 事件发生时，系统怎么反应？

系统负责人：我在第 6 个月模拟了一次回撤。  
event 结果是：

- 状态：`escalated`
- `simulation_mode_used = garch_t_dcc_jump`
- comparison 仍然是 `keep_active`

这意味着系统能识别风险事件，但不会因为一次 drawdown 就机械地扔掉当前 active plan。

验收官：什么时候它才会真地建议换计划？

系统负责人：当用户约束真的变了。  
第 9 个月我模拟了一个更保守的限制场景，系统立刻给出：

- comparison：`replace_active`
- `changed_bucket_count = 3`
- `product_switch_count = 2`
- `max_weight_delta = 0.65`

换句话说，这不是“小修小补”，而是用户约束已经把原 active plan 的逻辑前提改掉了。

验收官：换 plan 后，系统有没有记住？

系统负责人：有。  
我在这一步执行了 `approve-plan`，然后又记录了 feedback。  
到年末，系统知道：

- 哪个是 active plan
- 哪个 plan 曾被替换
- 哪些 recommendation 被执行/跳过

这说明它已经不再是“出一张卡片就结束”的 demo。

验收官：年末再回看，这套系统到底更好了什么？

系统负责人：从用户视角，主要是 4 点：

1. 概率更诚实  
   它会告诉你目标有多难，而不是只扔一个低百分比。

2. 建议更可执行  
   它已经能落到具体 ETF / 基金 / 黄金 / 现金类产品。

3. 计划管理更像真实顾问流程  
   active / pending / approve-plan / feedback 都有了。

4. 同一用户跨 onboarding、quarterly、event 的口径更一致  
   不会再因为 workflow 变化把模型 silently 切回老模式。

验收官：还有什么没到位？

系统负责人：也有 3 个诚实边界：

1. 年度验收是逻辑回放，不是未来真实日期 live 运行
2. 真实券商/账户 provider 还没接进来
3. Claw 自然语言壳层虽然可用，但还不是完整 memory/cron 闭环

## 最终判断

如果把这套系统当成第一次正式升级版本来验收，`v1.1` 已经成立。

它最重要的进步，不是“又多了几个命令”，而是：

- 更好的投资建议：体现在 execution plan、plan comparison、产品层和建议闭环
- 更准的投资建议：体现在 advanced simulation mode、真实历史数据路径、目标难度解释和 workflow 口径一致性

它还不是终局，但已经过了“能不能拿来做真实自然语言验收”的线。
