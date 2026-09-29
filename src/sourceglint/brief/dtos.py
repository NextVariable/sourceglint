"""Phase 6C §6, §33 — internal Brief DTOs.

INTERNAL to the brief layer. No DTO here is written to a frozen schema —
the only artifact the layer produces is deterministic Markdown (PRD §22).
The layer consumes ALREADY VALIDATED structured objects:
  * Research plan metadata (BriefContext)
  * validated Signals (signal.schema dicts)
  * validated FACT / INFERENCE Insights (insight.schema dicts)
  * validated RECOMMENDATIONs (insight.schema dicts, type=RECOMMENDATION)
  * their diagnostics (6A InsightDiagnostics / 6B RecommendationDiagnostics)
  * the Evidence Ledger and CoverageReport
and never raw adapter results (Phase 6C §6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

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


@dataclass(frozen=True)
class BriefContext:
    """Research context rendered at the top of the brief (§27).

    Answers "What did we research?" from the real research-plan fields.
    Every field is optional — absent fields are simply not rendered.
    """

    query: str = ""
    topic: str = ""
    mode: str = ""
    market: str = ""
    locale: str = ""
    languages: tuple[str, ...] = ()
    time_window: str = ""
    as_of: str = ""
    entities: tuple[str, ...] = ()
    decision_context: str = ""
    discovery_only: bool = False

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "topic": self.topic,
            "mode": self.mode,
            "market": self.market,
            "locale": self.locale,
            "languages": list(self.languages),
            "time_window": self.time_window,
            "as_of": self.as_of,
            "entities": list(self.entities),
            "decision_context": self.decision_context,
            "discovery_only": self.discovery_only,
        }


@dataclass(frozen=True)
class BriefInput:
    """Everything the brief layer is allowed to consume (§6).

    signals / insights / recommendations are sequences of frozen-schema
    dicts as produced by Phase 5 / 6A / 6B pipelines. Diagnostics are
    keyed by object id (dataclasses or plain mappings are both accepted
    and normalized to dicts by the selection layer).
    """

    context: BriefContext = field(default_factory=BriefContext)
    ledger: Any = None  # EvidenceLedger | None
    signals: tuple[dict, ...] = ()
    insights: tuple[dict, ...] = ()  # FACT + INFERENCE only
    recommendations: tuple[dict, ...] = ()  # type == RECOMMENDATION
    insight_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    recommendation_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    conflicts: tuple[Any, ...] = ()  # RecommendationConflict | mapping
    coverage: Any = None  # CoverageReport | mapping | None
    caps: Mapping[str, int] = field(default_factory=dict)

    def effective_caps(self) -> dict[str, int]:
        """Per-section caps: caller overrides win, defaults otherwise."""
        from .policy import DEFAULT_CAPS

        out = dict(DEFAULT_CAPS)
        for k, v in self.caps.items():
            if v is not None and int(v) > 0:
                out[k] = int(v)
        return out


@dataclass(frozen=True)
class SelectedFact:
    """One selected FACT, fully resolved by code for rendering."""

    insight_id: str
    statement: str
    confidence: float
    support: float
    evidence_ids: tuple[str, ...]
    weak: bool = False
    contradiction: bool = False


@dataclass(frozen=True)
class SelectedInference:
    """One selected INFERENCE, fully resolved by code for rendering."""

    insight_id: str
    statement: str
    confidence: float
    support: float
    evidence_ids: tuple[str, ...]
    weak: bool = False
    contradiction: bool = False


@dataclass(frozen=True)
class SelectedRecommendation:
    """One selected RECOMMENDATION with its code-resolved support chain.

    why_lines are the verbatim statements of the supporting insights
    (Phase 6C §11, §29) — the renderer never invents its own reason.
    evidence_ids is the resolved Recommendation → Insight → Signal →
    Evidence chain (§16). priority is the frozen bucket (now/next/watch).
    """

    insight_id: str
    action: str
    priority: str
    confidence: float
    risk: str
    priority_score: float
    why_lines: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SelectedEmergingSignal:
    """A weak/emerging item for the Emerging Signals section (§14)."""

    emerging_id: str  # insight_id (weak insight) or signal_id
    label: str
    evidence_ids: tuple[str, ...]
    origin: str = "insight"  # "insight" | "signal"


@dataclass(frozen=True)
class SelectedWatchout:
    """A contradiction surfaced in the Watchouts section (§13, §30).

    kind is "conflict" (from Phase 6B conflict detection) or "signal"
    (from a Phase 5 contradictory signal). text carries the ALREADY
    EXISTING upstream classification/rationale — never re-reasoned here.
    """

    kind: str
    title: str
    text: str = ""
    watchout_id: str = ""  # conflict group_id or signal_id
    rec_ids: tuple[str, ...] = ()
    support_evidence_ids: tuple[str, ...] = ()
    counter_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectedBrief:
    """The fully selected, ranked, capped brief content (§9, §10).

    Everything here is code-resolved from validated inputs; the renderer
    only formats it into Markdown.
    """

    context: BriefContext = field(default_factory=BriefContext)
    facts: tuple[SelectedFact, ...] = ()
    inferences: tuple[SelectedInference, ...] = ()
    recommendations: tuple[SelectedRecommendation, ...] = ()
    emerging: tuple[SelectedEmergingSignal, ...] = ()
    watchouts: tuple[SelectedWatchout, ...] = ()
    executive: tuple[str, ...] = ()
    coverage_lines: tuple[str, ...] = ()
    diagnostics: "BriefDiagnostics" = field(default_factory=lambda: BriefDiagnostics())

    def is_empty(self) -> bool:
        return not (
            self.facts
            or self.inferences
            or self.recommendations
            or self.emerging
            or self.watchouts
        )


@dataclass(frozen=True)
class BriefDiagnostics:
    """Internal render diagnostics (§33) — never shown in the Markdown.

    Records what was selected, what the caps dropped, and why, so eval
    can assert output stability and honest degradation.
    """

    selected_fact_ids: tuple[str, ...] = ()
    selected_inference_ids: tuple[str, ...] = ()
    selected_recommendation_ids: tuple[str, ...] = ()
    selected_emerging_ids: tuple[str, ...] = ()
    selected_watchout_ids: tuple[str, ...] = ()
    dropped_due_to_cap: Mapping[str, int] = field(default_factory=dict)
    evidence_count: int = 0
    warning_count: int = 0
    missing_layers: tuple[str, ...] = ()
    no_evidence: bool = False
    sections_rendered: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "selected_fact_ids": list(self.selected_fact_ids),
            "selected_inference_ids": list(self.selected_inference_ids),
            "selected_recommendation_ids": list(self.selected_recommendation_ids),
            "selected_emerging_ids": list(self.selected_emerging_ids),
            "selected_watchout_ids": list(self.selected_watchout_ids),
            "dropped_due_to_cap": dict(self.dropped_due_to_cap),
            "evidence_count": self.evidence_count,
            "warning_count": self.warning_count,
            "missing_layers": list(self.missing_layers),
            "no_evidence": self.no_evidence,
            "sections_rendered": list(self.sections_rendered),
        }


@dataclass(frozen=True)
class RenderedBrief:
    """Phase 6C final output: deterministic Markdown + diagnostics."""

    markdown: str
    diagnostics: BriefDiagnostics = field(default_factory=BriefDiagnostics)
