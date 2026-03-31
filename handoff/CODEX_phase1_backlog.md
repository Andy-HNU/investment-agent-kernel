# CODEX Phase 1 Backlog

更新日期: 2026-03-30

## 协作方式

- 继续使用 3 条子线:
  - `Developer`
  - `Reviewer`
  - `Tester`
- 子 agent 模型保持 `gpt-5.4` + `xhigh`
- 主线程负责:
  - 冻结口径校验
  - 结果集成
  - 回归测试
  - 阶段判断

## 当前判断

阶段 1 核心闭环已经完成。下面的清单属于“阶段 1 硬化项 / 质量项”，不是主干缺口。

## Recommended Before Phase 2

### goal_solver

- 把当前 deterministic/minimal 实现推进到更接近正式 ranking / infeasibility 口径
- 补更完整的 `all_results / solver_notes / infeasibility` 语义

### ev_engine

- 把当前启发式 scorer 推进到更贴近正式五项评分
- 补更完整的 `confidence_flag / confidence_reason / eliminated_actions` 口径

### orchestrator

- 为 `OrchestratorAuditRecord` 增加 file/json/sqlite 适配层
- 如在进入 Phase 2 前还要继续硬化，可继续补 manual-review / candidate-poverty / cooldown 组合回归

说明：

- `Round 5` 已完成 replay / override / provenance regression
- canonical demo/report CLI 已完成收口

### decision_card

- 继续把 `blocked / degraded / FREEZE / OBSERVE / quarterly_review` 的展示字段做得更稳定
- 如果后面要接 UI，可把部分字符串型 `guardrails / execution_notes` 下沉成更结构化字段

### product ux / onboarding

- 参考 [`USER_PRODUCT_FEEDBACK_2026-03-30.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/USER_PRODUCT_FEEDBACK_2026-03-30.md)
- 增加正式 onboarding schema，明确区分 `user_provided / system_inferred / externally_fetched / default_assumed`
- 不再把内部 candidate ID 直接暴露给用户，改为用户可读标题 + 解释 + 证据
- 把 top-N 候选方案与关键风险收益指标展示给用户
- 为“目标不可行”补 fallback ladder / alternatives

## Nice To Have

- 增加一条更真实的 `03 -> 05 -> 08 -> 02 -> 04 -> 07 -> 09` 高层 smoke
- 增加围绕 `manual_override / high_risk / cooldown / candidate_poverty` 的更多组合 smoke
- 在 `snapshot_ingestion` 增加更多跨域一致性校验

## Frontdesk / Data Next

以下事项已记录，但当前不急于接入 OpenClaw 主工程，可按独立切片缓慢推进:

### 1. 第一个真实 provider adapter

- 在现有 `http_json` provider-config seam 之上，补第一条真实外部数据源适配
- 覆盖认证、请求签名、限流、重试、超时与 source-ref 规范
- 保持 `externally_fetched` provenance 口径稳定

### 2. 自动刷新与数据新鲜度

- 增加定时刷新 / 手动刷新 / 失败补偿 / 结果缓存
- 给前台增加 `as_of / fetched_at / stale` 透明展示
- 避免每次都依赖模型上下文重复描述数据状态

### 3. 用户执行后回填闭环

- 系统只输出具体建议动作，不直接交易
- 用户自行执行后，把“是否执行 / 实际执行时间 / 执行摘要 / 偏差原因”回填系统
- monthly / event / quarterly 要能消费这类执行反馈，避免系统把“建议已出”误当成“动作已完成”

### 4. 最终用户产品壳层

- 继续沿用 `Codex + skill + SQLite + frontdesk CLI` 路线
- 补更稳定的建档、复查、结果解释与错误恢复
- 保持 fixed-flow，不把流程自由度交给模型即兴发挥

### Scope Guardrail

- `不做自动交易 / 不做代下单 / 不做 broker execution`
- 当前系统定位仍然是“给出具体建议动作 + 接收用户执行反馈”的决策辅助层
- 如后续要讨论 broker 对接，也只能作为数据回传或对账输入，不进入自动执行范围

## Phase 2

- 迁入 OpenClaw workspace 作为子项目
- 设计并落地 skill 输入/输出协议
- 集成 OpenClaw skill 调用链
- 在 OpenClaw 环境里完成二次测试
