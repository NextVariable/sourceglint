"""Phase 6B §10–§11, §18–§19, §32 — candidate generation + code validation.

The model proposes candidate actions. Code validates every draft:
  * support refs valid (insight ids exist and are FACT/INFERENCE)
  * action_class ∈ frozen set
  * gtm_dimensions ⊆ frozen enum (1..3)
  * confidence in [0, 1]
  * specificity guard (§33)
  * weak-signal intensity cap (§18) and contradiction cap (§19)
  * atomic action bundling warning (§11, MVP: warning not reject)

No silent repair (§32): invalid drafts are rejected with warnings.
The model never mints recommendation ids — ids are code-derived (§27).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import ModelResponse, ModelStatus
from ..insights.gtm_implications import GTM_DIMENSIONS
from .context import prepare_decision_context
from .dtos import RecommendationDraft
from .ids import normalize_action_anchor
from .model import (
    PROMPT_VERSIONS,
    RECOMMENDATION_GENERATION_RESPONSE_SCHEMA,
    TASK_RECOMMENDATION_GENERATION,
)
from .policy import (
    ACTION_CLASSES,
    CLASS_INTENSITY,
    CONTRADICTION_MAX_INTENSITY,
    MAX_CANDIDATES,
    WEAK_SIGNAL_MAX_INTENSITY,
)
from .prompts import get_recommendation_prompt
from .specificity import check_specificity

#: Multi-action bundling heuristics (§11 — MVP warning level).
_BUNDLE_PATTERNS: tuple[str, ...] = (
    " and ", " & ", " as well as ", ", ", "、", ";", "1) ", "2) ",
    " also ", " in addition ", " plus ", " then ",
)


def detect_action_bundling(action: str) -> list[str]:
    """Detect obvious multi-action bundling (§11).

    Returns the connector phrases found. MVP: recorded as a warning,
    NOT a hard reject (bundling detection is intentionally heuristic).
    """
    if not action:
        return []
    lower = action.lower()
    return [p.strip() for p in _BUNDLE_PATTERNS if p in lower]


@dataclass(frozen=True)
class CandidateGenerationResult:
    validated: tuple[RecommendationDraft, ...] = ()
    rejected: tuple[RecommendationDraft, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: str = "success"

    def to_dict(self) -> dict:
        return {
            "validated": [d.to_dict() for d in self.validated],
            "rejected": [d.to_dict() for d in self.rejected],
            "warnings": list(self.warnings),
            "model_status": self.model_status,
        }


def _support_flag(
    diagnostics: Mapping[str, Mapping[str, Any]],
    insight_id: str,
    key: str,
) -> bool:
    diag = diagnostics.get(insight_id)
    return bool(diag.get(key)) if isinstance(diag, Mapping) else False


def _id_set(insights: Sequence[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for ins in insights:
        iid = str(ins.get("insight_id") or "")
        if iid:
            ids.add(iid)
        for key in ("signal_ids", "evidence_ids"):
            for v in ins.get(key) or ():
                ids.add(str(v))
    return ids


def _validate_one(
    raw: Mapping[str, Any],
    *,
    insight_by_id: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Any],
    research_market: str,
    target_entity: str,
) -> tuple[RecommendationDraft | None, list[str]]:
    """Validate one raw candidate draft. Returns (draft, violations)."""
    violations: list[str] = []
    statement = str(raw.get("statement") or "").strip()
    action = str(raw.get("action") or "").strip()
    supporting = tuple(
        str(i) for i in (raw.get("supporting_insight_ids") or []) if str(i)
    )
    action_class = str(raw.get("action_class") or "")
    dims = tuple(str(d) for d in (raw.get("gtm_dimensions") or []) if str(d))
    confidence = raw.get("confidence")
    rationale = str(raw.get("rationale") or "").strip()
    expected_outcome = str(raw.get("expected_outcome") or "").strip()
    anchor_raw = str(raw.get("action_anchor") or "")

    # 1. statement / action non-empty (§10)
    if not statement:
        violations.append("statement is empty")
    if not action:
        violations.append("action is empty")

    # 2. supporting insight refs valid + FACT/INFERENCE only (§12)
    if not supporting:
        violations.append("no supporting_insight_ids (§12: ≥1 required)")
    for iid in supporting:
        ins = insight_by_id.get(iid)
        if ins is None:
            violations.append(f"hallucinated insight_id: {iid}")
        elif ins.get("type") not in ("FACT", "INFERENCE"):
            violations.append(
                f"supporting insight {iid} is not FACT/INFERENCE (§12)"
            )

    # 3. action_class ∈ frozen set
    if action_class not in ACTION_CLASSES:
        violations.append(f"unknown action_class: {action_class!r}")
    else:
        # 4. weak / contradiction intensity caps (§18, §19)
        intensity = CLASS_INTENSITY[action_class]
        weak = any(
            _support_flag(diagnostics, iid, "weak_signal")
            for iid in supporting if iid in insight_by_id
        )
        contra = any(
            _support_flag(diagnostics, iid, "contradiction_preserved")
            for iid in supporting if iid in insight_by_id
        )
        if weak and intensity > WEAK_SIGNAL_MAX_INTENSITY:
            violations.append(
                f"weak-signal policy (§18): action_class {action_class!r} exceeds "
                f"max intensity for weak supporting signals"
            )
        if contra and intensity > CONTRADICTION_MAX_INTENSITY:
            violations.append(
                f"contradiction policy (§19): action_class {action_class!r} exceeds "
                f"max intensity for contradictory supporting signals"
            )

    # 5. gtm_dimensions ⊆ frozen enum, 1..3 (§25)
    if not dims:
        violations.append("gtm_dimensions is empty (§25: 1-3 required)")
    for d in dims:
        if d not in GTM_DIMENSIONS:
            violations.append(f"unknown GTM dimension: {d}")
    if len(dims) > 3:
        violations.append(f"gtm_dimensions exceeds 3 (§25): {len(dims)}")

    # 6. confidence range
    try:
        conf_val = float(confidence)
        if conf_val < 0.0 or conf_val > 1.0:
            violations.append(f"confidence out of range: {conf_val}")
    except (TypeError, ValueError):
        violations.append(f"confidence not a number: {confidence!r}")

    if violations:
        return None, violations

    # 7. Specificity guard (§33) over statement + action + expected outcome.
    probe = " ".join(t for t in (statement, action, expected_outcome) if t)
    spec = check_specificity(
        probe,
        supporting_insight_ids=supporting,
        insight_by_id=insight_by_id,
        evidence_by_id=evidence_by_id,
        research_market=research_market,
        target_entity=target_entity,
    )
    if spec:
        return None, spec

    draft = RecommendationDraft(
        statement=statement,
        action=action,
        supporting_insight_ids=supporting,
        confidence=conf_val,
        action_class=action_class,
        gtm_dimensions=dims,
        action_anchor=normalize_action_anchor(anchor_raw),
        rationale=rationale,
        expected_outcome=expected_outcome,
    )
    return draft, []


def generate_candidate_recommendations(
    insights: Sequence[Mapping[str, Any]],
    model,
    evidence_by_id: Mapping[str, Any],
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
    insight_diagnostics: Mapping[str, Mapping[str, Any]] | None = None,
    max_candidates: int = MAX_CANDIDATES,
    target_entity: str = "",
) -> CandidateGenerationResult:
    """Validated FACT/INFERENCE insights → candidate RecommendationDrafts.

    `insights` are the validated FACT/INFERENCE insight dicts (6A output,
    each with insight_id/type/statement/confidence/signal_ids/evidence_ids).
    The model receives a minimal decision context (§9); code validates
    every draft (§32). Candidates are capped at max_candidates BEFORE
    dedup (§35).
    """
    if not insights:
        return CandidateGenerationResult(warnings=("generate: no insights to act on",))

    ctx = research_context or ResearchContext()
    diagnostics = insight_diagnostics or {}
    insight_by_id = {
        str(ins.get("insight_id") or ""): dict(ins)
        for ins in insights if ins.get("insight_id")
    }

    key = build_cache_key(
        task=TASK_RECOMMENDATION_GENERATION,
        prompt_version=PROMPT_VERSIONS[TASK_RECOMMENDATION_GENERATION],
        model_id=model.model_id,
        evidence_ids=_id_set(insights),
        research_context=ctx.to_dict(),
    )

    cached = None
    if cache is not None:
        cached = cache.get(key)
        if cached is not None and cached.ok:
            return _parse_response(
                cached, insight_by_id, diagnostics, evidence_by_id,
                ctx.market, target_entity, max_candidates,
            )

    prepared, _ = prepare_decision_context(
        insights, insight_diagnostics=diagnostics
    )
    payload: dict[str, Any] = {
        "insights": [p.to_model_payload() for p in prepared],
        "research_context": ctx.to_dict(),
        "max_candidates": max_candidates,
    }
    try:
        prompt = get_recommendation_prompt(TASK_RECOMMENDATION_GENERATION)
        payload["prompt"] = prompt.render()
    except (FileNotFoundError, KeyError):
        pass  # prompt optional for offline tests

    response = model.complete_structured(
        task=TASK_RECOMMENDATION_GENERATION,
        payload=payload,
        response_schema=RECOMMENDATION_GENERATION_RESPONSE_SCHEMA,
    )
    if cache is not None:
        cache.put(key, response)

    return _parse_response(
        response, insight_by_id, diagnostics, evidence_by_id,
        ctx.market, target_entity, max_candidates,
    )


def _parse_response(
    response: ModelResponse,
    insight_by_id: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Any],
    research_market: str,
    target_entity: str,
    max_candidates: int,
) -> CandidateGenerationResult:
    if not response.ok:
        return CandidateGenerationResult(
            warnings=(
                f"recommendation_generation: model {response.status.value}: "
                f"{response.error}",
            ),
            model_status=response.status.value,
        )

    raws = response.payload.get("recommendations") or []
    validated: list[RecommendationDraft] = []
    rejected: list[RecommendationDraft] = []
    warnings: list[str] = []

    for i, raw in enumerate(raws):
        try:
            draft, violations = _validate_one(
                raw,
                insight_by_id=insight_by_id,
                diagnostics=diagnostics,
                evidence_by_id=evidence_by_id,
                research_market=research_market,
                target_entity=target_entity,
            )
        except (TypeError, ValueError) as exc:
            warnings.append(
                f"recommendation_generation: draft {i} parse error: {exc}"
            )
            continue
        if draft is None:
            rejected.append(_as_draft(raw))
            warnings.append(
                f"recommendation_generation: rejected draft "
                f"(action={str(raw.get('action'))[:60]}...): {'; '.join(violations)}"
            )
            continue

        bundling = detect_action_bundling(draft.action)
        if bundling:
            warnings.append(
                f"recommendation_generation: draft {i} bundles multiple actions "
                f"(connectors: {', '.join(bundling)}) — prefer one primary action"
            )
        validated.append(draft)

    # Cap candidates (§35) BEFORE dedup. Deterministic: keep the highest
    # confidence valid drafts, ties broken by (action, insight set).
    if len(validated) > max_candidates:
        ordered = sorted(
            validated,
            key=lambda d: (-d.confidence, d.action, d.supporting_insight_ids),
        )
        validated = ordered[:max_candidates]
        warnings.append(
            f"recommendation_generation: capped to {max_candidates} candidates (§35)"
        )

    status = "success"
    if rejected and not validated:
        status = "invalid_output"
    elif rejected:
        status = "partial"

    # Deterministic pipeline order: by (action, insight set).
    validated = sorted(
        validated,
        key=lambda d: (d.action, d.supporting_insight_ids),
    )
    return CandidateGenerationResult(
        validated=tuple(validated),
        rejected=tuple(rejected),
        warnings=tuple(warnings),
        model_status=status,
    )


def _as_draft(raw: Mapping[str, Any]) -> RecommendationDraft:
    """Best-effort RecommendationDraft for the rejected list (audit only)."""
    return RecommendationDraft(
        statement=str(raw.get("statement") or ""),
        action=str(raw.get("action") or ""),
        supporting_insight_ids=tuple(
            str(i) for i in (raw.get("supporting_insight_ids") or []) if str(i)
        ),
        confidence=float(raw.get("confidence") or 0.0),
        action_class=str(raw.get("action_class") or ""),
        gtm_dimensions=tuple(
            str(d) for d in (raw.get("gtm_dimensions") or []) if str(d)
        ),
        action_anchor=normalize_action_anchor(str(raw.get("action_anchor") or "")),
        rationale=str(raw.get("rationale") or ""),
        expected_outcome=str(raw.get("expected_outcome") or ""),
    )
