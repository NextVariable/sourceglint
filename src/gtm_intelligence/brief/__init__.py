"""Phase 6C — Final Intelligence Brief & Deterministic Renderer.

Pipeline (end of the evidence chain):

    Research Plan
    → Evidence (Ledger)
    → Signals
    → FACT / INFERENCE Insights
    → Recommendations
    → Final Intelligence Brief

Core principle: the renderer does not think (Phase 6C PRD §2). Every
section of the brief is composed by code from ALREADY VALIDATED
structured objects — validated signals, FACT/INFERENCE insights,
RECOMMENDATION dicts, and their diagnostics. The brief layer:

  * selects   (deterministic ranking + per-section caps, §9–§10)
  * orders    (stable section order, §25; NOW → NEXT → WATCH, §15)
  * formats   (fixed Markdown layout, reuse of Phase 2 rendering
               helpers — never a second renderer contract, §41)
  * resolves  (Insight → Signal → Evidence → URL citations from the
               ledger, §16)
  * suppresses empty sections (§25)
  * degrades  gracefully (no signals / no insights / no recommendations
               / no evidence — §19–§20)

The brief layer does NOT: invent insights, infer new causality, create
recommendations, reinterpret evidence, change confidence or priority,
override contradictions, summarize raw web pages, or call any model
(Phase 6C §2, §23, Gate K).

STOP BOUNDARY (§48): output is the final Markdown brief only. No Skill
Interface, no SKILL.md packaging, no host adapters, no WorkBuddy /
Claude Code / Codex integration, no dashboard, no external writes.
"""
from __future__ import annotations

from .dtos import (
    BriefContext,
    BriefDiagnostics,
    BriefInput,
    RenderedBrief,
    SelectedBrief,
    SelectedEmergingSignal,
    SelectedFact,
    SelectedInference,
    SelectedRecommendation,
    SelectedWatchout,
)

__all__ = [
    "BriefContext",
    "BriefDiagnostics",
    "BriefInput",
    "RenderedBrief",
    "SelectedBrief",
    "SelectedEmergingSignal",
    "SelectedFact",
    "SelectedInference",
    "SelectedRecommendation",
    "SelectedWatchout",
]
