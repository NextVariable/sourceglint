# Changelog

Python 3.10 compatibility is exercised by the public CI matrix; recommendation ID construction avoids syntax that requires Python 3.12.

## 0.2.1 — 2026-10-04

- Retain direct-source public-search fallbacks in the host-only first-run path;
  a catalog entry marked ready no longer means it was queried in this run.
- Report original platforms, publication dates, actual host searches, missing
  aspects and small-sample limitations separately from pipeline completion.
- Preserve verbatim source excerpts in discovery reports, including observations
  that were not selected as headline facts.
- Include runtime configuration, schemas and model prompts in wheel/sdist
  distributions and resolve them from the installed package.
- Add MIT licensing, contribution guidance, installed-package checks and CI.

This is an early research Skill. Source breadth is partial, report completeness
is not certified automatically, and prior-window trend retrieval is unavailable.
