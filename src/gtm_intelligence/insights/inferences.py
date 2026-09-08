"""Phase 6A §15–§20, §27, §35 — INFERENCE synthesis + validation.

INFERENCE synthesis: model combines FACTs + Signals into higher-order
inferences. Code validates support, inference distance, evidence scope,
and recommendation leakage.

Key rules:
  - Each inference needs >=1 supporting fact + >=1 supporting signal (§16)
  - Contradictory signals must be preserved (model input carries counter
    evidence; prompt instructs preservation; §17)
  - Weak signals need calibrated language (prompt; validator flags
    all-weak inferences for lower confidence; §18)
  - Inference distance: 0/1/2 for MVP (§27)
  - Evidence scope: can reference union of evidence from multiple
    facts and signals (§35)
  - No over-synthesis: don't merge unrelated signals (prompt; §20)

The model NEVER invents evidence, mints IDs, or generates recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import ModelResponse, ModelStatus
from .dtos import INFERENCE, FactDraft, InferenceDraft
from .facts import _detect_phase6a_leakage
from .ids import derive_insight_id
from .model import (
    INFERENCE_SYNTHESIS_RESPONSE_SCHEMA,
    PROMPT_VERSIONS,
    TASK_INFERENCE_SYNTHESIS,
)
from .prompts import get_insight_prompt


# --- confidence ceiling (§26, §27) -----------------------------------------

#: Per-inference-distance confidence discount (§27): a longer reasoning
#: leap permits less confidence than a direct abstraction, even when the
#: supporting facts are themselves high-confidence.
DISTANCE_DISCOUNT_STEP = 0.15


def inference_confidence_ceiling(
    fact_confidences: Iterable[float],
    inference_distance: int,
) -> float | None:
    """Maximum confidence an INFERENCE may carry (§26).

    ceiling = min(supporting fact confidences) * (1 - 0.15 * distance)

    Returns None when there are no supporting facts to bound against.
    A deterministic code-side cap: model confidence above the ceiling is
    clamped (with an explicit warning), never silently accepted (§32 —
    the clamp is reported, not hidden).
    """
    confs = [float(c) for c in fact_confidences]
    if not confs:
        return None
    base = min(confs)
    discount = max(0.0, 1.0 - DISTANCE_DISCOUNT_STEP * int(inference_distance))
    return max(0.0, min(1.0, base * discount))


# --- validation (§16, §27, §35) -------------------------------------------


def validate_inference(
    draft: InferenceDraft,
    *,
    valid_fact_ids: set[str],
    valid_signal_ids: set[str],
    evidence_by_id: Mapping[str, Any],
    fact_evidence_map: Mapping[str, set[str]],
    signal_evidence_map: Mapping[str, set[str]],
) -> list[str]:
    """Code-side INFERENCE guardrails (PRD §16, §27, §35).

    Returns a list of violation strings (empty = valid). Hallucinated
    refs are REJECTED — never stripped or repaired (§32: No Silent Repair).
    """
    violations: list[str] = []

    # 1. Statement non-empty
    if not draft.statement or not draft.statement.strip():
        violations.append("statement is empty")
        return violations

    # 2. ≥1 supporting fact (§16)
    if not draft.fact_ids:
        violations.append("inference has no supporting fact (§16: ≥1 required)")

    # 3. ≥1 supporting signal (§16)
    if not draft.signal_ids:
        violations.append("inference has no supporting signal (§16: ≥1 required)")

    # 4. fact_ids valid
    for fid in draft.fact_ids:
        if fid not in valid_fact_ids:
            violations.append(f"hallucinated fact_id: {fid}")

    # 5. signal_ids valid
    for sid in draft.signal_ids:
        if sid not in valid_signal_ids:
            violations.append(f"hallucinated signal_id: {sid}")

    # 6. evidence_ids valid
    for eid in draft.evidence_ids:
        if eid not in evidence_by_id:
            violations.append(f"hallucinated evidence_id: {eid}")

    # 7. Evidence scope (§35): evidence must be in the union of cited
    #    facts' and signals' evidence
    cited_evidence: set[str] = set()
    for fid in draft.fact_ids:
        if fid in fact_evidence_map:
            cited_evidence |= fact_evidence_map[fid]
    for sid in draft.signal_ids:
        if sid in signal_evidence_map:
            cited_evidence |= signal_evidence_map[sid]
    for eid in draft.evidence_ids:
        if eid in evidence_by_id and eid not in cited_evidence:
            violations.append(
                f"evidence {eid} does not belong to any cited fact or signal"
            )

    # 8. Inference distance 0-2 (§27)
    if draft.inference_distance < 0 or draft.inference_distance > 2:
        violations.append(
            f"inference_distance out of range (0-2): {draft.inference_distance}"
        )

    # 9. Confidence 0-1
    if draft.confidence < 0.0 or draft.confidence > 1.0:
        violations.append(f"confidence out of range: {draft.confidence}")

    # 10. Recommendation leakage (§28, §32)
    leakage = _detect_phase6a_leakage(draft.statement)
    if leakage:
        violations.append(f"recommendation leakage: {', '.join(leakage)}")

    return violations


# --- synthesis (§15, §19) --------------------------------------------------


@dataclass(frozen=True)
class InferenceSynthesisResult:
    """Output of synthesize_inferences()."""
    validated: tuple[InferenceDraft, ...] = ()
    rejected: tuple[InferenceDraft, ...] = ()
    insight_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: str = "success"

    def to_dict(self) -> dict:
        return {
            "validated": [d.to_dict() for d in self.validated],
            "rejected": [d.to_dict() for d in self.rejected],
            "insight_ids": list(self.insight_ids),
            "warnings": list(self.warnings),
            "model_status": self.model_status,
        }


def _build_inference_payload(
    facts: list[FactDraft],
    fact_insight_ids: list[str],
    prepared_signals: list,
) -> dict:
    """Build the minimal payload for the inference synthesis model call.

    Includes validated facts (with their insight_ids), prepared signals,
    and explicitly flags contradictory signals for preservation (§17).
    """
    facts_payload = [
        {
            "insight_id": fid,
            "statement": f.statement,
            "signal_ids": list(f.signal_ids),
            "evidence_ids": list(f.evidence_ids),
            "confidence": f.confidence,
        }
        for f, fid in zip(facts, fact_insight_ids)
    ]
    signals_payload = [ps.to_model_payload() for ps in prepared_signals]

    # Flag contradictory signals for the model to preserve (§17)
    contradictory_signal_ids = [
        ps.signal_id for ps in prepared_signals
        if ps.counter_evidence_summaries
    ]

    return {
        "facts": facts_payload,
        "signals": signals_payload,
        "contradictory_signal_ids": contradictory_signal_ids,
    }


def synthesize_inferences(
    facts: list[FactDraft],
    fact_insight_ids: list[str],
    prepared_signals: list,
    model,
    evidence_by_id: Mapping[str, Any],
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> InferenceSynthesisResult:
    """FACT[] + Signal[] → INFERENCE[] (PRD §15, §19).

    Calls the model with inference_synthesis task. Parses response into
    InferenceDraft objects. Validates each draft against support, evidence
    scope, inference distance, and recommendation leakage.
    """
    if not facts or not prepared_signals:
        return InferenceSynthesisResult()

    ctx = research_context or ResearchContext()
    valid_fact_ids = set(fact_insight_ids)
    valid_signal_ids = {ps.signal_id for ps in prepared_signals}
    fact_evidence_map = {
        fid: set(f.evidence_ids)
        for f, fid in zip(facts, fact_insight_ids)
    }
    signal_evidence_map = {ps.signal_id: set(ps.evidence_ids) for ps in prepared_signals}
    fact_confidence_by_id = {
        fid: f.confidence for f, fid in zip(facts, fact_insight_ids)
    }

    # Build cache key (§30: includes fact structural IDs)
    all_evidence_ids = set()
    for ps in prepared_signals:
        all_evidence_ids |= set(ps.evidence_ids)
    all_fact_ids = set(fact_insight_ids)

    key = build_cache_key(
        task=TASK_INFERENCE_SYNTHESIS,
        prompt_version=PROMPT_VERSIONS[TASK_INFERENCE_SYNTHESIS],
        model_id=model.model_id,
        evidence_ids=all_evidence_ids | all_fact_ids,
        research_context=ctx.to_dict(),
    )

    # Check cache
    if cache is not None:
        cached = cache.get(key)
        if cached is not None and cached.ok:
            return _parse_inference_response(
                cached, valid_fact_ids, valid_signal_ids,
                evidence_by_id, fact_evidence_map, signal_evidence_map,
                fact_confidence_by_id,
            )

    # Build payload
    payload = _build_inference_payload(facts, fact_insight_ids, prepared_signals)

    try:
        prompt = get_insight_prompt(TASK_INFERENCE_SYNTHESIS)
        payload["prompt"] = prompt.render()
    except (FileNotFoundError, KeyError):
        pass

    response = model.complete_structured(
        task=TASK_INFERENCE_SYNTHESIS,
        payload=payload,
        response_schema=INFERENCE_SYNTHESIS_RESPONSE_SCHEMA,
    )

    if cache is not None:
        cache.put(key, response)

    return _parse_inference_response(
        response, valid_fact_ids, valid_signal_ids,
        evidence_by_id, fact_evidence_map, signal_evidence_map,
        fact_confidence_by_id,
    )


def _parse_inference_response(
    response: ModelResponse,
    valid_fact_ids: set[str],
    valid_signal_ids: set[str],
    evidence_by_id: Mapping[str, Any],
    fact_evidence_map: Mapping[str, set[str]],
    signal_evidence_map: Mapping[str, set[str]],
    fact_confidence_by_id: Mapping[str, float] | None = None,
) -> InferenceSynthesisResult:
    """Parse model response into validated + rejected InferenceDrafts."""
    if not response.ok:
        return InferenceSynthesisResult(
            warnings=(f"inference_synthesis: model {response.status.value}: {response.error}",),
            model_status=response.status.value,
        )

    inferences_raw = response.payload.get("inferences") or []
    validated: list[InferenceDraft] = []
    rejected: list[InferenceDraft] = []
    insight_ids: list[str] = []
    warnings: list[str] = []

    for i, inf_raw in enumerate(inferences_raw):
        try:
            draft = InferenceDraft(
                statement=str(inf_raw.get("statement") or ""),
                fact_ids=tuple(str(f) for f in inf_raw.get("fact_ids") or []),
                signal_ids=tuple(str(s) for s in inf_raw.get("signal_ids") or []),
                evidence_ids=tuple(str(e) for e in inf_raw.get("evidence_ids") or []),
                confidence=float(inf_raw.get("confidence") or 0.0),
                rationale=str(inf_raw.get("rationale") or ""),
                # `or 1` would corrupt a legal distance of 0 → explicit default.
                inference_distance=(
                    int(inf_raw["inference_distance"])
                    if inf_raw.get("inference_distance") is not None else 1
                ),
            )
        except (TypeError, ValueError) as exc:
            warnings.append(f"inference_synthesis: draft {i} parse error: {exc}")
            continue

        violations = validate_inference(
            draft,
            valid_fact_ids=valid_fact_ids,
            valid_signal_ids=valid_signal_ids,
            evidence_by_id=evidence_by_id,
            fact_evidence_map=fact_evidence_map,
            signal_evidence_map=signal_evidence_map,
        )
        if violations:
            rejected.append(draft)
            warnings.append(
                f"inference_synthesis: rejected draft (statement={draft.statement[:60]}...): "
                f"{'; '.join(violations)}"
            )
        else:
            # §26: clamp confidence to the supporting-fact ceiling. The
            # clamp is EXPLICIT (warning), not a silent repair (§32).
            fact_confidences = [
                conf for fid in draft.fact_ids
                if (conf := (fact_confidence_by_id or {}).get(fid)) is not None
            ]
            ceiling = inference_confidence_ceiling(
                fact_confidences, draft.inference_distance
            )
            if ceiling is not None and draft.confidence > ceiling:
                warnings.append(
                    f"inference_synthesis: confidence capped from {draft.confidence:.4f} "
                    f"to {ceiling:.4f} (supporting-fact ceiling, distance="
                    f"{draft.inference_distance})"
                )
                draft = replace(draft, confidence=ceiling)
            validated.append(draft)
            ins_id = derive_insight_id(
                type=INFERENCE,
                signal_ids=draft.signal_ids,
                evidence_ids=draft.evidence_ids,
            )
            insight_ids.append(ins_id)

    status = "success"
    if rejected and not validated:
        status = "invalid_output"
    elif rejected:
        status = "partial"

    return InferenceSynthesisResult(
        validated=tuple(validated),
        rejected=tuple(rejected),
        insight_ids=tuple(insight_ids),
        warnings=tuple(warnings),
        model_status=status,
    )
