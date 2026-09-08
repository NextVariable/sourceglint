"""Phase 6B §12–§14, §16 — deterministic support computation & confidence.

Everything here is CODE. The model never reports support metrics (§13),
never sets its own priority or confidence cap (§14).

support chain: a recommendation cites supporting insight ids; its
signal/evidence sets are the UNION over those insights (code-derived,
PRD §3 traceability: Recommendation → Insight → Signal → Evidence).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..insights.support import distinct_source_count
from .dtos import RecommendationSupport
from .policy import DISTANCE_DISCOUNT_STEP

#: How to read the signal/evidence ids off a validated insight dict.
_INSIGHT_SIGNAL_KEY = "signal_ids"
_INSIGHT_EVIDENCE_KEY = "evidence_ids"


def _ids(insight: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = insight.get(key) or ()
    return tuple(str(v) for v in values if str(v))


def resolve_support_chain(
    supporting_insight_ids: Iterable[str],
    insight_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Union of signal_ids / evidence_ids across the cited insights."""
    signal_ids: list[str] = []
    evidence_ids: list[str] = []
    seen_s: set[str] = set()
    seen_e: set[str] = set()
    for iid in supporting_insight_ids:
        ins = insight_by_id.get(iid)
        if ins is None:
            continue
        for sid in _ids(ins, _INSIGHT_SIGNAL_KEY):
            if sid not in seen_s:
                seen_s.add(sid)
                signal_ids.append(sid)
        for eid in _ids(ins, _INSIGHT_EVIDENCE_KEY):
            if eid not in seen_e:
                seen_e.add(eid)
                evidence_ids.append(eid)
    return tuple(signal_ids), tuple(evidence_ids)


def compute_support(
    supporting_insight_ids: Iterable[str],
    insight_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    contradiction_present: bool = False,
    weak_signal_present: bool = False,
) -> RecommendationSupport:
    """Code-computed support metrics for one recommendation (§13)."""
    confidences = [
        float(insight_by_id[iid].get("confidence") or 0.0)
        for iid in supporting_insight_ids
        if iid in insight_by_id
    ]
    signal_ids, evidence_ids = resolve_support_chain(
        supporting_insight_ids, insight_by_id
    )
    n_sources = distinct_source_count(evidence_ids, evidence_by_id)
    return RecommendationSupport(
        supporting_insight_count=len(confidences),
        supporting_signal_count=len(signal_ids),
        supporting_evidence_count=len(evidence_ids),
        independent_source_count=n_sources,
        min_insight_confidence=min(confidences) if confidences else 0.0,
        mean_insight_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
        contradiction_present=contradiction_present,
        weak_signal_present=weak_signal_present,
    )


def recommendation_confidence_ceiling(
    supporting_confidences: Iterable[float],
    action_distance: int,
) -> float | None:
    """Maximum confidence a Recommendation may carry (§14).

    ceiling = min(supporting insight confidences) * (1 - 0.15*distance)

    Returns None when there is no supporting insight to bound against.
    Higher action distance lowers the ceiling further (§15).
    """
    confs = [float(c) for c in supporting_confidences]
    if not confs:
        return None
    base = min(confs)
    discount = max(0.0, 1.0 - DISTANCE_DISCOUNT_STEP * int(action_distance))
    return max(0.0, min(1.0, base * discount))
