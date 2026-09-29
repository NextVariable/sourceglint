"""Phase 6C — deterministic brief policy constants (§10, §15, §34).

All caps / order mappings live here so the selection layer and tests
share one source of truth. No semantic reasoning lives in this module —
only code-owned layout constants.
"""
from __future__ import annotations

#: Per-section default output caps (Phase 6C §10). Content that exceeds a
#: cap is deterministically dropped (§34) — never "filled" to reach a
#: number. Callers may override per-section via BriefInput.caps.
DEFAULT_CAPS: dict[str, int] = {
    "facts": 5,
    "inferences": 5,
    "recommendations": 5,
    "watchouts": 3,
    "emerging": 3,
}

#: Max executive-summary extractive lines (top FACT + top INFERENCE +
#: top NOW action; missing layers simply degrade, §26).
EXECUTIVE_MAX_LINES: int = 3

#: Priority bucket → display order (Phase 6C §9, §15). The underlying
#: frozen values (now/next/watch) are never rewritten.
PRIORITY_ORDER: tuple[str, str, str] = ("now", "next", "watch")

#: Watchout kind → human label. The KIND itself is produced upstream by
#: Phase 6B conflict classification (never re-classified here, §13, §30).
WATCHOUT_KIND_LABELS: dict[str, str] = {
    "true_conflict": "Conflict",
    "segment_specific": "Segment nuance",
    "time_horizon_specific": "Timing nuance",
}

#: Overall-risk rank for deterministic tie-breaking (LOW first).
RISK_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

#: Fixed Markdown section headings (Phase 6C §25). Empty sections are
#: dropped by the renderer; these strings are presentation only.
SECTION_HEADINGS: dict[str, str] = {
    "executive": "Executive Summary",
    "facts": "What We Know",
    "inferences": "What It Likely Means",
    "actions": "Recommended Actions",
    "watchouts": "Watchouts",
    "emerging": "Emerging Signals",
    "coverage": "Coverage",
    "sources": "Sources",
}

#: Fixed no-evidence statement (Phase 6C §20). The brief must NEVER
#: fabricate "no major changes" — when 0 usable evidence exists this
#: exact, honest statement is emitted instead.
NO_EVIDENCE_STATEMENT = (
    "No usable evidence was retrieved for this research request."
)

#: Graceful-degradation notes (Phase 6C §19), appended under Coverage
#: only when the corresponding layer is genuinely absent.
NO_SIGNALS_NOTE = "No validated signals found."
NO_INSIGHTS_NOTE = "No validated higher-order insights were generated."
NO_RECOMMENDATIONS_NOTE = "No recommendation met the support threshold."
