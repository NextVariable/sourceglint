"""Phase 6B §14, §20–§22 — assessment, priority and risk derivation.

Two responsibilities, split by the §8 boundary:

  * model: per-candidate actionability assessment — expected impact,
    urgency, effort, feasibility, reversibility (semantic fields).
  * code: deterministic priority formula (§21), risk categories (§22),
    action distance (§15), confidence ceiling (§14) and the frozen
    action.priority bucket mapping.

Recommendation priority is an INDEPENDENT layer — it never touches the
frozen Phase 2 Signal Score (§21).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import ModelResponse, ModelStatus
from .ids import derive_recommendation_id
from .support import compute_support, resolve_support_chain
from .dtos import (
    RecommendationAssessment,
    RecommendationDraft,
    RecommendationSupport,
)
from .model import (
    PROMPT_VERSIONS,
    RECOMMENDATION_ASSESSMENT_RESPONSE_SCHEMA,
    TASK_RECOMMENDATION_ASSESSMENT,
)
from .policy import (
    CLASS_ACTION_DISTANCE,
    EVIDENCE_RISK_LOW_CONF,
    EVIDENCE_RISK_WEAK_LOW_SOURCE,
    EXECUTION_RISK_EFFORT_HIGH,
    EXECUTION_RISK_EFFORT_MED,
    EXECUTION_RISK_FEASIBILITY_LOW,
    EXECUTION_RISK_FEASIBILITY_MED,
    PRIORITY_NEXT_THRESHOLD,
    PRIORITY_NOW_THRESHOLD,
    PRIORITY_W_FEASIBILITY,
    PRIORITY_W_IMPACT,
    PRIORITY_W_REVERSIBILITY,
    PRIORITY_W_SUPPORT,
    PRIORITY_W_URGENCY,
    REVERSIBILITY_SCORE,
    REVERSIBILITY_VALUES,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_ORDER,
)
from .prompts import get_recommendation_prompt
from .support import recommendation_confidence_ceiling

#: Frozen action.priority enum (insight.schema.json) values.
PRIORITY_BUCKET_NOW = "now"
PRIORITY_BUCKET_NEXT = "next"
PRIORITY_BUCKET_WATCH = "watch"


@dataclass(frozen=True)
class AssessedRecommendation:
    """One fully scored recommendation (internal)."""

    draft: RecommendationDraft
    insight_id: str
    assessment: RecommendationAssessment
    support: RecommendationSupport
    supporting_signal_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    support_confidence: float = 0.0
    action_distance: int = 0
    confidence: float = 0.0  # after ceiling clamp
    priority: float = 0.0
    priority_bucket: str = "watch"
    reversibility: str = "medium"
    risk_factors: Mapping[str, str] = field(default_factory=dict)
    overall_risk: str = "LOW"
    weak_signal_present: bool = False
    contradiction_present: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "draft": self.draft.to_dict(),
            "assessment": self.assessment.to_dict(),
            "support": self.support.to_dict(),
            "supporting_signal_ids": list(self.supporting_signal_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "support_confidence": self.support_confidence,
            "action_distance": self.action_distance,
            "confidence": self.confidence,
            "priority": self.priority,
            "priority_bucket": self.priority_bucket,
            "reversibility": self.reversibility,
            "risk_factors": dict(self.risk_factors),
            "overall_risk": self.overall_risk,
            "weak_signal_present": self.weak_signal_present,
            "contradiction_present": self.contradiction_present,
            "warnings": list(self.warnings),
        }


def priority_bucket(priority: float) -> str:
    """Map the code-computed priority score onto the frozen
    action.priority enum now|next|watch (§36; thresholds §46)."""
    if priority >= PRIORITY_NOW_THRESHOLD:
        return PRIORITY_BUCKET_NOW
    if priority >= PRIORITY_NEXT_THRESHOLD:
        return PRIORITY_BUCKET_NEXT
    return PRIORITY_BUCKET_WATCH


def compute_reversibility(assessment: RecommendationAssessment) -> str:
    value = (assessment.reversibility or "").strip().lower()
    return value if value in REVERSIBILITY_VALUES else "medium"


def assess_priority(
    *,
    support_confidence: float,
    assessment: RecommendationAssessment,
    reversibility: str,
) -> float:
    """§21 priority formula — deterministic, centralized weights.

    priority = 0.30*support_confidence + 0.25*expected_impact
             + 0.20*urgency + 0.15*reversibility + 0.10*feasibility
    """
    return round(
        PRIORITY_W_SUPPORT * support_confidence
        + PRIORITY_W_IMPACT * assessment.expected_impact
        + PRIORITY_W_URGENCY * assessment.urgency
        + PRIORITY_W_REVERSIBILITY * REVERSIBILITY_SCORE[reversibility]
        + PRIORITY_W_FEASIBILITY * assessment.feasibility,
        4,
    )


# --- risk assessment (§22) --------------------------------------------------


def _aggregate_risk(factors: Mapping[str, str]) -> str:
    """Overall risk = max of the four factors (coarse, never pseudo-precise)."""
    best = RISK_LOW
    for value in factors.values():
        if RISK_ORDER.get(value, 0) > RISK_ORDER[best]:
            best = value
    return best


def assess_risk(
    *,
    support: RecommendationSupport,
    action_distance: int,
    assessment: RecommendationAssessment,
    reversibility: str,
) -> tuple[Mapping[str, str], str]:
    """§22 — risk categories. Deterministic; overall = max of factors."""
    factors: dict[str, str] = {}

    # Evidence risk: thin / weak / contradictory support is risky.
    if support.min_insight_confidence < EVIDENCE_RISK_LOW_CONF:
        factors["evidence_risk"] = RISK_HIGH
    elif (
        support.weak_signal_present
        and support.independent_source_count < EVIDENCE_RISK_WEAK_LOW_SOURCE
    ):
        factors["evidence_risk"] = RISK_HIGH
    elif (
        support.contradiction_present
        or support.weak_signal_present
        or support.independent_source_count < EVIDENCE_RISK_WEAK_LOW_SOURCE
    ):
        factors["evidence_risk"] = RISK_MEDIUM
    else:
        factors["evidence_risk"] = RISK_LOW

    # Execution risk: feasibility / effort (model semantic).
    if (
        assessment.feasibility < EXECUTION_RISK_FEASIBILITY_LOW
        or assessment.effort > EXECUTION_RISK_EFFORT_HIGH
    ):
        factors["execution_risk"] = RISK_HIGH
    elif (
        assessment.feasibility < EXECUTION_RISK_FEASIBILITY_MED
        or assessment.effort > EXECUTION_RISK_EFFORT_MED
    ):
        factors["execution_risk"] = RISK_MEDIUM
    else:
        factors["execution_risk"] = RISK_LOW

    # Reversibility risk.
    rev_risk = {
        "high": RISK_LOW,
        "medium": RISK_MEDIUM,
        "low": RISK_HIGH,
    }
    factors["reversibility_risk"] = rev_risk.get(reversibility, RISK_MEDIUM)

    # Contradiction risk: strategic change on contradictory support is
    # the riskiest combination (§19).
    if support.contradiction_present and action_distance >= 2:
        factors["contradiction_risk"] = RISK_HIGH
    elif support.contradiction_present:
        factors["contradiction_risk"] = RISK_MEDIUM
    else:
        factors["contradiction_risk"] = RISK_LOW

    return factors, _aggregate_risk(factors)


# --- assessment calls (§8) ---------------------------------------------------


@dataclass(frozen=True)
class AssessmentResult:
    assessed: tuple[AssessedRecommendation, ...] = ()
    failed_insight_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: str = "success"

    def to_dict(self) -> dict:
        return {
            "assessed": [a.to_dict() for a in self.assessed],
            "failed_insight_ids": list(self.failed_insight_ids),
            "warnings": list(self.warnings),
            "model_status": self.model_status,
        }


def assess_recommendations(
    drafts: Sequence[RecommendationDraft],
    model,
    *,
    insight_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Any],
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
    insight_diagnostics: Mapping[str, Mapping[str, Any]] | None = None,
) -> AssessmentResult:
    """Assess + score validated candidate drafts (PRD §14, §20–§22).

    For every validated draft: derive the recommendation id, the code
    support chain, call the model once for actionability, clamp
    confidence to the support ceiling, and derive priority + risk.
    """
    if not drafts:
        return AssessmentResult()

    ctx = research_context or ResearchContext()
    diags = insight_diagnostics or {}
    assessed: list[AssessedRecommendation] = []
    failed: list[str] = []
    warnings: list[str] = []
    status_failed = 0

    for draft in drafts:
        rec_id = derive_recommendation_id(
            supporting_insight_ids=draft.supporting_insight_ids,
            gtm_dimensions=draft.gtm_dimensions,
            action_class=draft.action_class,
            action_anchor=draft.action_anchor,
        )

        # Code support chain (§3, §12)
        signal_ids, evidence_ids = resolve_support_chain(
            draft.supporting_insight_ids, insight_by_id
        )
        confidences = [
            float(insight_by_id[iid].get("confidence") or 0.0)
            for iid in draft.supporting_insight_ids
            if iid in insight_by_id
        ]
        weak = any(
            bool((diags.get(iid) or {}).get("weak_signal"))
            for iid in draft.supporting_insight_ids
        )
        contra = any(
            bool((diags.get(iid) or {}).get("contradiction_preserved"))
            for iid in draft.supporting_insight_ids
        )
        support = compute_support(
            draft.supporting_insight_ids,
            insight_by_id,
            evidence_by_id,
            contradiction_present=contra,
            weak_signal_present=weak,
        )
        support_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        # Model assessment call (semantic — model owned, §8)
        assessment = _call_assessment(
            model, draft, rec_id, ctx, cache
        )
        if assessment is None:
            failed.append(rec_id)
            warnings.append(
                f"recommendation_assessment: no assessment for {rec_id}; "
                f"candidate dropped"
            )
            status_failed += 1
            continue

        reversibility = compute_reversibility(assessment)
        action_distance = CLASS_ACTION_DISTANCE.get(draft.action_class, 1)

        # Confidence ceiling (§14): clamp with an explicit warning.
        confidence = draft.confidence
        ceiling = recommendation_confidence_ceiling(
            confidences, action_distance
        )
        if ceiling is not None and confidence > ceiling:
            warnings.append(
                f"recommendation_assessment: confidence capped from "
                f"{confidence:.4f} to {ceiling:.4f} (support ceiling, "
                f"action_distance={action_distance})"
            )
            confidence = ceiling

        priority = assess_priority(
            support_confidence=support_confidence,
            assessment=assessment,
            reversibility=reversibility,
        )
        bucket = priority_bucket(priority)
        risk_factors, overall = assess_risk(
            support=support,
            action_distance=action_distance,
            assessment=assessment,
            reversibility=reversibility,
        )

        assessed.append(AssessedRecommendation(
            draft=draft,
            insight_id=rec_id,
            assessment=assessment,
            support=support,
            supporting_signal_ids=signal_ids,
            supporting_evidence_ids=evidence_ids,
            support_confidence=support_confidence,
            action_distance=action_distance,
            confidence=confidence,
            priority=priority,
            priority_bucket=bucket,
            reversibility=reversibility,
            risk_factors=risk_factors,
            overall_risk=overall,
            weak_signal_present=weak,
            contradiction_present=contra,
            warnings=(),
        ))

    status = "success"
    if status_failed and not assessed:
        status = "invalid_output"
    elif status_failed:
        status = "partial"

    return AssessmentResult(
        assessed=tuple(assessed),
        failed_insight_ids=tuple(failed),
        warnings=tuple(warnings),
        model_status=status,
    )


def _call_assessment(
    model,
    draft: RecommendationDraft,
    rec_id: str,
    ctx: ResearchContext,
    cache: SemanticCache | None,
) -> RecommendationAssessment | None:
    """One model assessment call for a candidate (may be cached)."""
    key = build_cache_key(
        task=TASK_RECOMMENDATION_ASSESSMENT,
        prompt_version=PROMPT_VERSIONS[TASK_RECOMMENDATION_ASSESSMENT],
        model_id=model.model_id,
        evidence_ids=(
            draft.supporting_insight_ids
            + draft.gtm_dimensions
            + (draft.action_class, rec_id)
        ),
        research_context=ctx.to_dict(),
    )

    cached = None
    if cache is not None:
        cached = cache.get(key)
        if cached is not None and cached.ok:
            return _parse_assessment(cached, rec_id)

    payload: dict[str, Any] = {
        "rec_id": rec_id,
        "statement": draft.statement,
        "action": draft.action,
        "action_class": draft.action_class,
        "gtm_dimensions": list(draft.gtm_dimensions),
        "supporting_insight_ids": list(draft.supporting_insight_ids),
        "expected_outcome": draft.expected_outcome,
    }
    try:
        prompt = get_recommendation_prompt(TASK_RECOMMENDATION_ASSESSMENT)
        payload["prompt"] = prompt.render()
    except (FileNotFoundError, KeyError):
        pass

    response = model.complete_structured(
        task=TASK_RECOMMENDATION_ASSESSMENT,
        payload=payload,
        response_schema=RECOMMENDATION_ASSESSMENT_RESPONSE_SCHEMA,
    )
    if cache is not None:
        cache.put(key, response)
    return _parse_assessment(response, rec_id)


def _parse_assessment(
    response: ModelResponse, rec_id: str
) -> RecommendationAssessment | None:
    if not response.ok:
        return None
    p = response.payload
    try:
        return RecommendationAssessment(
            expected_impact=_clamp01(p.get("expected_impact")),
            urgency=_clamp01(p.get("urgency")),
            effort=_clamp01(p.get("effort")),
            feasibility=_clamp01(p.get("feasibility")),
            reversibility=str(p.get("reversibility") or "medium"),
            rationale=str(p.get("rationale") or ""),
        )
    except (TypeError, ValueError):
        return None


def _clamp01(value: Any) -> float:
    v = float(value or 0.0)
    return max(0.0, min(1.0, v))
