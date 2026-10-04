# Sourceglint

**Find what appeared—and what people actually said—in the last 30 days.**

Sourceglint is an agent Skill for recent research: new tools, concrete workflows,
user needs, complaints and recurring discussions. It keeps publication dates,
original links, source observations and traceable findings, so the research can
be read directly or passed to another AI. Product and GTM advice are opt-in.

[MIT](LICENSE) · [Getting started](#get-started) · [Live comparison](docs/benchmarks/2026-10-04.md) · [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md)

## What you get

This checkout is the **0.2.2.dev0** development revision; the published 0.2.1
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
Ask the agent to use Sourceglint. Its first-run profile uses the host's existing
public search and reasoning, so platform-specific keys are optional. Host costs
and usage limits apply.

The agent operates this command and answers its requests:

```sh
.venv/bin/python -m sourceglint 'Claude Code workflows' \
  --model sourceglint.host_stdio:build_model \
  --host-sources-stdio --registry config/sources-host.yaml \
  --ledger runs/my-research/evidence.jsonl --json
```

The normalized ledger keeps excerpts up to 280 characters. Its companion
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
| Direct GitHub | Repositories created in the research window | Repository metadata, not releases, issues or adoption proof |
| Direct Reddit | Public RSS, optional OAuth | RSS may be blocked; limited text, no reliable engagement or full comments |
| Other direct connectors | Video metadata, developer and academic sources | Availability, local tools and credentials vary by provider |

Use `config/sources.yaml` for direct connectors and host fallbacks.
`sourceglint doctor --json` reports implementation, missing credential **names**,
local tools and historical test dates. It makes no network requests and does
not certify live availability. The broad catalog is a routing map, not a list
of functioning integrations. See [access matrix](docs/source-access-matrix.md),
[dated live snapshot](docs/source-live-status.json) and [fallback playbook](docs/source-fallback-playbook.md).

There is no public prior-window comparison yet: `--baseline` fails explicitly.
Recent attention is not proof of a growing trend. Scheduled monitoring is outside
the default research workflow. Browser-cookie imports and paid providers require
user authorization. `SUCCESS`, `PARTIAL` and research quality are distinct.
The [comparison](docs/benchmarks/2026-10-04.md) records strengths and remaining gaps

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
