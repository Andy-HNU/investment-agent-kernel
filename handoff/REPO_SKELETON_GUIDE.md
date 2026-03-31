# 仓库骨架说明

当前目录已经是“可直接交给 Codex 的 repo seed”。

三类内容的角色如下：
- `AGENTS.md`：仓库级硬约束与裁决顺序
- `system/`：冻结系统规格
- `tests/` + `pytest.ini` + CI：测试门禁

首轮开发建议：
1. 先在 `src/` 补类型与最小入口
2. 先过 contract tests
3. 再过 smoke test
4. 再迭代真实逻辑
