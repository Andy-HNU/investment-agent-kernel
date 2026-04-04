# CODEX v1.2 Patch Task Map: Target-Risk Frontier

日期：2026-04-04

读者：开发、审阅、测试、产品 owner、验收人员

## 定位

这不是 `v1.3`，也不是单独版本线。

这是挂在 `v1.2` 之上的补丁任务书，专门解决最新 Claw 自然语言验收里暴露出的一个核心能力缺口：

- 系统能给概率
- 系统能给推荐方案
- 但系统还不能稳定地回答：
  - 如果用户坚持目标收益率，回撤会是多少
  - 如果用户坚持回撤约束，可实现收益率/终值是多少
  - 推荐方案、最高概率方案、收益目标优先方案、回撤约束优先方案之间到底怎么权衡

一句话说，这个补丁要把系统从“给一个方案”升级成“给一条收益-风险前沿上的可解释选择面”。

## 要解决的问题

当前 `v1.2` 已具备：

- `implied_required_annual_return`
- `success_probability`
- `bucket_success_probability`
- `product_adjusted_success_probability`
- `recommended vs highest_probability`

但还缺少正式产品能力：

1. `收益目标优先方案`
2. `回撤约束优先方案`
3. `折中方案`
4. 双向反推：
   - 给定收益目标，反推所需风险/回撤
   - 给定回撤上限，反推可实现收益/目标金额
5. 前台与 Claw 对这些方案的正式解释

没有这层，用户看到“成功率 19.58%”时，无法判断究竟是：

- 目标太激进
- 当前回撤约束太紧
- 组合过于防守
- 还是系统推荐逻辑偏保守

## 目标

补丁完成后，系统必须能在同一轮输出里稳定给出：

1. `当前推荐方案`
2. `最高概率方案`
3. `收益目标优先方案`
4. `回撤约束优先方案`
5. `折中方案`

并且对每个方案都明确展示：

- 目标达成率
- 产品修正后达成率
- 隐含所需年化
- 90% 情景最大回撤
- 主要资产桶/产品结构
- 推荐原因/不推荐原因

## 非目标

本补丁不做：

- 新增版本线
- 改写 `v1.2` 的真实数据边界
- 新增真实券商 API
- 自动下单
- Claw memory/cron runtime 绑定

## 功能设计

### 1. Frontier 方案组

正式新增一个前台/顾问可消费的方案组：

- `recommended_plan`
- `highest_probability_plan`
- `target_return_priority_plan`
- `drawdown_priority_plan`
- `balanced_tradeoff_plan`

其中：

- `recommended_plan`
  - 保持当前排序逻辑的正式推荐
- `highest_probability_plan`
  - 候选中纯成功率最高
- `target_return_priority_plan`
  - 优先贴近用户目标收益/目标终值
  - 明示因此承担的回撤代价
- `drawdown_priority_plan`
  - 优先满足回撤边界
  - 明示因此放弃的收益/达成率
- `balanced_tradeoff_plan`
  - 介于收益目标和风险约束之间的折中点

### 2. 双向反推能力

补丁必须提供两条正式反推：

#### 2.1 给定收益目标，反推风险

输入：

- 目标年化/目标终值
- 期限
- 月投入
- 约束条件

输出：

- 达成该目标所需的风险预算区间
- 预期 90% 回撤
- 卫星预算/核心预算变化
- 若无法在当前约束下实现，必须明确说明

#### 2.2 给定回撤约束，反推收益

输入：

- 最大可接受回撤
- 期限
- 月投入
- 约束条件

输出：

- 在该回撤约束下可实现的合理收益率区间
- 对应可实现目标金额区间
- 当前用户目标与该区间的差距

### 3. 产品层协同

本补丁不允许只给桶级 frontier。

每个 frontier 方案必须下钻到：

- 资产桶预算
- 产品级结构
- 卫星预算
- 现金留存
- 若有季度执行策略，应说明产品维护差异

### 4. 用户可见解释

前台和 Claw 都必须能解释：

- 为什么推荐方案不是最高概率方案
- 为什么 8% 目标优先方案的回撤更高
- 为什么回撤优先方案的达成率/收益更低
- 当前用户该优先改哪个杠杆：
  - 目标
  - 风险
  - 期限
  - 月投入

## 数据结构

### 1. FrontierScenario

```python
@dataclass
class FrontierScenario:
    scenario_id: str
    scenario_type: Literal[
        "recommended",
        "highest_probability",
        "target_return_priority",
        "drawdown_priority",
        "balanced_tradeoff",
    ]
    allocation_name: str
    bucket_success_probability: float
    product_adjusted_success_probability: float
    implied_required_annual_return: float | None
    expected_terminal_value: float
    max_drawdown_90pct: float
    target_return_gap: float | None
    drawdown_gap: float | None
    rationale: list[str]
    execution_plan_summary: dict[str, Any]
```

### 2. FrontierAnalysis

```python
@dataclass
class FrontierAnalysis:
    recommended: FrontierScenario
    highest_probability: FrontierScenario
    target_return_priority: FrontierScenario | None
    drawdown_priority: FrontierScenario | None
    balanced_tradeoff: FrontierScenario | None
    frontier_notes: list[str]
    blocker_flags: list[str]
```

### 3. New Decision Card Surface

决策卡新增：

- `frontier_analysis`
- `why_not_highest_probability`
- `why_not_target_return_priority`
- `why_not_drawdown_priority`

## 实现方案

### Wave P1：Kernel Frontier Builder

目标：先把 kernel 内部的收益-风险前沿能力做出来。

文件：

- 修改：`src/goal_solver/engine.py`
- 修改：`src/goal_solver/types.py`
- 新增或修改：`src/frontdesk/service.py`
- 测试：`tests/contract/test_02_goal_solver_contract.py`

交付：

- 从现有候选结果中生成 5 类 frontier 场景
- 若场景不存在，必须返回 `None + 明确理由`
- 反推逻辑必须使用真实当前约束，不允许硬编码

### Wave P2：Decision Card / Frontdesk 展示

目标：把 frontier 结果正式展示给用户。

文件：

- 修改：`src/decision_card/builder.py`
- 修改：`src/decision_card/types.py`
- 修改：`src/frontdesk/cli.py`
- 测试：`tests/contract/test_09_decision_card_contract.py`

交付：

- 并排展示推荐方案与最高概率方案
- 在需要时展示收益目标优先和回撤优先方案
- 若两者一致，要明确说明“一致的原因”

### Wave P3：Claw Explainability Closure

目标：让 Claw 可以直接回答用户这类追问。

文件：

- 修改：`src/agent/nli_router.py`
- 修改：`src/integration/openclaw/bridge.py`
- 视情况修改：`src/agent/explainability.py`
- 测试：`tests/agent/test_19_claw_shell_contract.py`

交付：

- 新增或强化 explain intents：
  - `explain_probability`
  - `explain_plan_change`
  - `explain_execution_policy`
  - 新增 `explain_target_risk_tradeoff` 或等价路径
- 能回答：
  - “如果我坚持 8% 年化，回撤会是多少”
  - “如果我坚持回撤不超过 X，收益率能到多少”

### Wave P4：Sanity Guardrails

目标：把明显不合理的建议拦掉。

文件：

- 修改：`src/frontdesk/service.py`
- 修改：`src/decision_card/builder.py`
- 测试：`tests/contract/test_12_frontdesk_regression.py`

最低要求：

- 如果 `当前资产 + 确定性投入 >= 目标金额`
  - 不允许再把“延长期限/增加投入”作为有效提升建议
- 应改成提示：
  - 目标过低
  - 或目标口径应调整为 `incremental_gain`

## 测试计划

### 1. Contract Tests

必须新增或扩充：

- 推荐方案与最高概率方案不一致时的解释
- 推荐方案与最高概率方案一致时的解释
- `target_return_priority_plan` 存在/不存在的边界
- `drawdown_priority_plan` 存在/不存在的边界
- sanity guard：本金和确定性投入已覆盖目标时，不得输出伪优化建议

### 2. Product-Level Regression

必须验证：

- frontier 方案不是只换名字
- 每个 frontier 方案都有产品级结构
- 现金预算和卫星预算能跟方案一起变

### 3. Natural-Language Acceptance

至少覆盖这 4 类真实追问：

1. “如果我要 8% 年化，你给我的回撤是多少？”
2. “如果我坚持回撤不超过 8%，能做到多少收益？”
3. “为什么你推荐的不是最高概率方案？”
4. “如果推荐方案和最高概率方案是同一个，为什么是同一个？”

### 4. Forward Validation Impact Check

本补丁不要求重写前瞻验证框架，但必须检查：

- patch 不得破坏现有前瞻验证输出结构
- frontier 场景可被前瞻验证报告引用

## 验收标准

通过标准：

1. 用户可以在单轮输出里看到至少 3 类有信息差异的方案
2. 用户可以清楚知道：
   - 收益目标优先时要承担什么回撤
   - 回撤优先时要放弃多少收益/达成率
3. 系统不再只给单一低成功率数字而不解释
4. Claw 可以用中文稳定回答相关追问
5. 明显不合理的建议被拦截

不通过标准：

- 方案只是重命名，没有真实差异
- 仍然只在桶级说话，不下钻到产品层
- 无法回答“坚持 8% 年化会怎样”
- 无法回答“坚持回撤约束会怎样”

## 预估工作量

这是一个 `v1.2 patch`，不是新版本重构。

预计：

- 开发：中等偏大
- 推荐节奏：`2-3` 轮
- 若有 `10` 人团队：
  - `1` 总控
  - `3` kernel/frontier
  - `2` frontdesk/decision card
  - `1` Claw shell
  - `1` 数据验证
  - `1` 测试
  - `1` 独立审阅

## 一句话结论

这个补丁不是“再加几个字段”，而是把系统补成真正能回答：

- `你想要的收益，需要承担多少风险`
- `你能承受的风险，换来多少收益`

没有这层，用户看到达成率时仍然缺少决策抓手。
