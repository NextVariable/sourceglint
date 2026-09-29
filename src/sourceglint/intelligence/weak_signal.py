"""Phase 5 §17 — weak-signal detection, free of engagement bias.

A weak signal is a SMALL, EARLY trace of something that could matter:
few mentions (low volume), often with little engagement, but backed by
semantic substance — the topic is novel and/or central to the decision.

Rules:
  * VOLUME gates candidacy: `evidence_count <= WEAK_VOLUME_MAX`.
  * ENGAGEMENT never gates: no engagement floor, no engagement trigger.
    High engagement does not disqualify a candidate either — a low-volume
    cluster with many reactions is still early-stage.
  * SUBSTANCE nominates: high semantic novelty (or code novelty when the
    model did not assess it) OR high decision relevance OR the topic is
    fresh vs the baseline window (appeared_only_current). Without any of
    these, a low-volume cluster is treated as noise, not a weak signal.
  * semantic_novelty=None is UNKNOWN — it contributes 0.0 and never by
    itself triggers candidacy (Closeout §3: unknown ≠ neutral).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .dtos import WeakSignalAssessment

#: Volume above which a cluster is no longer "small" / early stage.
WEAK_VOLUME_MAX = 3
#: Nomination thresholds for the semantic substance inputs.
NOVELTY_NOMINATION = 0.6
RELEVANCE_NOMINATION = 0.6


def assess(
    *,
    features,
    decision_relevance: float,
    semantic_novelty: Optional[float] = None,
    code_novelty: float = 0.0,
) -> WeakSignalAssessment:
    """Classify one cluster as a weak-signal candidate or not.

    `features` is a `SignalFeatures` (evidence_count / engagement_total /
    appeared_only_current). `semantic_novelty` is the model's diagnostic
    novelty (may be None = not assessed); `code_novelty` is the
    baseline-window novelty factor (factors.code_novelty).
    """
    volume = int(features.evidence_count)
    engagement = int(features.engagement_total)
    dr = float(decision_relevance)

    # Novelty used for nomination: prefer the model's semantic reading,
    # fall back to the deterministic baseline novelty when the model did
    # not assess it. The value REPORTED on the assessment is that same
    # chosen novelty.
    if semantic_novelty is not None:
        novelty = float(semantic_novelty)
    else:
        novelty = float(code_novelty)

    if volume > WEAK_VOLUME_MAX:
        return WeakSignalAssessment(
            is_weak_candidate=False,
            reasons=(),
            volume=volume,
            novelty=novelty,
            engagement_total=engagement,
            decision_relevance=dr,
        )

    reasons: list[str] = []
    if novelty >= NOVELTY_NOMINATION:
        reasons.append(f"novel content (novelty {novelty:.2f})")
    if dr >= RELEVANCE_NOMINATION:
        reasons.append(f"high decision relevance ({dr:.2f})")
    if bool(getattr(features, "appeared_only_current", False)):
        reasons.append("absent from baseline window (newly appearing)")

    return WeakSignalAssessment(
        is_weak_candidate=bool(reasons),
        reasons=tuple(reasons),
        volume=volume,
        novelty=novelty,
        engagement_total=engagement,
        decision_relevance=dr,
    )
