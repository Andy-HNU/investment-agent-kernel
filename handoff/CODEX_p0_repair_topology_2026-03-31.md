# P0 修复拓扑与 Subagent 调度

日期：2026-03-31

目标：
- 修复用户不可接受的 `P0` 问题
- 引入规格审阅与随机画像验收
- 把“能跑”升级成“对用户语义正确、对文档承诺正确”

## 拓扑总览

### 主链优先级

1. `P0-1` Goal Solver 概率语义修复
2. `P0-5` 生产主链去 demo 化
3. `P0-3` 自然语言限制条件进入约束层
4. `P0-4` 自然语言持仓解析
5. `P0-2` 目标口径与前台文案修复
6. `P0-6` acceptance / spec-conformance 测试补齐

### 依赖关系

- `P0-1` 与 `P0-5` 可并行
- `P0-3` 与 `P0-4` 共用 parser，但可先独立实现 parser，再由主线程接入
- `P0-2` 需要消费 `P0-1` 的输出语义与 `P0-5` 的 defaults 语义
- `P0-6` 需要等前三类修复基本接入后再做最终随机画像验收

## Subagent 分工

### Worker A: Goal Solver Core

职责：
- 把伪 Monte Carlo 改成真实路径级模拟
- 确保 `n_paths / n_paths_lightweight / seed` 真正生效
- 补语义级测试，不只保留参数透传测试

写集：
- `src/goal_solver/*`
- `tests/contract/test_02*`
- 相关 goal solver smoke tests

验收标准：
- `_run_monte_carlo()` 不再吞掉 `n_paths / seed`
- 轻量版仍走 `n_paths_lightweight`
- 测试能抓住未来再次退化成启发式公式

### Worker B: Natural-Language Profile Parser

职责：
- 新增 canonical profile parser
- 把自然语言持仓/限制条件解析为结构化字段
- 输出置信度、解析说明、无法解析标记

写集：
- 新增 parser 模块
- parser 对应 tests

覆盖语句最低要求：
- `纯黄金`
- `全现金`
- `股债六四`
- `80%纳指 20%货基`
- `不碰股票`
- `不碰科技`
- `只能黄金和现金`
- `不买QDII`

验收标准：
- 可解析时给出结构化结果
- 不可解析时不能默默回退成默认组合

### Worker C: Production Main-Chain Cleanup

职责：
- 切断 production 主链对 `build_demo_*` 的直接依赖
- 改成明确的 product defaults / placeholder 输入模块
- 修正前台目标口径和模型估计提示

写集：
- `src/shared/onboarding.py`
- `src/frontdesk/service.py`
- `src/frontdesk/cli.py`
- `src/decision_card/builder.py`
- 必要的新 defaults 模块
- 相关 frontdesk / decision card tests

验收标准：
- production entrypoint 中不再直接 import `build_demo_*`
- 用户可见文案不再混淆“目标金额 / 收益 / 期末总资产”
- 对默认假设和模型估计有明确标识

### Worker D: Acceptance / Randomized Validation

职责：
- 新增自然语言输入验收
- 随机生成差异化画像
- 每个大功能点修完后进行 3 次随机验证
- 失败时输出最小复现

写集：
- `tests/*`
- 必要的 tests helper

验收标准：
- 不只是门禁，还能模拟用户输入
- 每轮随机画像覆盖差异性足够大
- 失败样例可复现，可用于回归

## 独立审阅与测试

### Review Agent

职责红线：
- 不能只做代码 review
- 必须做 spec audit
- 必须主动抓 hardcode/demo 泄漏/语义错位

检查维度：
- 文档承诺 vs 实现
- 用户语义 vs 内部约束
- demo/default/hardcoded 是否混入 production
- 文案是否与真实语义一致

### Testing Agent

职责：
- 设计随机画像测试矩阵
- 在合并后跑全量 + 随机画像 3 次验证
- 对失败样例给最小复现
- 回归通过前不宣告完成

## 主线程职责

主线程不把关键路径全外包，负责：
- 汇总 worker 输出
- 做跨模块集成
- 解决 parser 与 main-chain 的接线
- 处理 reviewer/tester 发现的最终问题
- 跑最终整体验收

## 发布门槛

以下任一不满足，不允许宣告修复完成：

1. reviewer 明确确认未发现规格偏离/硬编码红线
2. tester 完成全量测试
3. 每个大功能点完成后已做 3 次随机画像验证
4. 自然语言样例 `纯黄金 + 不碰股票` 已通过真实链路验收
5. production 主链已无直接 `build_demo_*` 导入
6. Goal Solver 不再是伪 Monte Carlo

## 本次执行记录

本轮实际并行分工：
- `Goodall` / `019d3fbf-e684-7912-b8eb-28776d3fb50a`
  负责 Goal Solver Monte Carlo 修复与 contract tests
- `Popper` / `019d3fbf-e718-7540-90e9-df998f5dc15e`
  负责自然语言画像 parser 初稿
- `Epicurus` / `019d3fbf-e7a2-71e2-8bd9-921c4be95c89`
  负责 production defaults / de-demo 初稿
- `Bernoulli` / `019d3fbf-e822-7c80-828d-eb41683a65b8`
  负责 acceptance tests 初步门禁与阻塞发现
- `Ampere` / `019d3fbf-e89b-7723-b645-65ecb95b43a4`
  负责第一次 spec audit checklist
- `Kepler` / `019d3fbf-e91b-7383-911b-8b6b22952556`
  负责第一次随机画像测试策略

主线程最终收口后已完成的修复：
- 真实 Monte Carlo 路径级模拟，`n_paths / seed` 生效
- `目标金额` 统一改成 `目标期末总资产`
- 自然语言 `current_holdings / restrictions` 进入约束层与持久化
- unresolved restriction 不再静默吞掉，改为 `warning + requires_confirmation`
- production 主链切断 `build_demo_*` 依赖
- `degraded onboarding` 也可沉淀 baseline，避免后续 monthly 断链
- `cash-only monthly` 不再因空权重被错误 `blocked`
- 随机画像 3 次全流程验收已写入测试并通过

## 最终收口状态

最后一轮 reviewer / tester 发现并已修复的问题：
- unresolved `current_holdings` 不能再静默回退成固定默认仓位
- product defaults 不能再硬编码 `technology`
- `cash-only snapshot` 不能再被误判成 `bundle_quality=partial`

最终验证结果：
- `python3 -m pytest -q` 全量通过
- 随机画像验收包含 onboarding / monthly continuity / full flow 三组各 3 次差异化验证
- 已补 deterministic 回归：`degraded onboarding -> monthly followup`

## 最终验证结果

最终收口后补修的红线问题：
- reviewer 发现的 “无法解析 holdings 时仍静默回退固定仓位” 已移除，改为 unresolved -> 空权重占位 + 明确提示
- reviewer 发现的 “product defaults 仍硬编码 technology 卫星主题” 已移除，product defaults 改为无默认主题偏置
- tester 发现的 “3 次随机验证只覆盖单一路径” 已补齐为 onboarding / monthly continuity / full-flow 各 3 次差异化随机画像
- tester 发现的 “degraded onboarding -> followup continue 缺少确定性自动化测试” 已补齐
- 额外修复：`all-cash snapshot` 不再被误判为 `PARTIAL_BUCKET_COVERAGE`，避免 onboarding 被错误降级

最终验证结论：
- `python3 -m pytest -q` 全量通过
- 自然语言验收测试通过
- 随机画像 3x onboarding / 3x monthly / 3x full-flow 验收通过
- production 主链静态门禁确认无直接 `build_demo_*` 依赖

当前边界说明：
- `src/demo_scenarios.py` / `src/shared/demo_flow.py` / 相关 demo smoke 仍保留，用于演示与测试，不进入 production 主链
