# src/ 目录说明

这是给 Codex 的最小代码骨架位置。

当前仓库只提供：
- 冻结系统规格 `system/`
- 根目录规则 `AGENTS.md`
- 测试门禁 `tests/` + `pytest.ini` + CI

首轮开发建议：
1. 先补类型定义与最小入口模块
2. 先过 contract tests
3. 再过 smoke tests
4. 再迭代真实逻辑
