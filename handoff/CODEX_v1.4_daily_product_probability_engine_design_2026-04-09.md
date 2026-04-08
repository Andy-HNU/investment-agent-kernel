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

### 3.4 方案 B 的完整定义

方案 B 不是“产品选五种模型之一”，而是：

> **产品边际过程 + 因子联合过程 + 产品残差过程** 的组合。

单个产品 `i` 在 `t -> t+1` 的日收益写成：

```text
r_i,t+1
= alpha_i(S_t)
+ beta_i,t' * f_t+1
+ u_i,t+1
+ J_sys,i,t+1
+ J_idio,i,t+1
- cost_i,t+1
```

其中：

- `S_t`：当期 regime
- `f_t+1`：因子收益向量
- `beta_i,t`：产品对因子的暴露
- `u_i,t+1`：产品 idiosyncratic 残差
- `J_sys,i,t+1`：系统 jump 通过因子或映射传到产品
- `J_idio,i,t+1`：产品自身 jump
- `cost_i,t+1`：费率、跟踪误差、流动性拖累

进一步拆开：

```text
u_i,t+1 = sqrt(h_i,t+1) * eps_i,t+1
eps_i,t+1 ~ StudentT(df_i)
```

以及：

```text
h_i,t+1 = omega_i + alpha_i * u_i,t^2 + beta_i * h_i,t
```

也就是说，方案 B 同时刻画：

- 因子共同驱动
- 产品自身波动聚集
- 厚尾
- jump
- regime 切换

但它把“共同依赖结构”压缩到因子层，而不是在几千产品上直接做联合状态估计。

### 3.5 方案 C 的完整定义

方案 C 不是“低配版方案 B”，而是：

> **以真实历史产品日收益路径为核心、按 regime 过滤后的经验重采样 challenger**。

其目标不是替代 primary，而是回答：

- primary 是否过于乐观
- 当前参数模型是否低估路径依赖
- 在真实历史路径形状下，达标概率是否显著下降

方案 C 的单条路径生成过程：

1. 先确定当前 regime `S_t`
2. 从历史中选出 regime 相近的交易日集合
3. 从该集合中抽取长度为 `B` 的历史块
4. 依次拼接成未来 `T` 个交易日的产品日收益序列
5. 在必要时叠加轻量 stress overlay

它不重新估计 GARCH/DCC 参数，而是直接复用真实历史中的：

- 波动聚集
- 厚尾
- 跨产品共同波动
- 连续回撤段

因此它天然更擅长当 challenger，而不是当前瞻主模型。

### 3.6 primary / challenger / stress 的协作关系

`v1.4` 明确禁止把多个模型简单平均成一个主概率。

角色关系固定为：

- `primary`
  - 输出正式主成功率和主收益区间
- `challenger`
  - 输出对照成功率与对照区间
- `stress`
  - 输出尾部损失强化视图

它们的作用关系是：

```text
主结果 = primary
置信度调整 = primary vs challenger/stress 的分歧函数
区间加宽 = primary 区间 + 模型分歧宽化
```

不允许：

- `primary` 与 `challenger` 数值平均
- `stress` 直接覆盖主成功率
- 任何 challenger/stress 结果在前台伪装成主结果

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

### 4.5 一次 formal run 的内部调用关系

一次 formal run 必须显式经历以下阶段：

1. **Data Assembly**
   - 读取产品价格、持仓、估值、事件数据
2. **Mapping Build**
   - 生成产品到因子的暴露与映射证据
3. **State Calibration**
   - 拟合产品边际状态、因子状态、regime、jump 状态
4. **Recipe Selection**
   - 确定 primary/challenger/stress recipe
5. **Daily Path Generation**
   - 按日频推进各条路径
6. **Portfolio Policy Simulation**
   - 注入现金流、再平衡、执行约束
7. **Event Evaluation**
   - 计算 success event
8. **Disclosure Assembly**
   - 组装 primary/challenger/stress 结果与置信度

formal run 禁止跳过第 4 步到第 7 步之间的任意层直接出结果。

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

### 7.7 映射的数学定义

产品 `i` 的最终因子暴露向量定义为：

```text
beta_i,final
= w_prior,i * beta_i,prior
+ w_holdings,i * beta_i,holdings
+ w_returns,i * beta_i,returns
```

满足：

```text
w_prior,i + w_holdings,i + w_returns,i = 1
w_* >= 0
```

其中：

- `beta_i,prior`：结构先验暴露
- `beta_i,holdings`：穿透持仓汇总暴露
- `beta_i,returns`：收益回归暴露

权重建议函数：

```text
w_holdings ∝ holdings_freshness * holdings_coverage
w_returns  ∝ regression_stability * history_length_score
w_prior    ∝ 1 - (w_holdings + w_returns)
```

再做一次 shrinkage：

```text
beta_i,shrunk
= lambda_i * beta_i,final + (1-lambda_i) * beta_i,anchor
```

这里 `beta_i,anchor` 通常取结构先验或同类产品簇均值，`lambda_i` 由证据质量决定。

### 7.8 回归暴露的正式计算

对每个产品，使用日频收益回归：

```text
r_i,t = alpha_i + B_i' f_t + e_i,t
```

估计要求：

- 主窗口：最近 `252` 交易日
- 最低窗口：`126` 交易日
- 使用指数衰减权重，半衰期建议 `63` 交易日
- 暴露稳定性由滚动窗口方差衡量

形式上可采用加权岭回归：

```text
min_B Σ_t w_t (r_i,t - alpha_i - B_i' f_t)^2 + λ ||B_i - B_i,prior||^2
```

这样收益回归既能贴市场，又不会完全漂离结构先验。

### 7.9 持仓暴露的正式计算

若产品 `i` 拥有底层持仓集合 `H_i`，则：

```text
beta_i,holdings = Σ_{j in H_i} weight_{i,j} * beta_j,security
```

其中 `beta_j,security` 可来自：

- 底层证券行业/风格分类
- 单证券历史回归
- 外部风险模型标签

若持仓覆盖率低于阈值，例如 `< 0.7`，则 `holdings_beta` 不得作为主证据。

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

### 8.5 层间信息流

这五层不是并列标签，而是严格的信息流：

```text
regime_layer
  -> factor_mean / factor_vol / systemic_jump
  -> dependency_layer(DCC on factors)
  -> factor_returns
  -> product marginal layer(beta + residual volatility + idio jump)
  -> product_returns
  -> portfolio construction layer
```

如果某一层未参与当期 recipe，必须在 `recipe_trace` 中显式标记，而不能让字段存在但对数值无影响。

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

扩展约束：

- `factor_betas` 必须是规范化后的低维向量
- `innovation_family` 只能是闭集枚举
- `garch_params` 至少包含 `omega / alpha / beta`
- `idiosyncratic_jump_profile` 至少包含：
  - `jump_probability_1d`
  - `loss_mean`
  - `loss_std`
  - `positive_jump_allowed`
- `carry_profile` 必须显式区分：
  - `dividend_carry`
  - `coupon_carry`
  - `roll_carry`
- `valuation_profile` 至少包含：
  - `valuation_anchor`
  - `reversion_speed`
  - `valuation_confidence`

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

建议补字段：

```python
    factor_series_ref: str
    calibration_window_days: int
    volatility_half_life_days: int
    dcc_variant: str             # dcc / block_dcc / sparse_dcc
    covariance_shrinkage: float
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

建议再补：

```python
    dependency_scope: str        # factor_level / factor_cluster_level
    path_count: int
    confidence_role: str         # primary / challenger / stress
    admissible_result_categories: list[str]
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

正式拟合过程：

1. 对因子或产品先估条件均值与条件波动
2. 取标准化残差：

```text
z_t = (r_t - mu_t) / sqrt(h_t)
```

3. 用最大似然或矩匹配估计 `tail_df`

建议边界：

- `tail_df < 3` 视为不稳定，需截断
- `tail_df > 30` 时可近似正态，但 formal 仍保留 `student_t` 标签

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

正式拟合方式：

- 单产品和单因子分别拟合
- 参数约束：
  - `omega > 0`
  - `alpha >= 0`
  - `beta >= 0`
  - `alpha + beta < 1`

建议使用滚动再估计或固定窗口平滑更新，而不是每日全量重拟合。

#### 输出如何影响模拟

在 `t -> t+1`，若上一期冲击大，则：

- `h_{t+1}` 上升
- 当期残差项 `sqrt(h_{t+1}) * eps_{t+1}` 变大
- 这直接扩大未来路径扇面

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

正式定义：

- `z_t` 只允许使用**因子标准化残差**
- 不允许直接对全产品残差求 DCC

推荐默认：

- `K = 8-12` 个因子
- `Qbar` 使用最近 `756` 日样本协方差再标准化
- `a` 建议 `0.01-0.05`
- `b` 建议 `0.90-0.98`

这组参数不是写死常数，而是校准初值范围；真实值应在 calibration 阶段估计并固化进 state。

#### DCC 输出如何影响产品

设因子收益向量为 `f_t`，产品收益共同部分为：

```text
r_i,t(common) = beta_i' f_t
```

如果 `R_t` 中：

- `US_EQ_GROWTH` 与 `CN_EQ_GROWTH` 相关抬升

则所有对这两个因子有暴露的产品，其共同波动会同步增强。

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

推荐估计：

1. 在每个因子上识别极端日：

```text
|z_t| > q_{0.995}
```

或

```text
|z_t| > 4σ
```

2. 统计：

- 极端事件频率 -> `jump_probability_1d`
- 极端损失均值/方差 -> `impact distribution`

3. 估计因子间联合极端共现概率，用于 systemic jump 触发

#### idiosyncratic jump 依据

从产品残差序列识别极端异常值：

- 因子解释之后的残差尾部
- 特定产品的跳跃频率与平均损失

即对产品残差：

```text
e_i,t = r_i,t - alpha_i - beta_i' f_t
```

识别尾部事件：

```text
|e_i,t / sqrt(h_i,t)| > threshold
```

并估：

- `idio_jump_probability_1d`
- `idio_jump_loss_mean`
- `idio_jump_loss_std`

#### 影响

每天先抽 systemic jump，再抽 idio jump，叠加到产品收益。

更具体地：

```text
J_sys,i,t+1 = M_sys,t+1 * exposure_i_to_jump_factors * L_sys,t+1
J_idio,i,t+1 = M_idio,i,t+1 * L_idio,i,t+1
```

其中：

- `M_*` 是 Bernoulli 触发变量
- `L_*` 是损失大小随机变量

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

建议 regime 数量控制在 `3-4`，例如：

- `risk_on`
- `neutral`
- `risk_off`
- `crisis`（可选）

状态转移：

```text
Pr(S_{t+1}=j | S_t=i) = P_{ij}
```

正式估计可先用：

- 明确规则标签
- 或 Markov switching 估计

但进入 formal 的 regime 定义必须稳定、可解释、可复验。

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

### 11.6 具体数值例子

假设当前组合包含 4 个产品：

- `CSI300 ETF`
- `Gold ETF`
- `NASDAQ ETF`
- `Short Bond ETF`

当前权重：

- `CSI300 ETF = 0.40`
- `Gold ETF = 0.20`
- `NASDAQ ETF = 0.25`
- `Short Bond ETF = 0.15`

当前 regime：

- `S_x = risk_off`

#### Step 1: 采样下一状态

若转移矩阵给出：

```text
P(risk_off -> risk_off) = 0.72
P(risk_off -> neutral)  = 0.24
P(risk_off -> risk_on)  = 0.04
```

本次采样结果仍为 `risk_off`。

#### Step 2: 生成下一日因子收益

假设采样得到：

```text
CN_EQ_BROAD      = -1.4%
CN_EQ_GROWTH     = -2.0%
US_EQ_GROWTH     = -3.2%
GOLD_GLOBAL      = +0.8%
CN_RATE_DURATION = +0.2%
CN_CREDIT_SPREAD = -0.3%
USD_CNH          = +0.1%
```

#### Step 3: 产品收益合成

`NASDAQ ETF` 的暴露若为：

```text
US_EQ_GROWTH = 1.05
USD_CNH      = 0.12
```

则其共同部分：

```text
beta' * f = 1.05 * (-3.2%) + 0.12 * 0.1% ≈ -3.35%
```

若：

- 产品条件波动项给出 `-0.90%`
- systemic jump 传导给出 `-1.40%`
- idio jump 未触发
- 成本拖累 `-0.02%`

则：

```text
r_nasdaq,x+1 ≈ -5.67%
```

同理可得：

- `CSI300 ETF ≈ -2.30%`
- `Gold ETF ≈ +0.92%`
- `Short Bond ETF ≈ -0.05%`

#### Step 4: 组合收益

```text
r_p,x+1
= 0.40*(-2.30%)
+ 0.20*(+0.92%)
+ 0.25*(-5.67%)
+ 0.15*(-0.05%)
≈ -2.16%
```

#### Step 5: 更新净值

若今日净值 `V_x = 100`，且当日净现金流为 `0.3`：

```text
V_{x+1} = 100 * (1 - 2.16%) + 0.3 = 98.14
```

再判断是否触发再平衡，然后进入下一日。

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

正式过程：

1. 对每个产品准备历史日收益序列
2. 给每个历史日打上 regime 标签
3. 在当前 `S_t` 对应的历史子集里抽样
4. 按 block size `B` 抽取连续历史段
5. 拼成长度为 `T` 的未来日收益路径
6. 在组合层复用同样的现金流与再平衡规则

block size 建议：

- 默认 `5-20` 个交易日
- 可按 regime 或资产波动特征调整

### 12.3 为什么不用简单平均

不允许：

- `primary` 和 `challenger` 直接取均值

允许：

- 报主结果
- 报 challenger 对比
- 根据分歧下调 `confidence_level`
- 根据分歧加宽 `success_probability_range`

### 12.4 challenger 输出如何作用于主结果

设：

- `p_primary = 0.55`
- `p_challenger = 0.46`

则系统不做：

```text
p = (0.55 + 0.46)/2
```

而做：

```text
model_dispersion = |0.55 - 0.46| = 0.09
```

再按披露策略：

- 下调 `confidence_level`
- 放宽 `success_probability_range`

例如：

- 主披露由 `55%`
- 改为 `46% ~ 55%`

这就是 challenger 的正式角色。

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

### 13.1.1 关键接口

建议显式定义这些接口，避免实现漂移：

```python
class FactorMappingBuilder(Protocol):
    def build(self, product_inputs: list[Any], as_of: str) -> list[ProductMarginalSpec]: ...

class StateCalibrator(Protocol):
    def calibrate(self, daily_input: DailySimulationInput) -> CalibratedStateBundle: ...

class RecipeRunner(Protocol):
    def run(self, daily_input: DailySimulationInput, recipe: SimulationRecipe) -> RecipeSimulationResult: ...

class DisclosureAssembler(Protocol):
    def assemble(
        self,
        primary: RecipeSimulationResult,
        challengers: list[RecipeSimulationResult],
        stresses: list[RecipeSimulationResult],
    ) -> ProbabilityDisclosureResult: ...
```

这样后续扩 DCC / copula / sparse dependence 时，不需要重写整个 orchestrator。

### 13.2 与旧代码关系

旧的：

- `goal_solver/engine.py`
- `calibration/engine.py`

不再直接承担全部概率引擎逻辑。

它们在 `v1.4` 中更像：

- 编排层
- 参数装配层
- 输出桥接层

建议调用关系固定为：

```text
frontdesk/orchestrator
  -> probability_engine.contracts
  -> probability_engine.factors
  -> probability_engine.regime
  -> probability_engine.volatility
  -> probability_engine.dependence
  -> probability_engine.jumps
  -> probability_engine.path_generator
  -> probability_engine.disclosure
  -> goal_solver/disclosure bridge
```

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

内存复杂度主要来自：

- 存整条产品路径：`O(P * T * N)`
- 存因子路径：`O(P * T * K)`

因此实现上不应默认把所有中间路径全量持久化；formal 主路径只保留：

- 统计摘要
- 必要的审计样本
- 关键路径片段

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

6. **块状向量化**
   - 在路径维 `P` 上做 numpy 批处理
   - 避免 Python for-loop 在产品维和路径维双重嵌套

7. **两阶段输出保留**
   - 第一阶段只保留：
     - success event
     - tail stats
     - drawdown stats
   - 第二阶段仅对审计样本路径保留完整轨迹

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

### 14.4 性能不变量

任何性能优化都不得改变：

- `resolved_result_category`
- `disclosure_level`
- `confidence_level`
- `primary/challenger/stress` 角色
- `evidence_bundle` 的语义 refs

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

### 15.5 必须新增的回归组

1. **Primary 路径正确性组**
   - 日频、逐产品、primary recipe 命中

2. **Challenger 分歧组**
   - 同一画像下 primary 与 challenger 分歧可见

3. **Stress 尾部组**
   - stress recipe 的 tail 风险强于 primary

4. **DCC 可扩展接口组**
   - 更换 dependence provider 不改 orchestrator 调用

5. **No Monthly / No Bucket Gate**
   - 任一 formal/Claw run 命中月级或桶级逻辑即失败

### 15.6 数学正确性回归

必须对以下对象做数值回归：

- GARCH 状态更新
- DCC 相关更新
- regime 转移采样分布
- jump 触发频率
- factor beta shrinkage
- portfolio path aggregation

这些测试要固定 seed，并对比：

- 均值
- 方差
- 分位数
- 命中率

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
