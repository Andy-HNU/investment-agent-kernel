# CODEX v1.4 Market Pressure And Model Convergence Patch

日期：2026-04-12

作者：Codex

状态：design-approved draft

作用：

- 作为 [CODEX_v1.4_daily_product_probability_engine_design_2026-04-09.md](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_v1.4_daily_product_probability_engine_design_2026-04-09.md) 的补丁规格
- 把“市场压力等级表达”和“challenger / primary / stress 三模型收敛”收成同一套可直接开发的工程规则
- 冻结前台展示、压力分数、stress 分级、模型差距门槛与回归验收

若本 patch 与 `v1.4` 主设计稿存在冲突，以本 patch 为准。

---

## 1. 问题定义

当前 `v1.4` 虽然已经具备：

- `historical replay` challenger
- `current market` primary
- `stress` 压力视图

但仍有两个产品化问题没有闭环：

1. **用户看不懂 `stress=0` 的意义**
   - 现在只暴露一个孤立 stress 结果
   - 无法解释“当前市场处于什么压力等级”
   - 也无法解释“如果市场继续恶化，会恶化到什么程度”

2. **三模型差距过大**
   - `challenger` 可能过于乐观
   - `stress` 可能过于悲观
   - `primary` 夹在中间，但缺少收敛门
   - 结果是模型分歧大到不适合直接拿给用户当产品解释

本 patch 的目标不是单独新增一个展示字段，而是：

**把 `historical replay / current market / deteriorated market` 三类场景同时做成前台可展示的正式输出，并用这套场景梯度约束三模型收敛。**

---

## 2. 产品目标

每次给用户的正式输出必须包含以下三类视角：

1. **历史回测**
   - 回答：如果未来更像过去，会怎样

2. **当前市场延续**
   - 回答：如果当前市场状态大体延续，会怎样

3. **市场劣化情景**
   - 回答：如果市场从当前状态继续恶化，会怎样

用户不再只看到：

- `primary`
- `challenger`
- `stress`

而是看到：

- `历史回测`
- `当前市场延续`
- `若市场轻度恶化`
- `若市场中度恶化`
- `若市场重度恶化`

这五组结果必须共用：

- 同一组最终选中的产品
- 同一组产品权重
- 同一套 `contribution / withdrawal / rebalance`
- 同一套 success event

它们唯一允许不同的是：

- 路径生成方法
- 压力 overlay

---

## 3. 不允许的做法

以下做法在 `v1.4` 中禁止：

1. 根据“希望用户看到多少成功率”倒推 `mean/drift`
2. 直接用 `success_probability` 给场景打压力等级
3. 只保留一个黑箱 `stress=悲观版`
4. 让 `challenger`、`primary`、`stress` 各玩各的，不共享同一产品和现金流语义
5. 将 `challenger / primary / stress` 结果简单平均成一个主概率

正确关系固定为：

```text
historical replay = historical-path challenger
current market = primary
deteriorated market = stress ladder built on top of current market
```

---

## 4. 场景体系冻结

### 4.1 场景种类

冻结以下 `scenario_kind`：

- `historical_replay`
- `current_market`
- `deteriorated_mild`
- `deteriorated_moderate`
- `deteriorated_severe`

### 4.2 角色映射

冻结以下映射：

- `historical_replay` 对应 `challenger`
- `current_market` 对应 `primary`
- `deteriorated_*` 对应新的 stress ladder

### 4.3 场景语义

- `historical_replay`
  - 用 observed product history 做 regime-conditioned block bootstrap
  - 不承载“当前市场压力等级”

- `current_market`
  - 用当前 runtime state 的正式 primary recipe
  - 承载当前市场压力等级

- `deteriorated_mild / moderate / severe`
  - 不是新的独立世界
  - 而是基于 `current_market` runtime input 做分级 downside overlay

---

## 5. 市场压力等级

### 5.1 压力分数字段

新增：

```python
@dataclass(frozen=True)
class MarketPressureSnapshot:
    scenario_kind: str
    market_pressure_score: float | None
    market_pressure_level: str | None
    current_regime: str | None
    regime_component: float | None
    drift_haircut_component: float | None
    volatility_component: float | None
    jump_probability_component: float | None
    tail_severity_component: float | None
    effective_daily_drift: float | None
    volatility_multiplier: float | None
    systemic_jump_probability_multiplier: float | None
    idio_jump_probability_multiplier: float | None
    systemic_jump_dispersion_multiplier: float | None
```

### 5.2 压力分数范围

冻结：

- `market_pressure_score` 范围是 `0 ~ 100`
- `historical_replay.market_pressure_score = null`

### 5.3 压力等级映射

冻结：

- `0 ~ 24` -> `L0_宽松`
- `25 ~ 49` -> `L1_中性偏紧`
- `50 ~ 74` -> `L2_风险偏高`
- `75 ~ 100` -> `L3_高压`

---

## 6. 市场压力分数公式

### 6.1 输入来源

压力分数只能使用以下模型输入状态：

- `factor_dynamics.expected_return_by_factor`
- `regime_state.current_regime`
- `regime_state.transition_matrix`
- `regime_state.regime_mean_adjustments`
- `regime_state.regime_vol_adjustments`
- `regime_state.regime_jump_adjustments`
- `jump_state.systemic_jump_probability_1d`
- `jump_state.systemic_jump_dispersion`

禁止使用：

- `success_probability`
- `cagr_range`
- `terminal_value`
- 任意事后结果指标

### 6.2 总分公式

冻结：

```text
pressure_score =
0.30 * regime_component
+ 0.10 * drift_haircut_component
+ 0.25 * volatility_component
+ 0.20 * jump_probability_component
+ 0.15 * tail_severity_component
```

最终结果 clamp 到 `[0, 100]`。

---

## 7. 五个 component 的计算规则

### 7.1 `regime_component`

先给 regime 基础分：

- `normal` -> `10`
- `risk_off` -> `45`
- `stress` -> `75`

再根据 self-transition 持久性加分：

```text
p_self = transition_matrix[current_regime][current_regime]
persistence_bonus = 25 * clamp01((p_self - 0.60) / 0.30)
regime_component = min(100, regime_base + persistence_bonus)
```

### 7.2 `drift_haircut_component`

定义：

```text
base_daily_drift =
mean(expected_return_by_factor.values()) / 252

current_mean_shift =
regime_mean_adjustments[current_regime].mean_shift

effective_daily_drift =
max(base_daily_drift + current_mean_shift, -0.005)

drift_haircut_ratio =
clamp01((base_daily_drift - effective_daily_drift) / max(base_daily_drift, 1e-9))

drift_haircut_component =
100 * drift_haircut_ratio
```

### 7.3 `volatility_component`

定义：

```text
current_vol_multiplier =
regime_vol_adjustments[current_regime].volatility_multiplier

volatility_component =
100 * clamp01((current_vol_multiplier - 1.0) / 0.40)
```

解释：

- `1.0x` -> `0`
- `1.4x` 及以上 -> `100`

### 7.4 `jump_probability_component`

定义：

```text
sys_mult =
regime_jump_adjustments[current_regime].systemic_jump_probability_multiplier

idio_mult =
regime_jump_adjustments[current_regime].idio_jump_probability_multiplier

jump_probability_component =
50 * clamp01((sys_mult - 1.0) / 1.0)
+ 50 * clamp01((idio_mult - 1.0) / 0.5)
```

### 7.5 `tail_severity_component`

定义：

```text
disp_mult =
regime_jump_adjustments[current_regime].systemic_jump_dispersion_multiplier

tail_severity_component =
100 * clamp01((disp_mult - 1.0) / 0.20)
```

首版不引入单独的 `tail_df_component`。若后续需要增强，再扩展到：

```text
tail_severity_component =
70 * dispersion_component
+ 30 * df_component
```

---

## 8. stress ladder 规则

### 8.1 设计原则

`stress` 不再只保留一个过于极端的结果。

必须拆成：

- `deteriorated_mild`
- `deteriorated_moderate`
- `deteriorated_severe`

它们都必须建立在 `current_market` 的 runtime input 之上。

### 8.2 overlay 参数表

冻结如下：

| 场景 | 额外 drift 下修 | 额外 vol | 额外 sys jump prob | 额外 idio jump prob | 额外 jump dispersion | regime persistence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `deteriorated_mild` | `-0.08 * base_daily_drift` | `+0.08` | `x1.20` | `x1.10` | `x1.05` | `+0.04` |
| `deteriorated_moderate` | `-0.16 * base_daily_drift` | `+0.18` | `x1.45` | `x1.20` | `x1.10` | `+0.08` |
| `deteriorated_severe` | `-0.28 * base_daily_drift` | `+0.32` | `x1.90` | `x1.35` | `x1.18` | `+0.14` |

### 8.3 应用方式

冻结：

```text
volatility_multiplier_new =
current_volatility_multiplier + overlay_vol

systemic_jump_probability_multiplier_new =
current_sys_jump_multiplier * overlay_sys

idio_jump_probability_multiplier_new =
current_idio_jump_multiplier * overlay_idio

systemic_jump_dispersion_multiplier_new =
current_dispersion_multiplier * overlay_disp

mean_shift_new =
current_mean_shift + overlay_drift

p_self_new =
min(0.95, current_p_self + persistence_uplift)
```

### 8.4 单调性约束

冻结以下验收门：

```text
success(current_market)
>= success(deteriorated_mild)
>= success(deteriorated_moderate)
>= success(deteriorated_severe)
```

允许少量 Monte Carlo 噪声，但回归测试必须锁住默认配置下的单调性。

---

## 9. historical replay 规则

### 9.1 不参与市场压力分数

冻结：

```text
historical_replay.market_pressure_score = null
historical_replay.market_pressure_level = null
```

### 9.2 语义固定

`historical_replay` 只回答：

> 如果未来更像过去这段 observed 历史路径，会怎样

它不是“当前市场正常状态”的代名词，也不是压力分数体系的一部分。

### 9.3 数据基线收敛要求

为了避免 `challenger = 100%` 的过乐观异常，必须新增以下约束：

1. observed history 不得继续锚定在过于平滑的 helper acceptance pattern
2. challenger 使用的 block library 必须保留真实粗糙度：
   - 最低波动门槛
   - 最低 drawdown 粗糙度门槛
   - 多产品联合块同步抽样
3. 对 benign observed acceptance case，challenger 不得长期锁死在 `1.0`

---

## 10. 三模型收敛规则

### 10.1 角色关系

冻结：

```text
historical_replay >= current_market >= deteriorated_mild >= deteriorated_moderate >= deteriorated_severe
```

这是成功率排序的目标关系，不代表每次都必须严格大于，但默认回归必须逼近该结构。

### 10.2 间距门

对 benign observed acceptance case，冻结以下回归门：

```text
historical_replay_success - current_market_success <= 0.15
current_market_success - deteriorated_mild_success <= 0.20
deteriorated_mild_success - deteriorated_moderate_success <= 0.20
deteriorated_moderate_success - deteriorated_severe_success <= 0.25
```

这些门是产品解释门，不是数学真理。其作用是防止出现：

- `challenger = 1.0`
- `primary = 0.80`
- `stress = 0.0`

这种对用户不可解释的断裂。

### 10.3 不允许的收敛方式

禁止用以下方式“收敛”三模型：

1. 通过人为提升/压低成功率直接补数字
2. 让 stress 和 primary 共享同一个结果再改标签
3. 把 challenger 改成读取 primary 的结果

允许的收敛方式只有：

1. challenger observed 基线更真实
2. stress ladder 更细、更温和、更单调
3. primary 继续基于市场/历史输入校准，而不是按目标反推

---

## 11. 输出 schema 补丁

新增：

```python
@dataclass(frozen=True)
class ScenarioComparisonResult:
    scenario_kind: str
    label: str
    pressure: MarketPressureSnapshot | None
    recipe_result: RecipeSimulationResult
```

并在 `ProbabilityEngineOutput` 中新增：

```python
current_market_pressure: MarketPressureSnapshot | None
scenario_comparison: list[ScenarioComparisonResult]
```

冻结规则：

- `current_market_pressure` 只对应 `primary`
- `historical_replay.pressure = null`
- `scenario_comparison` 的顺序必须固定为：
  - `historical_replay`
  - `current_market`
  - `deteriorated_mild`
  - `deteriorated_moderate`
  - `deteriorated_severe`

---

## 12. 前台展示合同

前台禁止只显示：

- `primary`
- `challenger`
- `stress`

必须展示为以下五张卡片或五个 section：

1. `历史回测`
2. `当前市场延续`
3. `若市场轻度恶化`
4. `若市场中度恶化`
5. `若市场重度恶化`

每张卡必须显示：

- 成功率
- 年化区间
- 终值区间

其中：

- `当前市场延续` 还必须显示：
  - `当前市场压力：X/100`
  - `当前等级：L0/L1/L2/L3`

- `市场劣化` 卡还必须显示：
  - 对应压力分数
  - 对应等级

---

## 13. 与 confidence 的关系

### 13.1 不等价

冻结：

```text
market_pressure_score != confidence_level
```

市场压力表示：

- 当前/恶化市场有多紧

`confidence_level` 表示：

- 模型分歧和证据质量有多高

### 13.2 解释关系

允许前台把二者组合解释为：

> 当前市场压力已处于 `L2`，且历史回测与当前市场延续结果分歧较大，因此本次结论置信度下调。

但禁止：

> 因为压力高，所以置信度一定低

---

## 14. 实现模块拆分

### 14.1 `src/probability_engine/contracts.py`

新增：

- `MarketPressureSnapshot`
- `ScenarioComparisonResult`

### 14.2 `src/probability_engine/pressure.py`

新增：

- `compute_market_pressure_snapshot(runtime_input, scenario_kind)`
- `build_deteriorated_runtime_input(runtime_input, level)`
- `scenario_pressure_level(score)`

### 14.3 `src/probability_engine/engine.py`

新增流程：

1. 运行 `primary`
2. 运行 `historical_replay`
3. 构造并运行：
   - `deteriorated_mild`
   - `deteriorated_moderate`
   - `deteriorated_severe`
4. 组装 `scenario_comparison`
5. 保持现有 `probability_disclosure_payload` 不变

### 14.4 `src/probability_engine/disclosure_bridge.py`

新增：

- pressure/explanation 附加字段

但不改变：

- `formal_strict_result`
- `formal_estimated_result`
- `degraded_formal_result`

这些 formal 语义。

### 14.5 `src/frontdesk/service.py`

输出：

- `current_market_pressure`
- `scenario_comparison`

### 14.6 `src/decision_card/builder.py`

展示：

- 历史回测
- 当前市场延续
- 市场劣化阶梯

---

## 15. 测试与验收

### 15.1 contract 测试

至少新增以下 contract：

1. `historical_replay.market_pressure_score is null`
2. `current_market.market_pressure_score in [0, 100]`
3. `mild < moderate < severe` 的压力分数严格递增
4. `current >= mild >= moderate >= severe` 的成功率单调递减
5. `normal -> risk_off -> stress` 时压力分数递增

### 15.2 integration 测试

对 benign observed acceptance case，新增：

1. `historical_replay - current_market <= 0.15`
2. `current_market - mild <= 0.20`
3. `mild - moderate <= 0.20`
4. `moderate - severe <= 0.25`

### 15.3 前台回归

必须锁住：

- summary payload 含 `current_market_pressure`
- 前台可见五类场景
- 不再只显示一个黑箱 `stress`

### 15.4 Claw 验收

Claw 至少要能输出：

- 历史回测结果
- 当前市场延续结果
- 三档市场劣化结果
- 当前市场压力等级

---

## 16. 实施顺序

推荐顺序：

1. 建 `contracts.py` / `pressure.py`
2. 把 `stress` 从单一结果拆成三档
3. 把 `scenario_comparison` 接进 engine
4. 接 frontdesk / decision card 展示
5. 最后收 challenger observed 基线，满足间距门

---

## 17. 最终一句话

`v1.4` 这轮不再把 `stress` 当一个孤立的悲观值，而是把：

- 历史回测
- 当前市场延续
- 市场劣化阶梯

一起做成正式产品输出；同时用这套阶梯把 `challenger / primary / stress` 的差距收敛到用户可解释的范围内。
