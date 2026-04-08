# CODEX Artifact Registry

日期：2026-04-01

目的：

- 整理当前仓库各目录文档的权威级别
- 标出哪些仍然 active，哪些只保留为历史记录或参考
- 避免后续开发时 `handoff / system / docs/legacy / docs/review` 相互冲突

## 权威级别总规则

优先级从高到低如下：

1. `system/`
   - 冻结主规格
   - 模块职责、输入输出、正式语义以此为准

2. `handoff/` 中被标记为 `active` 的执行文档
   - 当前阶段路线、差异 backlog、验收结论、Claw 接入边界

3. `docs/review/`
   - 审核/交叉核验记录
   - 用于解释“为何当前实现是这样”，不是下一步开发主线

4. `docs/tdd/`
   - 测试策略与门禁政策
   - 约束测试方式，但不定义业务语义

5. `docs/legacy/`
   - 早期思路与背景参考
   - 允许启发设计，但不得覆盖 `system/` 和 active handoff

## 当前 Active 文档

### 入口索引

- `handoff/README.md`
  - `handoff/` 的统一阅读入口
  - 用于快速定位 active / historical / reference-only 文档

### 主执行地图

- `handoff/CODEX_v1.2_task_map_2026-04-03.md`
  - 当前 `v1.2` 唯一正式执行地图
  - 覆盖真实源历史数据、产品选择/维护、观察持仓同步与 Claw 顾问壳升级

- `handoff/CODEX_v1.2_patch_dynamic_data_remediation_2026-04-04.md`
  - `v1.2` 动态数据修复补丁任务地图
  - 把 hardline audit 的三张清单展开成：
    - 正式修复顺序
    - 动态数据替换策略
    - 测试门与验收标准

- `handoff/CODEX_dynamic_data_hardline_audit_2026-04-04.md`
  - 动态数据硬红线与静态化审计
  - 定义后续开发的仓库级约束：
    - 动态数据不得写死到正式路径
    - fallback/default 不得伪装成真实来源
    - demo/test-only 内容必须与正式路径隔离
    - 正式路径判定与数据状态标签必须可审计

- `handoff/CODEX_v1.2_patch_product_simulation_universe_explanation_2026-04-06.md`
  - `v1.2` 后续核心补丁任务地图
  - 覆盖：
    - 逐产品独立模拟
    - 全市场产品宇宙
    - 估值链 / 政策新闻链入 kernel
    - 成功率解释重构

- `handoff/CODEX_v1.3_credibility_upgrade_task_map_2026-04-07.md`
  - `v1.3` 主任务地图
  - 覆盖：
    - `Gate 1`：结果类别、证据等级、披露判定与 Evidence Bundle
    - `Gate 2`：正式计算路径删除 fallback 与结构化失败
    - `Package 3`：蒙塔卡洛 / 校准 / 收益率与成功率可信度升级
    - `Package 4`：性能优化、状态复用与 Claw 闭环
  - 当前作为 `v1.3` 直接执行文档
  - 当前状态修正：
    - `Gate 1` / `Gate 2` 已落地
    - `Package 3` / `Package 4` 尚未闭环
    - `static_gaussian` 仅允许 test/demo 或 exploratory；不得作为 formal / Claw truth

- `handoff/CODEX_v1.3_claw_acceptance_prompts_2026-04-08.md`
  - `v1.3` 的 Claw 验收 prompt 固化文档
  - 明确：
    - `snapshot-backed formal guard`
    - `degraded formal path`
    - `runtime auto path`
    的最小 prompt、通过标准与结果解释

- `handoff/CODEX_v1.2_three_layer_acceptance_summary_2026-04-06.md`
  - `v1.2` 三层总验收汇总
  - 汇总：
    - Layer 1 / Layer 2 / Layer 3 的通过结论
    - 当前残余边界
    - 合主干前判定

- `handoff/CODEX_v1.1_task_map_2026-04-02.md`
  - `v1.1` 阶段正式执行地图
  - 当前保留作上一版本历史执行参考

- `handoff/CODEX_kernel_first_roadmap_2026-04-01.md`
  - `v1` 阶段的历史正式开发顺序
  - 当前继续作为背景路线保留，不再单独驱动 `v1.2`

### v1 阶段结论与验收

- `handoff/CODEX_v1_phase_reports_2026-04-02.md`
  - roadmap 五个阶段的正式汇总报告
  - 面向非技术读者说明“做成了什么、没做什么、为什么”

- `handoff/CODEX_v1_system_test_report_2026-04-02.md`
  - 本次 v1 的统一测试与验证证据入口

- `handoff/CODEX_phase5_claw_natural_language_acceptance_2026-04-02.md`
  - Phase 5 的真实 OpenClaw 自然语言输入/输出验收记录

### 当前进展与差异

- `handoff/CODEX_progress_status.md`
  - 当前主干完成状态与模块阶段总结

- `handoff/CODEX_system_doc_gap_backlog.md`
  - `system/` 文档 vs 当前实现差异 backlog
  - 是当前 kernel 开发的直接任务池

- `handoff/CODEX_acceptance_audit_2026-03-31.md`
  - 用户验收层发现的问题与修复后的残余边界

### Claw / OpenClaw 接入边界

- `handoff/CODEX_openclaw_reuse_map_2026-03-31.md`
  - 当前仓库与 OpenClaw 的 reuse boundary
  - 明确 no-copy / patch-back 原则

## 当前 Historical / Closed 文档

以下文档保留，但默认视为历史记录，不再作为新的执行顺序来源：

- `handoff/CODEX_p0_repair_topology_2026-03-31.md`
- `handoff/CODEX_p1_repair_topology_2026-03-31.md`
- `handoff/CODEX_7_round_ship_plan.md`
- `handoff/CODEX_phase1_backlog.md`
- `handoff/CODEX_first_round_prompt.md`

使用方式：

- 可用于回溯当时为什么这么做
- 不可覆盖当前 roadmap 和 active backlog

## 当前 Reference-Only 文档

以下文档保留作辅助背景，不直接驱动下一步实现：

- `handoff/FREEZE_AND_CONFLICT_NOTES.md`
- `handoff/PRE_HANDOFF_CHECKLIST.md`
- `handoff/REPO_SKELETON_GUIDE.md`
- `handoff/USER_PRODUCT_FEEDBACK_2026-03-30.md`

## docs/ 目录的使用约束

### `docs/legacy/`

作用：

- 保存最早的系统愿景、案例、设计直觉、产品化原始思路

边界：

- 只作参考
- 若和 `system/` 冲突，永远以 `system/` 为准
- 若和当前 `handoff` active roadmap 冲突，以 roadmap 为准

### `docs/archive/`

作用：

- 保存归档追踪、源包清单、命名标准化等辅助材料

边界：

- 只作 trace/reference
- 不定义当前业务语义
- 不覆盖 `system/`、active `handoff/` 或测试门禁

### `docs/review/`

作用：

- 保存阶段性交叉核验、自检、修改评审

边界：

- 解释历史，不定义下一步路线

### `docs/tdd/`

作用：

- 保存测试与 CI gate 策略

边界：

- 约束“怎么测”
- 不决定“做什么”

## 当前避免冲突的操作规则

1. 若新增开发路线，必须优先更新 `handoff/CODEX_kernel_first_roadmap_2026-04-01.md`
1.1 若进入新版本主线，必须新增对应任务地图并登记到本 registry
2. 若发现模块语义差异，优先更新 `handoff/CODEX_system_doc_gap_backlog.md`
3. 若发现 Claw / OpenClaw 接入边界变化，优先更新 `handoff/CODEX_openclaw_reuse_map_2026-03-31.md`
4. 不再新增新的“总路线 handoff”而不登记到本 registry
5. 若旧文档已被当前路线替代，可保留，但必须默认视为 historical
6. 若新增 active handoff 文档，需同步更新 `handoff/README.md` 与本 registry
7. 若发现“本应动态获取/动态计算”的内容被写死进正式路径，必须同步更新 `handoff/CODEX_dynamic_data_hardline_audit_2026-04-04.md`

## 当前一句话判定

现在开始：

- 看模块语义：先看 `system/`
- 看当前开发顺序：先看 `CODEX_v1.2_task_map_2026-04-03.md`
- 看 `v1.2` 动态数据修复补丁：看 `CODEX_v1.2_patch_dynamic_data_remediation_2026-04-04.md`
- 看动态数据硬边界：看 `CODEX_dynamic_data_hardline_audit_2026-04-04.md`
- 看 `v1.3` 可信度升级主线：看 `CODEX_v1.3_credibility_upgrade_task_map_2026-04-07.md`
- 看上一版本执行地图：再看 `CODEX_v1.1_task_map_2026-04-02.md`
- 看 `v1` 历史路线：再看 `CODEX_kernel_first_roadmap_2026-04-01.md`
- 看 v1 阶段结论：看 `CODEX_v1_phase_reports_2026-04-02.md`
- 看验证证据：看 `CODEX_v1_system_test_report_2026-04-02.md`
- 看当前任务池：先看 `CODEX_system_doc_gap_backlog.md`
- 看 Claw 接入边界：先看 `CODEX_openclaw_reuse_map_2026-03-31.md`
- 看早期思路：最后才看 `docs/legacy/`
