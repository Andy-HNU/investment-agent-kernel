# CODEX v1.4 Daily Product Probability Engine Design

日期：2026-04-09

作者：Codex

状态：design-approved draft

读者：开发、审阅、测试、产品 owner、Claw/OpenClaw 验收操作者

---

## 1. 文档定位

`v1.4` 是在 `v1.3` 可信输出治理完成后的下一阶段重构：

- `v1.3` 解决的是结果语义、证据等级、formal/degraded/failure、formal path 治理
- `v1.4` 解决的是概率引擎本体：**日频、逐产品、多层随机过程建模**

本设计稿是 `v1.4` 的主规格，目标不是再往旧 `simulation_mode` 体系上打补丁，而是把当前“单一 mode + 局部 product overlay”的架构重构为：

- 逐产品日频模拟
- 多层随机过程
- primary / challenger / stress 模型分工
- 无月级 fallback
- 无桶级 fallback

---

## 2. 目标与非目标

### 2.1 目标

`v1.4` 必须同时满足：

1. 所有 formal / Claw truth 概率均基于**日频逐产品**模拟
2. 不允许回退到月级 Monte Carlo
3. 不允许回退到桶级 Monte Carlo
4. 一个产品可同时具有：
   - 厚尾
   - 条件波动聚集
   - regime 敏感性
   - jump 风险
5. 模型结构支持：
   - primary model
   - challenger model
   - stress model
6. `DCC` 必须在可扩展的低维依赖结构上实现，而不是把几千产品直接做全连接

### 2.2 非目标

`v1.4` 不处理：

- 自动下单
- 盘中高频/分钟级模拟
- 券商直连
- 税务精算
- 完整衍生品 Greeks / options surface
- 跨租户分布式并行优化

---

## 3. v1.4 核心结论

### 3.1 主方案

`v1.4` 采用：

- **方案 B 作为 primary**
  - 产品边际 + 因子联合 + 产品残差
- **方案 C 作为 challenger**
  - 真实历史 regime-conditioned bootstrap

### 3.2 为什么不是方案 A

方案 A 是“全产品联合状态空间模型”。它的问题不是理论错误，而是：

- 全产品 DCC 维度爆炸
- 参数估计不稳
- 工程复杂度高
- formal 路径极难持续校准

`v1.4` 第一版不采用方案 A 作为主架构。

### 3.3 为什么方案 C 不是主模型

纯经验历史路径很有价值，但不适合作为唯一主引擎，因为：

- 对前瞻 regime 转移表达弱
- 对新产品、短历史产品覆盖弱
- 对解释层支持不如参数化模型

所以 `v1.4` 的正式角色分工是：

- **Primary**：方案 B
- **Challenger**：方案 C
- **Stress**：重尾/跳跃强化配方

---

## 4. 总体架构抽象设计

`v1.4` 将概率引擎拆成五层，而不再把 `student_t / garch_t / dcc / jump / regime` 当成互斥整包模型。

### 4.1 五层结构

1. **创新分布层**
   - `gaussian`
   - `student_t`
   - `empirical_residual`

2. **条件波动层**
   - `static`
   - `garch_t`

3. **依赖结构层**
   - `static_corr`
   - `dcc`

4. **跳跃层**
   - `none`
   - `systemic_plus_idio_jump`

5. **状态层**
   - `none`
   - `markov_regime`

### 4.2 运行角色

一次 formal run 不再只有“一个 simulation_mode”，而是一个 **SimulationRecipe**：

- `primary_recipe`
- `challenger_recipes`
- `stress_recipes`

每个 recipe 都是由上述五层组合而成。

### 4.3 默认角色

`v1.4` 默认角色固定如下：

- `primary_recipe`
  - `student_t + garch_t + dcc + jump + regime`
- `challenger_recipe`
  - `regime_switching_bootstrap`
- `baseline_recipe`
  - `historical_block_bootstrap`
- `stress_recipe`
  - `student_t + garch_t + dcc + amplified_jump + stressed_regime`

### 4.4 不允许的做法

以下做法在 `v1.4` formal 路径中禁止：

- 直接对几千产品做全产品 DCC
- challenger 结果直接覆盖 primary
- 把 5 种 recipe 简单平均成一个成功率
- 月级模拟作为日频失败时的 fallback
- 桶级模拟作为逐产品失败时的 fallback

---

## 5. 产品层、因子层、组合层的职责划分

### 5.1 产品层

产品层负责：

- 产品自身日频收益序列
- 产品边际分布
- 产品条件波动
- 产品 idiosyncratic jump
- 产品到因子的暴露

### 5.2 因子层

因子层负责：

- 共同驱动器的日频收益过程
- 因子 DCC
- regime 依赖均值/协方差
- systemic jump

### 5.3 组合层

组合层负责：

- 逐产品收益合成
- 现金流
- 再平衡
- 路径聚合
- 成功事件评估

---

## 6. 因子体系设计

### 6.1 因子的定义

这里的因子是：

> 一组可观测、可交易、日频可追踪、能共同驱动多个产品收益变化的基础风险源。

因子不是桶，也不是抽象标签，而是日频风险驱动序列。

### 6.2 v1.4 初始因子字典

第一版固定为 10 个左右的工程因子：

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

### 6.3 为什么先用 10 个

不是因为理论上“10 最优”，而是因为：

1. 覆盖当前产品宇宙足够
2. 因子层 DCC 在该维度下可稳健估计
3. 日频回归与校准复杂度可控
4. 解释性对用户仍可接受

后续允许扩到 `12-15`，但 `v1.4` 不以扩因子数量为目标。

### 6.4 因子的参考来源

`v1.4` 因子体系参考：

- Sharpe 的 return-based style analysis
- Ken French Data Library 的公开因子与组合序列
- MSCI Barra / Axioma 的 factor risk model 思路

参考链接：

- https://web.stanford.edu/~wfsharpe/art/sa/sa.htm
- https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- https://www.msci.com/data-and-analytics/factor-investing/equity-factor-models
- https://www.msci.com/www/research-report/developing-an-equity-factor/018871486
- https://www.simcorp.com/solutions/strategic-solutions/axioma-solutions/axioma-factor-risk-models/Axioma-Equity-Factor-Risk-Models

---

## 7. 产品到因子的映射设计

### 7.1 总原则

产品到因子的映射不能只靠手工，也不能只靠纯回归。

`v1.4` 采用四段式：

1. 结构先验
2. 持仓穿透
3. 收益回归
4. shrinkage 融合

### 7.2 结构先验

根据：

- 跟踪指数
- 产品说明书
- 资产类型
- 官方标签

给出初始暴露。

示例：

- `CSI300 ETF`
  - `CN_EQ_BROAD = 0.95`
- `Gold ETF`
  - `GOLD_GLOBAL = 0.95`
- `Short Bond ETF`
  - `CN_RATE_DURATION = 0.75`
  - `CN_CREDIT_SPREAD = 0.20`

### 7.3 持仓穿透

若有持仓数据：

- 先把底层持仓证券映射到因子
- 再按持仓权重汇总成产品暴露

适用：

- ETF
- LOF
- QDII
- 混合基金

### 7.4 收益回归

在日频层做：

```text
r_product,t = alpha + B * f_t + residual_t
```

设定：

- 主窗口：`252` 交易日
- 最小正式窗口：`126` 交易日
- 使用时间衰减或滚动估计
- 可加稀疏约束或稳定性正则

### 7.5 shrinkage 融合

最终暴露：

```text
beta_final
= w_prior * beta_prior
+ w_holdings * beta_holdings
+ w_return * beta_regression
```

权重由证据质量决定：

- 持仓透明度
- 持仓新鲜度
- 回归稳定性
- 产品历史长度
- 产品风格漂移程度

### 7.6 formal 约束

必须输出：

- `factor_mapping_source`
- `factor_mapping_confidence`
- `factor_mapping_evidence`

若映射证据不足：

- `FORMAL_STRICT`：不得给 `formal_independent_result`
- `FORMAL_ESTIMATION_ALLOWED`：最多给 `formal_estimated_result`

---

## 8. 分层建模设计

### 8.1 产品边际层

每个产品维护：

- 创新分布：`gaussian / student_t / empirical`
- 条件波动：`static / garch_t`
- 个体 jump：`jump_prob_1d / jump_loss_distribution`
- 因子暴露
- 产品成本与跟踪拖累

### 8.2 因子动态层

因子层负责：

- 因子条件均值
- 因子条件协方差
- DCC 动态相关
- regime 转移
- systemic jump

### 8.3 组合构造层

根据产品日收益：

- 计算组合日收益
- 注入现金流
- 判断再平衡
- 更新组合权重与净值

### 8.4 模型比较层

比较：

- primary vs challenger
- primary vs stress

输出：

- 模型分歧
- 区间加宽
- 置信度下调

---

## 9. 核心数据结构设计

### 9.1 产品边际规格

```python
@dataclass
class ProductMarginalSpec:
    product_id: str
    factor_betas: dict[str, float]
    innovation_family: str
    tail_df: float | None
    volatility_process: str
    garch_params: dict[str, float]
    idiosyncratic_jump_profile: dict[str, float]
    carry_profile: dict[str, float]
    valuation_profile: dict[str, float]
    residual_cluster: str | None
    mapping_confidence: str
    evidence_refs: list[str]
```

### 9.2 因子动态规格

```python
@dataclass
class FactorDynamicsSpec:
    factor_names: list[str]
    mean_process: str
    covariance_process: str
    innovation_family: str
    tail_df: float | None
    dcc_params: dict[str, float]
    garch_params_by_factor: dict[str, dict[str, float]]
    long_run_covariance: dict[str, dict[str, float]]
```

### 9.3 regime 状态规格

```python
@dataclass
class RegimeStateSpec:
    regime_names: list[str]
    current_regime: str
    transition_matrix: list[list[float]]
    regime_mean_adjustments: dict[str, dict[str, float]]
    regime_vol_adjustments: dict[str, dict[str, float]]
```

### 9.4 jump 状态规格

```python
@dataclass
class JumpStateSpec:
    systemic_jump_probability_1d: float
    systemic_jump_impact_by_factor: dict[str, float]
    systemic_jump_dispersion: float
```

### 9.5 Recipe 定义

```python
@dataclass
class SimulationRecipe:
    recipe_name: str
    role: str                  # primary / challenger / stress
    innovation_layer: str
    volatility_layer: str
    dependency_layer: str
    regime_layer: str
    jump_layer: str
```

### 9.6 主输入对象

```python
@dataclass
class DailySimulationInput:
    as_of: str
    products: list[ProductMarginalSpec]
    factor_dynamics: FactorDynamicsSpec
    regime_state: RegimeStateSpec
    jump_state: JumpStateSpec
    current_positions: list[dict[str, Any]]
    contribution_schedule: list[dict[str, Any]]
    rebalancing_policy: dict[str, Any]
    success_event_spec: SuccessEventSpec
    recipes: list[SimulationRecipe]
```

---

## 10. 每层的计算与参数估计规则

### 10.1 创新分布层

#### 目标

给每个产品或因子提供：

- 厚尾能力
- 对极端收益更真实的尾部

#### 计算

- 默认用 `student_t`
- `tail_df` 通过近 `252` 日标准化残差拟合
- 若样本不足，formal strict 不允许进入主结果

#### 影响

- `tail_df` 越小，尾部越厚
- 在相同波动下，极端收益出现频率更高

### 10.2 条件波动层

#### 目标

刻画：

- 波动聚集
- 风险冲击后的高波动延续

#### 计算

对每个产品或因子估：

```text
h_{t+1} = omega + alpha * eps_t^2 + beta * h_t
```

估计窗口：

- 主窗口：`252` 日
- 最短：`126` 日

#### 影响

- 当 `eps_t` 大时，下一期波动抬升
- 影响后续每条路径的散布程度

### 10.3 DCC 依赖层

#### 目标

刻画：

- 因子间相关性在市场状态下的动态变化

#### 关键原则

`v1.4` 的 DCC 不在全产品层做，而在因子层做。

#### 计算

输入是因子的标准化残差 `z_t`：

```text
Q_{t+1} = (1-a-b)Qbar + a z_t z_t' + b Q_t
R_{t+1} = normalize(Q_{t+1})
```

参数建议：

- `Qbar`：用最近 `756` 交易日估长期相关
- `a, b`：先共享参数，再允许后续扩展到 block-specific 参数

#### 影响

- 风险期中，成长/宽基等因子相关可能抬升
- 产品通过 `beta_to_factors` 吃到这种相关变化

#### 可扩展结构要求

代码结构必须允许未来扩展：

- factor-block DCC
- sparse DCC
- cluster DCC
- copula-based dependence

不能把 DCC 写死成单一矩阵实现。

### 10.4 jump 层

#### 目标

刻画：

- 系统性跳跃
- 产品个体跳跃

#### systemic jump 依据

从因子历史识别极端事件：

- 超过条件分布极端分位
- 或超过 `4 sigma`

估：

- `systemic_jump_probability_1d`
- `systemic_jump_impact_by_factor`
- `systemic_jump_dispersion`

#### idiosyncratic jump 依据

从产品残差序列识别极端异常值：

- 因子解释之后的残差尾部
- 特定产品的跳跃频率与平均损失

#### 影响

每天先抽 systemic jump，再抽 idio jump，叠加到产品收益。

### 10.5 regime 层

#### 目标

刻画：

- `risk_on`
- `neutral`
- `risk_off`

等市场状态切换。

#### 计算

采用 Markov regime：

- 当前状态 `S_t`
- 转移矩阵 `P`
- 在不同 regime 下：
  - 因子均值不同
  - 因子波动不同
  - systemic jump 概率不同

#### 影响

先采样 `S_{t+1}`，再在该状态下生成因子路径。

---

## 11. 日频逐产品模拟推演过程

以下描述单条路径、单个日步的推进，不是月级近似。

### 11.1 输入

在 `day x` 已知：

- 当前 regime `S_x`
- 每个因子的条件方差状态
- DCC 相关状态
- 每个产品的 GARCH 状态
- 当前组合权重与净值

### 11.2 `day x -> day x+1` 推演顺序

1. 采样下一状态 `S_{x+1}`
2. 更新因子 DCC 相关与因子条件波动
3. 生成因子冲击与因子收益
4. 判断 systemic jump
5. 对每个产品：
   - 更新产品条件波动
   - 生成产品 idiosyncratic 残差
   - 判断产品 idio jump
   - 合成产品收益
6. 用产品收益合成组合收益
7. 注入当日现金流
8. 判断是否触发再平衡
9. 更新组合净值、持仓、状态

### 11.3 单产品收益方程

```text
r_i,x+1
= mu_i(S_x)
+ beta_i' f_{x+1}
+ sqrt(h_i,x+1) * eps_i,x+1
+ J_sys,i,x+1
+ J_idio,i,x+1
- cost_i,x+1
```

### 11.4 组合净值更新

```text
r_p,x+1 = sum_i w_i,x * r_i,x+1
V_{x+1} = V_x * (1 + r_p,x+1) + contribution_{x+1}
```

### 11.5 曲线构建

重复上述步骤直到 horizon 结束：

- 例如 `756` 个交易日
- `10,000` 条路径

得到：

- `10,000` 条逐日组合净值曲线

再计算：

- success probability
- CAGR 分布
- max drawdown 分布
- downside tail
- rebalancing frequency

---

## 12. 方案 C 作为 challenger 的定义

### 12.1 含义

challenger 不是正式主结果替代品，而是：

- 用真实历史路径约束 primary 模型过度乐观
- 提供模型分歧
- 决定是否降低置信度、放宽区间

### 12.2 challenger 架构

`regime_switching_bootstrap`：

- 使用真实历史产品日收益路径
- 在 regime 相近的历史块中做 block bootstrap
- 保留历史路径中的波动聚集与尾部结构

### 12.3 为什么不用简单平均

不允许：

- `primary` 和 `challenger` 直接取均值

允许：

- 报主结果
- 报 challenger 对比
- 根据分歧下调 `confidence_level`
- 根据分歧加宽 `success_probability_range`

---

## 13. 代码架构抽象设计

### 13.1 新模块划分

建议新增/重构为以下模块：

- `src/probability_engine/contracts.py`
  - recipe、状态、输出 contract

- `src/probability_engine/factors.py`
  - 因子序列、因子暴露、因子回归

- `src/probability_engine/regime.py`
  - regime 状态与转移

- `src/probability_engine/volatility.py`
  - 单产品/因子 GARCH 状态更新

- `src/probability_engine/dependence.py`
  - DCC 与依赖结构接口

- `src/probability_engine/jumps.py`
  - systemic / idio jump

- `src/probability_engine/path_generator.py`
  - 日频路径推进器

- `src/probability_engine/challengers.py`
  - bootstrap challenger / stress recipes

- `src/probability_engine/disclosure.py`
  - 模型分歧、区间、置信度调整

### 13.2 与旧代码关系

旧的：

- `goal_solver/engine.py`
- `calibration/engine.py`

不再直接承担全部概率引擎逻辑。

它们在 `v1.4` 中更像：

- 编排层
- 参数装配层
- 输出桥接层

真正的逐产品日频模拟放到 `probability_engine/`。

### 13.3 强制边界

在 `v1.4` formal 路径中：

- 禁止月级模拟
- 禁止桶级模拟
- 禁止 `static_gaussian` 作为 formal truth
- 禁止 `goal_solver` 直接跳过 `probability_engine` 自己拍路径

---

## 14. 性能优化与时间复杂度

### 14.1 复杂度瓶颈

假设：

- `N` = 产品数
- `K` = 因子数
- `T` = horizon 日数
- `P` = 模拟路径数

主要复杂度：

- 因子 DCC 更新：`O(P * T * K^2)`
- 产品边际生成：`O(P * T * N * K)`
- 组合聚合：`O(P * T * N)`

若直接做全产品 DCC，将近似变成：

- `O(P * T * N^2)`

这是 `v1.4` 明确拒绝的路径。

### 14.2 性能策略

1. **因子层低维化**
   - DCC 只在因子层

2. **参数预估缓存**
   - `factor_betas`
   - `garch_params`
   - `jump_profiles`
   - `regime transition`
   都按 `as_of` 缓存

3. **路径并行**
   - 沿路径维 `P` 并行

4. **产品筛选**
   - 仅对候选组合涉及产品做日频模拟
   - 不对全市场所有产品同时展开路径

5. **结构化复用**
   - 同一 `as_of` 下复用：
     - factor state
     - regime state
     - mapping state

### 14.3 formal 性能目标

对一个典型组合候选集：

- 候选产品数：`20-80`
- 因子数：`10`
- 路径数：`2,000-10,000`
- horizon：`756` 交易日

formal 单次运行应控制在可交互范围；若超限，允许：

- 减少 challenger 路径数
- 延迟 stress 结果

但不允许：

- 回退到月级模拟
- 回退到桶级模拟

---

## 15. 测试与回归方案

### 15.1 单元测试

覆盖：

- 产品因子映射
- GARCH 更新
- DCC 更新
- regime 转移
- jump 采样
- 单日路径推进

### 15.2 合同测试

必须锁住：

- formal strict 不允许月级/桶级 fallback
- `primary_recipe` 必须是日频逐产品
- challenger 不得覆盖主结果
- stress 不得伪装主结果

### 15.3 回归测试

固定测试画像：

- A 股宽基 + 黄金 + 海外成长 + 短债
- 不同 regime
- 不同 jump 激活场景

### 15.4 Claw 验收

Claw 必须能明确看见：

- `primary_recipe`
- `challenger_recipe`
- `stress_recipe`
- 当前因子映射来源
- 当前 `mapping_confidence`
- 当前日频路径证据
- 当前是否存在 monthly/bucket fallback（应始终为 false）

---

## 16. v1.4 闭环标准

`v1.4` 只有同时满足以下条件才算完成：

1. formal / Claw 主结果全部基于日频逐产品模拟
2. primary 使用方案 B
3. challenger 使用方案 C
4. DCC 在因子层而非全产品层
5. 无月级 fallback
6. 无桶级 fallback
7. challenger/stress 不覆盖主结果
8. 因子映射输出有 evidence 与 confidence
9. Claw 可验 primary/challenger/stress 分工
10. 性能优化不改变结果语义

---

## 17. 对 v1.3 的继承关系

`v1.4` 不推翻 `v1.3`，而是在其上继承：

- formal/degraded/failure 语义
- Evidence Bundle
- DisclosureDecision
- confidence / calibration / failure artifact 治理

`v1.4` 重构的是：

- 概率引擎内部数值主链
- 因子/产品/依赖/状态/跳跃建模方式

---

## 18. 一句话结论

`v1.4` 的本质不是“再加几个 mode”，而是把概率引擎改造成：

> 以逐产品日频路径为核心、以因子层承接共同风险、以 challenger/stress 管模型风险、且不允许退回月级/桶级近似的正式概率系统。

