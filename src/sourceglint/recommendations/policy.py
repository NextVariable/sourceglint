"""Phase 6B §46 — centralized policy constants for the Recommendation layer.

Every weight, threshold, intensity cap and pattern list lives here so
the layer has no scattered magic numbers. Changing any of these is a
policy change: it must be deliberate and locked by tests (§45 order,
§46). The Phase 2 Signal Score is NOT modified — recommendation
priority is an independent layer (§21).
"""
from __future__ import annotations

from typing import Final

#: Action classes (§17) — control action intensity. The model chooses
#: one; code caps it against weak-signal / contradiction policy (§18,
#: §19) using CLASS_INTENSITY.
ACTION_CLASSES: Final[tuple[str, ...]] = (
    "observe",
    "validate",
    "experiment",
    "update",
    "investigate",
    "change",
)

#: Class -> intensity rank (higher = stronger commitment).
CLASS_INTENSITY: Final[dict[str, int]] = {
    "observe": 0,
    "investigate": 1,
    "validate": 2,
    "experiment": 3,
    "update": 4,
    "change": 5,
}

#: Weak-signal ceiling (§18): weak signals may at most be validated /
#: experimented on; irreversible update / change is forbidden.
WEAK_SIGNAL_MAX_INTENSITY: Final[int] = CLASS_INTENSITY["experiment"]

#: Contradiction ceiling (§19): mixed support must not yield one-sided
#: deterministic update / change; prefer validate / segment / experiment.
CONTRADICTION_MAX_INTENSITY: Final[int] = CLASS_INTENSITY["experiment"]

#: Class -> action distance (§15).
#:   0 = direct operational update (battlecard, reference, monitoring)
#:   1 = low-cost validation experiment
#:   2 = strategic intervention
CLASS_ACTION_DISTANCE: Final[dict[str, int]] = {
    "observe": 0,
    "investigate": 1,
    "validate": 1,
    "experiment": 1,
    "update": 0,
    "change": 2,
}

#: Distance discount step for the confidence ceiling (§14, §15):
#: ceiling = min(supporting insight confidence) * (1 - 0.15*distance).
DISTANCE_DISCOUNT_STEP: Final[float] = 0.15

#: Reversibility enum (§16) and its 0..1 numeric mapping used by the
#: priority formula (§21).
REVERSIBILITY_VALUES: Final[tuple[str, ...]] = ("high", "medium", "low")
REVERSIBILITY_SCORE: Final[dict[str, float]] = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.0,
}

#: Priority formula weights (§21 — suggested formula; centralized here).
#: priority = 0.30*support_confidence + 0.25*expected_impact
#:          + 0.20*urgency + 0.15*reversibility + 0.10*feasibility
PRIORITY_W_SUPPORT: Final[float] = 0.30
PRIORITY_W_IMPACT: Final[float] = 0.25
PRIORITY_W_URGENCY: Final[float] = 0.20
PRIORITY_W_REVERSIBILITY: Final[float] = 0.15
PRIORITY_W_FEASIBILITY: Final[float] = 0.10

assert abs(
    PRIORITY_W_SUPPORT + PRIORITY_W_IMPACT + PRIORITY_W_URGENCY
    + PRIORITY_W_REVERSIBILITY + PRIORITY_W_FEASIBILITY - 1.0
) < 1e-9, "priority weights must sum to 1"

#: Priority score -> bucket mapping. Buckets feed the FROZEN
#: insight.schema.json action.priority enum now|next|watch.
PRIORITY_NOW_THRESHOLD: Final[float] = 0.66
PRIORITY_NEXT_THRESHOLD: Final[float] = 0.45

#: Risk bands (§22). Aggregate by MAX over the four factors —
#: deliberately coarse (LOW < MEDIUM < HIGH), never pseudo-precise.
RISK_LOW: Final[str] = "LOW"
RISK_MEDIUM: Final[str] = "MEDIUM"
RISK_HIGH: Final[str] = "HIGH"
RISK_ORDER: Final[dict[str, int]] = {
    RISK_LOW: 0,
    RISK_MEDIUM: 1,
    RISK_HIGH: 2,
}

#: Evidence risk thresholds (code-computed inputs).
EVIDENCE_RISK_LOW_CONF: Final[float] = 0.4
EVIDENCE_RISK_WEAK_LOW_SOURCE: Final[int] = 2

#: Execution risk thresholds.
EXECUTION_RISK_FEASIBILITY_LOW: Final[float] = 0.4
EXECUTION_RISK_FEASIBILITY_MED: Final[float] = 0.6
EXECUTION_RISK_EFFORT_HIGH: Final[float] = 0.8
EXECUTION_RISK_EFFORT_MED: Final[float] = 0.6

#: Candidate cap (§35) — before semantic dedup.
MAX_CANDIDATES: Final[int] = 10

#: Dedup winner selection — deterministic tie-break key order (§28).
#: Higher priority, then higher confidence, then shorter action,
#: then stable id.
#: (Implementations sort by these keys; see dedup.py.)
