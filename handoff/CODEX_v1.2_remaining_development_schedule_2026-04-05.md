# CODEX v1.2 Remaining Development Schedule

日期：2026-04-05

本 worktree 当前执行的是主仓日程文档中的 `Layer 1`：

- 主文档：[/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_remaining_development_schedule_2026-04-05.md](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.2_remaining_development_schedule_2026-04-05.md)

当前 branch 只实现并验收：

1. `Product-Aware Solver Input`
2. `产品层过渡态概率修正入模`
3. `Frontier 解空间与绑定约束诊断`
4. `Solver 内生边界放开`

Layer 1 的目标是把系统从：

- `bucket_only_no_product_proxy_adjustment`

推进到至少能够诚实输出：

- `product_proxy_adjustment_estimate`
- `product_proxy_adjusted_success_probability`
- `frontier_max_expected_annual_return`
- `candidate_families`
- `binding_constraints`
- `structural_limitations`

同时必须明确披露：

- 当前仍不是逐产品独立历史重建的 Monte Carlo
- 产品层仍属于 proxy-adjusted 过渡态
- 外部数据若 degraded/fallback，不能冒充 formal-path fresh 结果

本 branch 的 Layer 1 验收重点：

1. 36 个月中风险画像在高目标收益压力下，frontier 不再只有保守族
2. 前台能同时显示：
   - 目标隐含所需年化
   - 方案自身可实现预期年化
   - 推荐 / 最高概率 / 目标收益优先 / 回撤优先
3. `target_annual_return` 可作为正式 onboarding 输入，由 kernel 折算 `goal_amount`
4. 不再让 advisor shell 自己把“目标年化收益率”错误折算成只基于当前资产的终值
