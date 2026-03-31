# 文档修改与复核记录

## 范围
- 修改：00 / 02 / 03 / 04 / 05 / 10
- 保持原样：03_05_self_check.md

## 本轮按清单完成的主项
1. 统一 02 / 04 / 00 中旧 `03_allocation_engine.md` 到 `08_allocation_engine.md`
2. 在 02 中补充 `candidate_allocations` 与 `GoalSolverParams / MarketAssumptions` 的双上游说明
3. 在 02 中补充 `GoalSolverParams.shrinkage_factor`
4. 在 03 中收紧 `current_drawdown` 与 `cashflow_events_raw` 口径，并补校验说明
5. 在 05 中写死 `RuntimeOptimizerParams / EVParams` 的唯一来源，并补 `calibration_quality` 规则表
6. 将 04 的 `RuntimeOptimizerParams` 改为 import 使用说明，不再本地定义
7. 将 10 的 `EVParams` 改为 import 使用说明，并补 `behavior_penalty_coeff / behavior_penalty_weight`、`effective_drawdown_threshold`、`correlation_spike_alert` 的消费口径
8. 在 00 中补统一编号映射，并把 `candidate_allocations` 来源明确到 08

## 复核结论
- 已完成上述清单项对应修改。
- 未删除任何未要求删除的原有章节标题；所有原章节仍保留。
- 未修改 `03_05_self_check.md` 的原文内容。
- 除参数归属收口与编号统一外，未额外新增清单之外的新业务模块。
