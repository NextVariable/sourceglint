# Runtime and repository map

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
| `docs/archive/` | Preserved early designs and obsolete phase reviews |
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
