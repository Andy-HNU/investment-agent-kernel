# Investment Agent Kernel v1.2 Phase Reports

日期：2026-04-04

读者：产品负责人、项目 owner、后续接手工程师、验收人员

## 总结

`v1.2` 不是在 `v1/v1.1` 上继续堆点功能，而是把系统往“可信、可执行、可解释、可持续跟踪”的顾问内核推进了一层。

这次交付围绕 6 条主线展开：

1. 真实源历史数据与跨周期覆盖
2. 分布建模升级
3. 产品选择引擎
4. 产品维护策略
5. 观测持仓同步与对账
6. Claw 顾问壳与证据展示

和上一轮最大的差异有 4 点：

- 正式路径不再依赖 `default / inline / synthetic` 假数据
- 成功率不再只停留在桶级口径，开始引入产品修正口径
- 系统不再假设“建议 = 用户已执行”，而是以 `observed_portfolio` 为真相源
- Claw 不再只做 onboarding/status 这类轻动作，而是扩到了 `quarterly / event / daily_monitor / explain_* / approve_plan`

这版已经足够作为 `v1.2 feature branch` 做系统级自然语言验收，但还不建议直接宣称“概率已经完全校准”。前瞻验证已经做出来了，结果说明方向是对的，但校准质量还需要继续打磨。

## 主线 1：Real-Source Market Data and Cycle Coverage

### 实现了什么

- 把正式数据边界改成“真实外部源抓取后缓存/落库”，不再接受 default/inline 进入正式路径。
- 在 `03` 文档和代码路径里补了：
  - 日频 10 年长期结构窗口
  - 日频 1-2 年短期 regime 窗口
  - 历史源 metadata / dataset_version / as_of / lookback_days
- 补了真实源 smoke 路径：
  - `akshare`
  - `baostock`
  - `yfinance`

### 已实现特性

- 正式历史数据可被版本化缓存
- 可区分历史数据来源与未来验证数据来源
- 能进入前瞻验证与模型解释

### 未完全实现的特性

- 周期覆盖仍主要是窗口规则与质量标记，还不是成熟的“自动牛熊识别 + 多周期充分性评分”
- 券商/账户 API 仍未进入真实接入范围
- `yfinance` live smoke 在本轮环境下触发 rate limit

### 未完全实现原因

- `v1.2` 先优先保证“正式路径不用假数据”，不是一口气做成完整市场数据平台
- 海外免费源天然带限频和环境不稳定性

### 建议

- `v1.2.1` 继续补 cross-check 源和周期覆盖评分
- 把 provider freshness/drift 监控再往前推一版

## 主线 2：Distribution Modeling Upgrade

### 实现了什么

- `02/03/05` 补了新的建模规格和代码路径：
  - `garch_t`
  - `garch_t_dcc`
  - `garch_t_dcc_jump`
- 新增并明确区分：
  - `simulation_mode_requested`
  - `simulation_mode_used`
  - `simulation_mode_auto_selected`
- 正式路径默认请求最强模式，缺数据时显式降级，不再静默退回 `static_gaussian`
- 新增前瞻验证脚本：
  - 单锚点验证
  - 滚动锚点验证

### 已实现特性

- 日频历史可以进入更真实的分布建模链
- 高级模式在正式路径上已经会被真实请求和真实披露
- 前瞻验证已经能输出：
  - 预测成功率
  - 实际终值
  - 是否真的达标
  - Brier 风格误差

### 未完全实现的特性

- 目前前瞻验证结果说明“已具备验证能力”，但不说明“已校准到理想水平”
- 产品修正成功率与桶级成功率在当前案例里仍然接近，说明产品层风险修正还偏轻
- 还没有把校准结果做成用户可视化分布图

### 未完全实现原因

- `v1.2` 重点是先把“真实验证闭环”做出来
- 真正把概率校准到稳定可信，需要多锚点、多资产、多场景的继续打磨

### 建议

- 下一步优先扩前瞻验证样本面，不要只看单个 `2021-01-01` 锚点
- 增强产品层风险修正，让产品级成功率和桶级成功率差异更有信息量

## 主线 3：Product Selection Engine

### 实现了什么

- 约束语义已往更细颗粒度推进：
  - `不买股票` 默认解释为禁个股，不等于禁 ETF/基金权益暴露
- 产品池不再只有极简映射，开始扩到：
  - A 股宽基/红利/行业
  - 债券分层
  - 黄金
  - 现金管理
  - QDII/海外
  - 个股候选边界
- 把 `satellite / qdii / overseas / cash` 这些原先缺口补进执行计划层

### 已实现特性

- 桶到产品不再只是一对一 demo
- 产品层证据字段开始成型
- 可为后续“核心+卫星+现金+债券结构”继续扩展

### 未完全实现的特性

- 产品筛选规则还不是成熟的多因子排序器
- 个股层目前更多是边界和池化能力，不是完整股票研究引擎
- 基金/ETF/场外产品的估值、流动性、跟踪误差还不是全量接入

### 未完全实现原因

- 产品层这次优先补的是执行闭环和资产覆盖面
- 更深入的选品逻辑需要继续叠估值/政策/新闻/维护规则

### 建议

- 后续把“产品注册表 + 产品证据 + 排序理由”再结构化一轮
- 明确核心仓与卫星仓的选品标准差异

## 主线 4：Product Maintenance Policy

### 实现了什么

- 这次把“只给一次性建议”推进到了“季度执行计划 + 高频监控建议”的框架：
  - quarterly execution policy
  - trigger rules
  - daily monitor summary
- 系统不再默认“核心仓完全静态”
- 盘中估算/收盘确认的中国市场约束已进入执行策略层

### 已实现特性

- `daily_monitor` 已有正式桥接与解释输出
- `quarterly` 和 `event` 已能进入真实自然语言桥接
- 执行计划差异解释已经能说明“为什么要换 plan”

### 未完全实现的特性

- 真正成熟的止盈止损/分批买卖规则还需要继续细化
- 当前卫星预算还未完全做到由目标收益缺口动态推导
- 场外基金盘中估算与收盘对账的策略还只是第一版

### 未完全实现原因

- 这次先把执行策略变成正式对象和正式输出
- 更细的交易管理属于下一轮优化，不适合在同一版里把规则写死太重

### 建议

- 用用户目标缺口、回撤预算、剩余期限，推导动态卫星预算
- 把核心仓/卫星仓/现金仓的触发规则再拆细

## 主线 5：Observed Portfolio Sync and Reconciliation

### 实现了什么

- 新增 `observed_portfolio` 正式路径
- 支持：
  - 手工录入
  - 导入
  - OCR 同步
- 系统开始显式区分：
  - target plan
  - planned actions
  - observed portfolio
  - reconciliation

### 已实现特性

- 用户在系统建议前自行操作，不会再被默认当成“已经执行系统计划”
- 支付宝/京东金融这类无 API 场景可以走产品级持仓同步
- `sync_portfolio_manual / import / ocr` 已进入 bridge/task surface

### 未完全实现的特性

- 真正的账单导入和 OCR 质量门还需要扩大样本
- broker API 仍只是接口预留，不是正式接入
- 对账结果还可以更强地反馈回后续推荐逻辑

### 未完全实现原因

- 当前目标是把“无 API 也能同步具体产品持仓”做实
- 账户自动化读取不现实，先把手工/半自动路径走通更重要

### 建议

- 扩充 OCR 样本和异常输入校验
- 对不同账户来源增加更明确的可信度分级

## 主线 6：Claw Adviser Shell and Evidence UX

### 实现了什么

- 扩大自然语言任务面：
  - `onboarding`
  - `show_user`
  - `status`
  - `monthly`
  - `quarterly`
  - `event`
  - `approve_plan`
  - `feedback`
  - `explain_probability`
  - `explain_plan_change`
  - `explain_data_basis`
  - `explain_execution_policy`
  - `sync_portfolio_manual/import/ocr`
  - `daily_monitor`
- 补了两个真实桥接缺陷：
  - 英文 `explain probability / explain data basis / explain execution policy` 路由
  - `approve_plan` 误把 `v12_bridge_user` 中的 `v12` 当成 plan version
- 真实 `openclaw agent` 日志也补了两条说明性对话

### 已实现特性

- bridge JSONL 已覆盖从建档到季度复核、事件复核、执行计划批准、状态查看
- Claw 侧能给出数据真实性解释
- 用户可以问“为什么是这个概率”“为什么用真数据缓存”

### 未完全实现的特性

- memory / cron 自动闭环仍未接上
- `feedback` 在本轮 bridge 序列里没有命中有效 `run_id`，说明这条链路还需再补一轮自然语言场景
- 当前 `openclaw agent` 的动作面说明日志没有覆盖全部新意图，只覆盖了最少动作清单

### 未完全实现原因

- `v1.2` 这次先把 adviser shell 的正式动作面扩全
- 更长的多轮顾问对话编排和 runtime 绑定属于下一阶段

### 建议

- 下一轮把 `feedback` 的真实自然语言闭环补上
- 再加一轮“用户质疑达成率合理性”的完整对话验收

## 本轮新增并已修复的关键问题

### 1. 高级分布模式下空权重集合直接崩溃

问题：

- 用户约束很严、风险暴露极低时，权重集合可能为空
- `garch_t` 路径会把空相关矩阵传进 `np.fill_diagonal`，直接报错

修复：

- 空权重集合现在按“零风险暴露，只走现金流路径”处理
- 不再异常退出
- 已补 contract test

### 2. 英文 explainability 意图未命中

问题：

- `explain probability / explain data basis / explain execution policy` 这类英文自然语言没有命中既有路由规则

修复：

- 已补英文别名
- 已补 agent contract test

### 3. `approve_plan` 版本号解析被用户 id 干扰

问题：

- `approve plan ... for user v12_bridge_user`
- 旧规则会把 `v12` 误解析成 plan version

修复：

- 版本号正则改为只接受独立 token 的 `vN`
- 已补 agent contract test

## 总体判断

`v1.2` 现在已经比 `v1/v1.1` 更接近“真实顾问内核”：

- 数据更真
- 模型更诚实
- 产品层更像产品
- Claw 壳层更像顾问

但最需要诚实面对的一点是：

- **前瞻验证已经能做，但校准质量还不够优秀**

这不意味着路线错了，恰恰说明系统开始有能力用真实未来去检验自己，而不是只会自证。

`v1.2` 的价值，不是把问题都解决完，而是把：

- 真数据
- 真验证
- 真自然语言链路
- 真执行闭环

一起接上了。
