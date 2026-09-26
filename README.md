# gtm-intelligence

Given a topic, this Skill researches what appeared and what people discussed recently across available sources. It combines duplicate coverage, surfaces tools, workflows, user needs and feedback, and keeps dates and original links. Product managers, creators, GTM teams, and technology workers can use the research for different purposes. Product/GTM recommendations are optional. See [the positioning decision](docs/adr/0002-discovery-first-positioning.md) and [the default-output decision](docs/adr/0003-research-default.md).

## Current state

The deterministic engine and host-neutral Python API are available. A host must inject a model implementing `IntelligenceModel.complete_structured` for semantic stages. The package does not ship a model provider or API credentials. The CLI accepts a trusted local model factory through `--model`; without one it exits with an actionable error.

The default path retrieves and evaluates evidence, skips GTM implications and recommendations, and renders a Recent Intelligence Brief. If sources are retrieved but no signal is validated, it still shows a limited dated evidence list, explicitly not a proven pattern. `--decision-support` opts into the existing GTM decision brief when the user asks for implications or actions. This routing has offline integration tests; realistic discovery quality and source coverage remain unverified.


The public runtime does not yet retrieve a prior comparison window. A baseline request now fails explicitly instead of returning a current-only brief as if it were a trend comparison. Recent discussion and engagement can be reported, but claims that a topic is rising require separate prior-window evidence.

## Local use

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m gtm_intelligence --help
```

The public API is `gtm_intelligence.application.api.run_gtm_intelligence`. It requires `query`, an injected `model`, and an explicit `as_of` timestamp; callers can inject a source registry and adapter factory. The CLI supplies the current UTC timestamp unless `--as-of` is provided. For a reproducible run, set `--as-of` explicitly.

```sh
.venv/bin/python -m gtm_intelligence \
  'Recent changes in AI meeting assistants' \
  --model path/to/trusted_model_factory.py \
  --as-of 2026-09-26T00:00:00Z
```

The model file must define `build_model()` and return an `IntelligenceModel` implementation. Only run model files you trust; they are executable Python. Add `--decision-support` only for an explicit decision question. For a host integration, call the Python API and inject the host's model and retrieval capabilities directly.

## Verification

`scripts/verify_full_suite.sh` runs the offline regression suite. Live connector tests are opt-in with `RUN_LIVE_TESTS=1`; they require network access and, for some sources, credentials. The public API integration tests use fixed evidence and a scripted model, so passing them verifies wiring and traceability, not the quality of a real model's GTM judgments. See `docs/phase7-evaluation.md` for the remaining product evaluation.

`SKILL.md` provides a host-driven entry point using the JSON-lines bridge in `host_stdio.py`. Its source and model requests are handled by the running agent with its own tools and reasoning. Codex discovered the installed Skill on 2026-09-26. Manual official-page and voice-of-customer bridge runs reached cited briefs, but the broader real-world GTM quality review remains open; pipeline `SUCCESS` does not establish research quality or market representativeness. See `docs/phase7-evaluation.md` for the run findings and remaining acceptance work.
