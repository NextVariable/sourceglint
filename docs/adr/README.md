# ADR — Architecture Decision Records

本目录记录 `sourceglint` 的所有**架构级决策**。

## 何时需要写 ADR

自 v0.2（Architecture Baseline）起，修改以下**冻结契约**必须新增 ADR（编号递增），不得静默改动：

| 契约 | 对应 Design Review 章节 |
|------|------------------------|
| Evidence Schema | §9 |
| Pipeline stages 及其 CODE/LLM 归属 | §7 / §11 |
| Signal Score 公式、权重、分级阈值 | §10 |
| FACT / INFERENCE / RECOMMENDATION contract | §12 |
| LLM / Code 边界 | §11 |
| Source Registry contract（sources.yaml 字段） | §8 |
| Output contract | §12 |

**小型实现细节**（变量命名、模板措辞、单个源连接器的内部实现）无需 ADR，由测试与 code review 兜底。

## 编号规则

- 格式：`NNNN-<kebab-case-slug>.md`，NNNN 从 `0001` 起递增，不重复使用。
- 一个 ADR 只记录一个决策。
- 已批准的 ADR 不被改写；如需变更，新开 ADR 并标注 `Supersedes: NNNN`。

## 模板

每个 ADR 包含六段（见 `0001-sourceglint-core-architecture.md` 示范）：

1. **Status** — Proposed / Accepted / Superseded
2. **Context** — 背景与约束
3. **Decision** — 决定是什么
4. **Why** — 理由
5. **Trade-offs** — 权衡
6. **Alternatives Rejected** — 否决过的替代方案及否决原因
7. **Consequences** — 后果（正面 + 负面 + 需要跟进的事）

## 索引

| ADR | 主题 | 状态 |
|-----|------|------|
| [0001](0001-sourceglint-core-architecture.md) | 核心架构基线（确定性引擎 + LLM JSON + 代码渲染） | Accepted |
| [0002](0002-discovery-first-positioning.md) | 近期信息与需求发现优先，决策支持按需深入 | Accepted |
| [0003](0003-research-default.md) | 近期研究默认输出，建议需明确启用 | Accepted |
