# 15_distribution_modeling_and_forward_validation_v1.2.md

> **文档定位**：本文件是 `v1.2` 针对真实数据建模与前瞻验证的跨层补充规格。它不替代 `02/03/05`，只负责把三层之间的正式口径和验证门写清。

---

## 0. 一句话定义

`v1.2` 的分布建模不再以假数据和静态 Gaussian 为默认正式路径。

系统正式改为：

- 使用真实外部源抓取并版本化缓存的历史数据
- 默认请求最高可用分布模式
- 用锚点前数据建模、锚点后真实数据回放来检验概率质量

---

## 1. 正式数据口径

### 1.1 允许的数据

- 真实外部源实时抓取得到的历史/快照数据
- 真实外部源抓取后版本化缓存的数据

### 1.2 不允许的数据

- default market snapshot
- inline synthetic history
- 任意系统自造历史序列

### 1.3 历史口径

- 长期结构窗口：默认 `10 年日频`
- 短期 regime 窗口：默认 `1-2 年日频`
- 产品真实历史不足时：
  - 基金类允许推算历史
  - 推算历史必须显式标记并降权

---

## 2. 分布模型口径

### 2.1 默认请求链

正式路径默认请求：

- `garch_t_dcc_jump`

若条件不足，按下列顺序自动降级：

1. `garch_t_dcc_jump`
2. `garch_t_dcc`
3. `garch_t`
4. `static_gaussian`

### 2.2 降级触发

- 历史长度不足
- 周期覆盖不足
- DCC 校准条件不满足
- jump 条件不满足
- 真实历史缺失，只剩兼容层

### 2.3 解释义务

任意正式 run 必须能解释：

- requested mode
- used mode
- 是否 auto selected
- 使用了哪一版历史数据
- 为什么不能上更高模式

---

## 3. 双层成功率

### 3.1 桶级成功率

`bucket_success_probability`

用途：

- 衡量战略配置本身是否合理

### 3.2 产品修正成功率

`product_adjusted_success_probability`

用途：

- 衡量具体产品计划执行后的成功率

修正输入包括：

- 费率
- 流动性
- wrapper 风险
- 产品风险标签
- 推算历史折扣

---

## 4. 前瞻验证（Forward Validation）

### 4.1 固定锚点验证

流程：

1. 设定锚点 `T0`
2. 只允许使用 `T0` 之前的真实历史数据
3. 基于当时条件求解策略与概率
4. 用 `T0` 之后的真实价格/收益序列回放未来
5. 比较预测概率与实际达标结果

### 4.2 滚动锚点验证

固定锚点外，`v1.2` 还要求支持滚动锚点组，例如：

- `2021-01-01`
- `2022-01-03`
- `2023-01-03`

### 4.3 核心指标

- `predicted_success_probability`
- `predicted_product_adjusted_success_probability`
- `realized_terminal_value`
- `goal_achieved`
- `brier_score_bucket`
- `brier_score_product_adjusted`

### 4.4 禁止事项

- 不得把锚点后的数据泄露到建模输入
- 不得用前瞻验证结果反向改写当时 run 的日志与输出

