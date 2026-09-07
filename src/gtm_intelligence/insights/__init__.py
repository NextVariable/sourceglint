"""Phase 6A — Insight Synthesis Layer (Signal → FACT → INFERENCE → Insight).

STOP BOUNDARY (PRD §47, §48): this package produces validated, traceable
Insights (FACT + INFERENCE only). It does NOT produce RECOMMENDATIONs,
GTM action strategies, final briefs, or Skill Interface packaging. Those
belong to Phase 6B+.

Pipeline (PRD §8):

    Signal Set
      → prepare_signals()           preparation.py   (code)
      → synthesize_facts()          facts.py         (model drafts, code validates)
      → validate_facts()            facts.py         (code gate)
      → synthesize_inferences()     inferences.py    (model drafts, code validates)
      → validate_inferences()       inferences.py    (code gate)
      → derive_gtm_implications()   gtm_implications.py (model drafts, code checks)
      → deduplicate_insights()      dedup.py         (code + model semantic judgment)
      → validate_insight_schema()   validation.py    (code gate)
      → InsightPipelineResult

LLM/CODE boundary (PRD §6): code owns signal selection, ordering, input
preparation, Insight IDs, schema validation, referential integrity, FACT
grounding validation, INFERENCE support validation, confidence range
validation, recommendation leakage detection, duplicate detection,
deterministic sorting, semantic cache, diagnostics, output serialization.
The model owns FACT abstraction, cross-signal synthesis, inference
generation, uncertainty wording, semantic GTM implication identification.
The model NEVER invents Evidence, NEVER mints Signal/Insight IDs, NEVER
changes Signal score, NEVER generates Recommendation, NEVER writes the
final brief.
"""
