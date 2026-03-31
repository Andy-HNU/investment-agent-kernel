# 投资系统测试启动包说明

这是一套可直接交给 Codex 的 **pytest + CI gate 启动骨架**。

## 目标
先建立测试门禁，再让业务代码进入主干。优先级如下：

1. 先把 `tests/` 骨架和 `conftest.py` 搭起来
2. 先落 4 组核心契约测试
3. 先落一个最小 smoke e2e
4. 先配 `coverage` 与 GitHub Actions
5. 再在 TDD 过程中逐步补实现与测试

## 目录概览

- `tests/conftest.py`：全局共享 fixture 与工厂入口
- `tests/fixtures/factories.py`：测试对象工厂
- `tests/helpers/contracts.py`：契约断言 helper
- `tests/contract/`：模块接口契约测试
- `tests/smoke/`：最小闭环冒烟测试
- `.github/workflows/ci_fast.yml`：PR 快速门禁
- `.github/workflows/ci_full.yml`：较重测试 / 手动或夜间运行

## 落地顺序建议

### 第 1 批
- 先创建模块与文件
- 让 import 路径跑通
- 让 contract 测试能执行
- 让 smoke test 至少跑出 `DecisionCard` / `RuntimeOptimizerResult` 的最小闭环

### 第 2 批
- 给 `GoalSolver` / `RuntimeOptimizer` / `EV Engine` 补更强单元测试
- 把 golden regression 和 calibration 指标接入

## 注意
这套文件是 **启动模板**，不是完整业务实现。  
Codex 应按现有系统文档的冻结口径补齐模块与类型，并确保以下分层不被破坏：

- `calibration/` 是状态与参数的 canonical source
- `runtime_optimizer/` 只编排，不评分
- `runtime_optimizer/ev_engine/` 只评分，不生成候选
- `decision_card/` 只消费结构化结果生成展示对象

