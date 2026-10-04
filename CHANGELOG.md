# Changelog

Python 3.10 compatibility is exercised by the public CI matrix; recommendation ID construction avoids syntax that requires Python 3.12.

## 0.2.2.dev3 — 2026-10-05

- Keep failed contradiction assessments explicitly unassessed; exclude those
  signals from fact generation and preserve empty support partitions.
- Enrich duplicate evidence with compatible source bodies while preserving
  identity, publication dates, quotes and retrieval provenance; register aliases.
- Apply copied-text origin suppression consistently to signal and insight support.
- Select bounded verbatim head/topic/tail excerpts with Unicode-safe offsets;
  fingerprint model inputs so body enrichment invalidates cached analyses.
- Try alternative public caption tracks within a four-attempt budget, retaining
  failure diagnostics and avoiding malformed tracks.

## 0.2.2.dev2 — 2026-10-05

- Use relevance-ranked Reddit RSS discovery, resolve public community names,
  prioritize exact observed communities, reject unrelated prefix collisions
  using public descriptions and deduplicate names without case sensitivity.
- Retrieve Reddit archive candidates in four time strata and retain available
  strata and distinct publication days during selection; report missing coverage
  instead of implying a full month.
- Fall back from archive HTTP 422 keyword-search failures to bounded community
  samples, preserve incomplete-source warnings and bound enrichment retries.
- Check visible HN subject text with limited overfetch; preserve actual story
  text when the provider supplies it, alongside comment evidence.
- Add selectable topics/routes and parent-date metrics to the live comparison runner.

## Unreleased — 2026-10-04

- Pass the original research topic into semantic analysis in general mode;
  bound batch body inputs and mark omitted passages explicitly.
- Read bounded source bodies in semantic analysis rather than only the first
  280 characters; preserve the short quote contract and unabridged raw export.
- Add GitHub issues/PRs, independently dated comments and recent replies in
  older threads; preserve comment anchors and classify community claims as T2.
- Add public Reddit archive discovery and dated comment evidence, with explicit
  archive provenance and filtering of unrelated feed entries and moderator bots.
- Read recent YouTube timed captions without downloading media or cookies.
- Make the maintained Skill workflow use bounded native retrieval plus host
  supplements instead of leaving deep connectors outside the first-run path.

- Clarify the research-first installation and workflow; add host metadata and
  move protocol details into progressively loaded references.
- Archive historical designs and obsolete manual review gates without deleting
  their content; document current runtime ownership.
- Add installed `sourceglint doctor`, separating offline readiness and dated
  live checks, and eliminate the duplicate diagnostics implementation.
- Query recent HN stories and comments with upstream date bounds, preserve
  original comment URLs and raw markup, and render readable text.
- Date-bound GitHub repository searches; classify them as pages and retain
  forks as provider metadata instead of falsely reporting comments.
- Prioritize the literal topic before broad query expansions.
- Persist normalized evidence and a separate unvalidated raw-source archive
  with `--ledger`, reject reused nonempty run files, and show
  cited excerpts before unselected observations.

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
