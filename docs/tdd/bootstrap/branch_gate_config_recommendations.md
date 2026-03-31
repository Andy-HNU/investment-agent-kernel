# 分支门禁配置建议

建议把 `main` 设为受保护分支，并将下列 checks 设为 required：

- `ci-lint`
- `ci-contract-core`
- `ci-smoke-e2e`
- `ci-coverage-core`

初期 `ci-typecheck` 可以先作为 advisory，待模块类型稳定后升级为 required。

## 升级顺序

### 阶段 1
required:
- lint
- contract-core
- smoke-e2e
- coverage-core

### 阶段 2
required:
- typecheck
- scenario-flows
- regression-golden

### 阶段 3
required:
- probability-calibration
- shadow-validation（后续补）

## 门禁原则

- 只要 contract test 挂了，说明接口口径被改坏，禁止合并
- 只要 smoke e2e 挂了，说明最小闭环被改坏，禁止合并
- 只要 coverage 低于阈值，禁止合并
- 改正式签名时，必须同步修改 contract tests
