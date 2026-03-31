# 投资系统测试与 TDD 规范 v1

> 文档定位：本文件是整套投资决策系统交付 Codex 开发时的测试主文档。
> 目标不是“证明系统一定赚钱”，而是建立一套可执行、可复盘、可阻止过拟合的测试协议。
>
> 本文覆盖三件事：
>
> 1. 如何按模块做 test-driven development
> 2. 如何设计研究/回测协议，尽量避免 backtest overfitting
> 3. 如何验证“目标达成概率”是校准过的，而不是拍脑袋的数字

---

## 0. 一句话定义

**本系统的测试目标不是保证结果，而是保证过程、边界、概率口径和联调行为都可信。**

更具体地说：

- 不能保证用户未来一定达成目标
- 但可以测试系统是否：
  - 正确消费输入
  - 正确执行约束
  - 正确比较候选动作
  - 正确输出结构化结果
  - 正确报告概率，并在历史样本上保持可接受的校准性
  - 没有因为多次试参、时间泄漏、指标挑选而把回测结果吹高

---

## 1. 测试总原则

### 1.1 先讲清“能保证什么，不能保证什么”

系统**不能保证**：

- 任一单账户一定达成目标
- 任一未来年份一定正收益
- 任一策略在所有市场状态下都跑赢基准

系统**应当保证**：

- 同一输入下结果可复现
- 同一约束下非法动作一定被拦截
- 同一候选集合下评分和排序是稳定、可解释的
- `Goal Solver` 给出的成功概率在历史 OOS 检验中具备基本校准性
- 系统性能的声明来自严格的时间切分和冻结测试，而不是边试边挑

### 1.2 测试优先级

优先级从高到低：

1. **正确性**：类型、字段、签名、边界、阻断规则
2. **一致性**：模块之间的 contract 是否一致
3. **稳健性**：异常输入、降级路径、极端场景是否稳定
4. **概率校准**：成功概率、风险摘要是否和历史实际大体对齐
5. **策略有效性**：在未见样本上是否仍有合理的目标改善与风险控制
6. **性能**：延迟、路径数、批量评估耗时

### 1.3 TDD 的实施顺序

每个功能严格按下面顺序开发：

1. 先写失败测试
2. 再写最小实现使测试通过
3. 再做重构
4. 再补回归测试
5. 最后才允许接入更大 workflow

禁止：

- 先把整条链写完，再补测试
- 在失败的最终冻结集上继续调参
- 因为想让回测更好看而临时修改测试口径

---

## 2. 测试分层总图

建议按 6 层组织：

### L1. 单元测试（Unit Tests）

对象：纯函数、校验器、适配器、评分子函数、阈值判断函数。

目标：

- 输入输出正确
- 边界值正确
- 极端值正确
- 错误信息正确

### L2. 契约测试（Contract Tests）

对象：模块接口。

重点验证：

- `03 -> 05`
- `05 -> 02`
- `05 -> 04/10`
- `04 -> 10`
- `07 -> 02/04/09`

目标：

- 字段名一致
- 类型一致
- 必填项一致
- 责任边界一致
- 版本号与 ID 透传正确

### L3. 场景测试（Scenario Tests）

对象：完整业务情境。

例如：

- 首次建档
- 月度巡检
- 行为高情绪阻断
- 回撤事件
- 卫星超配事件
- 季度复审
- 降级/阻断路径

目标：

- 流程顺序正确
- 触发条件正确
- 决策卡事实来源正确

### L4. 时间序列验证（Temporal Validation）

对象：`Goal Solver`、研究参数、启发式规则、候选排序效果。

目标：

- 避免未来函数
- 避免 train/test 泄漏
- 衡量 OOS 稳定性

### L5. 过拟合防护测试（Overfitting-Control Tests）

对象：研究与策略评估协议本身。

目标：

- 估计 backtest overfitting 风险
- 修正多次试参带来的性能膨胀
- 记录尝试次数与筛选路径

### L6. 影子运行 / 纸面运行测试（Shadow Tests）

对象：整套系统在仿真或真实数据上的“只建议不执行”模式。

目标：

- 观察真实数据流下的行为
- 验证概率校准是否漂移
- 验证运行时异常、延迟和人工可解释性

---

## 3. 模块级测试设计

---

## 3.1 03 Snapshot & Ingestion

### 必测内容

1. 字段标准化
2. 时间格式统一
3. 缺失值与质量标记
4. `snapshot_id / bundle_id` 生成
5. 五域拼装
6. `CompletenessLevel / QualityFlag` 正确写入

### 典型测试

- 市场域缺少 `series_dates` 时是否打 flag
- 账户权重和不接近 1.0 时是否打 `WEIGHT_SUM_MISMATCH`
- 行为域缺失时是否允许 bundle 继续生成但标记 degraded
- 同一输入两次构建时，除 ingest time 外其余确定性字段是否一致

### 通过标准

- 不偷偷修业务逻辑
- 只做标准化与冻结，不做解释层工作

---

## 3.2 05 Constraint & Calibration

### 必测内容

1. `SnapshotBundle -> CalibrationResult` 的纯解释路径
2. `MarketState / ConstraintState / BehaviorState` 生成
3. 降级逻辑
4. 参数版本治理
5. `CalibrationResult.calibration_quality` 的真实性

### 典型测试

- 市场历史窗口不足时，是否降级而不是静默当正常
- `effective_drawdown_threshold <= max_drawdown_tolerance` 是否始终成立
- 行为域缺失时 `BehaviorState` 是否进入保守兜底
- 参数版本变更时是否记录来源 bundle 和原因

### 通过标准

- 05 只解释，不直接做动作选择
- 所有降级必须显式可见

---

## 3.3 02 Goal Solver

### 必测内容

1. 输入合法性校验
2. 现金流计划构建
3. Monte Carlo 路径构建
4. 风险摘要统计
5. 硬约束过滤
6. 排序策略
7. `GoalSolverOutput` 结构

### 单元测试重点

- `CashFlowEvent.amount` 符号约定是否严格执行
- `contribution_pause / contribution_resume` 是否按月份正确生效
- 权重和必须约等于 1
- `success_probability` 在 `[0,1]`
- `shortfall_probability ≈ 1 - success_probability`
- `drawdown_budget_used_pct` 语义在兜底路径下允许 `> 1.0`

### 统计测试重点

- 固定 seed 下结果可复现
- 小样本路径数与大样本路径数方向一致
- 轻量入口与正式入口在同一输入上的排序方向大体一致

### 通过标准

- 02 只回答“够不够”
- 不生成运行期候选动作

---

## 3.4 04 Runtime Optimizer + 10 EV Engine

这两层必须既做单元测试，也做契约测试。

### 04 必测内容

1. 运行模式判定
2. `validate_ev_state_inputs()`
3. `build_ev_state()`
4. 候选动作生成
5. 候选贫乏降级协议
6. `RuntimeOptimizerResult` 汇总

### 10 必测内容

1. `run_ev_engine(state, candidate_actions, trigger_type) -> EVReport`
2. Feasibility Filter
3. 五项评分
4. 排序与推荐理由
5. `EVReport` 结构

### 04 ↔ 10 契约测试

必须冻结以下 contract：

- `run_ev_engine()` 主签名
- `EVReport` 必填字段
- `ranked_actions` 元素类型
- `trigger_type` 合法值
- `goal_solver_baseline / goal_solver_after_recommended` 使用的概率字段口径

### 典型场景测试

- 行为高情绪时，`FREEZE / OBSERVE` 保留，其他动作被冷静期拦截
- 卫星超配时，`REDUCE_SATELLITE` 必须进入候选集
- 回撤事件时，`ADD_DEFENSE` 必须进入候选集
- `REBALANCE_FULL` 在 MONTHLY 与 EVENT 下的触发条件不同
- 候选为空或过少时，poverty protocol 是否正确补齐

### 通过标准

- 04 不做评分
- 10 不做候选生成
- 联调时没有字段脑补和重复定义

---

## 3.5 07 Orchestrator

### 必测内容

1. workflow 触发路由
2. 阻断 / 降级判断
3. 输入版本透传
4. 调用顺序
5. 状态持久化元数据
6. 给 09 的 `DecisionCardBuildInput`

### 典型测试

- MONTHLY 是否复用最新有效 `GoalSolverOutput`
- QUARTERLY 是否强制先跑一次完整 Goal Solver
- `CalibrationResult` degraded 时是否按规则阻断或降级
- 行为事件时是否允许进入 blocked card 路径

### 通过标准

- 07 只编排，不偷做策略判断

---

## 3.6 09 Decision Card

### 必测内容

1. 事实抽取
2. 卡片类型路由
3. 文案不越权
4. 不编造不存在字段
5. blocked / runtime / quarterly / baseline 卡片区分

### 典型测试

- 运行期动作卡不得要求 EV 提供完整 `GoalSolverOutput`
- blocked 卡只使用 `blocking_reasons` 与已有事实，不写主观猜测
- 所有数值字段都必须能回指到 02/04/10/07 中真实存在的结构化字段

### 通过标准

- 09 只做展示，不做再判断

---

## 4. 仓库测试结构建议

```text
project_root/
├── tests/
│   ├── unit/
│   │   ├── test_snapshot_ingestion_*.py
│   │   ├── test_calibration_*.py
│   │   ├── test_goal_solver_*.py
│   │   ├── test_runtime_optimizer_*.py
│   │   ├── test_ev_engine_*.py
│   │   ├── test_orchestrator_*.py
│   │   └── test_decision_card_*.py
│   │
│   ├── contract/
│   │   ├── test_03_to_05_contract.py
│   │   ├── test_05_to_02_contract.py
│   │   ├── test_05_to_04_10_contract.py
│   │   ├── test_04_to_10_contract.py
│   │   └── test_07_to_09_contract.py
│   │
│   ├── scenario/
│   │   ├── test_first_onboarding_flow.py
│   │   ├── test_monthly_review_flow.py
│   │   ├── test_behavior_block_flow.py
│   │   ├── test_drawdown_event_flow.py
│   │   ├── test_satellite_overweight_flow.py
│   │   └── test_quarterly_review_flow.py
│   │
│   ├── temporal/
│   │   ├── test_walk_forward_goal_solver.py
│   │   ├── test_goal_prob_calibration.py
│   │   ├── test_strategy_oos_stability.py
│   │   └── test_regime_split_consistency.py
│   │
│   ├── research_guardrails/
│   │   ├── test_experiment_registry_integrity.py
│   │   ├── test_pbo_estimation.py
│   │   ├── test_deflated_sharpe_gate.py
│   │   └── test_no_holdout_contamination.py
│   │
│   └── fixtures/
│       ├── bundles/
│       ├── calibration/
│       ├── solver/
│       ├── runtime/
│       └── cards/
│
├── data/
│   ├── research/
│   ├── frozen_holdout/
│   └── shadow_runs/
│
└── reports/
    ├── test_reports/
    ├── temporal_validation/
    └── shadow_monitoring/
```

---

## 5. 避免回测过拟合：研究协议必须单独测试

这是最关键的一节。

### 5.1 冻结一个“最终保留集”

必须从一开始就冻结一个**最终 holdout**，开发阶段完全不允许看它的结果。

建议：

- 训练集：最早一段历史
- 验证集：中间一段历史
- 最终冻结集：最近一段历史

规则：

- 调参只允许用训练/验证
- 所有门槛、参数、规则一旦定版，再跑最终冻结集
- 若最终冻结集失败，不允许继续在这段数据上调
- 只能开新版本，换新的开发窗口重新来

### 5.2 时间顺序切分，禁止随机洗牌

时间序列验证必须按时间顺序切分，不能随机 shuffle。

推荐两层：

1. **基础层**：expanding / rolling walk-forward
2. **强化层**：带 purge / embargo 的时间切分；研究阶段可再加 CPCV/PBO

时间序列数据不适合普通随机交叉验证；`TimeSeriesSplit` 的官方文档也明确指出，时序数据需要保持 train 在前、test 在后，以避免训练在未来、评估在过去。citeturn486195search2

### 5.3 记录“你试过多少东西”

回测过拟合的根源之一不是模型复杂，而是**你试了很多版本，只报最好的那一个**。Bailey 等关于 PBO 的工作专门就是为估计这种 backtest overfitting 风险而提出的，并用 CSCV 估计某次高回测表现是否只是过拟合。citeturn616714search0turn647180search0

所以必须建立 `experiment_registry`，至少记录：

- 版本号
- 数据窗口
- 尝试的参数组合数
- 指标筛选顺序
- 是否触碰过最终 holdout
- 被淘汰的版本及原因

测试要求：

- 每次研究运行都必须落 registry
- 无 registry 的版本不得进入 benchmark 比较

### 5.4 对“好看的 Sharpe/收益”做去偏

Deflated Sharpe Ratio 的目的就是修正由多次试参和非正态收益导致的 Sharpe 膨胀。Bailey 与 López de Prado 明确把 DSR 定位为纠正 selection bias、backtest overfitting 和 non-normality 的工具。citeturn616714search2turn616714search6

因此研究门槛不应只看：

- CAGR
- Sharpe
- Max Drawdown

还要至少补：

- DSR
- PBO
- 参数扰动稳定性
- OOS 相对 IS 的衰减率

### 5.5 对数据窥探做现实性修正

White 的 Reality Check / bootstrap data-snooping 这一路文献就是为解决“从一堆规则里挑最优后，显著性被夸大”的问题建立的。White 的 bootstrap reality check 在后续综述和相关研究里仍被当作处理 data snooping 的标准工具之一。citeturn486195search0turn486195search7

所以你的协议里建议这样落地：

- v1：至少做 block bootstrap + best-vs-benchmark 显著性比较
- v2：加入 White Reality Check 或 SPA
- v3：研究层加入 full multiple-testing correction

### 5.6 不要把“最终收益最好”当唯一指标

这套系统不是纯 alpha 挖掘，而是 goal-based 决策系统。

因此研究目标函数应至少包含：

- 目标达成率 / shortfall rate
- 风险线突破频率
- 回撤深度
- 换手与交易成本
- 概率校准误差
- 用户行为保护效果

只看终值，很容易把系统推向高波动、高集中、不可执行的伪优解。

---

## 6. “目标达成率”应该怎么测

这里先说最重要的一句：

**不能测试“保证达成”，只能测试“预测的达成概率是否校准”。**

也就是：

- 系统说某类账户有 70% 达成概率
- 在历史 OOS 样本、合成样本和影子运行样本里，这类账户最终达成的频率应接近 70%

### 6.1 核心指标一：Brier Score

Brier score 衡量预测概率和实际结果之间的均方误差；scikit-learn 文档明确指出它是一个 strictly proper scoring rule，数值越小越好。citeturn389223search0turn389223search6

对本系统，定义：

- 事件：在给定期限内，账户是否达到 `goal_amount`
- 预测：`GoalSolverOutput.recommended_result.success_probability`
- 实际：到期后是否达成（0/1）

测试要求：

- 在每个 OOS 窗口计算 Brier score
- 与简单基线比较：
  - 恒定基线概率
  - 只按股债比的简化模型
  - 不考虑现金流事件的简化模型

### 6.2 核心指标二：校准曲线 / Reliability Diagram

校准曲线会把预测概率分箱，再比较每个 bin 的平均预测概率与实际发生频率。scikit-learn 官方文档把它直接称为 calibration curves，也就是 reliability diagrams。citeturn389223search1turn389223search4

建议分箱：

- `[0.0,0.1)`
- `[0.1,0.2)`
- ...
- `[0.9,1.0]`

通过标准：

- 主对角线附近
- 不允许长期系统性高估
- 允许保守低估，但也不能严重失真

### 6.3 核心指标三：分层目标达成频率

按用户画像与市场状态分层看：

- conservative / moderate / aggressive
- essential / important / aspirational
- bull / sideways / stress windows
- 高现金流 / 低现金流
- 高波动 / 低波动

检查：

- 哪一类群体最容易被高估
- 哪一类群体最容易被低估
- 是否某一风险偏好口径明显偏差

### 6.4 核心指标四：短缺频率与短缺深度

只看是否达成目标不够，还要看没达成时差多少。

建议同时监控：

- `shortfall_probability`
- 终值落后目标的平均比例
- 最差 5% 路径的短缺深度
- 风险预算越界频率

### 6.5 核心指标五：预测区间覆盖

如果系统输出未来终值区间或 tail summary，就要检查经验覆盖率是否接近名义覆盖率。
NIST 资料把 coverage interval / coverage probability 作为不确定性表达的正式口径；在预测区间评估里，经验覆盖率是否接近名义覆盖率是核心问题。citeturn389223search21turn389223search14

因此：

- 如果系统说 90% 路径会落在某区间内
- OOS 检验时，落在区间内的比例应该接近 90%

这能防止 Monte Carlo 区间看起来很精致，但实际过窄。

---

## 7. 目标达成率的验收口径：不说“保证”，说“三层验收”

建议把验收写成三层。

### 第一层：过程正确性验收

要求：

- 所有模块单元测试通过
- 所有契约测试通过
- 所有关键场景测试通过
- 无未来数据泄漏
- 无未记录实验

### 第二层：概率校准验收

要求：

- OOS Brier score 优于朴素基线
- 校准曲线无明显系统性高估
- 关键画像分组无灾难性失真
- 终值区间覆盖率可接受

### 第三层：策略有效性验收

要求：

- 在 OOS 上，推荐动作相对“恒定配置 / 纯月投 / 只看偏离不看 EV”的基线有稳定改进
- 风险线突破频率不高于系统声明
- 年化换手与成本在预算内
- 高情绪期的错误动作率明显下降

注意：

- 第三层失败，不代表系统完全不能用
- 但第二层失败，系统的概率口径就不可信，必须先修

---

## 8. 场景库设计：必须覆盖“坏时候”

要避免过拟合，场景库不能只测常规行情。

至少要有 5 类场景：

1. **慢牛**：连续上涨，低波动
2. **震荡**：收益不高，来回波动
3. **快速大跌**：高相关、流动性紧张
4. **高通胀/商品强**：黄金、防御资产相对占优
5. **结构性分化**：单主题大涨但 broad market 一般

每类场景都要测：

- Goal Solver 的成功概率变化
- Runtime 候选是否合理
- EV 是否把高集中、高情绪动作压下去
- Decision Card 是否解释正确

---

## 9. TDD 的用例写法建议

每个需求都写成以下格式：

### 9.1 需求模板

- **Given**：给定什么输入状态
- **When**：触发什么动作或 workflow
- **Then**：必须出现什么结构化输出
- **And**：不能出现什么越权行为

### 9.2 例子：行为高情绪阻断

- Given：`high_emotion_flag=True`、`panic_flag=True`
- When：进入 EVENT workflow，并请求 `REBALANCE_FULL`
- Then：`FREEZE` 与 `OBSERVE` 必须存在于候选或结果中
- And：`REBALANCE_FULL` 必须被 feasibility/cooldown 拦截
- And：Decision Card 必须输出 blocked 或 observe 型解释，不得伪造“市场判断”

### 9.3 例子：季度复审

- Given：进入 QUARTERLY workflow
- When：07 编排执行
- Then：必须先跑完整 Goal Solver，再进入 Runtime
- And：EVReport.trigger_type 必须是 `quarterly`
- And：09 必须构造 quarterly_review card

---

## 10. CI / 阶段门设计

建议分 4 道门。

### Gate A：本地开发门

- 单元测试
- 契约测试
- lint / type check

### Gate B：合并请求门

- 场景测试
- 快速 temporal smoke test
- 关键 fixture 回归对比

### Gate C：研究发布门

- 完整 walk-forward
- OOS 报告
- Brier / calibration 报告
- DSR / PBO / bootstrap 显著性报告
- 实验 registry 完整性检查

### Gate D：上线前门

- shadow run 一段时间
- 与人工基线或旧版本对比
- 冻结参数与数据版本
- 生成发布说明

未过 Gate C，不得声称“有统计支持的目标改善”。
未过 Gate D，不得进入真实执行模式。

---

## 11. 推荐的首批验收阈值（保守版）

这些阈值不是理论真理，而是开发初期的保守工程门槛。

### 11.1 正确性门槛

- 单元测试通过率：100%
- 契约测试通过率：100%
- 关键场景测试通过率：100%

### 11.2 概率门槛

- OOS Brier score 优于朴素基线
- 关键概率 bin 的经验达成率与预测值偏差不超过预先定义容忍带
- 无持续三个以上窗口的系统性高估

### 11.3 过拟合门槛

- 最终 holdout 未被开发期触碰
- 所有实验均已登记
- DSR 不为明显失真
- PBO 不可高得离谱
- OOS 性能衰减可解释

### 11.4 执行性门槛

- 年化换手不超过预算
- 成本后结论仍成立
- blocked / degraded / poverty 协议都经过场景覆盖

---

## 12. 给 Codex 的落地顺序建议

建议按下面顺序开发测试，而不是先啃整条大链：

### Phase 1：接口先行

先写并跑通：

- 03/05/02/04/10/07/09 的 dataclass 与 contract tests
- 所有 ID/version/trigger_type 的透传测试

### Phase 2：核心算法可复现

再写：

- Goal Solver 现金流与概率统计测试
- Runtime 候选生成测试
- EV 五项评分测试

### Phase 3：完整 workflow

再写：

- 首次建档
- 月度巡检
- 行为阻断
- 季度复审

### Phase 4：时间序列与研究门

最后写：

- walk-forward
- Brier / calibration
- DSR / PBO / bootstrap 显著性
- shadow run 监控

---

## 13. 最后一条工程裁决

**这套系统的测试终点，不是“找出历史上最赚钱的版本”，而是“找出在未见样本上仍然守纪律、概率口径不失真、风险边界不失控的版本”。**

如果 Codex 按这个文档开发，最后出来的系统也许不会是历史回测最漂亮的那个，但会更接近真正能上线、能复盘、能长期维护的那个。
