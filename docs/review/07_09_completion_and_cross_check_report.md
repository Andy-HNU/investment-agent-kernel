# 07 / 09 补充与交叉核验报告

## 1. 本次补充结果

本次新增两份实现文档：

- `07编排与工作流实现思路.md`
- `09决策卡实现思路.md`

补充原则：

- 风格对齐现有“实现思路”文档
- 术语对齐 00 / 02 / 03 / 04 / 05 / 10
- 不把编排逻辑写进 05，不把展示逻辑写进 04/10
- 尽量以现有冻结边界为准，不额外扩展新业务职责

---

## 2. 新增文档的内部自检

### 2.1 07 文档内部自检

已检查项：

- 07 只承担触发、路由、阻断、升级、回写
- 未把 Goal Solver / EV / Calibration 公式写进 07
- 明确 10 不允许被 07 直接调用，只能通过 04 间接调用
- 明确 07 向 09 传递的是 card build input，而不是直接输出 UI 文案
- 明确版本锚点：run_id / bundle_id / calibration_id / snapshot_id

结论：

- 未发现 07 文档内部自相矛盾项
- 07 的职责边界与总纲、03、05、04 的分层方向一致

### 2.2 09 文档内部自检

已检查项：

- 09 只负责展示，不负责求解/评分/编排
- 09 不自行决定 workflow，而由 07 传入 `card_type`
- 09 不补造数值、不二次评分、不伪造 blocked 场景下的动作建议
- 09 统一了基线卡、运行期动作卡、季度复审卡、阻断卡四类场景
- 09 明确保留 trace refs，支持复盘

结论：

- 未发现 09 文档内部自相矛盾项
- 09 的职责边界与 00、04、10 中“Decision Card 只做展示层”的口径一致

---

## 3. 与其他模块文档的接口接洽核验

### 3.1 07 ↔ 03

对接结论：可接。

- 03 输出 `SnapshotBundle`
- 07 决定是否因 `bundle_quality` 阻断 workflow
- 03 不自己做阻断判断，这与 07 的设计一致

### 3.2 07 ↔ 05

对接结论：可接。

- 05 输出 `CalibrationResult`
- 07 负责接收、判断 `calibration_quality`、注入 02/04
- 05 不做 workflow 决策，这与 07 的设计一致

### 3.3 07 ↔ 02

对接结论：可接。

- 07 决定何时调用完整 Goal Solver
- ONBOARDING / QUARTERLY 明确走完整求解
- MONTHLY / EVENT 默认复用既有基线
- 该划分与 04 中对 QUARTERLY 前置完整重算的要求一致

### 3.4 07 ↔ 04

对接结论：可接，但现有 04 文档中存在若干与 10 的接口口径冲突，见第 4 节。

- 07 作为 04 的唯一合法外层调用方，方向正确
- 04 只接收已准备好的基线与状态，07 的定位与之吻合

### 3.5 07 ↔ 09

对接结论：可接。

- 07 决定场景，09 负责渲染
- 09 接收统一 `DecisionCardBuildInput`
- 07 不写文案，09 不做 workflow

### 3.6 09 ↔ 02 / 04 / 10

对接结论：基本可接。

- 09 的基线配置解释卡依赖 02 输出
- 09 的运行期动作卡依赖 04/10 输出
- 09 的 blocked/degraded 卡依赖 07 输出

需要注意：

- 现有 04 与 10 对 `EVReport` 的字段口径不完全一致，09 正式落地前应先统一该对象定义

---

## 4. 现有文档中发现的冲突项

以下冲突不是 07 / 09 新增文档引入的，而是现有文档之间本就存在的接口口径不一致。为了避免后续实现出错，建议尽快修订。

### 冲突 1：04 与 10 对 `run_ev_engine()` 的签名不一致

现象：

- 04 的伪代码按 `run_ev_engine(ev_state=..., candidates=..., trigger_type=...)` 调用
- 10 的正式接口是 `run_ev_engine(candidate_actions, state)`

影响：

- 07 和 04 在真正落代码时会不知道该按哪套签名接入
- `trigger_type` 的归属不清晰，可能导致 runtime 与 ev 的接口重复定义

建议：

- 统一以 10 的正式接口为准，再由 04 补一个与 10 一致的调用示例
- 如果 `trigger_type` 确实需要传入，则应在 10 的正式接口中补上，而不是只在 04 的伪代码里出现

### 冲突 2：04 与 10 对 `EVReport` 字段口径不一致

现象：

04 的“字段对齐表”中写的是：

- `ranked_actions: list[Action]`
- `eliminated_actions: list[Action]`
- `confidence_flag: "normal" / "low"`
- `goal_solver_baseline: GoalSolverOutput`
- `goal_solver_after_recommended: GoalSolverOutput or None`

而 10 的正式定义是：

- `ranked_actions: list[EVResult]`
- `eliminated_actions: list[tuple[Action, FeasibilityResult]]`
- `confidence_flag: "high" / "medium" / "low"`
- `goal_solver_baseline: float`
- `goal_solver_after_recommended: float`

影响：

- 09 无法稳定地做字段映射
- 04 的候选贫乏逻辑会按错对象类型
- 实现层会在“结果对象到底长什么样”上反复打架

建议：

- 统一以 10 的正式 dataclass 为准
- 04 的“字段对齐表”整体改写，避免继续保留过时口径

### 冲突 3：04 的 `_apply_poverty_protocol()` 假定 `ranked_actions` 元素是 `Action`

现象：

04 的伪代码里会直接访问：

- `a.type`
- `safe_actions[0]`

但按 10 的定义，`ranked_actions` 元素其实是 `EVResult`，正确访问口径应为：

- `a.action.type`
- 如果覆盖推荐动作，也应同步覆盖 `recommended_score`、推荐理由或显式说明仅改变推荐动作口径

影响：

- 运行期贫乏降级逻辑会直接类型错位
- 09 读取推荐动作时可能看到“recommended_action 被改了，但 ranked_actions 没对应更新”的不一致状态

建议：

- 明确 poverty protocol 的修改对象是 `EVReport` 的哪几个字段
- 统一基于 `EVResult` 结构处理

### 冲突 4：04 把 `MarketState / ConstraintState / BehaviorState` 的“类型定义位置”写成 10，但 10 又声明这些对象的 canonical source 在 05

现象：

- 04 §6.1 表格中写“类型定义位置 = 10”
- 10 §3 明确写这些对象的 canonical source 以 05 为准，10 只是消费字段视图

影响：

- 实现时容易把正式类型定义误放进 10
- 会削弱 05 作为参数与状态治理层的定义权

建议：

- 04 把“类型定义位置”改为“canonical source = 05，04/10 消费其视图”
- 00 / 04 / 10 三份文档统一这一口径

### 冲突 5：04 的 poverty protocol 示例使用 `ev_report.replace(...)`，但 `EVReport` 只是 dataclass，并未说明提供 `.replace()` 方法

现象：

- 04 示例代码默认 `ev_report.replace(...)` 可用
- 但 10 的 `EVReport` 只是普通 dataclass，没有该实例方法定义

影响：

- 真正实现时会直接照抄出错

建议：

- 若采用 dataclass，示例应改为 `dataclasses.replace(ev_report, ...)`
- 或者显式声明 `EVReport` 使用具备 `.replace()` 的不可变对象实现

---

## 5. 功能完整性核验

### 5.1 07 功能完整性

已覆盖：

- 四类正式 workflow
- 触发、路由、阻断、降级、升级
- 03/05/08/02/04/09 的串联关系
- 版本锚点与追踪链
- 持久化与审计落账职责

当前未纳入 v1，但不构成功能缺失：

- 多账户并行编排
- 分布式调度
- 自动重试与故障转移

结论：

- 作为 v1 的 07 实现思路文档，功能覆盖已完整

### 5.2 09 功能完整性

已覆盖：

- 基线配置解释卡
- 运行期动作卡
- 季度复审卡
- blocked / degraded 卡
- 统一 build input
- 统一 card output
- 字段映射原则
- 低置信度 / observe / freeze 的特殊状态展示

当前未纳入 v1，但不构成功能缺失：

- 富交互前端协议
- 图表工厂
- 多端 UI 细节

结论：

- 作为 v1 的 09 实现思路文档，功能覆盖已完整

---

## 6. 对后续实现的建议修订顺序

建议按以下顺序处理，以减少 Claude / Codex 落地时的歧义：

1. **先修 04 ↔ 10 的 `EVReport` 与 `run_ev_engine` 接口口径冲突**
2. **再把 07 接入到 03 / 05 / 02 / 04 的正式调用链**
3. **最后按 09 的 `DecisionCardBuildInput` 与 `DecisionCard` 结构落展示层**

原因很简单：

- 07 依赖 04 的正式运行期输出
- 09 依赖 04/10 的正式结果对象
- 如果 04/10 的接口先不统一，07/09 即使文档写得对，代码落地时也会被旧口径拖偏

---

## 7. 最终结论

### 已完成

- 已补充 07 编排与工作流层实现文档
- 已补充 09 决策卡层实现文档
- 已完成新增文档内部自检
- 已完成与 03 / 05 / 02 / 04 / 10 的对接核验
- 已识别出现有文档中的主要冲突点

### 总结判断

- **07 / 09 两份新增文档本身是可落的，边界清楚，功能完整。**
- **真正的主要风险不在新增文档，而在 04 与 10 之间的接口口径尚未完全收口。**
- **只要先把 04 ↔ 10 的对象定义统一，07 / 09 就可以顺利接上整套系统。**
