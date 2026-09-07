"""Phase 6A §9 — internal Insight DTOs.

These are INTERNAL to the insight layer. None of them are written to
the frozen insight.schema.json. The only object that ever reaches a
frozen contract is the Insight dict produced by the pipeline, and it
must validate against schemas/insight.schema.json
(additionalProperties: false).

Design principles (matching Phase 5 dtos.py):
  * every stage boundary is typed, so a missing field is a bug not a
    KeyError at render time;
  * determinism snapshots (to_dict()) stay stable across runs;
  * diagnostics can be carried alongside insights WITHOUT polluting the
    frozen schema;
  * model payloads are minimal — score, confidence, URL, engagement,
    raw_metadata are NEVER sent to the model (PRD §10, §37).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# Re-export type constants for convenience.
from .ids import FACT, INFERENCE, RECOMMENDATION  # noqa: F401

__all__ = [
    "FACT",
    "INFERENCE",
    "RECOMMENDATION",
    "FactDraft",
    "GTMImplicationDraft",
    "InferenceDraft",
    "InsightDiagnostics",
    "InsightPipelineResult",
    "PreparedSignal",
]


@dataclass(frozen=True)
class PreparedSignal:
    """Deterministic, minimal view of one signal for the insight model.

    Carries only what the model needs for FACT/INFERENCE synthesis:
    identity, type, claim, evidence refs, supporting/counter summaries,
    market, language, and CODE-COMPUTED counts (PRD §37: the model never
    counts — counts are injected by code).

    Deliberately EXCLUDED from to_model_payload():
      - score (code-owned, PRD §6)
      - confidence (code-owned)
      - engagement (code-owned)
      - url (model never sees URLs, ADR-0001 D7)
      - raw_metadata
    """

    signal_id: str
    signal_type: str
    claim: str
    score: float
    confidence: float
    evidence_ids: tuple[str, ...]
    supporting_evidence_summaries: tuple[str, ...] = ()
    counter_evidence_summaries: tuple[str, ...] = ()
    market: str = ""
    language: str = ""
    current_count: int = 0
    baseline_count: int = 0
    weak_signal: bool = False

    def to_model_payload(self) -> dict:
        """Minimal, size-bounded payload for the insight model (PRD §10).

        Empty optionals are OMITTED rather than sent as "" — the model must
        not infer "unknown" as a neutral middle value (Closeout §3 invariant).
        """
        payload: dict[str, Any] = {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "claim": self.claim,
            "evidence_ids": list(self.evidence_ids),
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "weak_signal": self.weak_signal,
        }
        if self.supporting_evidence_summaries:
            payload["supporting_evidence_summaries"] = list(self.supporting_evidence_summaries)
        if self.counter_evidence_summaries:
            payload["counter_evidence_summaries"] = list(self.counter_evidence_summaries)
        if self.market:
            payload["market"] = self.market
        if self.language:
            payload["language"] = self.language
        return payload

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "claim": self.claim,
            "score": self.score,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "supporting_evidence_summaries": list(self.supporting_evidence_summaries),
            "counter_evidence_summaries": list(self.counter_evidence_summaries),
            "market": self.market,
            "language": self.language,
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "weak_signal": self.weak_signal,
        }


@dataclass(frozen=True)
class FactDraft:
    """Raw FACT synthesis output from the model (internal).

    The model produces the statement + confidence + rationale. Code
    derives the insight_id, validates signal_ids/evidence_ids, and checks
    grounding (PRD §12–§14).
    """

    statement: str
    signal_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    confidence: float
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "signal_ids": list(self.signal_ids),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class InferenceDraft:
    """Raw INFERENCE synthesis output from the model (internal).

    The model produces the statement + confidence + rationale. Code
    derives the insight_id, validates fact_ids/signal_ids/evidence_ids,
    and checks inference support (PRD §15–§17).

    inference_distance (PRD §27):
      0 = direct abstraction from one signal
      1 = simple synthesis across 2+ facts/signals
      2 = multi-step interpretation (MVP cap, PRD §27)
    """

    statement: str
    fact_ids: tuple[str, ...]
    signal_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    confidence: float
    rationale: str = ""
    inference_distance: int = 1

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "fact_ids": list(self.fact_ids),
            "signal_ids": list(self.signal_ids),
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "rationale": self.rationale,
            "inference_distance": self.inference_distance,
        }


@dataclass(frozen=True)
class GTMImplicationDraft:
    """Descriptive GTM implication mapping from the model (internal).

    Values are DESCRIPTIVE only (PRD §5, §24): "Price sensitivity differs
    by segment" is allowed; "Lower price to $9" is NOT (that is a
    Recommendation, Phase 6B). The recommendation leakage guard (§28)
    screens these values.
    """

    insight_id: str
    implications: Mapping[str, str | None]

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "implications": dict(self.implications),
        }


@dataclass(frozen=True)
class InsightDiagnostics:
    """Full score/trace explainability for one insight, kept OUT of the
    frozen schema (PRD §25).

    Carries support_strength (PRD §16), inference_distance (PRD §27),
    and the full supporting fact/signal/evidence chain for audit.
    """

    insight_id: str
    type: str
    support_strength: float = 0.0
    inference_distance: int = 0
    supporting_fact_ids: tuple[str, ...] = ()
    supporting_signal_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    weak_signal: bool = False
    contradiction_preserved: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "insight_id": self.insight_id,
            "type": self.type,
            "support_strength": self.support_strength,
            "inference_distance": self.inference_distance,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "supporting_signal_ids": list(self.supporting_signal_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "weak_signal": self.weak_signal,
            "contradiction_preserved": self.contradiction_preserved,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InsightPipelineResult:
    """Phase 6A output (PRD §31).

    Carries validated insight dicts (conforming to insight.schema.json)
    and diagnostics. Explicitly carries NO recommendation, no GTM action
    strategy, no final brief (PRD §48 stop boundary).
    """

    insights: tuple[dict, ...] = ()
    diagnostics: tuple[InsightDiagnostics, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "insights": [dict(i) for i in self.insights],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "warnings": list(self.warnings),
            "model_status": dict(self.model_status),
        }
