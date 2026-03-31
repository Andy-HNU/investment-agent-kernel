# 如何把模板接到真实代码

## 1. 先补真实模块

按当前系统文档，Codex 应优先创建：

- `src/calibration/types.py`
- `src/goal_solver/types.py`
- `src/runtime_optimizer/types.py`
- `src/runtime_optimizer/state_builder.py`
- `src/runtime_optimizer/optimizer.py`
- `src/runtime_optimizer/ev_engine/types.py`
- `src/runtime_optimizer/ev_engine/engine.py`
- `src/decision_card/builder.py`

## 2. 再替换测试中的 dict fixture

当前 fixture 为了让你快速开工，先使用了 dict 风格对象。  
一旦真实 dataclass 就位，建议把 factory 改为真实类型实例，而不是一直停留在 dict。

## 3. 为什么这样设计

因为当前阶段最重要的是：
- 收住接口
- 建立门禁
- 让 Codex 先按契约开发
- 避免实现跑偏

不是一开始就追求测试输入“100% 真实”。

## 4. 首批应该让哪些测试先变绿

1. `test_05_to_02_contract.py`
2. `test_05_to_04_contract.py`
3. `test_04_to_10_contract.py`
4. `test_07_to_09_contract.py`
5. `test_end_to_end_minimal.py`
