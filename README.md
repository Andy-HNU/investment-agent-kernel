# Investment Decision System — Codex Ready Repo Seed

这是把你原始“系统规格包 + TDD 启动包 + Codex handoff 说明”整理后的正式仓库版种子。

它的目标不是直接提供完整业务代码，而是把原始压缩包收口成一个 **可直接交给 Codex 开发的 repo seed**：
- 根目录规则明确
- 主规格目录明确
- 测试门禁位置明确
- 历史文档与冻结规格分层清楚
- 文件名统一为更稳定的 ASCII 方案

## 这一版和原始 zip 的区别
- 把 `system/` 保留为主规格目录
- 把 `TDD/investment_test_bootstrap/` 正式并入根目录：`tests/`、`pytest.ini`、`.coveragerc`、`.github/workflows/`
- 把旧文档、审阅记录、TDD 说明移动到 `docs/`
- 加入 `AGENTS.md`、`handoff/`、`pyproject.toml`、`.gitignore`
- 加入 `src/` 代码骨架目录与 `__init__.py`
- 修正测试环境：`tests/conftest.py` 会把 `src/` 加入 `sys.path`

## 权威性顺序
1. `AGENTS.md`
2. `tests/` 中 contract / smoke tests
3. `handoff/CODEX_first_round_prompt.md`
4. `system/` 中 patched / 冻结版文档
5. `docs/` 中背景与归档文档

## 目录概览
```text
.
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ pytest.ini
├─ .coveragerc
├─ .github/workflows/
├─ system/
├─ docs/
├─ handoff/
├─ tests/
└─ src/
```

## 推荐使用方式
### 交给 Codex 前
1. 把本目录作为正式仓库根目录
2. 初始化 git 仓库
3. 把 `handoff/CODEX_first_round_prompt.md` 直接作为 Codex 首轮任务说明

### 交给 Codex 的首轮目标
- 阅读 `AGENTS.md`
- 阅读 `system/` 主规格与 `tests/`
- 在 `src/` 下补最小类型与入口模块
- 先通过 contract tests
- 再通过 smoke test

### 你验收的最低标准
- contract tests 全通过
- smoke test 通过
- 没有越权重定义 canonical types
- 没有改坏冻结接口

## 当前已知说明
- `system/` 当前没有 06 号模块规格；这是源包现状，不需要 Codex 自行创造。
- `docs/legacy/`、`docs/review/` 中保留了历史信息，但不再充当冻结真相源。
- 当前 `src/` 仍是骨架，正式实现需要由 Codex 或开发者继续补齐。

## 首轮本地检查
```bash
pytest -q
```

在当前仓库骨架下，缺少正式实现时，部分 contract / smoke 会因为 `importorskip(...)` 被跳过；这是正常现象。首轮开发的目标就是把这些入口模块补到可测。

## 本地体验入口

Round 5 之后，仓库根目录保留两个稳定 demo 入口：

1. `python3 demo.py <scenario> [--json]`
2. `python3 scripts/full_flow_demo.py [--json]`

默认推荐先跑：

```bash
python3 scripts/full_flow_demo.py
python3 demo.py full_lifecycle --json
```

常用 canonical scenario：

```bash
python3 demo.py quarterly_review --json
python3 demo.py monthly_replay_override --json
python3 demo.py provenance_relaxed --json
python3 demo.py provenance_blocked --json
```

兼容 alias 仍保留，但输出会回落到 canonical scenario 名称：

`quarterly_full_chain`、`monthly_provenance_blocked`、`monthly_provenance_relaxed`、`journey`

其中 `full_lifecycle` / `scripts/full_flow_demo.py` 会覆盖：

`03 snapshot_ingestion -> 05 calibration -> 08 allocation -> 02 goal_solver -> 04 runtime_optimizer -> 07 orchestrator -> 09 decision_card`
