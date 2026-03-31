# 产品验收与偏离文档专项审计

日期：2026-03-31

范围：
- `src/frontdesk`
- `src/shared/onboarding.py`
- `src/goal_solver`
- `src/allocation_engine`
- 相关 contract/smoke tests

## 结论

当前系统的产品方向基本正确，但实现层存在数个 `P0` 级问题：

1. `success_probability` 对用户显示为“概率”，但当前实现不是文档承诺的 Monte Carlo 概率求解，而是启发式打分公式。
2. 前台把“目标金额”展示成单一字段，没有明确说明它是“目标期末总资产”，也没有说明是否含通胀、税费、贡献中断等假设。
3. 自然语言输入没有真正进入约束层。
4. 自然语言持仓解析几乎不可用，除 `cash` 外基本退化成通用默认仓位。
5. `demo` 假设和 demo builder 仍直接进入前台/建档主链，导致“产品化壳层”里混入研究样例默认值。
6. 现有测试大多在保护“当前输出结构和回归样例”，并没有系统性保护“是否符合文档语义”和“是否满足真实用户约束”。

## P0 清单

### P0-1 概率口径与实现不一致

文档写的是“参数化 Monte Carlo”，并明确要求：
- `run_goal_solver()` 使用 `n_paths`
- `run_goal_solver_lightweight()` 使用 `n_paths_lightweight`
- 固定 `seed` 保证结果可复现

证据：
- [system/02_goal_solver.md](../system/02_goal_solver.md) 明确写了 Monte Carlo 路径模拟与 `rng` 逻辑。
- [src/goal_solver/engine.py](../src/goal_solver/engine.py) 的 `_run_monte_carlo()` 实际直接 `del n_paths, seed`，然后用启发式公式生成 `probability / max_drawdown / tail metrics`。

直接风险：
- 用户看到的是“达成概率”，实际拿到的是“启发式评分”。
- 测试、决策卡、替代路径都在消费这个字段，误导面是全链路的。

必须动作：
- 在真正实现路径模拟前，把字段或文案降级为 `model_estimate` / `heuristic_estimate`，禁止对外称“概率”。
- 若继续保留 `success_probability` 字段，必须补齐真正路径级模拟。
- 增加一条硬测试：改变 `n_paths`/`seed` 时，`_run_monte_carlo()` 的底层采样行为必须受影响；不允许形参被吞掉。

### P0-2 “目标金额”口径对用户不清晰

当前前台只写“目标金额”，但系统内部定义其实是：
- `P(期末资产 >= goal_amount)`

证据：
- [system/02_goal_solver.md](../system/02_goal_solver.md)
- [src/shared/onboarding.py](../src/shared/onboarding.py)
- [src/decision_card/builder.py](../src/decision_card/builder.py)

直接风险：
- 用户无法区分“目标总资产”与“目标收益”。
- 用户无法知道目标是否为名义金额、实际购买力、税前、税后。

必须动作：
- 前台统一改名为“目标期末总资产”。
- 决策卡增加明确说明：
  - 是否含当前资产
  - 是否含后续投入
  - 是否名义金额
  - 是否未计税费/通胀
- 新增验收测试：用户询问“45万是收益还是总资产”时，系统必须给出无歧义解释。

### P0-3 自然语言限制条件未进入约束层

用户写入的 `restrictions` 目前主要只进入 provenance 和状态展示，没有被稳定编译成 `forbidden_buckets / forbidden_themes / allowed_buckets / qdii_allowed`。

证据：
- [src/shared/onboarding.py](../src/shared/onboarding.py) 记录了 `restrictions`
- [src/frontdesk/service.py](../src/frontdesk/service.py) 也只是在 provenance 里继续展示
- `rg restrictions src/goal_solver src/orchestrator src/decision_card` 无真正约束消费
- 下游 allocation engine 明明支持 `forbidden_buckets / forbidden_themes`，见 [src/allocation_engine/types.py](../src/allocation_engine/types.py) 和 [src/allocation_engine/validator.py](../src/allocation_engine/validator.py)

直接风险：
- 用户写“不能买股票”，系统仍可能给高权益仓位。
- 用户写“不能碰科技主题”，系统仍可能保留 `technology` satellite。

必须动作：
- 增加 `profile_parser` 层，把自然语言约束编译成 canonical profile。
- 对低置信度抽取项增加确认步骤。
- 增加验收测试：
  - “不碰股票” => `equity_*` 为 forbidden
  - “不碰科技” => technology theme forbidden
  - “只能黄金和现金” => allowed buckets 只剩 gold/cash

### P0-4 自然语言持仓解析退化成固定默认仓位

当前逻辑除 `cash` 外，几乎都退回固定权重：
- `equity_cn=0.52`
- `bond_cn=0.30`
- `gold=0.05`
- `satellite=0.13`

证据：
- [src/shared/onboarding.py](../src/shared/onboarding.py)
- [src/frontdesk/service.py](../src/frontdesk/service.py)

直接风险：
- “纯黄金”会被系统理解成通用混合仓。
- 当前画像和真实账户状态发生基础性错配。

必须动作：
- 支持至少一层规则解析：
  - `纯黄金`
  - `全现金`
  - `股债六四`
  - `80%纳指 20%货基`
- 不可解析时明确标记 `unparsed_holdings`，并要求确认，不能默默套通用仓位。
- 增加负面测试：无法识别的持仓描述不得自动伪装成精确权重。

### P0-5 demo 假设泄漏到产品主链

前台和 onboarding 主链仍大量直接依赖 `build_demo_*`。

证据：
- [src/shared/onboarding.py](../src/shared/onboarding.py) 直接 import `build_demo_allocation_input / build_demo_market_raw / build_demo_behavior_raw / build_demo_constraint_raw`
- [src/frontdesk/service.py](../src/frontdesk/service.py) 也直接 import demo builders
- [src/demo_scenarios.py](../src/demo_scenarios.py) / [src/shared/demo_flow.py](../src/shared/demo_flow.py) 中包含默认 `preferred_themes=["technology"]`、默认 market assumptions、默认 theme caps 等

直接风险：
- 前台不是“真实默认值 + 明确降级”，而是“研究样例配置穿透到产品”。
- 用户无意间被套用科技偏好、固定市场假设、固定阈值。

必须动作：
- 生产链禁止 import `build_demo_*`。
- demo fixtures 必须隔离到测试或 demo 命名空间。
- 建立静态检查：`src/frontdesk` / `src/shared/onboarding.py` / 其他 production entrypoint 中出现 `build_demo_` 直接 fail CI。

### P0-6 测试保护的是当前样例，不是文档语义

现有测试有价值，但大多是：
- contract 结构测试
- regression 样例输出测试
- smoke 主链打通测试

缺口：
- 没有自然语言到约束层的验收测试
- 没有自然语言到持仓权重的验收测试
- 没有“禁止 demo builder 进入生产主链”的静态测试
- 没有“`n_paths`/`seed` 真正参与概率计算”的语义测试

证据：
- [tests/contract/test_02_goal_solver_contract.py](../tests/contract/test_02_goal_solver_contract.py) 只验证 lightweight 调用把参数传给 `_run_monte_carlo()`，并未验证 `_run_monte_carlo()` 使用这些参数
- [tests/contract/test_09_product_feedback_regression.py](../tests/contract/test_09_product_feedback_regression.py) 主要在固定样例上断言输出文案和字段
- 当前 tests 中几乎没有覆盖 `restrictions` / 自然语言 holdings 的语义消费

必须动作：
- 新增 `spec-conformance` 测试层，不允许只做结构测试。
- 新增 `acceptance` 测试层，直接使用自然语言输入。

## P1 清单

### P1-1 用户画像维度过粗

当前核心只保留：
- `risk_preference`
- `max_drawdown_tolerance`
- `current_holdings`
- `restrictions`

建议升级为分层画像：
- 目标层：目标类型、金额、期限、刚性程度、优先级
- 风险层：风险偏好、风险承受能力、最大亏损容忍、波动厌恶
- 现金流层：收入稳定性、月度投入可持续性、应急金需求
- 账户层：税务属性、账户类型、流动性需求
- 约束层：禁投品类、集中持仓、主题偏好、合规限制
- 行为层：复核频率、冲动交易倾向、人工确认阈值

### P1-2 三档风险风格只能做 UI 标签，不能做核心建模

可以保留 `保守 / 中等 / 进取` 给用户看，但内部应拆成：
- `risk_tolerance_score`
- `risk_capacity_score`
- `loss_limit`
- `liquidity_need_level`
- `goal_priority`

### P1-3 目标口径应扩展到真实世界语义

建议补充：
- `goal_amount_basis`: nominal / real
- `goal_amount_scope`: total_assets / incremental_gain / spending_need
- `tax_assumption`
- `fee_assumption`
- `contribution_commitment_confidence`

### P1-4 无可行方案时的用户文案还不够锋利

当前可以回退到“最接近可行”的推荐，但应更明确：
- 当前不存在满足你回撤约束的配置
- 下面不是“推荐投资方案”，而是“最接近可行的临时参考”

## 为什么有审核和测试，问题还会漏出来

### 1. 测试目标错位

当前测试主要保障：
- 程序能跑
- 字段没坏
- 样例输出没变

但没有保障：
- 实现是否真的符合系统文档承诺
- 用户限制是否真的生效
- “概率”是否真是概率

### 2. review 没有做 spec audit

review agent 查的是“代码有没有明显 bug / 测试有没有过”。
但这类问题属于：
- 规格承诺和实现不一致
- 用户语义和内部约束断链

如果没有要求 reviewer 逐条对照 `system/*.md`，很容易漏掉。

### 3. regression 把错误固化了

一旦测试样例本身就建立在 demo 默认值和当前输出上，测试会把“错误行为”稳定下来，而不是把它识别出来。

### 4. demo 与 production 边界没有制度化

现在 repo 里 demo builders 和 production orchestration / onboarding 混在一起。
这类问题不是“某个工程师一时疏忽”，而是边界治理没建立。

## 我怎么知道还有没有别的严重问题

短答：以当前状态，不能高置信度知道“没有别的问题”。必须增加一层正式的“规格符合性审计”。

建议立刻建立 5 个 release gate：

1. `Spec Traceability Matrix`
   - 每条系统文档要求映射到一个测试 ID
   - 没有测试 ID 的规格，不允许宣称已实现

2. `No Demo In Prod`
   - 生产入口模块禁止 import `build_demo_*`
   - CI 静态扫描命中即失败

3. `Semantic Acceptance Tests`
   - 以自然语言作为输入
   - 断言约束、持仓、目标解释是否正确落库和生效

4. `Probability Integrity Gate`
   - 在真正 Monte Carlo 上线前，前台禁止用“概率”措辞
   - 上线后增加校准测试、seed 敏感性测试、单调性测试

5. `Independent Spec Review`
   - 单独 reviewer 不看 PR 描述，直接按 `system/*.md` 对实现做逐项核对
   - 与普通 code review 分开

## 建议的下一步执行顺序

1. 先修 `P0-1` 和 `P0-5`
2. 再修 `P0-3` 和 `P0-4`
3. 然后补 `Spec Traceability Matrix` 与 acceptance tests
4. 最后再做画像 schema 升级和风险建模细化

## 一句话判断

当前系统适合继续内部开发和验收，不适合把“达成概率”当成严肃对外承诺，也不适合把自然语言画像能力宣称为已完成。
