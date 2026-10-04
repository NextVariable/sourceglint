# Contributing

Install Python 3.10+ and run `python -m pip install -e '.[dev]'`, then
`python -m pytest tests -q`. Offline tests require no source credentials.
`RUN_LIVE_TESTS=1 python -m pytest tests/live -q` issues real upstream requests;
credential skips are expected and must remain distinct from successful calls.

For a connector change, verify query relevance, publication dates, the time
window, error handling and normalization against a real source. For a research
change, preserve original excerpts, citation chains and counterexamples; passing
fixture tests alone is not evidence of useful real-world research.

Build a wheel with `python -m pip wheel --no-deps . --wheel-dir dist`, install it
into a separate environment, and run `scripts/check_installed_runtime.py` from
outside the checkout. Configuration and schemas remain canonical in `config/`
and `schemas/`; the build includes them automatically. Do not maintain copied
runtime resources by hand. Add no credentials, private source dumps or personal
run histories to a pull request.

Bug reports should include the query, version, host capabilities, as-of date,
source status, observed behavior and expected behavior, with secrets removed.


Current entry points and file ownership are in [architecture](docs/architecture.md).
Historical design reviews and non-pytest review scripts live in `docs/archive/`;
they are not release checks. Skill instructions should stay concise; detailed
bridge contracts belong in `references/`. Validate `SKILL.md` after changing its
frontmatter and verify that local documentation links resolve.

For a comparative claim, preserve the versions, query, time cutoff, capabilities,
credential profile, source/query budgets, failures and actual engine outcomes.
Compare synthesized findings as well as retrieval counts. Never count manual
bridge waiting as engine latency, or an environment certificate failure as a
competitor defect. Full source dumps stay in ignored `runs/`; publish short,
linked summaries and metadata rather than third-party transcripts.
