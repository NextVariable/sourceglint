"""Phase 6B §7, §9, §10 — internal Recommendation DTOs.

All of these are INTERNAL to the recommendation layer. None of them are
written to a frozen schema. The only objects that reach a frozen
contract are:
  * Recommendation dicts produced by the pipeline — each validates
    against schemas/insight.schema.json as type=RECOMMENDATION
    (additionalProperties: false, action required);
  * diagnostics kept OUT of the frozen schema (PRD §3, §25).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "PreparedInsight",
    "RecommendationDraft",
    "RecommendationAssessment",
    "RecommendationSupport",
    "RecommendationDiagnostics",
    "RecommendationConflict",
    "RecommendationPipelineResult",
]


@dataclass(frozen=True)
class PreparedInsight:
    """Deterministic, minimal view of one validated FACT/INFERENCE insight
    that the recommendation model may cite (PRD §9).

    Only necessary decision context reaches the model: identity, type,
    statement, confidence, GTM implications, weak/contradiction metadata.
    Raw evidence, URLs, scores and ledger internals are NOT included.
    """

    insight_id: str
    type: str
    statement: str
    confidence: float
    gtm_implications: Mapping[str, str | None] = field(default_factory=dict)
    weak_signal: bool = False
    contradiction_preserved: bool = False

    def to_model_payload(self) -> dict:
        """Minimal payload for the recommendation model (§9)."""
        payload: dict[str, Any] = {
            "insight_id": self.insight_id,
            "type": self.type,
            "statement": self.statement,
            "confidence": self.confidence,
            "weak_signal": self.weak_signal,
            "contradiction_preserved": self.contradiction_preserved,
        }
        if self.gtm_implications:
            payload["gtm_implications"] = dict(self.gtm_implications)
        return payload

    def to_dict(self) -> dict:
        return self.to_model_payload()


@dataclass(frozen=True)
class RecommendationDraft:
    """Raw candidate recommendation from the model (internal).

    Code validates every field; nothing is trusted from the model
    without a check (PRD §8, §32).
    """

    statement: str
    action: str
    supporting_insight_ids: tuple[str, ...]
    confidence: float
    action_class: str
    gtm_dimensions: tuple[str, ...]
    action_anchor: str = ""
    rationale: str = ""
    expected_outcome: str = ""

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "action": self.action,
            "supporting_insight_ids": list(self.supporting_insight_ids),
            "confidence": self.confidence,
            "action_class": self.action_class,
            "gtm_dimensions": list(self.gtm_dimensions),
            "action_anchor": self.action_anchor,
            "rationale": self.rationale,
            "expected_outcome": self.expected_outcome,
        }


@dataclass(frozen=True)
class RecommendationAssessment:
    """Per-candidate actionability assessment from the model (PRD §20).

    Semantic fields the code cannot compute. All 0..1 except
    reversibility (high|medium|low). Used by the code-owned priority
    formula and risk assessment.
    """

    expected_impact: float = 0.0
    urgency: float = 0.0
    effort: float = 0.0
    feasibility: float = 0.0
    reversibility: str = "medium"
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "expected_impact": self.expected_impact,
            "urgency": self.urgency,
            "effort": self.effort,
            "feasibility": self.feasibility,
            "reversibility": self.reversibility,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class RecommendationSupport:
    """Code-computed support metrics for one recommendation (§13).

    Every field is derived by code from the supporting insight chain —
    never reported by the model.
    """

    supporting_insight_count: int = 0
    supporting_signal_count: int = 0
    supporting_evidence_count: int = 0
    independent_source_count: int = 0
    min_insight_confidence: float = 0.0
    mean_insight_confidence: float = 0.0
    contradiction_present: bool = False
    weak_signal_present: bool = False

    def to_dict(self) -> dict:
        return {
            "supporting_insight_count": self.supporting_insight_count,
            "supporting_signal_count": self.supporting_signal_count,
            "supporting_evidence_count": self.supporting_evidence_count,
            "independent_source_count": self.independent_source_count,
            "min_insight_confidence": self.min_insight_confidence,
            "mean_insight_confidence": self.mean_insight_confidence,
            "contradiction_present": self.contradiction_present,
            "weak_signal_present": self.weak_signal_present,
        }


@dataclass(frozen=True)
class RecommendationDiagnostics:
    """Full explainability for one recommendation, OUT of the frozen
    schema (PRD §3, §25). Priority / risk / traceability chain live here.
    """

    insight_id: str
    supporting_insight_ids: tuple[str, ...] = ()
    supporting_signal_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    gtm_dimensions: tuple[str, ...] = ()
    action_class: str = ""
    action_distance: int = 0
    reversibility: str = "medium"
    priority: float = 0.0
    priority_bucket: str = "watch"
    risk_factors: Mapping[str, str] = field(default_factory=dict)
    overall_risk: str = "LOW"
    support: RecommendationSupport = field(default_factory=RecommendationSupport)
    weak_signal_present: bool = False
    contradiction_present: bool = False
    conflict_group_id: str = ""
    collapsed_duplicate_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "supporting_insight_ids": list(self.supporting_insight_ids),
            "supporting_signal_ids": list(self.supporting_signal_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "gtm_dimensions": list(self.gtm_dimensions),
            "action_class": self.action_class,
            "action_distance": self.action_distance,
            "reversibility": self.reversibility,
            "priority": self.priority,
            "priority_bucket": self.priority_bucket,
            "risk_factors": dict(self.risk_factors),
            "overall_risk": self.overall_risk,
            "support": self.support.to_dict(),
            "weak_signal_present": self.weak_signal_present,
            "contradiction_present": self.contradiction_present,
            "conflict_group_id": self.conflict_group_id,
            "collapsed_duplicate_ids": list(self.collapsed_duplicate_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RecommendationConflict:
    """A detected conflict between two or more recommendations (§29)."""

    group_id: str
    rec_ids: tuple[str, ...]
    kind: str
    rationale: str = ""
    gtm_dimensions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "rec_ids": list(self.rec_ids),
            "kind": self.kind,
            "rationale": self.rationale,
            "gtm_dimensions": list(self.gtm_dimensions),
        }


@dataclass(frozen=True)
class RecommendationPipelineResult:
    """Phase 6B output (§1, §48).

    recommendations: tuple of dicts conforming to insight.schema.json
        (type == RECOMMENDATION). Diagnostics + conflicts are internal.
    """

    recommendations: tuple[dict, ...] = ()
    diagnostics: tuple[RecommendationDiagnostics, ...] = ()
    conflicts: tuple[RecommendationConflict, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "recommendations": [dict(r) for r in self.recommendations],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "warnings": list(self.warnings),
            "model_status": dict(self.model_status),
        }
