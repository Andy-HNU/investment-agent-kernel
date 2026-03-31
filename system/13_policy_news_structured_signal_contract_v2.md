# 13_policy_news_structured_signal_contract_v2.md
# 政策 / 新闻结构化信号契约 v2

> 文档定位：本文件规定 policy/news sidecar 如何把外部文本世界转换成可审计、可回放、可保守吸收的结构化信号。
>
> 它不是新闻分析方法论文，也不是 LLM prompt 集；它是进入当前 kernel 的正式 contract。

---

## 0. 一句话定义

**policy/news sidecar 只能向 kernel 输出结构化信号，不能把原始文本直接当成 solver 输入。**

---

## 1. 设计原则

1. 文本先分析，后结构化
2. 结构化后才能进入 `03/05`
3. 信号必须带来源、时间、置信度、是否要求人工复核
4. 信号只能保守影响参数边界、review gate 或解释层
5. 不允许“一条新闻直接改概率”

---

## 2. 允许进入 kernel 的字段

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class PolicyNewsSignal:
    signal_id: str
    as_of: str

    source_type: Literal["policy", "news", "analysis"]
    source_refs: list[str]

    policy_regime: Literal["supportive", "neutral", "tightening", "unclear"] | None = None
    macro_uncertainty: Literal["low", "medium", "high"] | None = None
    sentiment_stress: Literal["low", "medium", "high"] | None = None
    liquidity_stress: Literal["low", "medium", "high"] | None = None

    manual_review_required: bool = False
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
```

---

## 3. 不允许进入 kernel 的内容

- 原始新闻正文
- 未经结构化的长段政策文本
- LLM 自由发挥出的直接买卖结论
- 没有来源与时间锚点的情绪判断

---

## 4. sidecar -> 03/05 的正式进入方式

### 4.1 输入位置

- 可作为 `market_raw` 的补充字段
- 可作为 calibration 前的 sidecar evidence 附加对象

### 4.2 影响边界

- 可以触发 `manual_review_required`
- 可以影响 `degraded / review` 说明
- 可以保守调整某些参数边界
- 不可直接替代历史数据或价格序列

### 4.3 保守吸收原则

- 高不确定性优先触发 review，而不是直接改仓
- 低置信度信号优先进入解释层，而不是参数层
- 多源冲突时优先降级，不优先强结论

---

## 5. 与 Claw / OpenClaw 的边界

- 搜索与分析可由 `policy-news-search` / `policy-news-analysis` 承担
- 当前仓库只消费结构化结果
- 若 sidecar skill 发生修改，应 patch 回 Claw 原处，不在当前仓库保留复制版 skill

---

## 6. 前台展示要求

决策卡或 advisor shell 至少应能展示：

- 本轮信号来自哪些政策 / 新闻来源
- 当前信号是支持性、中性、收紧还是不明确
- 当前信号是否要求人工复核
- 当前信号有没有直接改变配置

---

## 7. 测试要求

- signal schema contract
- 来源 / 时间 / 置信度字段完整性测试
- manual review 触发测试
- 低置信度信号不直接改数学核心的回归测试
- replay 时 signal version pin 测试

---

## 8. v2 范围结论

本文件让 policy/news 从“外部聊天素材”变成“正式、可审计、可回放的 sidecar 信号”。  
这会提高系统解释力，但不会把新闻分析变成黑箱策略核心。
