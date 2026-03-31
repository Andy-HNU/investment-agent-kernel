# 交付前检查清单

## 必做
- 确认根目录存在：`AGENTS.md`、`README.md`、`system/`、`tests/`、`src/`
- 确认 `tests/conftest.py` 已把 `src/` 加入 `sys.path`
- 确认 `system/` 中 patched 文档是冻结真相源
- 确认 `docs/legacy/` 与 `docs/review/` 只作参考，不再充当冻结规格

## 推荐
- 把你的正式代码仓库初始化为 git 仓库后再交给 Codex
- 首轮只要求 Codex：搭骨架、过 contract、过 smoke
- 第二轮再要求它补 unit/scenario/regression

## 不建议
- 第一轮直接要求“全系统完整实现”
- 第一轮接入真实数据源或数据库
- 让 Codex 自行处理文档冲突而不提供 `AGENTS.md`
