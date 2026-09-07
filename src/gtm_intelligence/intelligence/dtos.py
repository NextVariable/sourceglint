"""Phase 5 internal DTOs (PRD §37).

These are INTERNAL to the intelligence layer. None of them are written to
the frozen Evidence / Signal schemas. The only object that ever reaches a
frozen contract is the Signal dict produced by `signals.py`, and it must
validate against `schemas/signal.schema.json`
(`additionalProperties: false`).

Why a separate DTO layer instead of dicts:
  * every stage boundary is typed, so a missing field is a bug not a
    KeyError at render time;
  * determinism snapshots (`to_dict()`) stay stable across runs;
  * diagnostics can be carried alongside signals WITHOUT polluting the
    frozen schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

WINDOW_CURRENT = "current"
WINDOW_BASELINE = "baseline"

#: Contradiction kinds (PRD §16). `contextual` covers segment disagreement
#: (enterprise positive vs consumer negative) which must NOT be reported as
#: a factual contradiction.
CONTRADICTION_NONE = "none"
CONTRADICTION_FACTUAL = "factual"
CONTRADICTION_EXPERIENCE = "experience"
CONTRADICTION_CONTEXTUAL = "contextual"

#: Hard caps applied to the model payload. Evidence snippets are already
#: capped at 280 by the Evidence contract; the title cap is new because
#: titles carry no schema cap but must not blow up the prompt (PRD §9).
MAX_TITLE_CHARS = 200
MAX_SNIPPET_CHARS = 280

#: Frozen signal_type values (Phase 1 signal.schema.json).
SIGNAL_TYPES = (
    "single_source",
    "cross_source",
    "repeated",
    "emerging",
    "contradictory",
)


def _as_tuple(values: Any) -> tuple:
    if values is None:
        return ()
    if isinstance(values, (list, tuple)):
        return tuple(values)
    raise TypeError(f"expected list/tuple, got {type(values).__name__}")


@dataclass(frozen=True)
class PreparedEvidence:
    """Deterministic, size-bounded view of one ledger evidence item.

    `url` is retained because PRD §13 source-independence math needs the
    canonical URL and its domain. It is deliberately EXCLUDED from
    `to_model_payload()` (PRD §6: URL is not required for semantic
    judgement).
    """

    evidence_id: str
    source: str
    source_type: str
    window: str
    title: str = ""
    snippet: str = ""
    published_at: str = ""
    market: str = ""
    language: str = ""
    source_tier: int | None = None
    evidence_quality: float | None = None
    engagement: Mapping[str, int] = field(default_factory=dict)
    url: str = ""
    has_text: bool = False

    # -- model boundary ----------------------------------------------------

    def to_model_payload(
        self,
        *,
        max_title_chars: int = MAX_TITLE_CHARS,
        max_snippet_chars: int = MAX_SNIPPET_CHARS,
    ) -> dict:
        """Minimal, size-bounded payload for the semantic model (PRD §6).

        Empty optionals are OMITTED rather than sent as "" — the model must
        not infer "unknown" as a neutral middle value (Closeout §3).
        """
        payload: dict[str, Any] = {"evidence_id": self.evidence_id}
        for key in ("source", "source_type", "published_at", "market", "language"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.title:
            payload["title"] = self.title[:max_title_chars]
        if self.snippet:
            payload["snippet"] = self.snippet[:max_snippet_chars]
        # window is always known (absent in ledger == current).
        payload["window"] = self.window
        return payload

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "source_type": self.source_type,
            "window": self.window,
            "title": self.title,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "market": self.market,
            "language": self.language,
            "source_tier": self.source_tier,
            "evidence_quality": self.evidence_quality,
            "engagement": dict(self.engagement),
            "url": self.url,
            "has_text": self.has_text,
        }


@dataclass(frozen=True)
class ResearchContext:
    """The slice of the Research Plan the model is allowed to see.

    Needed for Decision Relevance (PRD §20) and for the semantic cache
    key (PRD §28). It carries no credentials and no raw evidence.
    """

    mode: str = "general"
    entities: tuple[str, ...] = ()
    market: str = "global"
    decision_context: str = ""
    languages: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "entities": list(self.entities),
            "market": self.market,
            "decision_context": self.decision_context,
            "languages": list(self.languages),
        }


@dataclass(frozen=True)
class ClusterDraft:
    """Raw semantic-clustering output from the model (internal)."""

    label: str
    claim: str
    evidence_ids: tuple[str, ...]
    confidence: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "claim": self.claim,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ValidatedCluster:
    """A cluster whose identity and membership were verified by code.

    `cluster_id` is derived from the SORTED evidence id set, never from the
    model's label — the same evidence set always yields the same id even if
    a different model words the label differently (PRD §10).
    """

    cluster_id: str
    label: str
    claim: str
    evidence_ids: tuple[str, ...]
    confidence: float
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "label": self.label,
            "claim": self.claim,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ContradictionAssessment:
    """Support / counter classification for one cluster (PRD §16)."""

    cluster_id: str
    supporting_evidence_ids: tuple[str, ...] = ()
    counter_evidence_ids: tuple[str, ...] = ()
    kind: str = CONTRADICTION_NONE
    confidence: float = 0.0
    rationale: str = ""
    degraded: bool = False

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "counter_evidence_ids": list(self.counter_evidence_ids),
            "kind": self.kind,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "degraded": self.degraded,
        }


@dataclass(frozen=True)
class SignalFeatures:
    """Everything code can count WITHOUT asking a model (PRD §12)."""

    cluster_id: str
    evidence_count: int = 0
    unique_sources: tuple[str, ...] = ()
    unique_source_types: tuple[str, ...] = ()
    source_tiers: tuple[int, ...] = ()
    unique_domains: tuple[str, ...] = ()
    independent_source_count: int = 0
    independence_kinds: tuple[str, ...] = ()
    current_count: int = 0
    baseline_count: int = 0
    appeared_only_current: bool = False
    appeared_only_baseline: bool = False
    has_baseline_data: bool = False
    engagement_total: int = 0
    languages: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    first_party_count: int = 0
    community_count: int = 0

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "evidence_count": self.evidence_count,
            "unique_sources": list(self.unique_sources),
            "unique_source_types": list(self.unique_source_types),
            "source_tiers": list(self.source_tiers),
            "unique_domains": list(self.unique_domains),
            "independent_source_count": self.independent_source_count,
            "independence_kinds": list(self.independence_kinds),
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "appeared_only_current": self.appeared_only_current,
            "appeared_only_baseline": self.appeared_only_baseline,
            "has_baseline_data": self.has_baseline_data,
            "engagement_total": self.engagement_total,
            "languages": list(self.languages),
            "markets": list(self.markets),
            "first_party_count": self.first_party_count,
            "community_count": self.community_count,
        }


@dataclass(frozen=True)
class WeakSignalAssessment:
    """PRD §17 — weak-signal candidacy, never a synonym for low engagement."""

    is_weak_candidate: bool
    reasons: tuple[str, ...] = ()
    volume: int = 0
    novelty: float = 0.0
    engagement_total: int = 0
    decision_relevance: float = 0.0

    def to_dict(self) -> dict:
        return {
            "is_weak_candidate": self.is_weak_candidate,
            "reasons": list(self.reasons),
            "volume": self.volume,
            "novelty": self.novelty,
            "engagement_total": self.engagement_total,
            "decision_relevance": self.decision_relevance,
        }


@dataclass(frozen=True)
class SignalDiagnostics:
    """PRD §25 — full score explainability, kept OUT of the frozen schema."""

    signal_id: str
    cluster_id: str
    raw_factors: Mapping[str, float] = field(default_factory=dict)
    effective_factors: Mapping[str, float] = field(default_factory=dict)
    clamped_factors: Mapping[str, bool] = field(default_factory=dict)
    score: float = 0.0
    reasons: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    weak_signal: WeakSignalAssessment | None = None
    semantic_flags: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "cluster_id": self.cluster_id,
            "raw_factors": dict(self.raw_factors),
            "effective_factors": dict(self.effective_factors),
            "clamped_factors": dict(self.clamped_factors),
            "score": self.score,
            "reasons": dict(self.reasons),
            "warnings": list(self.warnings),
            "weak_signal": (
                self.weak_signal.to_dict() if self.weak_signal else None
            ),
            "semantic_flags": dict(self.semantic_flags),
        }


@dataclass(frozen=True)
class IntelligencePipelineResult:
    """Phase 5 output. Explicitly carries NO insight / recommendation /
    brief (PRD §38, §47)."""

    signals: tuple[dict, ...] = ()
    clusters: tuple[ValidatedCluster, ...] = ()
    diagnostics: tuple[SignalDiagnostics, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signals": [dict(s) for s in self.signals],
            "clusters": [c.to_dict() for c in self.clusters],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "warnings": list(self.warnings),
            "model_status": dict(self.model_status),
        }


__all__ = [
    "CONTRADICTION_CONTEXTUAL",
    "CONTRADICTION_EXPERIENCE",
    "CONTRADICTION_FACTUAL",
    "CONTRADICTION_NONE",
    "SIGNAL_TYPES",
    "WINDOW_BASELINE",
    "WINDOW_CURRENT",
    "ClusterDraft",
    "ContradictionAssessment",
    "IntelligencePipelineResult",
    "PreparedEvidence",
    "ResearchContext",
    "SignalDiagnostics",
    "SignalFeatures",
    "ValidatedCluster",
    "WeakSignalAssessment",
]
