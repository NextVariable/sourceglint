"""Phase 7 §17–§19 — full-stack application orchestrator (compose only).

Composes Phase 3 → Phase 6C into one canonical run. Pure composition:
no scoring, clustering, insight, recommendation or rendering logic lives
here — each stage is an existing module call with validated hand-off.

Stage failure semantics (§19):
  * research all-sources-failed -> structured FAILED (no silent empty)
  * research partial           -> continue, PARTIAL
  * no usable evidence         -> NO_EVIDENCE result (brief still says so)
  * signals empty              -> brief degrades (no signals note)
  * insights empty             -> signals + coverage still render
  * recommendations empty      -> FACT/INFERENCE still render
A downstream stage NEVER discards upstream results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..brief.dtos import BriefContext, BriefInput
from ..brief.pipeline import run_brief_pipeline
from ..insights.pipeline import run_insight_pipeline
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import IntelligencePipelineError
from ..intelligence.pipeline import run_intelligence_pipeline
from ..ledger import EvidenceLedger
from ..pipeline.degradation import AllSourcesFailedError
from ..pipeline.orchestrator import ResearchPipeline, ResearchPipelineResult
from ..recommendations.pipeline import run_recommendation_pipeline

STAGE_OK = "ok"
STAGE_NONE = "none"
STAGE_DEGRADED = "degraded"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"


def _stage(value: str) -> str:
    return value


@dataclass(frozen=True)
class ApplicationResult:
    """One full engine run's outcome (pre-SkillResult packaging)."""

    status: str  # SUCCESS | PARTIAL | NO_EVIDENCE | FAILED  (see interface.Status)
    brief: Any = None  # RenderedBrief | None
    evidence_count: int = 0
    signal_count: int = 0
    insight_count: int = 0
    recommendation_count: int = 0
    coverage: Any = None
    warnings: tuple[str, ...] = ()
    stage_statuses: Mapping[str, str] = field(default_factory=dict)
    signals: tuple[dict, ...] = ()
    insights: tuple[dict, ...] = ()
    recommendations: tuple[dict, ...] = ()

    @property
    def markdown(self) -> str:
        return self.brief.markdown if self.brief is not None else ""


def build_research_context(
    plan: Mapping[str, Any],
    *,
    languages: tuple[str, ...] = (),
) -> ResearchContext:
    """Map a research_plan dict onto the Phase 5 ResearchContext DTO."""
    return ResearchContext(
        mode=str(plan.get("mode") or "general"),
        entities=tuple(str(e) for e in (plan.get("entities") or [])),
        market=str(plan.get("market") or "global"),
        decision_context=str(plan.get("decision_context") or ""),
        languages=tuple(languages or (plan.get("languages") or ["en"])),
    )


def _evidence_by_id(ledger: EvidenceLedger) -> dict[str, Mapping[str, Any]]:
    """eid -> full payload map for the 6A/6B evidence contracts."""
    return {r.evidence_id: r.to_payload() for r in ledger}


def _weak_signal_ids(signal_diagnostics: Sequence[Any]) -> set[str]:
    """Signal ids whose Phase 5 assessment flags a weak candidate."""
    out: set[str] = set()
    for d in signal_diagnostics:
        weak = getattr(d, "weak_signal", None)
        if weak is not None and bool(getattr(weak, "is_weak_candidate", False)):
            out.add(str(getattr(d, "signal_id", "")))
    return out


def _run_insights(
    signals: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    model: Any,
    *,
    research_context: ResearchContext,
    cache: Any,
    weak_signal_ids: set[str],
) -> tuple[Any, list[str]]:
    """Phase 6A. Raises nothing for ordinary emptiness (pipeline returns
    an empty result with warnings)."""
    warnings: list[str] = []
    result = run_insight_pipeline(
        signals,
        evidence_by_id,
        model,
        research_context=research_context,
        cache=cache,
        weak_signal_ids=weak_signal_ids,
    )
    warnings.extend(f"insights: {w}" for w in result.warnings)
    return result, warnings


def _run_recommendations(
    insights: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    model: Any,
    *,
    research_context: ResearchContext,
    cache: Any,
    insight_diagnostics: Sequence[Any],
    target_entity: str,
) -> tuple[Any, list[str]]:
    warnings: list[str] = []
    result = run_recommendation_pipeline(
        insights,
        evidence_by_id,
        model,
        research_context=research_context,
        cache=cache,
        insight_diagnostics=insight_diagnostics,
        target_entity=target_entity,
    )
    warnings.extend(f"recommendations: {w}" for w in result.warnings)
    return result, warnings


@dataclass(frozen=True)
class OrchestrationContext:
    """Injected runtime wiring for one application run (§15, §45)."""

    research: ResearchPipeline  # Phase 3 orchestrator (adapters + config + cache)
    model: Any  # host-injected union model (Phase 5 / 6A / 6B boundary)
    as_of: datetime
    ledger: EvidenceLedger = field(default_factory=lambda: EvidenceLedger(":memory:"))
    semantic_cache: Any = None
    drop_baseline_only: bool = True


def orchestrate(
    parsed: Any,
    *,
    plan: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    ctx: OrchestrationContext,
    target_entity: str = "",
) -> ApplicationResult:
    """Run the canonical full pipeline for one parsed request.

    ``sources`` is the source-registry payload (list of entries) that the
    ResearchPipeline validates and the adapter factory resolves.
    """
    warnings: list[str] = []
    stage: dict[str, str] = {}
    research_ctx = build_research_context(
        plan, languages=tuple(parsed.languages)
    )

    # ---- Phase 3: research (evidence + coverage) -------------------------
    try:
        research_result: ResearchPipelineResult = ctx.research.run(
            plan=plan,
            sources=sources,
            ledger=ctx.ledger,
        )
    except AllSourcesFailedError as exc:
        stage["research"] = STAGE_FAILED
        warnings.append(
            "research: all sources failed — no usable evidence retrieved"
        )
        for rep in exc.per_source.values():  # pragma: no cover - defensive
            for w in getattr(rep, "warnings", []):
                warnings.append(f"research:{rep.source}: {w}")
        return ApplicationResult(
            status="FAILED",
            evidence_count=0,
            warnings=tuple(warnings),
            stage_statuses=stage,
        )

    evidence_count = research_result.coverage.final_evidence_count
    stage["research"] = (
        STAGE_DEGRADED
        if research_result.coverage.failed_sources
        else STAGE_OK
    )
    warnings.extend(f"research: {w}" for w in research_result.warnings)
    warnings.extend(
        f"research:{name}: {w}"
        for name, rep in research_result.source_statuses.items()
        for w in rep.warnings
    )

    # No-evidence guard (§19, §20): report cleanly, do not fabricate.
    if evidence_count == 0:
        brief = _render_empty_brief(parsed, research_result, ctx.ledger, ctx.as_of)
        return ApplicationResult(
            status="NO_EVIDENCE",
            brief=brief,
            evidence_count=0,
            coverage=research_result.coverage,
            warnings=tuple(warnings),
            stage_statuses={
                "research": stage["research"],
                "signals": STAGE_SKIPPED,
                "insights": STAGE_SKIPPED,
                "recommendations": STAGE_SKIPPED,
                "brief": STAGE_OK,
            },
        )

    # ---- Phase 5: signals -------------------------------------------------
    try:
        signal_result = run_intelligence_pipeline(
            ctx.ledger,
            ctx.model,
            as_of=ctx.as_of,
            research_context=research_ctx,
            cache=ctx.semantic_cache,
            drop_baseline_only=ctx.drop_baseline_only,
        )
    except IntelligencePipelineError as exc:
        warnings.append(f"signals: {exc}")
        brief = _render_without_signals(parsed, research_result, ctx.ledger, ctx.as_of)
        return ApplicationResult(
            status="PARTIAL",
            brief=brief,
            evidence_count=evidence_count,
            coverage=research_result.coverage,
            warnings=tuple(warnings),
            stage_statuses={
                **stage,
                "signals": STAGE_FAILED,
                "insights": STAGE_SKIPPED,
                "recommendations": STAGE_SKIPPED,
                "brief": STAGE_OK,
            },
        )
    warnings.extend(f"signals: {w}" for w in signal_result.warnings)
    signals = signal_result.signals
    stage["signals"] = STAGE_DEGRADED if not signals else STAGE_OK

    if not signals:
        brief = _render_without_signals(parsed, research_result, ctx.ledger, ctx.as_of)
        return ApplicationResult(
            status="PARTIAL",
            brief=brief,
            evidence_count=evidence_count,
            signal_count=0,
            coverage=research_result.coverage,
            warnings=tuple(warnings),
            stage_statuses={
                **stage,
                "insights": STAGE_SKIPPED,
                "recommendations": STAGE_SKIPPED,
                "brief": STAGE_OK,
            },
        )

    # ---- Phase 6A: FACT / INFERENCE insights ------------------------------
    evidence_by_id = _evidence_by_id(ctx.ledger)
    weak_ids = _weak_signal_ids(signal_result.diagnostics)
    insight_result, ins_warnings = _run_insights(
        signals,
        evidence_by_id,
        ctx.model,
        research_context=research_ctx,
        cache=ctx.semantic_cache,
        weak_signal_ids=weak_ids,
    )
    warnings.extend(ins_warnings)
    insights = insight_result.insights
    stage["insights"] = STAGE_DEGRADED if not insights else STAGE_OK

    # ---- Phase 6B: recommendations ----------------------------------------
    if not insights:
        brief = _render_insights_only(
            parsed, research_result, ctx.ledger, ctx.as_of, signals, ()
        )
        return ApplicationResult(
            status="PARTIAL",
            brief=brief,
            evidence_count=evidence_count,
            signal_count=len(signals),
            insight_count=0,
            coverage=research_result.coverage,
            warnings=tuple(warnings),
            stage_statuses={
                **stage,
                "recommendations": STAGE_SKIPPED,
                "brief": STAGE_OK,
            },
        )

    rec_result, rec_warnings = _run_recommendations(
        insights,
        evidence_by_id,
        ctx.model,
        research_context=research_ctx,
        cache=ctx.semantic_cache,
        insight_diagnostics=insight_result.diagnostics,
        target_entity=target_entity,
    )
    warnings.extend(rec_warnings)
    recommendations = rec_result.recommendations
    stage["recommendations"] = STAGE_DEGRADED if not recommendations else STAGE_OK

    # ---- Phase 6C: brief ----------------------------------------------------
    diag_by_id = {
        d.insight_id: d.to_dict()
        for d in insight_result.diagnostics
        if hasattr(d, "to_dict")
    }
    rec_diag_by_id = {
        d.insight_id: d.to_dict()
        for d in rec_result.diagnostics
        if hasattr(d, "to_dict")
    }
    brief = _compose_brief(
        parsed,
        research_result,
        ctx.ledger,
        ctx.as_of,
        signals,
        insights,
        recommendations,
        diag_by_id,
        rec_diag_by_id,
        rec_result.conflicts,
    )

    status = "PARTIAL" if research_result.coverage.failed_sources else "SUCCESS"
    stage["brief"] = STAGE_OK
    return ApplicationResult(
        status=status,
        brief=brief,
        evidence_count=evidence_count,
        signal_count=len(signals),
        insight_count=len(insights),
        recommendation_count=len(recommendations),
        coverage=research_result.coverage,
        warnings=tuple(warnings),
        stage_statuses=stage,
        signals=tuple(signals),
        insights=tuple(insights),
        recommendations=tuple(recommendations),
    )


# ------------------------------------------------------------- brief helpers

def _brief_input(
    parsed: Any,
    *,
    coverage: Any,
    ledger: Any,
    as_of: datetime,
    signals: Sequence[Mapping[str, Any]] = (),
    insights: Sequence[Mapping[str, Any]] = (),
    recommendations: Sequence[Mapping[str, Any]] = (),
    insight_diagnostics: Mapping[str, Any] | None = None,
    recommendation_diagnostics: Mapping[str, Any] | None = None,
    conflicts: Sequence[Any] = (),
) -> BriefInput:
    return BriefInput(
        context=BriefContext(
            query=parsed.query,
            topic=getattr(parsed, "topic", ""),
            mode=parsed.mode,
            market=parsed.market,
            languages=tuple(parsed.languages),
            time_window=parsed.time_window_text,
            as_of=as_of.date().isoformat() if as_of.tzinfo is not None
            else as_of.isoformat(),
            entities=tuple(parsed.entities),
            decision_context=parsed.decision_context,
        ),
        ledger=ledger,
        signals=tuple(signals),
        insights=tuple(insights),
        recommendations=tuple(recommendations),
        insight_diagnostics=insight_diagnostics or {},
        recommendation_diagnostics=recommendation_diagnostics or {},
        conflicts=tuple(conflicts),
        coverage=coverage,
    )


def _compose_brief(
    parsed: Any,
    research_result: ResearchPipelineResult,
    ledger: Any,
    as_of: datetime,
    signals: Sequence[Mapping[str, Any]],
    insights: Sequence[Mapping[str, Any]],
    recommendations: Sequence[Mapping[str, Any]],
    insight_diagnostics: Mapping[str, Any],
    recommendation_diagnostics: Mapping[str, Any],
    conflicts: Sequence[Any],
) -> Any:
    brief_input = _brief_input(
        parsed,
        coverage=research_result.coverage,
        ledger=ledger,
        as_of=as_of,
        signals=signals,
        insights=insights,
        recommendations=recommendations,
        insight_diagnostics=insight_diagnostics,
        recommendation_diagnostics=recommendation_diagnostics,
        conflicts=conflicts,
    )
    return run_brief_pipeline(brief_input)


def _render_empty_brief(
    parsed: Any, research_result: ResearchPipelineResult, ledger: Any, as_of: datetime
) -> Any:
    return run_brief_pipeline(
        _brief_input(
            parsed, coverage=research_result.coverage, ledger=ledger, as_of=as_of
        )
    )


def _render_without_signals(
    parsed: Any, research_result: ResearchPipelineResult, ledger: Any, as_of: datetime
) -> Any:
    return run_brief_pipeline(
        _brief_input(
            parsed, coverage=research_result.coverage, ledger=ledger, as_of=as_of
        )
    )


def _render_insights_only(
    parsed: Any,
    research_result: ResearchPipelineResult,
    ledger: Any,
    as_of: datetime,
    signals: Sequence[Mapping[str, Any]],
    insights: Sequence[Mapping[str, Any]],
) -> Any:
    return run_brief_pipeline(
        _brief_input(
            parsed,
            coverage=research_result.coverage,
            ledger=ledger,
            as_of=as_of,
            signals=signals,
            insights=insights,
        )
    )
