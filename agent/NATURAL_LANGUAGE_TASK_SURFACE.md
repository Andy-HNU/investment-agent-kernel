# Natural Language Task Surface

## Supported Intents

- 新用户建档
- 月度复查
- 季度复盘
- 查询当前状态
- 确认执行计划
- 回填执行结果
- 询问政策/新闻对当前方案的影响
- 定义 recurring review task

## Required Intent Shape

- `task_name`
- `task_type`
- `trigger_type`
- `input_scope`
- `workflow_steps`
- `output_expectation`

## Boundary

- 调度由 OpenClaw cron 管
- 自然语言解析由 advisor shell 管
- 本仓库只要求最终被翻译成稳定 workflow 调用
