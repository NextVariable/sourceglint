"""Phase 6A §11–§14, §32, §34 — FACT synthesis + grounding validation.

FACT synthesis: model compresses one or more Signals into grounded
FACT statements. Code validates:
  - referential integrity (signal_ids + evidence_ids exist)
  - evidence scope (evidence belongs to cited signals, §34)
  - confidence range (0–1)
  - statement non-empty
  - recommendation leakage (§28, §32)
  - NO silent repair: hallucinated refs are REJECTED, not stripped (§32)

Grounding rules (§12) are enforced via the prompt (fact_synthesis.md)
and basic pattern detection in the validator. The prompt carries the
detailed calibration instructions; the code catches egregious violations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.guardrails import detect_recommendation_leakage
from ..intelligence.model import ModelResponse
from .dtos import FACT, FactDraft
from .grounding import VOC_PREFIXES, check_fact_grounding
from .ids import derive_insight_id
from .model import (
    FACT_SYNTHESIS_RESPONSE_SCHEMA,
    PROMPT_VERSIONS,
    TASK_FACT_SYNTHESIS,
)
from .prompts import get_insight_prompt

# --- additional recommendation patterns for Phase 6A (§28) -----------------

#: Patterns beyond Phase 5's RECOMMENDATION_PATTERNS that indicate
#: advisory/action content. VOC quotes (e.g., 'Users say "should..."')
#: are distinguished by checking sentence-level position.
PHASE6A_RECOMMENDATION_PATTERNS: tuple[str, ...] = (
    "prioritize ",
    "you must launch",
    "we must launch",
    "should launch",
    "should target",
    "should invest",
    "allocate budget",
    "decrease price",
    "lower the price",
    "focus on",
    "run campaign",
    "partner with",
    "we need to",
)

#: Patterns that indicate the recommendation is reported user voice,
#: NOT assistant-generated advice (§28). Shared with the grounding
#: validator (grounding.VOC_PREFIXES).
_VOC_RE = re.compile(
    "|".join(re.escape(p) for p in VOC_PREFIXES),
    re.IGNORECASE,
)

_P6A_RE_RE = re.compile(
    "|".join(re.escape(p) for p in PHASE6A_RECOMMENDATION_PATTERNS),
    re.IGNORECASE,
)


def _detect_phase6a_leakage(text: str) -> list[str]:
    """Detect Phase 6A advisory patterns, excluding VOC quotes."""
    if not text:
        return []
    # Check if this is reported user voice
    is_voc = bool(_VOC_RE.search(text))
    hits: set[str] = set()
    for match in _P6A_RE_RE.finditer(text):
        hits.add(match.group(0).lower())
    # Phase 5 patterns
    for p in detect_recommendation_leakage(text):
        hits.add(p)
    if is_voc:
        # Remove hits that appear after a VOC prefix — they are reported
        # user desire, not assistant advice. For MVP, if the entire
        # statement starts with a VOC prefix, all advisory hits are
        # considered reported speech.
        hits = {h for h in hits if not _is_after_voc_prefix(text, h)}
    return sorted(hits)


def _is_after_voc_prefix(text: str, phrase: str) -> bool:
    """Check if `phrase` appears after a VOC reporting prefix."""
    lower = text.lower()
    for voc in VOC_PREFIXES:
        voc_pos = lower.find(voc)
        if voc_pos >= 0:
            phrase_pos = lower.find(phrase)
            if phrase_pos > voc_pos:
                return True
    return False


# --- validation (§14, §32, §34) --------------------------------------------


def validate_fact(
    draft: FactDraft,
    *,
    valid_signal_ids: set[str],
    evidence_by_id: Mapping[str, Any],
    signal_evidence_map: Mapping[str, set[str]],
    code_counts: Mapping[str, tuple[int, int]] | None = None,
) -> list[str]:
    """Code-side FACT guardrails (PRD §14, §32, §34).

    Returns a list of violation strings (empty = valid). Each violation
    is a human-readable description of what failed. Hallucinated refs
    are REJECTED — never stripped or repaired (§32: No Silent Repair).

    `code_counts` maps a cited signal_id to its code-computed
    (current_count, baseline_count) pair (§37); it feeds the
    unsupported-quantification guard so the model may mirror code-provided
    counts but may not invent numbers.
    """
    violations: list[str] = []

    # 1. Statement non-empty
    if not draft.statement or not draft.statement.strip():
        violations.append("statement is empty")
        return violations  # nothing else to check meaningfully

    # 2. signal_ids valid (exist in input signals)
    for sid in draft.signal_ids:
        if sid not in valid_signal_ids:
            violations.append(f"hallucinated signal_id: {sid}")

    # 3. evidence_ids valid (exist in ledger)
    for eid in draft.evidence_ids:
        if eid not in evidence_by_id:
            violations.append(f"hallucinated evidence_id: {eid}")

    # 4. Evidence scope (§34): evidence must belong to cited signals
    cited_evidence: set[str] = set()
    for sid in draft.signal_ids:
        if sid in signal_evidence_map:
            cited_evidence |= signal_evidence_map[sid]
    for eid in draft.evidence_ids:
        if eid in evidence_by_id and eid not in cited_evidence:
            violations.append(
                f"evidence {eid} does not belong to any cited signal"
            )

    # 5. Confidence range 0-1
    if draft.confidence < 0.0 or draft.confidence > 1.0:
        violations.append(f"confidence out of range: {draft.confidence}")

    # 6. Recommendation leakage (§28, §32)
    leakage = _detect_phase6a_leakage(draft.statement)
    if leakage:
        violations.append(f"recommendation leakage: {', '.join(leakage)}")

    # 7. Grounding (§12, §13, §37): quantification / causality /
    #    universality / future must be backed by cited evidence or
    #    code-computed counts. Runs only when referential checks passed —
    #    a hallucinated ref is already rejected on its own (§32).
    if not any("hallucinated" in v or "does not belong" in v for v in violations):
        grounding = check_fact_grounding(
            draft.statement,
            signal_ids=draft.signal_ids,
            evidence_ids=draft.evidence_ids,
            signal_evidence_map=signal_evidence_map,
            evidence_by_id=evidence_by_id,
            code_counts=code_counts,
        )
        violations.extend(f"grounding: {g}" for g in grounding)

    return violations


# --- synthesis (§11) -------------------------------------------------------


@dataclass(frozen=True)
class FactSynthesisResult:
    """Output of synthesize_facts(). Carries validated + rejected drafts."""
    validated: tuple[FactDraft, ...] = ()
    rejected: tuple[FactDraft, ...] = ()
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


def _build_model_payload(
    prepared: Iterable,
    evidence_by_id: Mapping[str, Any],
) -> dict:
    """Build the minimal payload for the fact synthesis model call."""
    signals_payload = [ps.to_model_payload() for ps in prepared]
    return {"signals": signals_payload}


def synthesize_facts(
    prepared_signals: list,
    model,
    evidence_by_id: Mapping[str, Any],
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> FactSynthesisResult:
    """Signal → FACT synthesis (PRD §11).

    Calls the model with fact_synthesis task. Parses response into
    FactDraft objects. Validates each draft against referential integrity,
    grounding rules, and recommendation leakage. Rejected drafts are
    returned separately — they are NEVER silently repaired (§32).
    """
    if not prepared_signals:
        return FactSynthesisResult()

    ctx = research_context or ResearchContext()
    valid_signal_ids = {ps.signal_id for ps in prepared_signals}
    signal_evidence_map = {ps.signal_id: set(ps.evidence_ids) for ps in prepared_signals}
    code_counts = {
        ps.signal_id: (ps.current_count, ps.baseline_count)
        for ps in prepared_signals
    }

    # Build cache key
    all_evidence_ids = set()
    for ps in prepared_signals:
        all_evidence_ids |= set(ps.evidence_ids)

    key = build_cache_key(
        task=TASK_FACT_SYNTHESIS,
        prompt_version=PROMPT_VERSIONS[TASK_FACT_SYNTHESIS],
        model_id=model.model_id,
        evidence_ids=all_evidence_ids,
        research_context=ctx.to_dict(),
        input_payload=[ps.to_model_payload() for ps in prepared_signals],
    )

    # Check cache
    if cache is not None:
        cached = cache.get(key)
        if cached is not None and cached.ok:
            return _parse_fact_response(
                cached, prepared_signals, evidence_by_id,
                valid_signal_ids, signal_evidence_map, code_counts,
            )

    # Build payload
    payload = _build_model_payload(prepared_signals, evidence_by_id)

    # Call model
    try:
        prompt = get_insight_prompt(TASK_FACT_SYNTHESIS)
        payload["prompt"] = prompt.render()
    except (FileNotFoundError, KeyError):
        pass  # prompt is optional for offline tests

    response = model.complete_structured(
        task=TASK_FACT_SYNTHESIS,
        payload=payload,
        response_schema=FACT_SYNTHESIS_RESPONSE_SCHEMA,
    )

    # Cache successful responses
    if cache is not None:
        cache.put(key, response)

    return _parse_fact_response(
        response, prepared_signals, evidence_by_id,
        valid_signal_ids, signal_evidence_map, code_counts,
    )


def _parse_fact_response(
    response: ModelResponse,
    prepared_signals: list,
    evidence_by_id: Mapping[str, Any],
    valid_signal_ids: set[str],
    signal_evidence_map: Mapping[str, set[str]],
    code_counts: Mapping[str, tuple[int, int]] | None = None,
) -> FactSynthesisResult:
    """Parse model response into validated + rejected FactDrafts."""
    if not response.ok:
        return FactSynthesisResult(
            warnings=(f"fact_synthesis: model {response.status.value}: {response.error}",),
            model_status=response.status.value,
        )

    facts_raw = response.payload.get("facts") or []
    validated: list[FactDraft] = []
    rejected: list[FactDraft] = []
    insight_ids: list[str] = []
    warnings: list[str] = []

    for i, fact_raw in enumerate(facts_raw):
        try:
            draft = FactDraft(
                statement=str(fact_raw.get("statement") or ""),
                signal_ids=tuple(str(s) for s in fact_raw.get("signal_ids") or []),
                evidence_ids=tuple(str(e) for e in fact_raw.get("evidence_ids") or []),
                confidence=float(fact_raw.get("confidence") or 0.0),
                rationale=str(fact_raw.get("rationale") or ""),
            )
        except (TypeError, ValueError) as exc:
            warnings.append(f"fact_synthesis: draft {i} parse error: {exc}")
            continue

        violations = validate_fact(
            draft,
            valid_signal_ids=valid_signal_ids,
            evidence_by_id=evidence_by_id,
            signal_evidence_map=signal_evidence_map,
            code_counts=code_counts,
        )
        if violations:
            rejected.append(draft)
            warnings.append(
                f"fact_synthesis: rejected draft (statement={draft.statement[:60]}...): "
                f"{'; '.join(violations)}"
            )
        else:
            validated.append(draft)
            # Derive deterministic insight_id
            ins_id = derive_insight_id(
                type=FACT,
                signal_ids=draft.signal_ids,
                evidence_ids=draft.evidence_ids,
            )
            insight_ids.append(ins_id)

    status = "success"
    if rejected and not validated:
        status = "invalid_output"
    elif rejected:
        status = "partial"

    return FactSynthesisResult(
        validated=tuple(validated),
        rejected=tuple(rejected),
        insight_ids=tuple(insight_ids),
        warnings=tuple(warnings),
        model_status=status,
    )
