# system/ 说明

这是当前仓库的主规格目录。

版本组织：

- `00` 到 `10`：当前主链冻结规格，内部保留各模块原始版本号（如 `v2`、`v2.1`、`v1.2 patched`）
- `11` 到 `14`：围绕产品映射、provider、多源 sidecar 与开源级发布准备的 `v2` 补充规格

阅读建议：

- 先读 `00-10` 主链，理解 kernel 核心模块
- 再读 `v2` 补充规格，理解产品化、数据源矩阵、policy/news sidecar 与开源级门槛

阅读优先级建议：
1. `00_system_topology_and_main_flow.md`
2. `05_constraint_and_calibration_v1.1_patched.md`
3. `04_runtime_optimizer_v2.2_patched.md`
4. `10_ev_engine_v1.2_patched.md`
5. `09_decision_card_spec_v1.1_patched.md`
6. 其余模块文档

新增 `v2` 补充规格：
1. `11_product_mapping_and_execution_planner_v2.md`
2. `12_provider_capability_matrix_v2.md`
3. `13_policy_news_structured_signal_contract_v2.md`
4. `14_open_source_release_readiness_v2.md`

注意：
- patched / 附录收口优先于正文旧口径
- 当前编号缺少 06，不表示缺文件，而是原始系统当前没有对应冻结实现规格
- 若要看当前开发顺序与 active handoff，请先看 [`handoff/README.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/README.md) 和 [`CODEX_artifact_registry_2026-04-01.md`](/root/AndyFtp/investment_system_codex_ready_repo/handoff/CODEX_artifact_registry_2026-04-01.md)
- `v2` 补充规格默认与 `00-10` 主链并存；若后续要正式替换旧语义，应在 handoff 与对应 system 文档中显式宣布
