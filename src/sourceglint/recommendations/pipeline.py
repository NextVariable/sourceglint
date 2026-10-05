"""Phase 6B §6, §30, §31 — the Recommendation pipeline orchestrator.

Validated FACT/INFERENCE Insights
  → generate_candidate_recommendations()   (model + code)
  → assess_recommendations()               (model + code)
  → deduplicate_recommendations()          (code + model semantic groups)
  → detect_conflicts()                     (model + code)
  → build recommendation dicts (type=RECOMMENDATION, frozen schema)
  → RecommendationPipelineResult

Failure semantics (§31-style): generation failure with zero validated
candidates → empty result; per-candidate assessment failure drops that
candidate only; dedup/conflict model failure degrades (structural dedup
still runs, conflicts skipped). No silent repair anywhere (§32).

STOP BOUNDARY (§48): output is a Recommendation Set only.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..intelligence.cache import SemanticCache
from ..intelligence.dtos import ResearchContext
from ..insights.validation import (
    validate_insight_schema,
)
from .assess import AssessedRecommendation, assess_recommendations
from .conflicts import detect_conflicts
from .dedup import deduplicate_recommendations
from .dtos import (
    RecommendationDiagnostics,
    RecommendationPipelineResult,
)
from .generate import generate_candidate_recommendations
from .policy import MAX_CANDIDATES

_REC_TYPE = "RECOMMENDATION"


def _filter_insights(
    insights: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict], list[str]]:
    """Keep FACT/INFERENCE insight dicts keyed by insight_id."""
    by_id: dict[str, dict] = {}
    warnings: list[str] = []
    for ins in insights:
        iid = str(ins.get("insight_id") or "")
        if not iid:
            warnings.append("insight without insight_id skipped")
            continue
        ins_type = str(ins.get("type") or "")
        if ins_type not in ("FACT", "INFERENCE"):
            warnings.append(
                f"insight {iid}: type {ins_type!r} not usable for recommendations"
            )
            continue
        by_id[iid] = dict(ins)
    return by_id, warnings


def _to_diag_map(
    insight_diagnostics: Mapping[str, Any] | Sequence[Any] | None,
) -> Mapping[str, Mapping[str, Any]]:
    """Normalize the optional 6A diagnostics into {insight_id: diag dict}.

    Accepts either a mapping (id → dict/object) or a sequence of objects
    with to_dict()/attributes (e.g. InsightDiagnostics)."""
    if insight_diagnostics is None:
        return {}
    if isinstance(insight_diagnostics, Mapping):
        out: dict[str, Mapping[str, Any]] = {}
        for iid, diag in insight_diagnostics.items():
            if hasattr(diag, "to_dict"):
                diag = diag.to_dict()
            out[str(iid)] = dict(diag)
        return out
    # Sequence of diagnostics objects
    out = {}
    for diag in insight_diagnostics:
        if hasattr(diag, "to_dict"):
            d = diag.to_dict()
        elif isinstance(diag, Mapping):
            d = dict(diag)
        else:  # pragma: no cover
            continue
        iid = str(d.get("insight_id") or "")
        if iid:
            out[iid] = d
    return out


def _build_rec_dict(assessed: AssessedRecommendation) -> dict:
    """Build a recommendation dict conforming to insight.schema.json."""
    draft = assessed.draft
    rec: dict[str, Any] = {
        "insight_id": assessed.insight_id,
        "type": _REC_TYPE,
        "statement": draft.statement,
        "confidence": assessed.confidence,
        "action": {
            "action": draft.action,
            "priority": assessed.priority_bucket,
        },
    }
    if draft.rationale:
        rec["rationale"] = draft.rationale
    return rec


def _build_diagnostics(
    assessed: AssessedRecommendation,
    *,
    conflict_group_ids: Mapping[str, str],
    collapsed_duplicate_ids: Sequence[str] = (),
) -> RecommendationDiagnostics:
    draft = assessed.draft
    return RecommendationDiagnostics(
        insight_id=assessed.insight_id,
        supporting_insight_ids=draft.supporting_insight_ids,
        supporting_signal_ids=assessed.supporting_signal_ids,
        supporting_evidence_ids=assessed.supporting_evidence_ids,
        gtm_dimensions=draft.gtm_dimensions,
        action_class=draft.action_class,
        action_distance=assessed.action_distance,
        reversibility=assessed.reversibility,
        priority=assessed.priority,
        priority_bucket=assessed.priority_bucket,
        risk_factors=dict(assessed.risk_factors),
        overall_risk=assessed.overall_risk,
        support=assessed.support,
        weak_signal_present=assessed.weak_signal_present,
        contradiction_present=assessed.contradiction_present,
        conflict_group_id=conflict_group_ids.get(assessed.insight_id, ""),
        collapsed_duplicate_ids=tuple(collapsed_duplicate_ids),
        warnings=assessed.warnings,
    )


def run_recommendation_pipeline(
    insights: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Any],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
    insight_diagnostics: Mapping[str, Any] | Sequence[Any] | None = None,
    max_candidates: int = MAX_CANDIDATES,
    target_entity: str = "",
) -> RecommendationPipelineResult:
    """Run the full Insight → Recommendation pipeline (Phase 6B)."""
    warnings: list[str] = []
    insight_by_id, filter_warnings = _filter_insights(insights)
    warnings.extend(filter_warnings)
    if not insight_by_id:
        warnings.append("recommendation: no FACT/INFERENCE insights to act on")
        return RecommendationPipelineResult(warnings=tuple(warnings))

    ctx = research_context or ResearchContext()
    diag_map = _to_diag_map(insight_diagnostics)

    # 1. Candidate generation (model) + code validation (§10, §32)
    gen = generate_candidate_recommendations(
        list(insight_by_id.values()),
        model,
        evidence_by_id,
        research_context=ctx,
        cache=cache,
        insight_diagnostics=diag_map,
        max_candidates=max_candidates,
        target_entity=target_entity,
    )
    warnings.extend(gen.warnings)
    if not gen.validated:
        warnings.append("recommendation_generation: no valid candidates")
        return RecommendationPipelineResult(
            warnings=tuple(warnings),
            model_status={"generation": gen.model_status},
        )

    # 2. Assessment + deterministic scoring (§14, §20–§22)
    assess_result = assess_recommendations(
        list(gen.validated),
        model,
        insight_by_id=insight_by_id,
        evidence_by_id=evidence_by_id,
        research_context=ctx,
        cache=cache,
        insight_diagnostics=diag_map,
    )
    warnings.extend(assess_result.warnings)
    if not assess_result.assessed:
        warnings.append("recommendation_assessment: no assessed candidates")
        return RecommendationPipelineResult(
            warnings=tuple(warnings),
            model_status={
                "generation": gen.model_status,
                "assessment": assess_result.model_status,
            },
        )

    # 3. Dedup — structural + semantic (§28)
    dedup_result = deduplicate_recommendations(
        list(assess_result.assessed),
        model,
        research_context=ctx,
        cache=cache,
    )
    warnings.extend(dedup_result.warnings)
    survivors = list(dedup_result.kept)

    # Attach collapsed duplicate ids to winners' diagnostics.
    collapsed_by_winner: dict[str, tuple[str, ...]] = {}
    for group in dedup_result.collapsed:
        if group:
            collapsed_by_winner[group[0]] = group[1:]

    # 4. Conflict detection (§29, §30)
    conflict_result = detect_conflicts(
        survivors, model, research_context=ctx, cache=cache
    )
    warnings.extend(conflict_result.warnings)
    conflicts = list(conflict_result.conflicts)

    conflict_group_ids: dict[str, str] = {}
    for conf in conflicts:
        for rid in conf.rec_ids:
            conflict_group_ids[rid] = conf.group_id

    # 5. Build frozen-schema dicts + deterministic ordering
    #    Order: priority desc, then insight_id asc (stable, deterministic).
    ordered = sorted(
        survivors, key=lambda a: (-a.priority, a.insight_id)
    )

    rec_dicts: list[dict] = []
    diagnostics: list[RecommendationDiagnostics] = []
    for assessed in ordered:
        rec = _build_rec_dict(assessed)
        violations = validate_insight_schema(rec)
        if violations:
            warnings.append(
                f"recommendation schema: {assessed.insight_id}: "
                f"{'; '.join(violations)}"
            )
            continue
        rec_dicts.append(rec)
        diag = _build_diagnostics(
            assessed,
            conflict_group_ids=conflict_group_ids,
            collapsed_duplicate_ids=collapsed_by_winner.get(assessed.insight_id, ()),
        )
        diagnostics.append(diag)

    # 6. Model status
    model_status = {
        "generation": gen.model_status,
        "assessment": assess_result.model_status,
        "dedup": _dedup_status(dedup_result),
        "conflict": conflict_result.model_status,
    }

    return RecommendationPipelineResult(
        recommendations=tuple(rec_dicts),
        diagnostics=tuple(diagnostics),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        model_status=model_status,
    )


def _dedup_status(dedup_result) -> str:
    if dedup_result.warnings:
        for w in dedup_result.warnings:
            if "skipped" in w or "model " in w:
                return "partial"
    return "success"
