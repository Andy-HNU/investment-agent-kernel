# handoff/ 入口

从现在开始，进入 `handoff/` 目录后按这个顺序看：

1. [`CODEX_artifact_registry_2026-04-01.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_artifact_registry_2026-04-01.md)
   - 先确认哪些文档仍然 active，哪些只是历史记录或参考

2. [`CODEX_v1.2_task_map_2026-04-03.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_task_map_2026-04-03.md)
   - 当前 `v1.2` 唯一正式执行地图
   - 覆盖真实数据、产品选择/维护、账户同步与 Claw 顾问壳升级

3. [`CODEX_v1.2_patch_dynamic_data_remediation_2026-04-04.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_patch_dynamic_data_remediation_2026-04-04.md)
   - `v1.2` 动态数据修复补丁任务地图
   - 把 hardline audit 的三张清单展开成正式修复顺序、实现边界、测试门与验收标准

4. [`CODEX_dynamic_data_hardline_audit_2026-04-04.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_dynamic_data_hardline_audit_2026-04-04.md)
   - 动态数据硬红线与全仓静态化审计
   - 明确正式路径判定、数据分级标签，以及哪些内容必须实时化，哪些只能当 fallback/default，哪些必须隔离为 demo/test-only

5. [`CODEX_v1.2_patch_product_simulation_universe_explanation_2026-04-06.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_patch_product_simulation_universe_explanation_2026-04-06.md)
   - `v1.2` 后续核心补丁任务地图
   - 覆盖逐产品独立模拟、全市场产品宇宙、估值/政策新闻入 kernel、成功率解释重构

6. [`CODEX_v1.3_credibility_upgrade_task_map_2026-04-07.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.3_credibility_upgrade_task_map_2026-04-07.md)
   - `v1.3` 主任务地图
   - 覆盖：
     - `Gate 1`：结果语义、证据等级、披露判定、Evidence Bundle
     - `Gate 2`：正式计算路径删除 fallback 与结构化失败
     - `Package 3`：蒙塔卡洛 / 概率 / 收益率可信度升级
     - `Package 4`：性能优化与 Claw 闭环
   - 当前状态修正：
     - `Gate 1` / `Gate 2` 已落地
     - `Package 3` / `Package 4` 仍未闭环
     - `static_gaussian` 仅允许本地 test/demo 或 exploratory，不能作为 formal / Claw truth

7. [`CODEX_v1.3_claw_acceptance_prompts_2026-04-08.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.3_claw_acceptance_prompts_2026-04-08.md)
   - `v1.3` 的 Claw 验收 prompt 固化文档
   - 明确：
     - `snapshot-backed formal guard`
     - `degraded formal path`
     - `runtime auto path`
     三类场景的最小 prompt 与通过标准

8. [`CODEX_v1.4_daily_product_probability_engine_design_2026-04-09.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.4_daily_product_probability_engine_design_2026-04-09.md)
   - `v1.4` 主设计稿
   - 定义：
     - 日频逐产品概率引擎
     - 方案 B 作为 primary、方案 C 作为 challenger
     - 因子映射、GARCH、DCC、jump、regime 的分层建模
     - 代码抽象、性能复杂度、测试回归与无月级/桶级 fallback 约束

9. [`CODEX_v1.2_three_layer_acceptance_summary_2026-04-06.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_three_layer_acceptance_summary_2026-04-06.md)
   - `v1.2` 三层总验收汇总
   - 汇总 Layer 1 / Layer 2 / Layer 3 的通过结论、残余边界与合主干前判定

10. [`CODEX_v1.1_task_map_2026-04-02.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.1_task_map_2026-04-02.md)
   - `v1.1` 阶段主执行地图
   - 当前保留为上一版本历史参考

11. [`CODEX_kernel_first_roadmap_2026-04-01.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_kernel_first_roadmap_2026-04-01.md)
   - `v1` 阶段的历史 roadmap，保留作回溯参考

12. [`CODEX_v1_phase_reports_2026-04-02.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1_phase_reports_2026-04-02.md)
   - roadmap 五个阶段的正式结论、价值、边界与后续建议

13. [`CODEX_v1_system_test_report_2026-04-02.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1_system_test_report_2026-04-02.md)
   - 本次 v1 的统一验证证据入口

14. [`CODEX_phase5_claw_natural_language_acceptance_2026-04-02.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_phase5_claw_natural_language_acceptance_2026-04-02.md)
   - 真实 OpenClaw 自然语言输入/输出验收

15. [`CODEX_system_doc_gap_backlog.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_system_doc_gap_backlog.md)
   - 当前 kernel 任务池

16. [`CODEX_progress_status.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_progress_status.md)
   - 模块进展基线与历史完成情况

17. [`CODEX_openclaw_reuse_map_2026-03-31.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_openclaw_reuse_map_2026-03-31.md)
   - Claw / OpenClaw 接入边界与复用规则

其余 `handoff/` 文件除非在 artifact registry 中被标为 active，否则默认视为 historical / reference-only，不再直接驱动下一步实现。
