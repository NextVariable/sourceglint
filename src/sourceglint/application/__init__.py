"""Phase 7 §17–§19, §60 — Application orchestrator.

The orchestrator is the full-stack composition of the existing engine:

    ResearchPlan
    -> Research Pipeline   (Phase 3, evidence + coverage)
    -> Signal Pipeline     (Phase 5)
    -> Insight Pipeline    (Phase 6A, FACT / INFERENCE)
    -> Recommendation      (Phase 6B)
    -> Brief Pipeline      (Phase 6C, deterministic markdown)

Boundaries (§18): the orchestrator owns stage invocation, validated
hand-off between stages, per-stage status, warnings, graceful
degradation and final result packaging. It does NOT own scoring,
clustering, recommendation generation or rendering semantics — every
stage is an existing module call.

Failure semantics (§19): a downstream stage's failure never discards
upstream results. Research-all-sources-failed is a structured FAILED
result; anything downstream degrades (signals kept when insights fail,
insights kept when recommendations fail, etc.).
"""
