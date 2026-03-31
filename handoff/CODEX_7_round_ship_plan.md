# CODEX 7-Round Ship Plan

更新日期: 2026-03-29

## 协作约定

- 继续使用 3 条子线:
  - `Developer`
  - `Reviewer`
  - `Tester`
- 子 agent 模型统一保持 `gpt-5.4` + `xhigh`
- 每一轮默认遵守:
  - 主线程决定切片与集成
  - `Developer` 负责实现
  - `Reviewer` 负责文档边界与架构审阅
  - `Tester` 负责 contract / smoke / regression 设计与回归

## 上线定义

这里的“上线”定义为：

- 系统本体达到稳定可运行、可测试、可审计
- 作为 OpenClaw 子项目接入 `projects/`
- 暴露成可调用的 skill
- 完成一轮 OpenClaw 侧集成测试并可内部使用

## 7 轮计划

### Round 1

主题：`07 orchestrator` 正式主入口化

目标：

- 让 07 在需要时直接驱动 `03 -> 05`
- 保持 07 对 `08 / 02 / 04 / 09` 的正式编排边界
- 补“写什么”的持久化/审计落账适配对象

验收口径：

- 07 可直接消费原始五域输入
- 07 输出包含可供基础设施层消费的持久化对象
- provenance / blocked / degraded 语义不回退

### Round 2

主题：`10 ev_engine` 正式化

目标：

- 五项评分结构继续贴近文档
- feasibility filter 规则更完整
- 推荐理由、淘汰理由与 confidence 口径收紧

### Round 3

主题：`05 calibration` 参数治理闭环

目标：

- 收紧 `ParamVersionMeta`
- 补 `updated_reason / can_be_replayed / temporary`
- 补 manual / degraded / replay 语义
- 打通 07 -> 05 的 metadata 传播

本轮已完成：

- `ParamVersionMeta` typed 化
- `update_goal_solver_params / update_runtime_optimizer_params / update_ev_params`
- prior behavior / degraded market prior reuse
- manual override / replay metadata
- constraint conflict -> degraded + manual review
- 07 在 raw-input 生成 calibration 时透传 `manual_override / replay_mode`
- 05 -> 02 / 04 语义传播 contract
- “真实 05 产物进入 07” 的 partial / degraded smoke

### Round 4

主题：`09 decision_card` 正式化

目标：

- 进一步收紧到 `DecisionCardBuildInput` 单一正式入口
- 完整表达 `FREEZE / OBSERVE / blocked / degraded / quarterly_review`
- 强化 `guardrails / execution_notes / low-confidence`

本轮已完成：

- `build_decision_card(...)` 已收成 formal input only，只接受 `DecisionCardBuildInput`
- `DecisionCardBuildInput.validate()` 已收紧:
  - quarterly 缺输入报错
  - non-blocked 卡拒绝 `blocking_reasons`
- runtime card 现在会显式输出:
  - `low_confidence`
  - `runner_up_action`
  - `evidence_highlights`
  - `review_conditions`
  - `next_steps`
- `RUNTIME_ACTION` 缺 `recommended_action / ranked_actions` 时显式报错
- blocked card 不再泄漏正常动作建议
- quarterly review card 维持主动作 `review`，同时正式消费 baseline/runtime 双证据
- 已新增 `09` 专属 direct contract，并更新最小 smoke 走 formal input path

### Round 5

主题：系统联调与阶段 1 回归硬化

目标：

- 强化 `03 -> 05 -> 08 -> 02 -> 04 -> 07 -> 09` 全链 smoke
- 增补 replay / override / provenance regression
- 清理阶段 1 剩余接口毛刺

完成口径：

- canonical demo lifecycle / report CLI 已落地
- legacy demo 入口已收口到 compatibility layer
- replay / override / provenance regression 已补齐
- full pytest 绿色

### Round 6

主题：OpenClaw 子项目接入

目标：

- 迁入 OpenClaw workspace `projects/`
- 补 `README.md / PROJECT.md / RULES.md` 等治理文件
- 设计稳定的 OpenClaw-facing skill I/O 面

### Round 7

主题：OpenClaw skill 集成测试与上线收口

目标：

- skill 调用链联通
- OpenClaw 侧集成 smoke / regression
- 运行说明、限制项、验收结论收口

## 当前执行位置

- `Round 1` 已完成
- `Round 2` 已完成
- `Round 3` 已完成
- `Round 4` 已完成
- `Round 5` 已完成
- 下一步进入 `Round 6`
- `Round 6` 起始优先级：
  1. 迁入 OpenClaw workspace `projects/`
  2. 设计稳定的 OpenClaw-facing skill I/O 面
  3. 准备 OpenClaw 侧集成 smoke / regression
