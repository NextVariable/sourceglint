"""Phase 6A §24–§25, §28 — descriptive GTM implications + leakage guard.

GTM implications are DESCRIPTIVE only (§5, §24):
  "Price sensitivity differs by segment" → OK (describes what the
  insight means for a dimension)
  "Lower the price to $9" → REJECT (action, Phase 6B territory)

16 frozen dimensions (§24). Sparsity: only materially relevant (§25).
Recommendation leakage guard (§28) screens implication values for
action language, distinguishing VOC quotes from assistant advice.

GTM implication ≠ GTM action (§5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import ModelResponse, ModelStatus
from .dtos import FACT, INFERENCE, GTMImplicationDraft
from .facts import _detect_phase6a_leakage
from .model import (
    GTM_IMPLICATIONS_RESPONSE_SCHEMA,
    PROMPT_VERSIONS,
    TASK_GTM_IMPLICATIONS,
)
from .prompts import get_insight_prompt

#: Frozen GTM dimension enum (common.schema.json gtm_dimension).
GTM_DIMENSIONS: frozenset[str] = frozenset({
    "market", "icp", "pain_point", "product", "positioning", "messaging",
    "pricing", "competitor", "channel", "creator", "content", "launch",
    "localization", "distribution", "conversion", "retention",
})

#: Imperative action verbs that indicate prescriptive advice (§28).
#: Checked at the START of an implication value (case-insensitive).
_IMPERATIVE_VERBS: tuple[str, ...] = (
    "target ", "launch ", "lower ", "increase ", "decrease ",
    "prioritize ", "focus on ", "run ", "partner with ", "allocate ",
    "invest ", "build ", "create ", "ship ", "roll out ",
)


def _detect_imperative_leakage(text: str) -> list[str]:
    """Detect imperative action verbs at the start of an implication value.

    "Target enterprise buyers first" → leakage (imperative "target")
    "The target market is enterprise" → no leakage (descriptive, not at start)
    "Lower price to $9" → leakage (imperative "lower")
    "Lower-than-expected adoption" → no leakage (adjective, not imperative)
    """
    if not text:
        return []
    lower = text.lower().strip()
    hits: list[str] = []
    for verb in _IMPERATIVE_VERBS:
        if lower.startswith(verb):
            hits.append(verb.strip())
    return hits


def _detect_gtm_leakage(text: str) -> list[str]:
    """Combined leakage detection for GTM implication values (§28)."""
    if not text:
        return []
    hits = set(_detect_phase6a_leakage(text))
    hits.update(_detect_imperative_leakage(text))
    return sorted(hits)


def validate_gtm_implications(implications: Mapping[str, Any]) -> list[str]:
    """Validate that GTM implications are descriptive, not prescriptive.

    Returns a list of violation strings (empty = valid).
    """
    violations: list[str] = []

    for key, value in implications.items():
        # 1. Key must be a frozen GTM dimension
        if key not in GTM_DIMENSIONS:
            violations.append(f"unknown GTM dimension: {key}")
            continue

        # 2. Value must be string or null
        if value is not None and not isinstance(value, str):
            violations.append(f"dimension {key}: value must be string or null, got {type(value).__name__}")
            continue

        # 3. Null is OK (assessed, no implication, §25)
        if value is None:
            continue

        # 4. Non-empty string required if present
        if not value.strip():
            violations.append(f"dimension {key}: empty string — use null instead")
            continue

        # 5. Recommendation leakage (§28): no action language
        leakage = _detect_gtm_leakage(value)
        if leakage:
            violations.append(
                f"dimension {key}: recommendation leakage: {', '.join(leakage)}"
            )

    return violations


# --- derivation (§24) -----------------------------------------------------


@dataclass(frozen=True)
class GTMImplicationResult:
    """Output of derive_gtm_implications()."""
    implications: tuple[GTMImplicationDraft, ...] = ()
    rejected: tuple[tuple[str, Mapping[str, Any]], ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: str = "success"

    def to_dict(self) -> dict:
        return {
            "implications": [gi.to_dict() for gi in self.implications],
            "rejected": [{"insight_id": iid, "implications": dict(impl)} for iid, impl in self.rejected],
            "warnings": list(self.warnings),
            "model_status": self.model_status,
        }


def derive_gtm_implications(
    insights: Sequence[tuple[Any, str, str]],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> GTMImplicationResult:
    """Derive descriptive GTM implications for each validated insight.

    `insights` is a sequence of (draft, insight_id, type) tuples where
    draft is a FactDraft or InferenceDraft, insight_id is the derived
    deterministic ID, and type is FACT or INFERENCE.

    For each insight, the model is called with TASK_GTM_IMPLICATIONS.
    The response is parsed into a GTMImplicationDraft and validated
    against the descriptive-only rule.
    """
    if not insights:
        return GTMImplicationResult()

    ctx = research_context or ResearchContext()
    validated: list[GTMImplicationDraft] = []
    rejected: list[tuple[str, Mapping[str, Any]]] = []
    warnings: list[str] = []

    for draft, ins_id, ins_type in insights:
        # Build cache key
        key = build_cache_key(
            task=TASK_GTM_IMPLICATIONS,
            prompt_version=PROMPT_VERSIONS[TASK_GTM_IMPLICATIONS],
            model_id=model.model_id,
            evidence_ids=draft.evidence_ids,
            research_context=ctx.to_dict(),
        )

        # Check cache
        cached_resp = None
        if cache is not None:
            cached_resp = cache.get(key)

        if cached_resp is not None and cached_resp.ok:
            implications_raw = cached_resp.payload.get("implications") or {}
        else:
            payload: dict[str, Any] = {
                "insight_id": ins_id,
                "type": ins_type,
                "statement": draft.statement,
                "signal_ids": list(draft.signal_ids),
                "evidence_ids": list(draft.evidence_ids),
            }
            try:
                prompt = get_insight_prompt(TASK_GTM_IMPLICATIONS)
                payload["prompt"] = prompt.render()
            except (FileNotFoundError, KeyError):
                pass

            response = model.complete_structured(
                task=TASK_GTM_IMPLICATIONS,
                payload=payload,
                response_schema=GTM_IMPLICATIONS_RESPONSE_SCHEMA,
            )

            if cache is not None:
                cache.put(key, response)

            if not response.ok:
                warnings.append(
                    f"gtm_implications: insight {ins_id} model {response.status.value}: {response.error}"
                )
                continue

            implications_raw = response.payload.get("implications") or {}

        # Validate
        violations = validate_gtm_implications(implications_raw)
        if violations:
            rejected.append((ins_id, dict(implications_raw)))
            warnings.append(
                f"gtm_implications: rejected for {ins_id}: {'; '.join(violations)}"
            )
        else:
            validated.append(GTMImplicationDraft(
                insight_id=ins_id,
                implications=dict(implications_raw),
            ))

    status = "success"
    if rejected and not validated:
        status = "invalid_output"
    elif rejected:
        status = "partial"

    return GTMImplicationResult(
        implications=tuple(validated),
        rejected=tuple(rejected),
        warnings=tuple(warnings),
        model_status=status,
    )
