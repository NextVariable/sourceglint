# ADR-0001: sourceglint 核心架构基线

- **Status**: Accepted
- **Date**: 2026-09-06
- **Version**: 对应 Design Review v0.2 Architecture Baseline（§19 Frozen Decisions）
- **Supersedes**: 无（首个 ADR）

---

## Context

早期目标是提供有证据依据的 GTM 情报。以下工程约束支撑该目标：复杂输出需要结构校验；来源访问需要可配置的独立连接器；检索、引用和展示需要可回放测试。当前默认研究定位见 ADR-0003。

约束：单人维护、个人长期使用、多市场（MVP English-first，日语为 P2 验证市场）、跨宿主（首要 Claude Code/Codex 类环境，WorkBuddy 为后续兼容目标）、防止幻觉引用、评估可回放。

## Decision

- **产品形态**：单核心 Skill `sourceglint` + 7 mode 调度（general/trend/competitor/market/voc/launch/channel），不拆 7 个独立 Skill。
- **架构主线**：`Host Adapter → Skill Contract → Research Engine`。Research Engine 为确定性 Python 流水线；**LLM 仅在语义环节介入且只输出符合 JSON Schema 的结构化数据**；最终报告由代码（Jinja2）渲染。
- **核心流水线**：User Query → Intent Parsing → Research Planning → Query Expansion → Source Retrieval → Normalization → Evidence Ledger → Deduplication → Semantic Clustering → Signal Scoring → Contradiction Check → Insight Synthesis → GTM Decision Layer → Deterministic Renderer。
- **证据模型**：Evidence Ledger（JSONL，每次 run 一目录）为唯一 SoT；每条 Insight → Signal Cluster → Evidence ID → Source URL 全程可回溯；LLM 从不接触 URL 字符串，渲染器按 evidence_id 注入真实 URL。
- **推理合同**：FACT / INFERENCE / RECOMMENDATION 严格三分，禁止混写；证据不足输出 `Insufficient evidence`。
- **信号评分**：加权几何平均 `SignalScore = DR^0.35 × EQ^0.20 × R^0.15 × MS^0.15 × N^0.15`，公式与权重放 `scoring.yaml` 可配；engagement 仅为 Market Signal 子因子。
- **LLM/Code 边界**：LLM = Query Expansion / Research Plan / Semantic Clustering / Decision Relevance / Contradiction Analysis / Insight / GTM Action。Code = 时间过滤 / URL / Evidence ID / Schema 校验 / Cache / Source Registry / 排序 / 评分 / 引用校验 / 渲染。
- **Source Registry**：`sources.yaml` 为唯一 SoT，声明 enabled/tier/cost/auth/priority/capabilities/rate_limit/markets/languages/cache_ttl。
- **MVP 源**：Host Web Search、Official Web Sources、Reddit（免费链路）、HN Algolia、GitHub API 共 5 类；YouTube/X 等 Phase 2+。
- **SKILL.md 预算**：目标 ≤8KB，soft limit 12KB；超限先迁移逻辑到 schema/config/script，不堆 Prompt。
- **语言/市场**：MVP English-first，但数据模型从第一版预留 `market/locale/language/query_language/source_language` 字段，不写死 English。
- **评估**：Golden Set + Automated Structural Eval + Human Judgment 三层；自动指标进 CI，人工指标按版本周期；eval 原始输入/输出全部落盘可回放。

## Why

- 通过 **Schema + Validator + 代码渲染** 校验结构，减少模型输出格式漂移。
- 强制 evidence_id 引用使幻觉引用在结构上不可行——模型从未接触 URL 字符串。
- 加权几何平均避免纯乘法的单因子趋零误杀，也避免算术平均的"单一因子补偿其他因子"。
- sources.yaml 统一维护来源配置，避免多个配置副本发生漂移。
- 单 Skill + mode 调度：7 mode 共享约 90% 流水线，拆分会把共享逻辑同步成本放大 7 倍。

## Trade-offs

| 权衡点 | 代价 | 接受理由 |
|--------|------|---------|
| 引擎逻辑进 Python 项目 | 需要维护真 Python 工程（依赖/测试/发布） | 支持独立安装、自动检查与版本维护 |
| Insight 层强制 evidence_id | LLM 需看到 Ledger 内容，长 Ledger 耗上下文 | 聚类后只给模型看簇摘要 + 代表引文缓解；条目 >200 代码预聚合 |
| 决策层 token 成本 | 每次运行高于纯检索 Skill | 这是差异化所在（GTM Decision Layer） |
| 加权几何平均需校准权重 | 权重调优负担 | 通过 eval 集回归确定默认权重，权重暴露在 yaml 可调 |
| 免费源打底 | 免费链路可能政策收紧（Reddit） | sources.yaml 插件化，失效即降级 |

## Alternatives Rejected

- **纯 Markdown skill（lightweight 路线）**：Evidence Ledger、去重、双窗口对比、评分公式无法在 Markdown 层可靠实现。
- **拆 7 个独立 Skill**：共享流水线同步成本放大 7 倍；若某 mode 后期工作流显著分化，届时以真实证据再拆。
- **提示词堆 LAW/badge/自检防漂移**：无法替代结构校验与实际行为测试。
- **纯乘法 Signal Score**：单因子趋零过度敏感。
- **加权算术平均**：允许单一因子极高补偿其他因子极低（爆款内容盖过决策相关性）。
- **模型自由生成 citation URL**：幻觉引用的主要来源，被明确禁止（PRD §17）。
- **单一商业 API 供应商**：成本与单点依赖风险；免费打底 + 付费插件化更安全。
- **浏览器 cookie 提取 / 登录态抓取**：ToS 灰色地带 + 高权限面，任何 Phase 不做。
- **20+ 源广度优先**：MVP 验证架构而非源数量。

## Consequences

正面：
- 抗漂移、防幻觉引用由结构保证，不随模型版本波动。
- 引擎 host-agnostic，未来新 harness 通过 adapter 接入。
- Ledger JSONL + eval 落盘 = 可回放、可审计、可回归。

负面：
- 引擎代码量大，MVP 交付前有一段纯工程期（无立即可用的输出）。
- 决策层质量依赖模型 GTM 素养，需 eval 集持续守门。
- LLM 层（聚类/洞察/决策）无法纯 unit test，需 Golden Cases 人工评审。

需跟进：
- MVP 首要验证项：「LLM 只输出 JSON」抗漂移假设（eval 场景 11/12 压测）。
- eval 人工评审每周约 1 小时预算（Golden Set + 人工 rubric）。
- 首个实现 Phase 从 Implementation Plan 的 Phase 1（Contracts）开始。
