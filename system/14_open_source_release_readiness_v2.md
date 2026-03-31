# 14_open_source_release_readiness_v2.md
# 开源级发布准备与质量门 v2

> 文档定位：本文件规定当前仓库在接入 Claw 前，达到“个人长期使用 + 对外开源不丢人”所需的发布准备标准。
>
> 这不是商用 SLA 文档，而是开源级 readiness 文档。

---

## 0. 一句话定义

**Open-source readiness 的目标是：让别人拉下仓库后，能理解边界、复现实验、跑通样例，并知道哪些东西已经做了、哪些还没做。**

---

## 1. 范围目标

### 1.1 本阶段要做到

- 单用户长期低频使用足够稳定
- 开源用户能安装、运行、复现 sample flow
- provider 覆盖范围与缺口公开透明
- degraded / fallback / replay 行为有文档和样例

### 1.2 本阶段不承诺

- 商用级全资产覆盖
- 企业级可用性 SLA
- 自动交易
- 多租户平台能力

---

## 2. 必备发布材料

- `README`
- 安装说明
- 本地运行说明
- sample dataset / frozen fixtures
- sample commands / sample flow
- provider capability matrix
- 风险边界与非目标范围说明
- 已知缺口清单

---

## 3. 必备质量门

### 3.1 可复现性

- 固定 sample dataset 时结果可重放
- 固定 `seed / n_paths / as_of` 时结果可解释
- replay 不依赖外部源当场状态

### 3.2 可诊断性

- degraded 原因可读
- fallback 原因可读
- provider 缺口可读
- 执行计划与产品替代原因可读

### 3.3 可安装性

- 新用户能按说明完成本地安装
- 能跑通一条最小 end-to-end flow

### 3.4 可披露性

- 覆盖了哪些资产
- 哪些资产是 partial / degraded
- 哪些 provider 是主源 / 备源
- 哪些功能还没做

---

## 4. 与 Claw 接入的关系

只有在本文件的最小标准满足后，才进入 Claw 集成阶段。  
原因：

- 否则 advisor shell 会被迫替 kernel 擦大量边界问题
- 集成成本高，且容易把“kernel 未完成”误判成“agent 体验差”

---

## 5. 推荐输出物

- `provider capability matrix` 正文
- `product pool` 正文
- `policy/news structured signal` 正文
- `sample dataset`
- `frozen replay fixtures`
- `known gaps / non-goals`

---

## 6. 测试与验收要求

- sample flow smoke
- replay fixture regression
- install / local-run smoke
- documentation completeness checklist
- 自然语言画像 3x 随机验收继续保留

---

## 7. v2 范围结论

本文件把“做得不丢人”从口头要求收成正式门槛。  
它要求的是：

- 诚实
- 可复现
- 可解释
- 能跑

而不是虚假地宣称“已经商用级完成”。
