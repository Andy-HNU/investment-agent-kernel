# Kernel First Roadmap for Advisor-Agent Integration

  ## Summary

  开发顺序调整为：

  1. 先补强 kernel
  2. 再做实时抓取与历史数据底座
  3. 最后做 advisor agent / Claw 接入

  这样做的原因是对的：当前 Claw 集成测试上下文成本高，如果 kernel 还在变，agent shell 会反复重做，既费 token，也费验收成本。
  后续原则固定为：

  - 当前仓库继续作为 decision kernel
  - Claw 继续作为未来 advisor shell / runtime
  - OpenClaw 现有 skill 不复制回当前仓库
  - 若修改借用来的 Claw skill，只回 patch 到 Claw 原路径；当前仓库只保留引用、边界和 patch-back 规则

  ## Roadmap

  ### Phase 1. Kernel completion

  目标：把当前系统从“可运行内核”补到“可稳定被 Claw 调用的正式内核”。

  优先顺序：

  - 02 goal_solver
      - 补齐更正式的 Monte Carlo / infeasibility 细节
      - 强化 solver_notes 和用户可解释结果链
      - 明确哪些输出是真概率，哪些只是模型估计，避免再次语义漂移
  - 10 ev_engine + 04 runtime_optimizer
      - 补完整的 FeasibilityFilter 覆盖
      - 收紧五项分量公式与量纲校准
      - 补候选动作规则族、amount 预填/裁剪、monthly/event/quarterly 差异规则
      - 强化推荐理由生成规则，避免“能跑但解释虚”
  - Product Mapping / Execution Planner
      - 在资金桶决策核之外新增“产品映射层”，不把具体产品选择逻辑硬塞进 solver 数学核心
      - 把 bucket allocation 映射到具体 ETF / 基金 / 国债 / 黄金 / 现金管理产品清单
      - 支持宽基 / 红利 / 行业 / 风格 / 纯债 / 政金债 / 黄金 ETF 等产品族
      - 定义产品池、候选筛选规则、替代品规则、执行理由与用户可读执行计划
      - 输出“可执行计划”，而不只是抽象资金桶
  - 03 snapshot_ingestion + 05 calibration
      - 完成更完整的五域 raw snapshot typing
      - 增加 cashflow_events_raw 等严格校验
      - 补 market calibration 的保守收缩逻辑、vol floor、correlation handling、version uniqueness
      - 明确 degraded / fallback / replay 的解释链
      - 增加 policy/news 结构化信号入口：
          - 不让新闻文本直接改写 solver 数学
          - 允许 sidecar 产出可审计的结构化 regime / uncertainty / review flags
          - 经 05 保守吸收后，只影响参数约束、review gate 或解释层
  - 07 orchestrator
      - 补 replay / override / provenance 深水区
      - 增加真正的 persistence / audit 执行适配层
      - 保证任一 run 都能回放“当时输入、参数、建议、反馈”
  - 08 allocation_engine + 09 decision_card
      - 强化候选多样性，避免“换名字不换方案”
      - 拆清 low_confidence / degraded / blocked / escalated
      - 继续产品化 decision card 的解释度，但不进入具体产品推荐层

  完成标准：

  - kernel 输出语义和 system/ 文档主承诺一致
  - 不依赖 demo builder / 打桩默认值去假装正式结论
  - 可长期作为 Claw 的稳定工具面，不需要 agent 再替 kernel 擦语义屁股
  - 用户侧结果至少提升到“资金桶建议 + 具体产品执行计划”双层输出

  ### Phase 2. Real-time and historical data development

  目标：把“外部输入”和“历史数据底座”从半真实/打桩推进到正式 provider architecture。

  拆成两条线：

  - 2A. 03/05 实时输入
      - 建立 provider abstraction，不把单一源写死进主链
      - 第一版优先接免费公开源，低频场景先不要求付费 API
      - 明确资产覆盖目标与能力矩阵：
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
      - 对每类资产标注：
          - 主源 / 备源 / 降级源
          - 实时支持情况
          - 历史支持情况
          - 当前已验证状态
      - 建议分层：
          - 行情/快照：AKShare 优先，必要时加公开 HTTP/网页源备份
          - 券商/账户/持仓：broker/account provider 或手工快照导入接口，用于 `account_raw / live_portfolio`
          - 新闻：公开新闻源 + AKShare 能直接取的新闻接口
          - 政策：官方站点为主，配合 Claw 的 policy-news-search / analysis
      - 输出进入 market_raw / account_raw / behavior_raw / live_portfolio 的标准化 contract
      - policy/news sidecar 只允许以结构化信号进入：
          - `policy_regime`
          - `macro_uncertainty`
          - `sentiment_stress`
          - `manual_review_required`
      - 保留 fail-open / fallback / freshness / provenance 体系
      - 同时建立免费源工程红线：
          - monitoring / alerting
          - rate limit / retry / backoff
          - cache / TTL / refresh strategy
          - persistence / audit logging
          - validation / reconciliation
          - schema drift detection
          - source fallback priority
          - ToS / 商用边界 / 可持续性评估
  - 2B. 02/04 历史数据底座
      - 建立历史价格/收益序列获取、清洗、缓存、统一口径层
      - 明确哪些数据用于：
          - Goal Solver 的历史分布/参数校准
          - Runtime / EV 的状态解释和回放
      - 不直接把实时抓取结果当回测资产使用
      - 增加本地缓存与快照化机制，保证复现和低频系统稳定性
      - 增加数据版本与落账要求：
          - 历史数据集版本号
          - provider snapshot 落账格式
          - replay 引用的数据版本锚点
          - idempotent refresh / retention policy

  完成标准：

  - 03/05 不再只靠通用 http_json adapter 演示
  - 02/04 不再主要依赖默认 expected_returns / volatility / correlation_matrix
  - provider capability matrix 能明确说明各资产类别当前覆盖程度
  - 所有外部输入都能回答：
      - 来源是什么
      - 抓取时间是什么
      - fallback 了没有
      - 是否足以进入正式求解/评估

  ### Phase 3. Data and provider testing

  目标：把“能抓到”升级成“抓得对、用得稳、回得放”。

  测试分 4 类：

  - Provider contract
      - 行情/新闻/政策/快照 provider 的字段 contract、错误处理、fail-open/fail-closed、freshness、provenance
      - 针对免费源增加 source-specific regression，防字段漂移
  - Semantic data tests
      - 外部抓取进入 03 -> 05 后是否正确影响 calibration / state
      - 历史序列进入 02/04 后是否真正影响 Monte Carlo / EV，而不是只挂接口不生效
  - Replay / reproducibility
      - 固定快照和历史数据集时，run_id 对应结果可回放
      - seed / n_paths / historical window 变化对结果有真实影响
      - 外部源变化不会污染已落账 run 的复现
  - Acceptance tests
      - 用真实 provider mock + 冻结历史样本做 end-to-end
      - 场景至少覆盖：
          - onboarding with external market/account snapshot
          - monthly with refreshed account snapshot
          - policy/news sidecar available but not rewriting solver math
          - degraded / fallback / stale data cases
          - 自由表达自然语言画像输入
          - 每个大功能点完成后的三次差异化随机画像回归
          - 本轮画像验收不过，则不得进入下一轮随机画像

  完成标准：

  - 测试保护“规格与语义”，不只是保护“当前输出结构”
  - provider source 漂移能被尽早发现
  - 历史数据和实时输入都能通过 replay 解释清楚

  ### Phase 4. Open-source quality hardening before Claw

  目标：在接入 Claw 前，把 kernel 从“正式第一版”再补到“个人长期可用、对外开源不丢人”的程度。

  内容包括：

  - provider 多源策略硬化
      - 主源 / 备源 / 降级源优先级
      - 资产类别覆盖矩阵与缺口清单
      - 数据缺口与覆盖范围文档
      - drift 发现后的快速切换策略
  - 工程运行硬化
      - monitoring / alerting
      - retry / backoff / rate limit
      - cache / TTL / refresh discipline
      - persistence / audit logging
      - validation / reconciliation
  - 开源级可复现与可诊断能力
      - 一键 demo / sample dataset / frozen fixtures
      - run replay / dataset replay / seed pinning
      - 错误与 degraded 状态的人类可读诊断
  - 产品映射层硬化
      - 产品池来源说明
      - 产品替代品与停用策略
      - 产品计划输出的解释度与可维护性
  - 开源发布质量
      - 安装说明
      - 本地运行说明
      - provider 能力矩阵
      - 非目标范围与风险边界说明

  完成标准：

  - 单用户长期低频使用足够稳定
  - 对外开源时，别人能理解边界、复现实验、跑通 sample flow
  - 即便不是商用级全覆盖，也不会因为明显粗糙的 provider / replay / docs 质量而失真
  - 资产覆盖范围与工程边界都被明确披露，不靠暗含假设

  ### Phase 5. Advisor-agent / Claw integration

  目标：在 kernel 和数据底座稳定后，再做低上下文成本的 Claw 接入。

  只在前 4 阶段稳定后开始。内容包括：

  - 当前仓库新增 agent/ 与 integration/openclaw/ 文档层
      - tool contracts
      - skill routing
      - playbook
      - OpenClaw boundary
      - patch-back policy
  - Claw 侧负责：
      - memory-system
      - policy-news-search / analysis
      - cron / recurring task intent
      - advisor shell 对话组织
      - runtime acceptance
  - 当前仓库负责：
      - frontdesk/workflow 稳定调用面
      - decision kernel JSON contract
      - sidecar evidence contract
      - 不复制外部 skills，只记录引用路径与 patch-back 规则

  完成标准：

  - Claw 能把自然语言任务稳定路由到当前仓库
  - 当前仓库不承担 scheduler / memory runtime
  - 修改外部 Claw skill 时，有明确 patch-back 记录，不在当前仓库养 fork

  ## Important Interfaces and Contracts

  后续开发必须显式冻结这些接口：

  - frontdesk_app.py 的 workflow surface
      - onboarding/onboard
      - monthly
      - event
      - quarterly
      - show-user
      - status
      - feedback
  - 外部输入 contract
      - external_snapshot_source
      - external_data_config
      - FetchedSnapshotPayload
      - raw_overrides -> market_raw / account_raw / behavior_raw / live_portfolio
  - 历史数据 contract
      - 价格序列、收益序列、日期轴、资产桶映射、缓存键、as-of 版本锚点
      - 数据集版本号、provider 来源、落账格式、replay version pin
      - 必须显式区分“实时快照输入”和“历史回放/校准输入”
  - 产品映射与执行计划 contract
      - bucket allocation -> concrete products
      - 产品池 schema、筛选规则、替代品规则、执行理由、风险标签
      - 用户确认前后状态与执行计划版本锚点
  - policy/news structured signal contract
      - sidecar 输出字段、置信度、来源、as-of 时间、是否触发 manual review
      - 明确禁止把原始新闻文本直接当成 solver 输入
  - OpenClaw integration contract
      - 当前仓库只保留 source map、boundary、patch-back policy

  ## Test Plan

  ### Kernel-first gates

  - system/ 文档对应的 spec-conformance tests 持续补齐
  - 02/04/10 的公式与语义测试优先于 UI/agent 测试
  - 多方案差异化必须进 acceptance，而不是只看字段存在
  - 自然语言自由表达画像测试必须持续保留
  - 每个大功能点完成后，必须做 3 次差异化随机画像验收
  - 当前画像验收不过，不进入下一轮随机画像或下一功能点

  ### Data gates

  - provider contract tests
  - source drift regression
  - historical replay consistency tests
  - stale/fallback/fail-open acceptance
  - broker/account/live_portfolio provider contract tests
  - asset-coverage matrix consistency tests
  - cache / TTL / refresh strategy tests
  - monitoring / alerting smoke
  - retry / rate-limit / backoff tests
  - persistence / audit logging tests
  - validation / reconciliation tests
  - data-version pinning / replay-dataset consistency tests
  - policy/news structured signal contract tests

  ### Open-source hardening gates

  - provider capability matrix 与已知缺口文档齐全
  - 资产覆盖矩阵按 `A股/港股/美股/ETF/基金/债券/黄金/现金类/QDII/行业指数` 明示
  - sample dataset / frozen replay fixtures 可直接运行
  - 产品映射层有替代品回归与产品停用回归
  - README / install / local-run / risk-boundary 文档可供外部用户独立上手

  ### Agent-last gates

  - agent 文档契约测试
  - Claw runtime smoke
  - advisor 对话回路验收
  - memory / policy-news / recurring task routing 验收

  ## Assumptions

  - 短期内不做自动交易和代下单
  - 低频场景下，第一版实时/历史数据优先使用免费公开源
  - AKShare 可作为第一优先免费源，但不能假设其所有接口都长期稳定或全部免认证
  - 政策数据优先采用官方站点，news/policy 分析由 Claw sidecar 提供，不直接改写 solver 数学结论
  - agent 接入阶段放最后，等 kernel、数据底座和开源级硬化稳定后再开始，避免反复烧上下文和集成成本
