# 架构与目录职责

Sourceglint 采用[智能体技能规范](https://agentskills.io/specification)中的渐进加载方式：`SKILL.md` 定义入口，`references/` 提供按需读取的协议，`scripts/` 提供可执行工具。Python 运行时独立放在 `src/`，避免把完整工程实现塞进技能说明。

用户请求经过解析、检索、时间过滤和去重，进入证据账本；智能体负责聚类和推理，运行时检查引用及结论依据，最后生成报告。命令行和技能都调用同一个公开接口。

| 位置 | 职责 |
| --- | --- |
| `SKILL.md`、`agents/`、`references/` | 技能入口、界面信息与交互协议 |
| `src/sourceglint/application/` | 请求执行与运行时组装 |
| `src/sourceglint/interface/` | 输入解析与结果契约 |
| `src/sourceglint/connectors/` | 来源访问、网络传输与结果映射 |
| `src/sourceglint/pipeline/` | 查询计划、时间过滤、缓存与去重 |
| `src/sourceglint/intelligence/`、`insights/` | 聚类、来源冲突与结论核验 |
| `src/sourceglint/recommendations/` | 明确启用后的决策建议 |
| `src/sourceglint/brief/` | 报告筛选与展示 |
| `config/`、`schemas/` | 唯一维护的配置与数据结构定义 |
| `scripts/`、`tests/`、`evals/` | 验证工具、自动测试与公开测试题 |
| `docs/adr/`、`docs/examples/` | 设计决策与实际输出样例 |

`api.py` 保留稳定的接口导出。早期确定性对象契约所用的 `rendering.py`、`scoring.py`、`validation.py`、`ids.py`、`ledger.py` 和 `citations.py` 仍被使用或测试；当前报告由 `brief/` 展示。两套契约并存属于维护成本，不能把这些文件误判为废弃后直接删除。

配置和结构定义只修改根目录的维护版本；打包过程复制到安装资源中。`build/` 和生成的 `_data` 不是第二份源码。`runs/`、缓存目录及构建产物均不提交。

来源正文有明确读取预算：模型每条最多读取 6,000 字符，批次总预算为 48,000 字符；证据账本最多保留 12,000 字符正文，省略部分会标记。原始导出保存实际取得的材料，不等于已验证结论。来源快照、配置检查、真实检索和最终报告质量分别验收。

## English

### Runtime and repository map

The maintained entry points are `sourceglint` / `python -m sourceglint` and
`from sourceglint.api import run_sourceglint`. The CLI and Skill both call that
public API. A host supplies retrieval and structured reasoning; the Python
engine validates evidence, applies the publication window, combines duplicates,
resolves citation chains and renders the result.

```text
Query → request parser → retrieval → evidence ledger
      → host clustering and synthesis → validation → dated report
```

| Path | Purpose |
| --- | --- |
| `SKILL.md`, `references/`, `agents/` | Host instructions, protocol and UI metadata |
| `src/sourceglint/application/` | Public run composition and default runtime wiring |
| `src/sourceglint/interface/` | Request parsing and result contract |
| `src/sourceglint/connectors/` | Direct-source transport and mapping |
| `src/sourceglint/pipeline/` | Query planning, retrieval, publication filtering and deduplication |
| `src/sourceglint/intelligence/`, `insights/`, `recommendations/` | Host reasoning, grounding checks and opt-in decisions |
| `src/sourceglint/brief/` | Current report selection and rendering |
| `config/`, `schemas/` | Canonical runtime configuration and JSON contracts |
| `scripts/` | Maintained installation checks and evaluation recorder |
| `tests/` | Current contract, unit, integration and opt-in live tests |
| `docs/adr/`, `docs/examples/` | Accepted design decisions and curated acceptance evidence |
| `runs/`, `.cache/`, `build/` | Ignored local research, caches and generated build output |

`rendering.py`, `scoring.py`, `validation.py`, `ids.py`, `ledger.py` and
`citations.py` support the original deterministic object contract. They are
still used or tested; they are not abandoned files. The current application
uses `brief/` for its richer report. `api.py` intentionally re-exports the
application API as the stable import surface.

Runtime resources stay in one maintained location. `setup.py` copies canonical
configuration, schemas and the dated source snapshot into the built package;
`resources.data_path` resolves either installed data or checkout data. Do not
edit `build/` or generated `_data` directories.

`--ledger` writes normalized retained evidence (280-character quotes plus up to 12,000 characters of source body) and a
raw companion containing retrieved bodies and provider metadata before filtering.
The raw archive is not a validated corpus. Keep private run data out of public Git.

The live source snapshot is historical evidence, not a probe. `sourceglint
doctor` checks configuration without making network requests. Research reports
describe the actual run. Both are needed to distinguish an implemented route,
local readiness and successful delivery.

Deep retrieval helpers live in `connectors/_deep.py` and `connectors/_captions.py`.
Semantic model inputs retain up to 6,000 characters of body per item; snippets
remain small quotations. Raw exports preserve the complete returned body.

The research topic is passed explicitly to semantic clustering and relevance
assessment, including general-mode requests. Batch body excerpts have a 48,000
character budget; oversized excerpts include an explicit omitted-middle marker.
Later claim analysis reads up to 6,000 characters per supporting body. This is
bounded analysis, not a claim to have read every full source. The ledger retains
up to 12,000 characters per body and raw exports retain the returned full text.
