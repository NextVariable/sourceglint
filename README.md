# Sourceglint

**Find what appeared—and what people actually said—in the last 30 days.**

Sourceglint is an agent Skill for recent research: new tools, concrete workflows,
user needs, complaints and recurring discussions. It keeps publication dates,
original links, source observations and traceable findings, so the research can
be read directly or passed to another AI. Product and GTM advice are opt-in.

[MIT](LICENSE) · [Getting started](#get-started) · [Evaluation](docs/benchmarks/2026-10-05-competitive-retest.md) · [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md)

## What you get

This checkout is the **0.2.2.dev2** development revision; the published 0.2.1
release remains available separately.

A recent research brief separates supported observations, cautious inferences,
weak signals and coverage limits. A JSONL evidence ledger preserves dated source
records and evidence IDs for reuse. Missing sources and counterexamples stay
visible; a completed pipeline never means a representative market sample.

For example, ask your agent:

> Use Sourceglint to research Claude Code workflows from the last 30 days.
> Find concrete examples, new tools, user complaints and counterexamples.
> Keep the original links and dates. Give me the evidence file too.

Or in Chinese:

> 用 Sourceglint 查最近 30 天 AI 编程工作流里出现了什么新工具、实际做法和用户反馈，保留原文链接、日期和反例。先给研究结果。

See [dated examples](docs/examples/2026-10-04/README.md) and the
[dated evaluation record](docs/benchmarks/2026-10-05-competitive-retest.md). These are bounded
runs, not a claim that every source or topic works equally well.

## Get started

You need **Python 3.10+** and an agent with search/fetch, reasoning and interactive
terminal tools. Keep the complete repository; `SKILL.md` alone is not enough.
There is no bundled model subscription or maintainer account.

For Codex, install into its Skill folder, using an unused destination:

```sh
git clone https://github.com/NextVariable/sourceglint.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

On Windows use `.venv\Scripts\python.exe`. Other hosts can place the complete
folder in their supported Skill directory; compatibility requires the same
interactive bridge capabilities and has not been certified for every host.
Ask the agent to use Sourceglint. Its first-run profile combines bounded native
retrieval with the host's public search and reasoning, so platform keys are optional. Host costs
and usage limits apply.

The agent operates this command and answers its requests:

```sh
.venv/bin/python -m sourceglint 'Claude Code workflows' \
  --model sourceglint.host_stdio:build_model \
  --host-sources-stdio --registry config/sources-hybrid.yaml \
  --ledger runs/my-research/evidence.jsonl --json
```

The normalized ledger keeps excerpts up to 280 characters and, when retrieved,
a separate source body up to 12,000 characters. Its companion
`evidence.raw.jsonl` keeps the retrieved body and provider metadata before
filtering; raw records may be outdated or invalid and are not findings.
Use a fresh ledger path for every run. Add `--as-of 2026-10-04T00:00:00Z` to pin
the window, or `--decision-support` when you explicitly want product/GTM advice.
This is an agent-operated bridge, not an unattended shell search client.
The exact request/response contract is in [host protocol](references/host-protocol.md).

## Access and limitations

| Route | What it provides | Boundary |
| --- | --- | --- |
| Host search, default | Dated public pages across relevant routed platforms | Index-dependent; no full-platform or private-access guarantee |
| Direct HN | Recent stories and matching comments, original item URLs | Search samples, not complete discussion threads |
| Direct GitHub | Repositories, issues/PRs and independently dated comments, including recent replies to old issues | Bounded samples; community claims are not verified defects or adoption proof |
| Direct Reddit | RSS/OAuth discovery, public archive bodies and dated comments | Archive coverage and freshness vary; sampled communities and threads |
| Direct YouTube | Recent video metadata and public timed captions through `yt-dlp` | Captions can fail or be unavailable; no media download |
| Other direct connectors | Developer and academic sources | Availability and credentials vary by provider |

Use `config/sources-hybrid.yaml` for bounded native retrieval plus host supplements.
Use `config/sources-host.yaml` when only host search is available, or
`config/sources.yaml` for the broader direct registry.
`sourceglint doctor --json` reports implementation, missing credential **names**,
local tools and historical test dates. It makes no network requests and does
not certify live availability. The broad catalog is a routing map, not a list
of functioning integrations. See [access matrix](docs/source-access-matrix.md),
[dated live snapshot](docs/source-live-status.json) and [fallback playbook](docs/source-fallback-playbook.md).

There is no public prior-window comparison yet: `--baseline` fails explicitly.
Recent attention is not proof of a growing trend. Scheduled monitoring is outside
the default research workflow. Browser-cookie imports and paid providers require
user authorization. `SUCCESS`, `PARTIAL` and research quality are distinct.
The latest [competitive retest](docs/benchmarks/2026-10-05-competitive-retest.md)
in month-wide sampling, community discovery and relevance; no overall superiority
is established. Its [metrics](docs/benchmarks/2026-10-05-competitive-retest.metrics.json)
keep different output stages separate.

The earlier [comparison](docs/benchmarks/2026-10-04.md) records strengths and remaining gaps
records the implemented depth improvements and the limits of the new comparison.

The current [Skill audit](docs/reviews/2026-10-05-skill-audit.md) separates
format, installation and live-retrieval checks from unresolved quality gaps.

The [sampling repair](docs/reviews/2026-10-05-sampling-repair.md) records
time-stratified Reddit discovery, visible-topic filtering and remaining provider failures.

## Develop and verify

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

Offline tests verify contracts and regression behavior. Live tests require
`RUN_LIVE_TESTS=1`; a missing credential is a skip, not a live pass.
`scripts/check_installed_runtime.py` checks a separately installed wheel from
outside the checkout. `scripts/verify_first_install.sh` checks a clean export
of the **committed** tree. None of these replace an actual research run.

The wheel includes runtime configuration, schemas, prompts and diagnostic data.
It installs the engine, not the host Skill registration. GitHub is the current
distribution channel; a PyPI release is not implied.

The canonical API is `sourceglint.application.api.run_sourceglint(query, model=…,
as_of=…)`; inject host reasoning, adapters and an optional `EvidenceLedger`.
See [architecture](docs/architecture.md) for maintained components and
[historical archive](docs/archive/README.md) for earlier design material.
