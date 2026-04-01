# 12_provider_capability_matrix_v2.md
# Provider 能力矩阵与多源接入规格 v2

> 文档定位：本文件把 roadmap 里的 provider 能力矩阵、首批开源数据源候选池和多源策略补成正式系统规格。
>
> 它约束的是“接什么源、覆盖哪些资产、主备怎么分、验证到什么程度”，不是具体抓取实现细节。

---

## 0. 一句话定义

**Provider Capability Matrix 是系统对外部数据源覆盖范围与可信度的正式声明。**

它回答 4 个问题：

- 哪些资产已经覆盖
- 每类资产的主源 / 备源 / 降级源是什么
- 实时和历史支持到什么程度
- 当前是否已验证

---

## 1. 第一版数据源候选池

### 1.1 中国市场

- 主源：`akfamily/akshare`
- 补位：`Micro-sheep/efinance`
- A 股历史补位：`shimencaiji/baostock`

### 1.2 海外与交叉验证

- `ranaroussi/yfinance`
- `dpguthrie/yahooquery`
- `pydata/pandas-datareader`

### 1.3 暂不作为第一优先免费主源

- `waditu/tushare`

原因：

- 可保留为扩展源
- 但不把它作为第一版默认免费主源

### 1.4 政策与新闻

- 政策：官方站点原文优先
- 新闻：公开新闻源优先

### 1.5 账户 / 持仓 / 组合快照

- 手工快照导入：本地 JSON / CSV / 表单归一化导入
- broker/account provider：后续接入券商导出或账户 API 适配器
- 第一版要求至少具备：
  - `account_raw` 导入路径
  - `live_portfolio` 导入路径
  - 来源标记、时间锚点、freshness 与 fallback 标记

---

## 2. 资产覆盖矩阵

### 2.1 第一版目标资产

- A 股
- 港股
- 美股
- ETF
- 公募基金
- 债券 / 国债 / 政金债
- 黄金
- 现金类 / 货基 / 短债替代
- QDII
- 行业指数 / 宽基指数 / 风格指数

### 2.2 每类资产必须标注

- `primary_source`
- `fallback_source`
- `degraded_source`
- `realtime_support`
- `historical_support`
- `verified_status`
- `notes`

### 2.3 能力矩阵记录结构

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class ProviderCoverageRecord:
    asset_class: str
    region: str
    primary_source: str | None
    fallback_source: str | None
    degraded_source: str | None

    realtime_support: Literal["none", "partial", "full"]
    historical_support: Literal["none", "partial", "full"]
    verified_status: Literal["planned", "in_progress", "verified", "degraded", "blocked"]

    notes: list[str]
```

---

## 3. 多源策略

### 3.1 主备优先级

- 主源：默认正式读取源
- 备源：主源失败或校验不通过时的替代
- 降级源：只保证最低限度可用与解释

### 3.2 使用原则

- 不把单一免费源写死进主链
- 主备切换必须可追踪
- 任何 fallback 都必须被记录和展示

### 3.3 第一版接入策略

- `AKShare` 作为中国市场主源
- `efinance / baostock` 作为补位与交叉验证
- `yfinance / yahooquery` 作为海外与 cross-check
- 政策以官网为主
- 新闻先走公开源

---

## 4. 工程红线

- `monitoring / alerting`
- `rate limit / retry / backoff`
- `cache / TTL / refresh strategy`
- `persistence / audit logging`
- `validation / reconciliation`
- `schema drift detection`
- `source fallback priority`
- `ToS / 使用边界 / 可持续性评估`

---

## 5. 验证状态定义

- `planned`
  - 已列入矩阵，尚未接入
- `in_progress`
  - 已接入但未通过完整验证
- `verified`
  - 已通过 contract + semantic + replay 验证
- `degraded`
  - 能用，但有已知覆盖缺口或稳定性问题
- `blocked`
  - 暂不可用或不满足最低要求

---

## 6. 与 03 / 05 / 02 / 04 的关系

### 6.1 对 03 / 05

- 定义 `market_raw / account_raw / behavior_raw / live_portfolio` 的来源覆盖
- 定义 freshness / provenance / fallback 规则
- 其中 `account_raw / live_portfolio` 不得留在“口头支持”状态，必须进入 capability matrix

### 6.2 对 02 / 04

- 定义历史数据的合法来源池
- 不允许拿“临时实时抓取结果”伪装成正式历史回测数据

---

## 7. 测试要求

- provider contract tests
- source drift regression
- asset-coverage matrix consistency tests
- broker/account/live_portfolio provider contract tests
- validation / reconciliation tests
- fallback / degraded acceptance
- replay-dataset consistency tests

---

## 8. v2 范围结论

本文件的目标不是一次性把所有资产做到商用级覆盖。  
它的目标是：

- 把第一版多源接入说清楚
- 把覆盖范围和缺口公开化
- 让系统在个人长期使用和对外开源时不靠暗含假设
