# OpenClaw Boundary

## Source of Truth

- current repo:
  - decision kernel
  - workflow persistence
  - execution plan state
- OpenClaw:
  - memory runtime
  - policy/news runtime
  - cron / recurring task runtime
  - conversation shell

## No-Copy Rule

- 不复制 OpenClaw skill 正文到本仓库
- 只记录引用路径和边界
- 如需修改外部 skill，只 patch 回原仓库

## Integration Rule

- OpenClaw 调本仓库 workflow
- 本仓库返回结构化结果
- OpenClaw 负责把结果组织成 advisor 对话
