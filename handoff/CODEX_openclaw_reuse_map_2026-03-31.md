# OpenClaw Reuse Map

日期：2026-03-31

目的：
- 明确当前投资系统接入 OpenClaw 现有能力时，哪些可以直接复用
- 避免把旧的规则型投资 overlay 与当前目标概率型决策内核混为一体
- 为后续 agent 化产品提供稳定参考边界

## 结论

当前仓库应继续作为：
- 目标求解与候选配置的权威决策内核
- 运行期优化、决策卡、frontdesk 状态持久化的权威来源

OpenClaw 现有资产应主要作为：
- memory / policy-news / cron / routing / playbook 的 companion layer
- 截图导入、日报周报、新闻工作流的参考实现

不建议直接把 `projects/investment/` 旧规则引擎整体并入当前仓库。

## 直接复用

### 1. 记忆机制

来源：
- `/root/.openclaw/workspace/skills/memory-system/SKILL.md`
- `/root/.openclaw/workspace/MEMORY.md`

可复用内容：
- 永久记忆 / 衰减记忆的分类规则
- “记住 / 别记 / 恢复记忆 / 周总结” 的对话协议
- 周归档与长期记忆沉淀方式

建议接入方式：
- 作为 advisor agent 的长期协作记忆协议
- 不直接改写当前 frontdesk SQLite；先作为外层记忆系统并行存在

### 2. 政策与新闻 skill

来源：
- `/root/.openclaw/workspace/skills/policy-news-search/SKILL.md`
- `/root/.openclaw/workspace/skills/policy-news-analysis/SKILL.md`

可复用内容：
- 搜索与分析解耦
- source labeling
- knowledge-gap 明示
- SQLite 知识沉淀流程

建议接入方式：
- 作为 market/policy intelligence sidecar
- 先为当前决策卡提供“外部解释层”，不直接改写 solver 数学结论

### 3. 定时与任务意图

来源：
- `/root/.openclaw/workspace/CRON.md`
- `/root/.openclaw/workspace/projects/investment/agent/NATURAL_LANGUAGE_TASK_SURFACE.md`

可复用内容：
- recurring task intent 结构
- cron 约定
- reminder / review / digest 的节奏化设计

建议接入方式：
- 用于后续把 monthly / quarterly / policy-watch / memory-digest 挂到 Claw cron
- 当前仓库不重复开发调度器

### 4. Agent 路由与控制面

来源：
- `/root/.openclaw/workspace/projects/investment/agent/SKILL_ROUTING.md`
- `/root/.openclaw/workspace/projects/investment/agent/OPENCLAW_CONTROL_SURFACE.md`
- `/root/.openclaw/workspace/projects/investment/agent/EXTENSIBILITY_MAP.md`

可复用内容：
- “自然语言 -> skill/workflow” 的映射方式
- 控制面与代码面分离
- 哪些内容可由 agent 编辑，哪些必须交给 Codex 改代码

建议接入方式：
- 作为未来 advisor-agent routing 说明书
- 不直接把旧 CLI 命令当成当前仓库的权威接口

## 仅作参考，不直接并入

### 1. 旧投资 overlay 的规则型引擎

来源：
- `/root/.openclaw/workspace/projects/investment/src/investment_agent/`
- `/root/.openclaw/workspace/projects/investment/system/*.md`

原因：
- 该项目的主目标是仓位管理、风险预警、周报月报、新闻辅助建议
- 当前仓库的主目标是目标达成概率、候选配置、运行期动作优化、决策卡
- 两者的“顶层目标函数”不同

处理原则：
- 可参考其 screenshot/news/report workflow
- 不直接替换当前 goal solver / EV / decision card 主链

### 2. 固定配置与个案长期规则

来源：
- `/root/.openclaw/workspace/MEMORY.md`
- `/root/.openclaw/workspace/projects/investment/system/02_allocation_model.md`
- `/root/.openclaw/workspace/projects/investment/system/04_monthly_rule.md`

原因：
- 含个人账户特定规则与固定长期比例
- 不应污染当前“按用户画像与目标求解”的通用系统

处理原则：
- 只当样例，不当默认值

## 接入后的角色分工

### 当前投资仓库负责

- user profile -> governance / constraints
- candidate allocations
- goal probability / shortfall / drawdown solving
- runtime optimization / EV
- decision card / frontdesk state / feedback

### OpenClaw companion layer 负责

- memory discipline
- policy/news retrieval and analysis
- recurring task intent
- cron execution
- advisor workflow routing
- screenshot/report/news tooling参考

## 当前最合理的接入姿势

1. 保持当前仓库为 decision kernel
2. 把 OpenClaw skill / memory / policy-news / cron 作为外层 agent 能力吸收
3. 先做“advisor agent manuals + skillbook + tool contracts”
4. 再决定是否把 screenshot/news/report 工具逐步桥接到当前 frontdesk

## 红线

- 不把旧规则型 overlay 直接声明为当前系统的主引擎
- 不把 OpenClaw 的个人记忆和固定仓位规则写成当前仓库默认值
- 不让 policy/news 解释层直接改写 solver 输出，只能作为补充证据层
