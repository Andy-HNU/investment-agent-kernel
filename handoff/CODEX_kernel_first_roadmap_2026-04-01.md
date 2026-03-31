# CODEX Kernel-First Roadmap

日期：2026-04-01

## 目标

把当前仓库先收口成可稳定复用的 `decision kernel`，再补强实时抓取与历史数据底座，最后才做 `advisor agent / Claw` 接入。

这样做的原因：

- 当前 Claw 集成测试上下文成本高
- 若 kernel 仍在频繁变化，agent shell 会反复重做
- 先把内核和数据层做稳，后续接入更省 token，也更容易验收

## 执行顺序

### 第一阶段：Kernel First

优先顺序：

1. `02 goal_solver`
   - 更正式的 Monte Carlo / infeasibility 细节
   - 更深的 `solver_notes` 与结果解释口径

2. `10 ev_engine` + `04 runtime_optimizer`
   - FeasibilityFilter 全覆盖
   - 五项分量公式与量纲校准
   - 候选动作规则族、amount 预填/裁剪、mode 差异规则

3. `03 snapshot_ingestion` + `05 calibration`
   - 更完整的五域 raw snapshot typing
   - 更严格的输入校验
   - 更正式的 market calibration / correlation handling / version uniqueness

4. `07 orchestrator`
   - replay / override / provenance 深水区
   - persistence / audit 执行适配层

5. `08 allocation_engine` + `09 decision_card`
   - 候选多样性增强
   - `low_confidence / degraded / blocked / escalated` 语义硬化
   - 多方案展示解释度增强

### 第二阶段：实时抓取与历史数据

拆成两条线：

1. `03/05` 实时输入
   - provider abstraction
   - 免费公开源优先
   - fail-open / freshness / provenance / fallback 保留

2. `02/04` 历史数据底座
   - 历史价格/收益序列获取、清洗、缓存、统一口径
   - 区分“实时快照输入”和“历史回放/校准输入”

### 第三阶段：数据与 provider 测试

必须覆盖：

- provider contract
- semantic data tests
- replay / reproducibility
- stale / fallback / degraded acceptance

### 第四阶段：Advisor Agent / Claw 接入

只在前三阶段稳定后开始。

接入原则：

- 当前仓库继续作为 `decision kernel`
- Claw 作为未来 `advisor shell / runtime`
- OpenClaw skills 不复制进当前仓库
- 若修改借用来的 Claw skill，只回 patch 到原仓库

## 当前阶段判定

当前已进入：

- `第一阶段：Kernel First`

当前不进入：

- Claw runtime 集成开发
- advisor shell 正式验收
- scheduler / cron 重复开发

## 当前开发红线

1. 不为了 agent 接入而提前篡改 kernel 语义
2. 不把外部 policy/news 解释层直接混进 solver 数学结论
3. 不把 Claw 的 skill 正文复制回当前仓库
4. 不把旧 handoff 文档当成新的执行地图，除非 artifact registry 明确标为 active
