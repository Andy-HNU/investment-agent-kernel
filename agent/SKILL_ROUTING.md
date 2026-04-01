# Skill Routing

## Routing Rule

1. 先判断是否需要 memory / policy-news / recurring task
2. 再调用本仓库 workflow
3. 最后由 advisor shell 负责用户可读解释

## Task Mapping

### 新用户建档
- OpenClaw:
  - memory load
  - natural-language profile parsing
- Kernel:
  - `frontdesk_app.py onboard`

### 月度复查
- OpenClaw:
  - optional memory recall
  - optional policy/news sidecar
- Kernel:
  - `frontdesk_app.py monthly`

### 季度复盘
- OpenClaw:
  - gather updated profile context
- Kernel:
  - `frontdesk_app.py quarterly`

### 用户追问“为什么推荐这个方案”
- Kernel:
  - read `decision_card`, `candidate_options`, `execution_plan_comparison`
- OpenClaw:
  - convert structured evidence to explanation

### 用户要求看政策/新闻影响
- OpenClaw:
  - `policy-news-search`
  - `policy-news-analysis`
- Kernel:
  - absorb only structured sidecar fields, never raw text

### 用户提出定时任务
- OpenClaw:
  - convert to task intent / cron definition
- Kernel:
  - does not own scheduler runtime
