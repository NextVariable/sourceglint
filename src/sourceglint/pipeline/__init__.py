"""sourceglint research pipeline (Phase 3).

This subpackage is the deterministic Research Pipeline orchestration layer.
It MUST NOT call LLMs and MUST NOT touch the Evidence schema or Scoring
internals — it only emits normalized Evidence objects to the ledger.

Modules:
  * query_expansion    — deterministic query expansion (Phase 3 §4)
  * retrieval_plan     — build retrieval plans from a research plan (Phase 3 §6)
  * adapters           — SourceAdapter Protocol + RawSourceResult DTO (Phase 3 §7/§8)
  * source_registry    — runtime loader/validator for sources.yaml (Phase 3 §22)
  * normalization      — RawSourceResult → Evidence (Phase 3 §12)
  * time_filter        — research-window filtering (Phase 3 §13/§14)
  * deduplication      — multi-layer dedup (Phase 3 §15/§16)
  * cache              — local retrieval cache (Phase 3 §17)
  * degradation        — source status taxonomy (Phase 3 §18/§20)
  * coverage           — CoverageReport DTO (Phase 3 §19)
  * orchestrator       — ResearchPipeline orchestrator (Phase 3 §23)
"""