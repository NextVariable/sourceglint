# Validation and evaluation records

Latest: [2026-10-05 release audit](reviews/2026-10-05-release-audit.md) —
12-topic live matrix, transport and grounding repairs, and explicit limitations.


A passing offline suite, a working installation, a successful live request and a
useful research report are separate acceptance levels. No current result proves
complete recall or overall superiority over other research tools.

The reproducible topic manifest is [retrieval-matrix.json](../evals/retrieval-matrix.json).

```sh
.venv/bin/python scripts/run_competitive_matrix.py \
  --as-of 2026-10-05 --directory runs/my-comparison \
```

Use an empty destination. The runner records the source revision and file hashes,
query language, cutoff, credentials-present boolean, failures and completed cells.
It does not save tokens. It uses public routes plus existing GitHub authorization;
paid search, browser cookies and platform credentials are excluded. Both engines
receive the same query and source selection. Their internal budgets and output
stages differ. Independent comments are not comparable to ranked parent items.
Concurrent requests can affect rate limits, so this is not a latency benchmark.

The twelve cases cover developer workflows, complaints, security, non-developer
products, Chinese, Japanese and an invented-name negative control. Three cases
also exercise YouTube. Inspect relevance and citation support in the artifacts;
nonempty output alone does not pass a quality gate. Full-Skill synthesis requires
a separate host-operated run and is not supplied by this native comparison.

`compare_research_reports.py --engine ddgs` provides an optional search-snippet
separately configured report comparison that can incur provider costs; it is not
run by the public matrix. See the recorded conditions before comparing outputs.

## Dated records

records HN story/comment balance, repository-alias regressions, native-source
coverage limits, final hybrid acceptance and isolated installation checks.
It separates retrieval observations from ranked items and does not certify
overall superiority or complete recall.

The earlier [competitive retest](benchmarks/2026-10-05-competitive-retest.md)
in month-wide sampling, community discovery and relevance; no overall superiority
is established. Its [metrics](benchmarks/2026-10-05-competitive-retest.metrics.json)
keep different output stages separate.

The earlier [comparison](benchmarks/2026-10-04.md) records strengths and remaining gaps
records the implemented depth improvements and the limits of the new comparison.

The current [Skill audit](reviews/2026-10-05-skill-audit.md) separates
format, installation and live-retrieval checks from unresolved quality gaps.

The [sampling repair](reviews/2026-10-05-sampling-repair.md) records
time-stratified Reddit discovery, visible-topic filtering and remaining provider failures.

The [research-quality repair](reviews/2026-10-05-quality-repair.md) records
assessment failure handling, body enrichment, copied-report suppression and
bounded topic/caption reading.

The [bulk audit](reviews/2026-10-05-bulk-audit.md) records seeded stress
checks, a five-topic live matrix, real host scenarios and the remaining relevance
and recall limits; test volume does not certify research completeness.

## Local verification

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src scripts
.venv/bin/python scripts/check_repository.py
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

Offline tests verify contracts and regressions. Live tests require
`RUN_LIVE_TESTS=1`; missing credentials are skips, not passes.
`scripts/check_installed_runtime.py` checks a wheel installed outside the checkout.
`scripts/verify_first_install.sh` checks a clean export of the committed tree.
Neither replaces an actual research run. Historical records retain their original
versions and limits; do not add their result counts into a current pass total.
