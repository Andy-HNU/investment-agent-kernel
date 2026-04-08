# CODEX v1.4 Daily Product Probability Engine Design

日期：2026-04-09

作者：Codex

状态：design-approved draft

读者：开发、审阅、测试、产品 owner、Claw/OpenClaw 验收操作者、新加入项目的工程师

---

## 1. 文档定位

`v1.4` 是 `v1.3` 之后的下一阶段主规格。`v1.3` 解决的是：

- formal / degraded / failure 结果语义
- Evidence Bundle
- DisclosureDecision
- execution policy / disclosure policy
- silent fallback 清理

`v1.4` 不再处理这些治理边界本身，而是建立一个**真正可用于 daily product-level probability 的正式概率引擎**。

本稿是 `v1.4` 的唯一主设计文件，目标不是“列出几个模型名字”，而是把以下内容写成一个脱离本次聊天也足以指导开发的工程规格：

- 主模型与 challenger 的选择理由
- success probability 的严格事件定义
- 日频逐产品建模链
- 五层随机特征的组合方式
- 因子体系、映射与 shrinkage
- GARCH / DCC / jump / regime 的正式公式和状态更新
- 与现有 `goal_solver / calibration / orchestrator` 的关系
- 性能边界、缓存边界、测试与 Claw 验收边界

本稿明确约束：

- `v1.4` formal path **只允许日频逐产品模拟**
- **禁止月级 fallback**
- **禁止桶级 fallback**
- **禁止把 primary / challenger / stress 结果简单平均**

---

## 2. 设计目标与非目标

### 2.1 目标

`v1.4` 必须同时满足以下 12 项：

1. formal / Claw truth 概率全部来自**日频逐产品**路径模拟
2. 成功率绑定统一 `SuccessEventSpec`
3. 主模型采用方案 B，challenger 采用方案 C，stress 单独定义
4. 一个产品可同时拥有多层随机特征，而不是“选择一个模型标签”
5. 因子层承担共同依赖结构，产品层承担边际和残差
6. 因子层初始维度控制在 `~10` 个可交易可观测驱动器
7. primary、challenger、stress 的职责固定且不可混淆
8. 输出必须能区分 `primary result`、`challenger disagreement`、`stress tail view`
9. formal path 下不允许任何月级或桶级求生式回退
10. 复杂度、缓存、内存控制要足以支撑日常交互运行
11. 数学正确性与 Claw 语义验收都必须可回归
12. 新团队成员只看本文即可知道实现方式、边界和测试门

### 2.2 非目标

`v1.4` 不处理：

- 自动下单
- 分钟级/盘中高频路径
- 税务精算
- 期权 Greeks / 波动率曲面
- 多租户分布式求解调度
- 券商真实交易 API 直连

---

## 3. 总结论

### 3.1 主架构结论

`v1.4` 采用：

- **方案 B 作为 primary**
- **方案 C 作为 challenger**
- **stress 配方单独输出**

### 3.2 为什么不是方案 A

方案 A 可以概括为：

> 直接对全产品层做联合动态状态建模，例如全产品联合 GARCH / 全产品联合 DCC / 大规模状态空间建模。

不选 A，不只是因为 `DCC` 维度太大，还包括以下 6 个更根本的问题：

1. **依赖结构不可扩展**
   - 全产品联合相关矩阵维度约为 `N x N`
   - 当 `N` 到几百甚至几千时，参数量和矩阵更新代价都不可接受

2. **状态估计不稳**
   - 新产品、短历史产品、停牌/拆分/换基产品会让联合状态估计非常脆

3. **formal path 不可校准**
   - 全产品联合模型一旦漂移，很难把“是数据问题还是状态估计问题”拆清楚

4. **映射与可解释性差**
   - 从产品直接到联合状态空间，解释层很难回答“为什么这个产品在这个因子上受压”

5. **产品宇宙扩展成本过高**
   - `v1.4` 已经明确要走全市场运行时产品宇宙；方案 A 会让 universe 扩展和建模复杂度绑定得过紧

6. **工程推进路径不适合作为 first formal engine**
   - 方案 A 更像后续成熟版本或研究线路，不适合作为 `v1.4` 第一版正式主链

### 3.3 方案 B 与方案 A 的本质差异

方案 A 与方案 B 的差异，不只是“B 把 DCC 放到低维因子层”。更完整的差异是：

| 维度 | 方案 A | 方案 B |
| --- | --- | --- |
| 建模对象 | 全产品联合状态 | 因子联合 + 产品边际 + 产品残差 |
| 依赖结构 | 产品层联合相关 | 因子层联合相关 |
| 新产品接入 | 直接进入联合状态，成本高 | 先映射到因子，再挂接产品边际，成本可控 |
| 解释性 | 依赖关系黑箱化 | 可拆成因子共同项 + 产品残差项 |
| 稳定性 | 对缺失序列敏感 | 允许产品层局部缺口，不污染全部依赖结构 |
| 计算复杂度 | 近似 `O(P*T*N^2)` | 近似 `O(P*T*K^2 + P*T*N*K)` |

其中：

- `P` = 路径数
- `T` = 未来交易日数
- `N` = 产品数
- `K` = 因子数，`K << N`

### 3.4 为什么方案 B 是 primary

方案 B 的完整定义是：

> 产品边际过程 + 因子联合过程 + 产品残差过程 + 跳跃 + regime 条件化。

它适合作为 primary，因为它同时满足：

- 前瞻可模拟
- 新产品可挂接
- formal path 可校准
- 因子/产品双层解释清晰
- 依赖结构复杂度可控

### 3.5 为什么方案 C 是 challenger

方案 C 的完整定义是：

> 基于真实历史产品日收益路径、按 regime 过滤后的 block bootstrap challenger。

它的价值在于：

- 保留真实路径形状
- 天然包含真实历史中的波动聚集、连续回撤、联合下跌、尾部事件
- 用于审查 primary 是否过于乐观、是否压平了路径风险

它不适合做唯一 primary，因为：

- 对短历史产品和新产品覆盖弱
- 对前瞻 regime 转移表达弱
- 对参数拆解与解释支持弱于方案 B

### 3.6 为什么不能做“五种模型简单平均”

`v1.4` 明确禁止：

- `primary + challenger + stress` 简单平均
- `student_t / bootstrap / regime / jump / stress` 多模型加权平均成一个主概率

原因是：

1. **不同模型承担不同角色，不是同类预测器**
   - primary 是主结果
   - challenger 是对照器
   - stress 是尾部放大器

2. **简单平均会破坏 formal truth 语义**
   - 用户会误以为“主概率来自一个统一引擎”
   - 实际上平均会把对照器和 stress 混入主结果

3. **平均会隐藏模型分歧**
   - 而 `v1.4` 的目标正是把模型分歧显式暴露出来

正式机制固定为：

```text
Primary output = primary recipe only
Confidence adjustment = f(primary, challenger disagreement, stress gap)
Range widening = primary range widened by disagreement/stress evidence
```

不允许：

```text
published_probability = mean(primary, challenger, stress)
```

---

## 4. Success Event 的严格定义

`v1.4` 的成功率不是自由概念，必须绑定统一的事件定义。所有以下模块都必须引用**同一份** `SuccessEventSpec`：

- probability engine
- calibration / replay
- decision card
- Claw explain

### 4.1 对象定义

```python
@dataclass
class SuccessEventSpec:
    horizon_days: int
    horizon_months: int
    target_type: str              # goal_amount / annual_return / benchmark_outperform
    target_value: float
    drawdown_constraint: float | None
    benchmark_ref: str | None
    contribution_policy: str      # scheduled_fixed / scheduled_variable / none
    withdrawal_policy: str        # none / scheduled / stochastic
    rebalancing_policy_ref: str
    return_basis: str             # nominal / real
    fee_basis: str                # net / gross
    success_logic: str            # terminal_only / joint_target_and_drawdown / benchmark_relative
```

### 4.2 v1.4 默认 formal success 事件

默认 formal success 定义为：

```text
在 horizon 结束时，组合净值达到目标终值，
且整个路径的最大回撤不超过用户声明阈值，
并按约定贡献计划持续投入、按正式再平衡策略执行，
收益口径为 nominal net-of-fees。
```

### 4.3 默认 success 公式

若：

- `V_T` = 期末净值
- `G*` = 目标期末净值
- `MDD(path)` = 路径最大回撤
- `DD*` = 用户最大可接受回撤

则默认 success 指示变量：

```text
I_success(path) = 1{ V_T >= G* and MDD(path) <= DD* }
```

成功率：

```text
Pr(success) = (1 / P) * Σ_{p=1..P} I_success(path_p)
```

其中：

- `P` = 模拟路径条数

### 4.4 禁止的歧义

以下歧义在 `v1.4` 中禁止出现：

- Monte Carlo 计算“达到目标终值”
- Claw 解释成“年化收益达标”
- calibration 回放按“胜过 benchmark”
- frontdesk 又把 success 理解成“不亏钱”

`SuccessEventSpec` 必须进入：

- `ProbabilityEngineInput`
- `ProbabilityEngineOutput`
- `CalibrationReplaySpec`
- `DecisionCard.probability_explanation`

### 4.5 `v1.4` 到现有 formal surface 的冻结映射

`v1.4` 不重新发明对外结果语义。它必须桥接到 `v1.3` 已存在的 formal surface：

- `run_outcome_status`
- `resolved_result_category`
- `DisclosureDecision`
- `EvidenceBundle`
- `product_probability_method`
- `formal_path_visibility`

固定映射如下：

| `v1.4` 内部对象 | 既有 formal surface |
| --- | --- |
| `primary_result.success_probability` | `success_probability_point` |
| `primary_result.success_probability_range` | `success_probability_range` |
| `primary_result.recipe_name` | `simulation_recipe_primary` |
| `challenger_results[*]` | `model_comparison.challengers` |
| `stress_results[*]` | `model_comparison.stresses` |
| `model_disagreement` | `EvidenceBundle.model_disagreement` |
| `success_event_spec` | `EvidenceBundle.success_event_spec` |
| `daily path evidence` | `EvidenceBundle.daily_simulation_evidence` |
| `factor mapping evidence` | `EvidenceBundle.factor_mapping_summary` |

`product_probability_method` 必须由引擎结果规范化映射得到，禁止自由文本：

```text
if primary recipe is daily product path and observed coverage == 1.0:
    product_probability_method = product_independent_path
elif primary recipe is daily product path and observed coverage < 1.0 but estimated path is admissible:
    product_probability_method = product_estimated_path
elif primary result depends on proxy/synthetic substitute:
    product_probability_method = product_proxy_path
else:
    product_probability_method = hybrid_independent_estimate
```

### 4.6 Formal 资格矩阵与降级矩阵

这是 `v1.4` 的冻结 contract，后续实现不得自定义。

关键资格维度：

- `daily_product_path_available`
- `monthly_fallback_used`
- `bucket_fallback_used`
- `independent_weight_adjusted_coverage`
- `observed_weight_adjusted_coverage`
- `factor_mapping_confidence`
- `distribution_readiness`
- `calibration_quality`

#### 4.6.1 `FORMAL_STRICT`

| 条件 | 门槛 | 不满足时 |
| --- | --- | --- |
| `daily_product_path_available` | 必须为 `true` | `null` |
| `monthly_fallback_used` | 必须为 `false` | `null` |
| `bucket_fallback_used` | 必须为 `false` | `null` |
| `independent_weight_adjusted_coverage` | `= 1.0` | `formal_estimated_result` 或 `degraded_formal_result` |
| `observed_weight_adjusted_coverage` | `>= 0.95` | `degraded_formal_result` |
| `factor_mapping_confidence` | `>= medium` | `degraded_formal_result` |
| `distribution_readiness` | `ready` | `degraded_formal_result` |
| `calibration_quality` | `strong / acceptable` | `degraded_formal_result` |

#### 4.6.2 `FORMAL_ESTIMATION_ALLOWED`

| 条件 | 门槛 | 不满足时 |
| --- | --- | --- |
| `daily_product_path_available` | 必须为 `true` | `null` |
| `monthly_fallback_used` | 必须为 `false` | `null` |
| `bucket_fallback_used` | 必须为 `false` | `null` |
| `observed_weight_adjusted_coverage` | `>= 0.60` | `degraded_formal_result` |
| `estimated_weight_adjusted_coverage` | `<= 0.40` | `degraded_formal_result` |
| `factor_mapping_confidence` | `>= low` | `degraded_formal_result` |
| `distribution_readiness` | `partial` 及以上 | `degraded_formal_result` |
| `calibration_quality` | `weak` 及以上 | `degraded_formal_result` |

#### 4.6.3 固定降级矩阵

| 触发原因 | `resolved_result_category` | `disclosure_level` |
| --- | --- | --- |
| 无日频逐产品主路径 | `null` | `unavailable` |
| 命中月级/桶级 fallback | `null` | `unavailable` |
| independent 覆盖不足但 estimated 仍可成立 | `formal_estimated_result` | `range_only` |
| 映射/分布/校准不足但仍存在主结果 | `degraded_formal_result` | `range_only` |
| primary/challenger/stress 全不可用 | `null` | `diagnostic_only` |

---

## 5. 五层随机特征：产品不是“选一个模型”，而是多层特征叠加

`v1.4` 明确：一个产品不是“从五种模型中选一种”，而是同时拥有五层随机特征。

### 5.1 五层

1. **创新分布层**
   - 该产品/因子的标准化创新使用什么分布
   - 例如 `student_t`

2. **条件波动层**
   - 波动是否具有聚集性
   - 例如 `GARCH(1,1)`

3. **依赖结构层**
   - 产品共同风险如何联动
   - 在 `v1.4` 中通过因子层 DCC 体现

4. **跳跃层**
   - 是否可能出现系统性或产品特异性离散跳变

5. **状态层**
   - 当前位于何种 regime
   - 各层参数如何被 regime 条件化

### 5.2 对产品的含义

一个产品 `i` 在 `t -> t+1` 的收益不是“用一个名字叫 GARCH 的模型算出来”，而是：

```text
创新分布   -> 决定 eps_i,t+1 的尾部
条件波动   -> 决定 h_i,t+1
依赖结构   -> 决定共同因子冲击 f_t+1
跳跃层     -> 决定 J_sys,i,t+1 和 J_idio,i,t+1
状态层     -> 决定均值、波动、jump 概率和 DCC 参数所在区间
```

因此同一个产品可以同时表现为：

- `student_t` 厚尾
- `garch_t` 波动聚集
- 因子层相关抬升
- systemic jump 暴露
- `risk_off` regime 下均值下调、波动上调

### 5.3 Recipe 只是五层组合，不是单层名字

因此一个 recipe 应该写成五层组合，例如：

```text
primary_recipe
= student_t innovation
+ garch_t volatility
+ factor_dcc dependence
+ systemic_plus_idio_jump
+ markov_regime
```

而不是：

```text
simulation_mode = "garch_t_dcc_jump"
```

后者只能作为兼容标签，不应再作为内部设计中心。

---

## 6. Primary / Challenger / Stress 机制

### 6.1 Primary

Primary 必须回答：

- 正式主成功率
- 正式主收益区间
- 正式主路径统计

`v1.4` primary 固定是**方案 B**。

### 6.2 Challenger

Challenger 必须回答：

- 若保留真实历史路径结构，主模型是否显著偏乐观
- 在相同 `SuccessEventSpec` 下，primary 与经验路径结果差多少

`v1.4` challenger 固定是**方案 C**。

### 6.3 Stress

Stress 不是另一个“候选真相”，而是尾部视图：

- 放大 systemic jump
- 放大 regime persistence
- 放大 tail thickness

它只负责：

- tail loss
- downside percentile
- stressed drawdown

### 6.4 三者关系

主输出规则：

```text
published_point = primary_only
published_range = widen(primary_range, challenger_gap, stress_gap)
confidence_level = g(primary evidence, challenger disagreement, stress sensitivity, calibration quality)
```

### 6.5 不允许的行为

- challenger 覆盖 primary
- stress 覆盖 primary
- three-way average
- challenger 成功率被当成主成功率

### 6.6 分歧到披露的固定函数

`v1.4` 不允许把“模型分歧如何影响披露”留给实现者自由决定。

定义：

- `p_primary`：primary 成功率
- `p_chal_best`：可用 challenger 中与 primary 偏差最大的成功率
- `p_stress`：stress 成功率
- `gap_chal = |p_primary - p_chal_best|`
- `gap_stress = max(0, p_primary - p_stress)`
- `gap_total = max(gap_chal, gap_stress)`

若 primary 原始区间为 `[L_primary, U_primary]`，则正式披露区间固定为：

```text
L_publish = max(0, L_primary - 0.5 * gap_total)
U_publish = min(1, U_primary + 0.5 * gap_total)
```

置信度下调规则固定为：

| `gap_total` | 置信度调整 |
| --- | --- |
| `< 0.03` | 不下调 |
| `0.03 <= gap_total < 0.07` | 下调一级 |
| `>= 0.07` | 直接降为 `low` |

这条规则必须由引擎层生成，不能由 UI、decision card、Claw 层二次解释。

---

## 7. 方案 B：产品边际 + 因子联合 + 产品残差

### 7.1 单产品收益方程

产品 `i` 在日 `t+1` 的净收益定义为：

```text
r_i,t+1
= μ_i(S_t)
+ β_i,t' f_t+1
+ u_i,t+1
+ J_sys,i,t+1
+ J_idio,i,t+1
- c_i,t+1
```

其中：

- `μ_i(S_t)`：regime 条件化后的产品确定性漂移项
- `β_i,t`：产品对因子向量的暴露
- `f_t+1`：因子收益向量
- `u_i,t+1`：产品 idiosyncratic 残差项
- `J_sys,i,t+1`：系统 jump 传导到产品的冲击
- `J_idio,i,t+1`：产品自身 jump
- `c_i,t+1`：费用、跟踪误差、流动性拖累等成本项

### 7.2 产品残差

```text
u_i,t+1 = sqrt(h_i,t+1) * eps_i,t+1
eps_i,t+1 ~ StudentT(df_i)
```

### 7.3 产品条件波动

默认使用 `GARCH(1,1)`：

```text
h_i,t+1 = ω_i(S_t) + α_i(S_t) * u_i,t^2 + β_i(S_t) * h_i,t
```

约束：

```text
ω_i > 0
α_i >= 0
β_i >= 0
α_i + β_i < 1
```

### 7.4 因子共同项

因子收益向量：

```text
f_t+1 = m(S_t) + H_t+1^{1/2} R_t+1^{1/2} z_t+1 + J_factor,t+1
```

其中：

- `m(S_t)`：regime 条件化因子均值
- `H_t+1`：因子条件方差对角矩阵
- `R_t+1`：因子相关矩阵
- `z_t+1`：标准化因子创新
- `J_factor,t+1`：因子层系统 jump

### 7.5 系统 jump 传导到产品

若因子 jump 冲击向量为 `L_sys,t+1`，产品对 jump 的敏感度向量为 `γ_i`，则：

```text
J_sys,i,t+1 = M_sys,t+1 * γ_i' L_sys,t+1
```

其中：

- `M_sys,t+1 ~ Bernoulli(p_sys(S_t))`

### 7.6 产品特异 jump

```text
J_idio,i,t+1 = M_idio,i,t+1 * L_idio,i,t+1
M_idio,i,t+1 ~ Bernoulli(p_idio,i(S_t))
L_idio,i,t+1 ~ JumpLossDist_i
```

### 7.7 成本项

```text
c_i,t+1
= fee_drag_i / trading_days_per_year
+ tracking_drag_i,t+1
+ liquidity_drag_i,t+1
+ fx_hedging_drag_i,t+1
```

### 7.8 方案 B 的核心优点

- 产品路径是逐产品的，不是桶级平均
- 共同依赖结构被压缩到因子层，避免全产品联合爆炸
- 残差项保留产品特异风险
- jump 和 regime 都可显式进方程
- 因子映射让新产品接入可控

---

## 8. 方案 C：真实历史 regime-conditioned bootstrap

### 8.1 定义

方案 C 的核心不是“再拟一遍参数”，而是：

> 使用真实产品历史日收益路径，在 regime 条件下做 block bootstrap，生成 challenger 路径。

### 8.2 输入

- 产品历史日收益序列 `r_i,τ`
- 每个历史日的 regime 标签 `S_τ`
- 当前时点的 regime `S_t`
- block size `B`
- path horizon `T`

### 8.3 路径生成

对每条 challenger 路径：

1. 根据当前 `S_t` 选出 regime 相近的历史日集合 `Ω(S_t)`
2. 在 `Ω(S_t)` 中按 block size `B` 抽连续块
3. 按顺序拼接成长度 `T` 的未来产品日收益序列
4. 将同样的 contribution / withdrawal / rebalancing policy 注入组合层

### 8.4 block bootstrap 数学形式

记 `b_k` 为第 `k` 个历史块，块内长度为 `B`：

```text
b_k = { r_{·,τ_k}, r_{·,τ_k+1}, ..., r_{·,τ_k+B-1} }
```

组合后的 challenger 路径：

```text
path_C = concat(b_1, b_2, ..., b_m)[:T]
```

### 8.5 方案 C 的作用

它天然保留：

- 厚尾
- 波动聚集
- 连续回撤段
- 历史联合崩跌

所以 challenger 主要用来回答：

- primary 是否低估了路径依赖
- primary 是否压平了尾部
- primary 的 regime 迁移是否过于平滑

### 8.6 为什么 C 不是 primary

- 对前瞻 regime 演化表达较弱
- 对新产品、短历史产品覆盖较差
- 对 explanatory decomposition 支持较弱
- 对反事实调参不如参数模型灵活

---

## 9. 因子体系设计

### 9.1 什么是因子

`v1.4` 中的因子是：

> 一组可观测、可交易、可日频跟踪、能共同驱动多个产品收益变化的低维风险源。

因子不是产品桶，不是主题标签，也不是静态分类名。
它必须满足：

- 有日频收益序列
- 能映射多个产品
- 能进入依赖结构建模
- 能被解释层引用

### 9.2 为什么需要因子层

没有因子层，系统只剩两个坏选择：

1. 全产品联合建模
2. 产品彼此近似独立

因子层的作用是：

- 在低维空间承载共同风险
- 给 DCC 提供可估计的对象
- 给产品映射提供统一桥梁
- 支撑 explanation 层回答“共同风险来自哪里”

### 9.3 为什么先定 10 个左右

第一版不是追求覆盖所有细节风格，而是先满足 formal engine 的稳定性。

选择 `~10` 个因子的原因：

1. `K` 在 `8-12` 时，DCC 可估计、可缓存、可解释
2. 当前产品宇宙大头能被这组因子覆盖
3. 因子数量过多会把 DCC 和映射稳定性一起拖垮
4. 对 challenger 和 stress 的对照仍足够敏感

### 9.4 初始因子字典

第一版固定约 10 个工程因子：

- `CN_EQ_BROAD`
- `CN_EQ_GROWTH`
- `CN_EQ_VALUE`
- `US_EQ_BROAD`
- `US_EQ_GROWTH`
- `HK_EQ_BROAD`
- `CN_RATE_DURATION`
- `CN_CREDIT_SPREAD`
- `GOLD_GLOBAL`
- `USD_CNH`

### 9.5 参考来源

因子设计参考以下公开框架：

- Sharpe return-based style analysis
- Ken French Data Library
- MSCI Barra / Axioma factor risk model 思路

保留的参考链接：

- https://web.stanford.edu/~wfsharpe/art/sa/sa.htm
- https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- https://www.msci.com/data-and-analytics/factor-investing/equity-factor-models
- https://www.simcorp.com/solutions/strategic-solutions/axioma-solutions/axioma-factor-risk-models/Axioma-Equity-Factor-Risk-Models

这些来源不是要求系统直接复制参数，而是作为：

- 因子定义
- 暴露解释
- 风险分解
- 低维共同风险建模

的设计参考。

---

## 10. 产品到因子的映射：四段式

`v1.4` 不允许“纯手工映射”或“纯回归映射”作为唯一来源。正式映射必须走四段式：

1. 结构先验
2. 持仓穿透
3. 收益回归
4. shrinkage 融合

### 10.1 结构先验

基于：

- 跟踪指数
- 资产类型
- 产品说明书
- wrapper 类型
- 官方标签

给出 `beta_prior`

示例：

- `CSI300 ETF`
  - `CN_EQ_BROAD = 0.95`
- `Gold ETF`
  - `GOLD_GLOBAL = 0.95`
- `中短债 ETF`
  - `CN_RATE_DURATION = 0.70`
  - `CN_CREDIT_SPREAD = 0.25`

### 10.2 持仓穿透

如果有 holdings：

```text
β_i,holdings = Σ_j weight_{i,j} * β_j,security
```

如果穿透覆盖率不足，例如 `< 0.70`，则 holdings 证据权重必须被压低。

### 10.3 收益回归

对产品日收益回归：

```text
r_i,t = α_i + B_i' f_t + e_i,t
```

主窗口：

- 252 个交易日

最低正式窗口：

- 126 个交易日

推荐使用指数衰减权重，半衰期 `63` 日。

可采用加权岭回归：

```text
min_B Σ_t w_t (r_i,t - α_i - B_i' f_t)^2 + λ ||B_i - B_i,prior||^2
```

### 10.4 shrinkage 融合

最终暴露：

```text
β_i,raw = w_prior,i β_i,prior + w_holdings,i β_i,holdings + w_returns,i β_i,returns
```

满足：

```text
w_prior,i + w_holdings,i + w_returns,i = 1
w_* >= 0
```

再对 `β_i,raw` 做 shrinkage：

```text
β_i,final = λ_i β_i,raw + (1 - λ_i) β_i,anchor
```

其中：

- `β_i,anchor`：结构先验或同类产品簇均值
- `λ_i`：由证据质量决定

### 10.5 权重建议

```text
w_holdings ∝ holdings_freshness * holdings_coverage
w_returns  ∝ regression_stability * history_length_score
w_prior    = 1 - (w_holdings + w_returns)
```

### 10.6 正式输出

每个产品必须输出：

- `factor_mapping_source`
- `factor_mapping_confidence`
- `factor_mapping_evidence`
- `beta_prior`
- `beta_holdings`
- `beta_returns`
- `beta_final`

---

## 11. 分层状态与公式

### 11.1 创新分布层

默认创新分布为 `Student-t`，不再把高斯作为 formal 主分布。

标准化残差：

```text
z_t = (r_t - μ_t) / sqrt(h_t)
```

拟合 `tail_df`：

```text
z_t ~ StudentT(df)
```

建议：

- `df < 3` 视为不稳定，需要裁剪
- `df > 30` 可近似正态，但内部仍保留 `student_t` 家族标签

### 11.2 条件波动层：GARCH

对每个因子 `k`：

```text
h_{k,t+1} = ω_k(S_t) + α_k(S_t) ε_{k,t}^2 + β_k(S_t) h_{k,t}
```

对每个产品 `i`：

```text
h_{i,t+1} = ω_i(S_t) + α_i(S_t) u_{i,t}^2 + β_i(S_t) h_{i,t}
```

### 11.3 依赖结构层：DCC

对因子标准化残差 `z_t`：

```text
Q_{t+1} = (1 - a - b) Q̄ + a z_t z_t' + b Q_t
```

归一化得到相关矩阵：

```text
R_{t+1} = D_{t+1}^{-1/2} Q_{t+1} D_{t+1}^{-1/2}
```

其中 `D_{t+1}` 为 `Q_{t+1}` 对角元素构成的对角矩阵。

### 11.4 跳跃层

系统 jump 触发：

```text
M_sys,t+1 ~ Bernoulli(p_sys(S_t))
```

系统 jump 损失向量：

```text
L_sys,t+1 ~ F_sys_jump(S_t)
```

产品系统 jump：

```text
J_sys,i,t+1 = M_sys,t+1 * γ_i' L_sys,t+1
```

产品个体 jump：

```text
M_idio,i,t+1 ~ Bernoulli(p_idio,i(S_t))
L_idio,i,t+1 ~ F_idio,i(S_t)
J_idio,i,t+1 = M_idio,i,t+1 * L_idio,i,t+1
```

### 11.5 状态层：regime 转移

设 regime 集合为 `{1, ..., M}`，当前状态为 `S_t`，转移矩阵为 `Π`：

```text
Pr(S_{t+1}=j | S_t=i) = Π_{ij}
```

不同 regime 下可条件化：

- 因子均值 `m(S_t)`
- 因子波动参数 `ω_k, α_k, β_k`
- 产品波动参数 `ω_i, α_i, β_i`
- jump 概率 `p_sys(S_t), p_idio,i(S_t)`

### 11.6 因子映射 shrinkage 融合公式

再次明确：

```text
β_i,final = λ_i ( w_prior,i β_i,prior + w_holdings,i β_i,holdings + w_returns,i β_i,returns )
          + (1 - λ_i) β_i,anchor
```

---

## 12. 日频逐产品模拟推演顺序

单条路径、单日步 `x -> x+1` 必须按下列顺序推进：

1. 采样 `S_{x+1}`
2. 更新因子 GARCH 状态
3. 更新因子 DCC 相关状态
4. 生成因子创新、因子收益
5. 判断 systemic jump
6. 对每个产品：
   - 更新产品 GARCH 状态
   - 生成产品残差创新
   - 判断产品 idio jump
   - 合成产品日收益
7. 合成组合日收益
8. 注入 contribution / withdrawal
9. 判断再平衡
10. 更新净值、权重、路径状态

禁止：

- 先按月聚合后再近似回写日级
- 先在桶级求收益再映射到产品

### 12.1 单日状态更新顺序合同

为避免实现时在 GARCH / DCC / jump 的顺序上各做各的，`v1.4` 冻结如下顺序：

1. 已知 `S_x`、`h_f,x`、`Q_x`、`h_i,x`
2. 采样 `S_{x+1}`
3. 在 `S_{x+1}` 条件下采样因子创新 `eps_f,x+1`
4. 生成因子收益 `f_{x+1}`
5. 用 **本步因子标准化残差** 更新 DCC，得到 `R_{x+1}`
6. 对每个产品：
   - 用上一期产品残差更新 `h_i,x+1`
   - 生成 pre-jump 残差项
   - 合成 pre-jump 产品收益
7. 在 pre-jump 产品收益上叠加：
   - systemic jump
   - idiosyncratic jump
8. 最后再扣：
   - fee
   - carry
   - tracking / liquidity cost
9. 合成组合收益并更新净值

附加边界：

- GARCH 更新只使用 **pre-jump** 残差
- jump 不反推进入同一步的波动更新
- cost/carry 一律在 jump 之后入账

---

## 13. 具体数值例子：day x -> day x+1

以下例子用于让实现者知道各层如何在一次日步中协同。

### 13.1 设定

组合当前包含 4 个产品：

- `cn_equity_dividend_etf`
- `cn_satellite_energy_etf`
- `cn_gold_etf`
- `cn_bond_gov_etf`

当前权重：

- `dividend = 0.40`
- `energy = 0.20`
- `gold = 0.20`
- `bond = 0.20`

当前净值：

- `V_x = 100.00`

当日净现金流：

- `contribution_{x+1} = 0.30`

当前 regime：

- `S_x = risk_off`

下一日 regime 转移矩阵的一行：

```text
Π(risk_off -> risk_off) = 0.70
Π(risk_off -> neutral)  = 0.25
Π(risk_off -> risk_on)  = 0.05
```

### 13.2 第一步：采样下一 regime

假设采样结果：

```text
S_{x+1} = risk_off
```

### 13.3 第二步：采样因子

简化后使用 4 个相关因子：

- `CN_EQ_BROAD`
- `CN_CREDIT_SPREAD`
- `GOLD_GLOBAL`
- `USD_CNH`

设 `risk_off` 下的因子条件均值：

```text
m = [-0.20%, -0.05%, +0.10%, +0.02%]
```

设当期因子波动（标准差）：

```text
σ = [1.20%, 0.35%, 0.80%, 0.25%]
```

设 DCC 给出的相关矩阵近似：

```text
R =
[[1.00, 0.35, -0.10, 0.15],
 [0.35, 1.00, -0.05, 0.10],
 [-0.10,-0.05, 1.00, 0.05],
 [0.15, 0.10, 0.05, 1.00]]
```

采样标准化创新后得到：

```text
f_{x+1} =
CN_EQ_BROAD      = -1.40%
CN_CREDIT_SPREAD = -0.30%
GOLD_GLOBAL      = +0.80%
USD_CNH          = +0.10%
```

### 13.4 第三步：systemic jump

设 `risk_off` 下：

```text
p_sys = 3%
```

本次触发了系统 jump，因子 jump 冲击向量：

```text
L_sys = [-1.00%, -0.20%, +0.10%, +0.00%]
```

### 13.5 第四步：产品层

#### 产品 1：红利 ETF

暴露：

```text
β_dividend = [0.90, 0.05, 0.00, 0.00]
```

共同项：

```text
β'f = 0.90*(-1.40%) + 0.05*(-0.30%) = -1.275%
```

产品 GARCH 更新后：

```text
sqrt(h_dividend,x+1) = 0.75%
```

采样 idio 创新：

```text
eps = -0.60
u = 0.75% * (-0.60) = -0.45%
```

系统 jump 敏感度：

```text
γ_dividend = [0.70, 0.10, 0.00, 0.00]
J_sys = 0.70*(-1.00%) + 0.10*(-0.20%) = -0.72%
```

本次无个体 jump，成本拖累 `0.01%`。

则：

```text
r_dividend,x+1
= 0.00%
+ (-1.275%)
+ (-0.45%)
+ (-0.72%)
+ 0.00%
- 0.01%
= -2.455%
```

#### 产品 2：能源 ETF

暴露：

```text
β_energy = [1.05, 0.15, 0.00, 0.05]
```

共同项：

```text
β'f = 1.05*(-1.40%) + 0.15*(-0.30%) + 0.05*(0.10%) = -1.51%
```

设残差项 `u = -0.80%`，系统 jump 传导 `-0.95%`，无 idio jump，成本 `0.02%`：

```text
r_energy,x+1 = -1.51% - 0.80% - 0.95% - 0.02% = -3.28%
```

#### 产品 3：黄金 ETF

暴露：

```text
β_gold = [0.00, 0.00, 0.95, 0.05]
```

共同项：

```text
β'f = 0.95*(0.80%) + 0.05*(0.10%) = +0.765%
```

设残差项 `+0.12%`，系统 jump 传导 `+0.05%`，无 idio jump，成本 `0.01%`：

```text
r_gold,x+1 = 0.765% + 0.12% + 0.05% - 0.01% = +0.925%
```

#### 产品 4：国债 ETF

暴露近似：

```text
β_bond = [0.00, -0.40, 0.00, 0.00]
```

共同项：

```text
β'f = -0.40 * (-0.30%) = +0.12%
```

设残差项 `-0.15%`，系统 jump 传导 `-0.01%`，成本 `0.01%`：

```text
r_bond,x+1 = 0.12% - 0.15% - 0.01% - 0.01% = -0.05%
```

### 13.6 第五步：组合收益和净值

组合日收益：

```text
r_p,x+1
= 0.40*(-2.455%)
+ 0.20*(-3.28%)
+ 0.20*(+0.925%)
+ 0.20*(-0.05%)
= -1.464%
```

净值更新：

```text
V_{x+1} = 100.00 * (1 - 1.464%) + 0.30 = 98.836
```

如果未触发再平衡，则持仓权重按新净值漂移；若触发再平衡，则按 policy 更新权重后进入 `x+1 -> x+2`。

这个例子展示了 `v1.4` 的顺序是：

```text
先 regime
再因子
再产品残差 / jump
再组合净值
```

不是先月级预期收益，再把月级结果摊回产品。

---

## 14. 代码架构设计

### 14.1 新模块

建议新增模块：

- `src/probability_engine/contracts.py`
  - 顶层输入输出 contract
- `src/probability_engine/success_event.py`
  - `SuccessEventSpec`
- `src/probability_engine/factor_library.py`
  - 因子定义、因子序列引用
- `src/probability_engine/factor_mapping.py`
  - 四段式映射与 shrinkage
- `src/probability_engine/regime.py`
  - regime 状态和转移
- `src/probability_engine/volatility.py`
  - 因子/产品 GARCH 状态
- `src/probability_engine/dependence.py`
  - DCC 接口和未来扩展接口
- `src/probability_engine/jumps.py`
  - systemic / idio jump
- `src/probability_engine/path_generator.py`
  - daily step 推进
- `src/probability_engine/portfolio_policy.py`
  - contribution / withdrawal / rebalance
- `src/probability_engine/recipes.py`
  - primary / challenger / stress recipe 定义与解析
- `src/probability_engine/challengers.py`
  - regime-conditioned bootstrap
- `src/probability_engine/disclosure_bridge.py`
  - 接到 `v1.3` 的 `DisclosureDecision / EvidenceBundle`

### 14.2 关键接口

```python
class FactorMappingBuilder(Protocol):
    def build(
        self,
        products: list["ProductRuntimeRecord"],
        factor_library: "FactorLibrarySnapshot",
        as_of: str,
    ) -> list["ProductMarginalSpec"]: ...


class ProbabilityStateCalibrator(Protocol):
    def calibrate(
        self,
        sim_input: "DailyProbabilityEngineInput",
    ) -> "CalibratedProbabilityState": ...


class RecipeRunner(Protocol):
    def run(
        self,
        calibrated_state: "CalibratedProbabilityState",
        recipe: "SimulationRecipe",
    ) -> "RecipeSimulationResult": ...


class DisclosureAssembler(Protocol):
    def assemble(
        self,
        primary: "RecipeSimulationResult",
        challengers: list["RecipeSimulationResult"],
        stresses: list["RecipeSimulationResult"],
        success_event_spec: "SuccessEventSpec",
    ) -> "ProbabilityEngineOutput": ...
```

### 14.3 与旧模块关系

#### 现有 `goal_solver`

`goal_solver` 在 `v1.4` 后不再负责：

- 直接生成概率路径
- 直接决定主 Monte Carlo 模式

它的角色改成：

- 提供目标与约束输入
- 消费 probability engine 输出的分布摘要
- 负责 candidate search、allocation search、frontier assembly

#### 现有 `calibration`

`calibration` 不再是“单一 market assumptions 输出器”，而是：

- 继续负责部分 baseline 校准
- 为 `probability_engine` 提供：
  - regime 输入
  - factor library refs
  - valuation state
  - evidence refs

#### 新的调用关系

```text
frontdesk / orchestrator
  -> build DailyProbabilityEngineInput
  -> probability_engine.factor_mapping
  -> probability_engine.state_calibrator
  -> probability_engine.recipe_runner(primary)
  -> probability_engine.recipe_runner(challenger)
  -> probability_engine.recipe_runner(stress)
  -> probability_engine.disclosure_bridge
  -> goal_solver / decision_card / frontdesk
```

### 14.4 DCC 未来扩展接口预留

`dependence.py` 不得把 DCC 写死成单实现。接口应允许未来扩展：

- `factor_level_dcc`
- `factor_block_dcc`
- `sparse_dcc`
- `copula_dependence`

接口建议：

```python
class DependenceProvider(Protocol):
    def initialize(self, factor_names: list[str], state: dict[str, Any]) -> Any: ...
    def update(self, standardized_factor_residual: list[float], prev_state: Any) -> Any: ...
    def current_correlation(self, state: Any) -> list[list[float]]: ...
    def dependency_scope(self) -> str: ...
```

### 14.5 Schema 冻结要求

以下对象在 `v1.4` 设计阶段即冻结，不再用“建议补字段”口吻解释：

- `SuccessEventSpec`
- `ProductMarginalSpec`
- `FactorDynamicsSpec`
- `RegimeStateSpec`
- `JumpStateSpec`
- `SimulationRecipe`
- `DailyProbabilityEngineInput`
- `RecipeSimulationResult`
- `ProbabilityEngineOutput`

后续如需扩展：

- 只允许新增可选字段
- 不允许删除本规格中已有必需字段
- 不允许改变既有字段语义

---

## 15. Formal 约束与禁止事项

### 15.1 只允许日频逐产品

formal path 下：

- 只能接受日频产品 return series
- 只能在产品层推进路径

### 15.2 明确禁止

formal path 禁止：

- 月级模拟 fallback
- 桶级模拟 fallback
- `product_overlay_on_bucket_mc`
- 无产品路径时退回 bucket success probability
- `static_gaussian` 作为 formal truth

### 15.3 对估计结果的边界

`v1.4` 仍兼容 `formal_estimated_result`，但必须满足：

- estimation basis 明确
- range-only 披露
- Evidence Bundle 中有 estimation evidence

估计结果不能拿来伪装成产品独立主结果。

---

## 16. 性能、复杂度与内存控制

### 16.1 复杂度符号

- `P`：路径条数
- `T`：未来交易日数
- `N`：参与模拟的产品数
- `K`：因子数

### 16.2 主要复杂度

#### 因子 GARCH + DCC

```text
O(P * T * K^2)
```

#### 产品共同项 + 残差项

```text
O(P * T * N * K)
```

#### 组合聚合

```text
O(P * T * N)
```

#### 总体主复杂度

```text
O(P * T * (K^2 + N*K + N))
≈ O(P * T * (K^2 + N*K))
```

### 16.3 为什么不能做全产品 DCC

若在产品层直接做 DCC，复杂度接近：

```text
O(P * T * N^2)
```

当：

- `N=500`

则单日相关更新就是 `250,000` 级别矩阵元素；
若 `N=5000`，则是 `25,000,000` 级别。
这还不包括参数估计、缓存、矩阵正定修复和路径存储成本。

因此 `v1.4` 强制：

- DCC 只在因子层做
- 产品只通过 `β_i` 接收共同项

### 16.4 缓存与复用

允许缓存：

- factor library snapshot
- factor return history
- mapping state
- GARCH 参数
- DCC 长期相关 `Q̄`
- regime transition matrix
- jump profiles

缓存 key 至少包含：

- `as_of`
- `product_universe_signature`
- `factor_library_signature`
- `valuation_signature`
- `history_revision`
- `mapping_revision`
- `probability_engine_revision`

### 16.5 向量化

必须优先在以下维度向量化：

- 路径维 `P`
- 因子维 `K`

避免：

- Python for-loop 同时跨 `P` 与 `N`

### 16.6 内存控制

不能默认持久化完整 `P * T * N` 路径张量。

formal 主路径只保留：

- success event statistics
- CAGR / drawdown / tail quantiles
- 少量审计 sample paths

完整路径仅允许：

- debug artifact
- replay artifact
- challenger 分歧诊断样本

### 16.7 性能不变量

任何性能优化不得在未声明情况下改变：

- `resolved_result_category`
- `product_probability_method`
- `disclosure_level`
- `confidence_level`
- `SuccessEventSpec`
- Evidence Bundle 的核心 semantic refs

换句话说：

> 性能优化可以改变执行方式，不能偷偷改变证据语义和正式输出含义。

### 16.8 Formal 性能门禁

为了让“性能可接受”不再是自由解释，冻结一组 formal 基线规模：

- `N = 48` 个产品
- `K = 10` 个因子
- `T = 756` 个交易日
- `P_primary = 4000`
- `P_challenger = 2000`
- `P_stress = 2000`

在该基线下，门禁固定为：

- primary 单独运行：`<= 20s`
- primary + challenger + stress：`<= 45s`
- 峰值内存：`<= 2.5GB`

若超出门禁，允许优化：

- state cache
- factor precompute
- path batching
- 审计样本裁剪

但不允许：

- 降低到月级
- 降低到桶级
- 移除某一建模层

---

## 17. 数据结构设计

### 17.1 产品边际规格

```python
@dataclass
class ProductMarginalSpec:
    product_id: str
    asset_bucket: str
    factor_betas: dict[str, float]
    innovation_family: str
    tail_df: float | None
    volatility_process: str
    garch_params: dict[str, float]
    idiosyncratic_jump_profile: dict[str, float]
    carry_profile: dict[str, float]
    valuation_profile: dict[str, float]
    mapping_confidence: str
    factor_mapping_source: str
    factor_mapping_evidence: list[str]
    observed_series_ref: str
```

### 17.2 因子动态规格

```python
@dataclass
class FactorDynamicsSpec:
    factor_names: list[str]
    factor_series_ref: str
    innovation_family: str
    tail_df: float | None
    garch_params_by_factor: dict[str, dict[str, float]]
    dcc_params: dict[str, float]
    long_run_covariance: dict[str, dict[str, float]]
    covariance_shrinkage: float
    calibration_window_days: int
```

### 17.3 regime 规格

```python
@dataclass
class RegimeStateSpec:
    regime_names: list[str]
    current_regime: str
    transition_matrix: list[list[float]]
    regime_mean_adjustments: dict[str, dict[str, float]]
    regime_vol_adjustments: dict[str, dict[str, float]]
    regime_jump_adjustments: dict[str, dict[str, float]]
```

### 17.4 jump 规格

```python
@dataclass
class JumpStateSpec:
    systemic_jump_probability_1d: float
    systemic_jump_impact_by_factor: dict[str, float]
    systemic_jump_dispersion: float
    idio_jump_profile_by_product: dict[str, dict[str, float]]
```

### 17.5 Recipe 定义

```python
@dataclass
class SimulationRecipe:
    recipe_name: str
    role: str                       # primary / challenger / stress
    innovation_layer: str
    volatility_layer: str
    dependency_layer: str
    jump_layer: str
    regime_layer: str
    estimation_basis: str
    dependency_scope: str
    path_count: int
```

### 17.6 主输入对象

```python
@dataclass
class DailyProbabilityEngineInput:
    as_of: str
    products: list[ProductMarginalSpec]
    factor_dynamics: FactorDynamicsSpec
    regime_state: RegimeStateSpec
    jump_state: JumpStateSpec
    current_positions: list[dict[str, Any]]
    contribution_schedule: list[dict[str, Any]]
    withdrawal_schedule: list[dict[str, Any]]
    rebalancing_policy: dict[str, Any]
    success_event_spec: SuccessEventSpec
    recipes: list[SimulationRecipe]
    evidence_bundle_ref: str
```

### 17.7 输出对象

```python
@dataclass
class RecipeSimulationResult:
    recipe_name: str
    role: str
    success_probability: float
    success_probability_range: tuple[float, float]
    cagr_range: tuple[float, float]
    drawdown_range: tuple[float, float]
    sample_count: int
    path_stats: dict[str, Any]
    calibration_link_ref: str | None


@dataclass
class ProbabilityEngineOutput:
    primary_result: RecipeSimulationResult
    challenger_results: list[RecipeSimulationResult]
    stress_results: list[RecipeSimulationResult]
    model_disagreement: dict[str, Any]
    probability_disclosure_payload: dict[str, Any]
    evidence_refs: list[str]
```

---

## 18. 测试与回归方案

### 18.1 单元测试

必须覆盖：

- 因子映射四段式与 shrinkage
- 因子/产品 GARCH 更新
- DCC 更新与相关矩阵归一化
- systemic / idio jump 触发
- regime 转移采样
- 单日步 path generation
- 组合净值更新

### 18.2 合同测试

必须锁住：

1. formal path 只能日频逐产品
2. 不允许月级 fallback
3. 不允许桶级 fallback
4. primary = 方案 B
5. challenger = 方案 C
6. challenger/stress 不能覆盖主结果
7. `SuccessEventSpec` 在 probability engine / calibration / decision card / Claw 中一致

### 18.3 数学正确性回归

固定 seed 回归：

- GARCH 更新后的均值与波动范围
- DCC 更新后的相关矩阵性质
- regime 转移分布
- jump 触发频率
- factor beta shrinkage 稳定性
- product-level path aggregation

建议比较：

- mean
- variance
- 5% / 50% / 95% quantiles
- event hit-rate

冻结容忍区间：

- 均值误差：`<= 3%` 相对偏差
- 方差误差：`<= 5%` 相对偏差
- 分位数误差：`<= 5%` 相对偏差
- success probability 误差：`<= 2pp`
- jump 命中率误差：`<= 1pp`

### 18.4 集成测试

必须覆盖：

1. `frontdesk -> orchestrator -> probability_engine -> decision_card`
2. `goal_solver` 消费 probability engine 输出后不再自行回退到月级/桶级
3. `challenger gap` 能进入 disclosure widening
4. `stress gap` 能进入 tail explanation

### 18.5 Claw 验收

Claw 必须能看到：

- `primary_recipe`
- `challenger_recipe`
- `stress_recipe`
- `product_probability_method`
- `success_event_spec`
- `factor_mapping_source`
- `mapping_confidence`
- `daily_simulation_evidence`
- `monthly_fallback_used=false`
- `bucket_fallback_used=false`

Claw 还必须看到：

- `run_outcome_status`
- `resolved_result_category`
- `DisclosureDecision`
- `EvidenceBundle.model_disagreement`
- `gap_total`
- `challenger_available`
- `stress_available`

### 18.6 回归场景

至少固定以下场景：

1. A 股红利 + 黄金 + 债券
2. A 股宽基 + 海外成长 + 黄金 + 债券
3. 高成长卫星受限场景
4. regime 切换场景
5. systemic jump 场景
6. 只有短历史产品的 degraded / estimated 场景

并冻结 fixture 组：

- 因子序列 fixture
- regime 标签 fixture
- 4 组产品组合 fixture
- 1 组短历史 degraded fixture
- 1 组高 stress jump fixture

这些 fixture 的 `source_ref` 与 `revision` 必须进入 `EvidenceBundle`。

---

## 19. 实施波次建议

### Wave 1：接口和约束落地

- 新建 `probability_engine/` 模块骨架
- 接入 `SuccessEventSpec`
- formal path 禁掉月级/桶级 fallback
- 接 recipe 角色 contract

### Wave 2：方案 B 主链

- 因子库
- 因子映射四段式
- 产品 GARCH
- 因子 GARCH + DCC
- primary path generator

### Wave 3：方案 C challenger

- regime-conditioned bootstrap
- challenger gap
- disclosure widening

### Wave 4：jump / stress / 回归

- systemic / idio jump
- stress recipe
- 数学回归
- Claw 验收固定化

---

## 20. 剩余风险点

`v1.4` 设计完成后，仍有这些实现风险需要在开发时重点盯：

1. **因子映射质量**
   - 新产品或资料缺失产品的 `beta_final` 稳定性仍可能不足

2. **短历史产品覆盖**
   - 方案 B 可通过结构先验 + shrinkage 接入，但 challenger 对短历史产品天然弱

3. **regime 定义漂移**
   - regime 标签若不稳定，会污染 primary 与 challenger 的比较

4. **jump 参数过拟合**
   - jump 触发频率和损失分布如果样本太少，容易把 tail 放大得过头

5. **性能与语义不变性的冲突**
   - cache / top-K / sample thinning 若处理不当，会悄悄改变 formal 输出

这些风险不否定设计方向，但必须在实现时用测试和 Evidence Bundle 约束住。

---

## 21. 一句话结论

`v1.4` 不是“再加几个 mode”，而是把概率引擎改造成：

> 一个以日频逐产品路径为核心、以方案 B 为主模型、以方案 C 为 challenger、以因子层承接共同依赖、以 jump 和 regime 提供尾部与状态真实性、并明确禁止月级与桶级 fallback 的正式概率系统。
