# 架构决策记录

本目录记录 `sourceglint` 的所有**架构级决策**。

## 何时需要写 ADR

自 v0.2（架构基线）起，修改以下**冻结契约**必须新增 ADR（编号递增），不得静默改动：

| 契约 | 对应设计审查章节 |
|------|------------------------|
| 证据结构 | §9 |
| 流水线阶段及代码与模型的职责 | §7 / §11 |
| 信号评分公式、权重、分级阈值 | §10 |
| 事实、推断与建议契约 | §12 |
| 模型与代码边界 | §11 |
| 来源注册契约（sources.yaml 字段） | §8 |
| 输出契约 | §12 |

**小型实现细节**（变量命名、模板措辞、单个源连接器的内部实现）无需 ADR，由测试与 代码审查 兜底。

## 编号规则

- 格式：`NNNN-<kebab-case-slug>.md`，NNNN 从 `0001` 起递增，不重复使用。
- 一个 ADR 只记录一个决策。
- 已批准的 ADR 不被改写；如需变更，新开 ADR 并标注 `Supersedes: NNNN`。

## 模板

每个 ADR 包含七段（见 `0001-sourceglint-core-architecture.md` 示范）：

1. **状态** — 提议、已采纳或已替代
2. **背景** — 背景与约束
3. **决策** — 决定是什么
4. **理由** — 理由
5. **权衡** — 权衡
6. **否决的替代方案** — 否决过的替代方案及否决原因
7. **后果** — 后果（正面 + 负面 + 需要跟进的事）

## 索引

| ADR | 主题 | 状态 |
|-----|------|------|
| [0001](0001-sourceglint-core-architecture.md) | 核心架构基线（确定性引擎 + 模型结构化输出 + 代码渲染） | 已采纳 |
| [0002](0002-discovery-first-positioning.md) | 近期信息与需求发现优先，决策支持按需深入 | 已采纳 |
| [0003](0003-research-default.md) | 近期研究默认输出，建议需明确启用 | 已采纳 |

## English

This directory records architecture decisions. Changes to frozen contracts require a new, incrementally numbered ADR: evidence schemas, pipeline ownership, signal scoring, facts/inferences/recommendations, model/code boundaries, source registry and output contracts. Small implementation details are covered by tests and code review.

Use `NNNN-<kebab-case-slug>.md`, starting at `0001`, with one decision per record. Preserve accepted records; replace them through a new ADR with `Supersedes: NNNN`. Each record covers status, context, decision, rationale, tradeoffs, rejected alternatives and consequences.

| ADR | Topic | Status |
| --- | --- | --- |
| [0001](0001-sourceglint-core-architecture.md) | Core architecture: deterministic engine, structured model output and code rendering | Accepted |
| [0002](0002-discovery-first-positioning.md) | Recent discovery first; decision support on request | Accepted |
| [0003](0003-research-default.md) | Research by default; recommendations explicitly enabled | Accepted |
