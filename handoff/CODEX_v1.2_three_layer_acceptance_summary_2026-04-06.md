# CODEX v1.2 Three-Layer Acceptance Summary

日期：2026-04-06

范围：

- Layer 1：真实数据与产品感知建模内核
- Layer 2：动态产品选择与维护内核
- Layer 3：观察持仓同步与顾问壳闭环

## 总结

`v1.2` 当前三层都已完成对应范围内的开发与验收闭环。

最终判定：

- Layer 1：`PASS`
- Layer 2：`PASS`
- Layer 3：`PASS`

当前分支：

- `feat/v1-2-layer3`

当前验收状态：

- OpenClaw 真实自然语言验收已覆盖三层关键链路
- 全量 `pytest -q` 通过
- `git diff --check` 通过

## Layer 1 结论

Layer 1 已完成的关键点：

- `target_annual_return` 正式入模，不再错误折算目标金额
- `product_probability_method`、`expected_annual_return`、frontier 诊断正式透出
- `product_proxy_adjustment_estimate` 过渡态已诚实披露
- `market_history` formal-path 的 `source_ref / audit_window / freshness_state` 可审计
- `required_annual_return`、frontier ceiling、binding constraints 可直接解释

Layer 1 验收通过的核心证据：

- `36个月尽量达到年化8%` 被正确理解为 `target_annual_return=0.08`
- `目标隐含所需年化 = 8.00%`
- `期末目标金额` 由 kernel 正式推导，不再由壳层手工乱算
- OpenClaw 可解释：
  - 当前推荐方案
  - 最高概率方案
  - 目标收益优先方案不可用原因
  - frontier 被 `required_annual_return` 卡住的结构化原因

Layer 1 边界：

- 仍不是逐产品独立 Monte Carlo 终态
- 该边界已在后续补丁中继续推进，不计入 Layer 1 失败

## Layer 2 结论

Layer 2 已完成的关键点：

- `tinyshare/Tushare` 主源正式接入
- runtime product universe 不再只依赖本地 `15` 个产品 catalog
- 股票与基金/ETF universe 可动态生成
- 股票估值链基于 observed 数据运行
- `PE<=40` 与 `30分位` 低估筛选链路可用
- policy/news 评分链可作为 kernel 可消费输入
- execution plan / maintenance policy / item-level trigger 条件可见
- execution realism 收口，账户金额闭合问题被修复

Layer 2 验收通过的核心证据：

- `product_universe_audit_summary.source_status = observed`
- `valuation_audit_summary.source_status = observed`
- `execution_realism_summary.executable = true`
- A/B/C 放宽约束诊断能显示：
  - 候选空间变化
  - 删除原因变化
  - frontier 上限与结构限制

Layer 2 边界：

- 政策/新闻原始材料仍优先由 Claw skill 提供
- 基金/ETF 估值仍不是“基金自身直接 observed PE”统一终态，而是走跟踪指数/底层映射逻辑

## Layer 3 结论

Layer 3 已完成的关键点：

- `observed_portfolio` 同步进 `user_state`
- `reconciliation_state` 持久化并可被 daily workflow 消费
- `daily_monitor` 可基于 observed/reconciliation 输出动作
- `explain_probability` 与 `explain_plan_change` 可用
- OpenClaw bridge / CLI / NLI 路由一致
- 逐产品独立模拟路径正式进入前台验收闭环

Layer 3 验收通过的核心证据：

- `observed_portfolio.snapshot_id = andy_layer3_sync_001`
- `reconciliation_state.status = drifted`
- `daily_monitor.status = monitoring_ready`
- `product_probability_method = product_independent_path`
- `product_independent_success_probability = 47.40%`
- `formal_path_status = degraded` 时会诚实解释原因，而不是静默包装成 fresh

Layer 3 边界：

- `behavior_raw = prior_default` 时 formal-path 仍可能 degraded
- 若当前无 active plan，`explain_plan_change` 对比字段为空属预期行为

## 当前残余边界

以下仍属于已知边界，但不再阻塞 `v1.2` 当前三层验收：

1. 当前虽然已进入 `product_independent_path`，但仍不是最终意义上的全市场逐产品独立 Monte Carlo 终态
2. `policy_news_source_status = unavailable` 时，产品排序不会凭空伪造信号
3. `behavior_raw` 未提供真实输入时，formal-path 会诚实标记为 degraded

## 合主干前判定

当前状态可判定为：

- 三层范围内功能闭环完成
- 数据来源、fallback、formal-path、执行真实性均已具备诚实披露
- 真实 OpenClaw 自然语言验收已覆盖关键链路
- 代码与测试状态满足合主干前条件

建议：

- 可以准备把 `feat/v1-2-layer3` 合回 `main`
- 合并后，后续新增能力应继续按
  `CODEX_v1.2_patch_product_simulation_universe_explanation_2026-04-06.md`
  管理下一轮增量开发
