# Sourceglint

**Research the last 30 days across platforms.**

[简体中文](README.zh-CN.md) · [Examples](docs/examples/2026-10-04/README.md) · [Documentation](docs/README.md)

Information is scattered across communities, social platforms, official sites and research papers. Sourceglint is an open-source Skill for product managers, GTM teams and tech explorers: research a question to discover what happened recently, what people are discussing, and which tools, needs and feedback deserve a closer look.

It searches available sources, combines duplicate coverage, and returns a report with dates and original links, plus evidence you can pass to an AI for further analysis. Product and GTM recommendations are available when explicitly requested.

## What you can research

| Purpose | Example question |
| --- | --- |
| Product discovery | What are users praising or complaining about in AI meeting assistants? Which needs recur? |
| Market research | What changed in Japan's AI meeting assistant market, and what are Japanese users discussing? |
| Technology learning | Which AI video tools, technical developments and practical workflows appeared recently? |

After installation, ask your agent:

> Use Sourceglint to research AI video tools and user feedback from the last 30 days. Keep dates, original links and counterexamples.

## Install

Requires Python 3.10+ and an agent with web search, reasoning and an interactive terminal. For Codex, use an unused Skill directory:

```sh
git clone https://github.com/NextVariable/sourceglint-skill.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

Then ask your agent to use Sourceglint. Keep the complete repository; `SKILL.md` alone is insufficient. On Windows, use `.venv\Scripts\python.exe`. The doctor command checks local readiness; actual research determines source availability.

## Results and coverage

You receive a cited report and an evidence file containing links, dates and source excerpts. Reports distinguish maker claims, user experiences and interpretations, retain counterexamples, and disclose missing sources or thin evidence.

The default combines public GitHub, Reddit, Hacker News and YouTube retrieval with the agent's web search. Discussion, comment and caption enrichment is attempted where available. Platform credentials are optional enhancements; the agent's costs and usage limits still apply.

Research is bounded sampling. Coverage depends on access, rate limits, language and topic. A completed report does not establish complete platform coverage or prove market demand. Historical-window growth comparison and default scheduled monitoring are not supported.

## More

- [Recorded research examples](docs/examples/2026-10-04/README.md)
- [Source access](docs/source-access-matrix.md) and [fallbacks](docs/source-fallback-playbook.md)
- [Agent integration and evidence exports](references/host-protocol.md)
- [Validation records](docs/validation.md)
- [Repository guide](docs/repository-guide.md) and [contributing](CONTRIBUTING.md)

Licensed under [MIT](LICENSE).
