# 投资系统 pytest + CI gate 启动包

已包含：

- 测试启动包说明
- 给 Codex 的任务说明
- pytest.ini
- .coveragerc
- 共享 conftest
- 测试工厂 factories
- 4 组契约测试
- 1 个最小 smoke test
- fast / full 两份 GitHub Actions workflow
- 分支门禁配置建议
- 模板接入真实代码的实现备注

建议直接把整个 zip 交给 Codex，然后要求它先按 contract + smoke + coverage 把主干门禁搭起来。
