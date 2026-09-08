"""Phase 6A §8, §31 — the insight pipeline orchestrator.

Signal Set
  → prepare_signals()           preparation.py     (code)
  → synthesize_facts()          facts.py           (model + code)
  → synthesize_inferences()     inferences.py      (model + code)
  → derive_gtm_implications()   gtm_implications.py (model + code)
  → deduplicate_insights()      dedup.py           (code)
  → validate_insight_schema()   validation.py      (code gate)
  → InsightPipelineResult

Determinism: insight IDs are code-derived; output ordering is
insight_id ascending, never model order. Failure semantics (PRD §31):
fact synthesis failure → pipeline fails; inference failure → facts
still returned (partial); gtm failure → insights still returned.

STOP BOUNDARY (PRD §48): output is FACT + INFERENCE only. No
RECOMMENDATION, no action, no final brief.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..intelligence.cache import SemanticCache
from ..intelligence.dtos import ResearchContext
from .dedup import deduplicate_insights
from .dtos import FACT, INFERENCE, InsightDiagnostics, InsightPipelineResult
from .facts import FactSynthesisResult, synthesize_facts
from .gtm_implications import derive_gtm_implications
from .inferences import InferenceSynthesisResult, synthesize_inferences
from .preparation import prepare_signals
from .support import compute_support_strength, distinct_source_count
from .validation import validate_insight_schema

_FACT_STAGE = "fact_synthesis"
_INFERENCE_STAGE = "inference_synthesis"
_GTM_STAGE = "gtm_implications"


def run_insight_pipeline(
    signals: Iterable[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
    weak_signal_ids: set[str] | None = None,
) -> InsightPipelineResult:
    """Run the full Signal → FACT → INFERENCE → Insight pipeline (Phase 6A).

    Returns an InsightPipelineResult. Does NOT produce RECOMMENDATIONs
    or final briefs (PRD §48 stop boundary).
    """
    warnings: list[str] = []

    # 1. Prepare signals
    prepared, prep_warnings = prepare_signals(
        signals, evidence_by_id, weak_signal_ids=weak_signal_ids
    )
    warnings.extend(f"prepare: {w}" for w in prep_warnings)
    if not prepared:
        warnings.append("prepare: no signals to analyze")
        return InsightPipelineResult(warnings=tuple(warnings))

    ctx = research_context or ResearchContext()

    # 2. Synthesize facts
    fact_result = synthesize_facts(
        prepared, model, evidence_by_id,
        research_context=ctx, cache=cache,
    )
    warnings.extend(fact_result.warnings)
    if not fact_result.validated:
        warnings.append("fact_synthesis: no valid facts produced")
        # Facts are required for inferences; but we still return empty
        return InsightPipelineResult(
            warnings=tuple(warnings),
            model_status={_FACT_STAGE: fact_result.model_status},
        )

    # 3. Synthesize inferences
    inference_result = synthesize_inferences(
        list(fact_result.validated), list(fact_result.insight_ids),
        prepared, model, evidence_by_id,
        research_context=ctx, cache=cache,
    )
    warnings.extend(inference_result.warnings)

    # 4. Derive GTM implications (for each validated fact + inference)
    fact_insights = [
        (f, fid, FACT)
        for f, fid in zip(fact_result.validated, fact_result.insight_ids)
    ]
    inference_insights = [
        (inf, iid, INFERENCE)
        for inf, iid in zip(inference_result.validated, inference_result.insight_ids)
    ]
    all_insights = fact_insights + inference_insights

    gtm_result = derive_gtm_implications(
        all_insights, model, research_context=ctx, cache=cache,
    )
    warnings.extend(gtm_result.warnings)

    # 5. Build insight dicts (conforming to insight.schema.json)
    gtm_map = {gi.insight_id: gi.implications for gi in gtm_result.implications}
    insight_dicts: list[dict] = []
    for draft, ins_id, ins_type in all_insights:
        ins_dict: dict[str, Any] = {
            "insight_id": ins_id,
            "type": ins_type,
            "statement": draft.statement,
            "signal_ids": list(draft.signal_ids),
            "evidence_ids": list(draft.evidence_ids),
            "confidence": draft.confidence,
        }
        if ins_id in gtm_map:
            implications = gtm_map[ins_id]
            if implications:
                ins_dict["gtm_implications"] = dict(implications)
        if draft.rationale:
            ins_dict["rationale"] = draft.rationale
        insight_dicts.append(ins_dict)

    # 6. Deduplicate
    dedup_result = deduplicate_insights(insight_dicts)
    warnings.extend(dedup_result.warnings)

    # 7. Validate schema (code gate)
    validated_insights: list[dict] = []
    for ins_dict in dedup_result.kept:
        violations = validate_insight_schema(ins_dict)
        if violations:
            warnings.append(
                f"schema: {ins_dict.get('insight_id')}: "
                f"{'; '.join(violations)}"
            )
        else:
            validated_insights.append(ins_dict)

    # 8. Deterministic order: insight_id ascending
    validated_insights.sort(key=lambda i: str(i.get("insight_id") or ""))

    # 9. Build diagnostics (§16, §26, §35)
    diagnostics: list[InsightDiagnostics] = []
    for ins_dict in validated_insights:
        ins_type = ins_dict["type"]
        signal_ids = tuple(ins_dict.get("signal_ids") or ())
        evidence_ids = tuple(ins_dict.get("evidence_ids") or ())
        supporting_facts: tuple[str, ...] = ()
        inference_distance = 0
        if ins_type == INFERENCE:
            # Find the inference draft to get fact_ids + distance
            for inf_draft, iid in zip(inference_result.validated, inference_result.insight_ids):
                if iid == ins_dict["insight_id"]:
                    supporting_facts = inf_draft.fact_ids
                    inference_distance = inf_draft.inference_distance
                    break
        weak = any(ps.weak_signal for ps in prepared if ps.signal_id in set(signal_ids))
        contradiction = any(
            bool(ps.counter_evidence_summaries)
            for ps in prepared if ps.signal_id in set(signal_ids)
        )
        support_strength = compute_support_strength(
            insight_type=ins_type,
            n_signals=len(signal_ids),
            n_evidence=len(evidence_ids),
            n_sources=distinct_source_count(evidence_ids, evidence_by_id),
            n_facts=len(supporting_facts),
            contradiction_preserved=contradiction,
            weak_signal=weak,
        )
        diagnostics.append(InsightDiagnostics(
            insight_id=ins_dict["insight_id"],
            type=ins_type,
            support_strength=support_strength,
            inference_distance=inference_distance,
            supporting_fact_ids=supporting_facts,
            supporting_signal_ids=signal_ids,
            supporting_evidence_ids=evidence_ids,
            weak_signal=weak,
            contradiction_preserved=contradiction,
        ))

    # 10. Model status
    model_status = {
        _FACT_STAGE: fact_result.model_status,
        _INFERENCE_STAGE: inference_result.model_status,
        _GTM_STAGE: gtm_result.model_status,
    }

    return InsightPipelineResult(
        insights=tuple(validated_insights),
        diagnostics=tuple(diagnostics),
        warnings=tuple(warnings),
        model_status=model_status,
    )
