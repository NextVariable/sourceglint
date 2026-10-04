"""Phase 7 §15–§16, §22 — canonical public entry point.

``run_sourceglint(...)`` is THE single public API. Hosts, the CLI
and the Skill runtime all call exactly this function (Gate F). It:

    natural-language query
    -> SkillRequest normalization (interface.request)
    -> deterministic parsing (interface.parser)
    -> full-stack application orchestration (application.orchestrator)
    -> SkillResult (interface.result)

The pipeline composition is delegated — this module only wires the
runtime (model + adapters + registry) and packages the result.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..interface.parser import parse_request
from ..interface.request import MODES, SkillRequest
from ..interface.result import SkillResult, Status
from ..ledger import EvidenceLedger
from .orchestrator import OrchestrationContext, orchestrate
from .runtime import default_adapter_factory, default_sources

# Re-export the pipeline types callers need to construct offline runs.
from ..pipeline.orchestrator import PipelineConfig, ResearchPipeline

__all__ = ["run_sourceglint"]


def _to_iso(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def run_sourceglint(
    query: str,
    *,
    # --- optional request overrides (empty => parsed from the query) -----
    mode: str = "",
    market: str = "",
    window_days: int | None = None,
    languages: Sequence[str] = (),
    entities: Sequence[str] = (),
    target: str = "",
    baseline: bool = False,
    decision_support: bool = False,
    source_preferences: Sequence[str] = (),
    decision_context: str = "",
    # --- runtime injection (host-neutral) --------------------------------
    model: Any = None,
    adapter_factory: Any = None,
    sources: Sequence[Mapping[str, Any]] | None = None,
    retrieval_cache: Any = None,
    semantic_cache: Any = None,
    as_of: datetime | str | None = None,
    ledger: Any = None,
) -> SkillResult:
    """Run the canonical sourceglint pipeline for one request.

    ``query`` is required; ``model`` is required (host-injected union
    model implementing the Phase 5/6A/6B complete_structured contract).
    ``adapter_factory`` and ``sources`` default to the repository
    registry wiring; inject fakes for offline/deterministic runs.
    """
    if not query or not str(query).strip():
        raise ValueError("query is required and non-empty")
    if model is None:
        raise ValueError(
            "run_sourceglint requires a host-injected model "
            "(IntelligenceModel protocol). The core is host-neutral; no "
            "vendor client is bundled."
        )
    if mode and mode not in MODES:
        raise ValueError(f"mode must be one of {MODES!r}; got {mode!r}")
    if baseline:
        raise ValueError(
            "prior-window retrieval is not wired in the public runtime; "
            "baseline comparisons are not yet available"
        )

    # 1) Normalize + parse.
    request = SkillRequest(
        query=str(query),
        mode=mode,
        market=market,
        window_days=window_days,
        languages=tuple(languages),
        entities=tuple(entities),
        target=target,
        baseline=baseline,
        source_preferences=tuple(source_preferences),
        decision_context=decision_context,
    )
    parsed = parse_request(request)

    if parsed.needs_clarification:
        return SkillResult(
            status=Status.FAILED,
            request=parsed,
            warnings=(parsed.clarification_reason,),
            stage_statuses={"parse": "needs_clarification"},
        )

    # 2) Wire the runtime.
    if as_of is None:
        raise ValueError("as_of is required; the host must supply the run timestamp")
    as_of_dt = _to_iso(as_of)
    source_list = list(sources) if sources is not None else default_sources()
    factory = adapter_factory or default_adapter_factory
    research = ResearchPipeline(
        config=PipelineConfig(as_of=as_of_dt.isoformat(), cache=retrieval_cache),
        adapter_factory=factory,
    )
    ctx = OrchestrationContext(
        research=research,
        model=model,
        as_of=as_of_dt,
        ledger=ledger if ledger is not None else EvidenceLedger(":memory:"),
        semantic_cache=semantic_cache,
    )

    # 3) Run the full engine.
    outcome = orchestrate(
        parsed,
        plan=parsed.to_plan(),
        sources=source_list,
        ctx=ctx,
        target_entity=target or parsed.target,
        include_recommendations=decision_support,
    )

    # 4) Package.
    diagnostics: dict[str, Any] = {
        "evidence_count": outcome.evidence_count,
        "signal_count": outcome.signal_count,
        "insight_count": outcome.insight_count,
        "recommendation_count": outcome.recommendation_count,
    }
    if outcome.coverage is not None:
        diagnostics["coverage"] = outcome.coverage.to_dict()
    return SkillResult(
        status=Status(outcome.status),
        brief_markdown=outcome.markdown,
        request=parsed,
        research_plan=parsed.to_plan(),
        warnings=outcome.warnings,
        stage_statuses=outcome.stage_statuses,
        diagnostics=diagnostics,
    )
