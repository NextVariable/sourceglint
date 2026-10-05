# Sourceglint

**Recent research you can trace back to the source.**

Find new tools, practical workflows and user feedback from the last 30 days.
Keep original dates, links and a reusable evidence file. Product and GTM advice
is available when you ask for it.

[中文](README.zh-CN.md) · [Examples](docs/examples/2026-10-04/README.md) · [Source access](docs/source-access-matrix.md) · [Evaluation](docs/validation.md) · [Contributing](CONTRIBUTING.md)

[![Tests and installed package](https://github.com/NextVariable/sourceglint/actions/workflows/tests.yml/badge.svg)](https://github.com/NextVariable/sourceglint/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Start with a question

> Use Sourceglint to research Claude Code workflows from the last 30 days.
> Find concrete examples, new tools, user complaints and counterexamples.
> Keep the original links and dates. Give me the evidence file too.

Your agent produces a brief that separates source observations from inferences,
with visible coverage gaps. The JSONL ledger preserves evidence IDs, original
URLs, publication dates and bounded excerpts for follow-up research.

A [recorded example](docs/examples/2026-10-04/discovery.md) distinguishes maker
announcements from comments in one conversation; it explicitly says these are
not independent adoption statistics. That distinction is part of the output,
including when evidence is thin.

## Install

Requires **Python 3.10+** and an agent with web search/fetch, reasoning and an
interactive terminal. For Codex, clone into an unused Skill directory:

```sh
git clone https://github.com/NextVariable/sourceglint.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

Ask your agent to use Sourceglint. Keep the complete repository: `SKILL.md` alone
is insufficient. On Windows use `.venv\Scripts\python.exe`. Other hosts need the
same bridge capabilities; compatibility has not been certified for every host.
`doctor` checks local readiness without network access. Your host's costs and
usage limits apply; there is no bundled model account.

## How it works

```text
Your question → native retrieval + host search → dated, deduplicated evidence
             → host reasoning → citation checks → brief + evidence ledger
```

The default hybrid profile combines bounded GitHub, Reddit, Hacker News and
YouTube retrieval with your agent's public search. Platform keys are optional.
The agent runs the command below and answers its search and reasoning requests:

```sh
.venv/bin/python -m sourceglint 'Claude Code workflows' \
  --model sourceglint.host_stdio:build_model \
  --host-sources-stdio --registry config/sources-hybrid.yaml \
  --ledger runs/my-research/evidence.jsonl --json
```

Use a fresh ledger path. Add `--as-of 2026-10-05T00:00:00Z` for a fixed cutoff,
or `--decision-support` for explicit product/GTM questions. This is an
agent-operated bridge; it waits for the host's responses. See the
[host protocol](references/host-protocol.md) for integration details.

## What to expect

GitHub can supply repositories, issues and dated comments; HN supplies stories
and comments; Reddit can supplement public discovery with archive bodies and
comments; YouTube attempts public captions without downloading media. These
are bounded samples. Access, dates, relevance and depth vary by source and run.
See [access and credentials](docs/source-access-matrix.md) and the
[fallback guide](docs/source-fallback-playbook.md).

`SUCCESS` means the pipeline produced a brief. It does not certify research
quality, complete coverage or representativeness. Unknown dates are excluded;
missing sources and unanswered questions stay visible. There is no prior-window
comparison yet (`--baseline` fails explicitly), so recent discussion does not
establish growth. Scheduled monitoring is outside the default workflow.

The ledger retains short quotes and, when retrieved, up to 12,000 characters of
source body with omission markers. Its `.raw.jsonl` companion retains retrieved
text before filtering; raw records are not validated findings. Browser-cookie
imports and paid providers require authorization.

## Project status

**0.2.2.dev4 — development revision.** The published 0.2.1 release remains a
separate snapshot. Current comparisons have not established overall superiority
are in [validation records](docs/validation.md).

The repository separates [Skill instructions](SKILL.md), the Python engine,
runtime contracts and evaluation evidence. [Architecture](docs/architecture.md)
explains ownership; [documentation](docs/README.md) routes to current references
and preserved history. GitHub is the distribution channel; a wheel installs the
engine, not the host Skill registration, and a PyPI release is not implied.

To develop, install `.[dev]` and run `python -m pytest tests -q`. The
[contributor guide](CONTRIBUTING.md) covers lint, packaging and real-source checks.
Licensed under [MIT](LICENSE).
