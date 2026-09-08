"""Phase 6B §29–§30 — recommendation conflict detection.

Different insights may generate opposed actions ("raise price" vs
"lower price"). This is NOT necessarily an error — it may apply to
different segments or horizons (§29). The model classifies each
conflict group as true_conflict | segment_specific |
time_horizon_specific; code validates refs and deterministic group ids.

Conflicts are never auto-resolved (§30): both sides are kept and the
group is tagged with a deterministic conflict_group_id for the future
renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from ..intelligence.model import ModelResponse, ModelStatus
from .assess import AssessedRecommendation
from .dtos import RecommendationConflict
from .model import (
    CONFLICT_KINDS,
    PROMPT_VERSIONS,
    RECOMMENDATION_CONFLICT_RESPONSE_SCHEMA,
    TASK_RECOMMENDATION_CONFLICT,
)
from .prompts import get_recommendation_prompt


def _group_id(rec_ids: Sequence[str]) -> str:
    """Deterministic conflict-group id: sorted member ids joined."""
    return "+".join(sorted(set(rec_ids)))


@dataclass(frozen=True)
class ConflictDetectionResult:
    conflicts: tuple[RecommendationConflict, ...] = ()
    warnings: tuple[str, ...] = ()
    model_status: str = "success"

    def to_dict(self) -> dict:
        return {
            "conflicts": [c.to_dict() for c in self.conflicts],
            "warnings": list(self.warnings),
            "model_status": self.model_status,
        }


def detect_conflicts(
    recommendations: Sequence[AssessedRecommendation],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> ConflictDetectionResult:
    """Detect + classify conflicts among the surviving recommendations.

    The model receives compact candidate summaries and returns conflict
    groups; code validates every ref and derives deterministic group ids.
    A failed model call degrades to "no conflicts detected" (§30 keeps
    both sides regardless).
    """
    if len(recommendations) < 2:
        return ConflictDetectionResult()

    ctx = research_context or ResearchContext()
    by_id = {r.insight_id: r for r in recommendations}

    key = build_cache_key(
        task=TASK_RECOMMENDATION_CONFLICT,
        prompt_version=PROMPT_VERSIONS[TASK_RECOMMENDATION_CONFLICT],
        model_id=model.model_id,
        evidence_ids=tuple(sorted(by_id)),
        research_context=ctx.to_dict(),
    )

    cached = None
    if cache is not None:
        cached = cache.get(key)
    if cached is not None and cached.ok:
        raw_groups = cached.payload.get("conflict_groups") or []
    else:
        payload: dict[str, Any] = {
            "recommendations": [
                {
                    "rec_id": r.insight_id,
                    "action": r.draft.action,
                    "action_class": r.draft.action_class,
                    "gtm_dimensions": list(r.draft.gtm_dimensions),
                    "priority": r.priority,
                    "supporting_insight_ids": list(r.draft.supporting_insight_ids),
                }
                for r in recommendations
            ]
        }
        try:
            prompt = get_recommendation_prompt(TASK_RECOMMENDATION_CONFLICT)
            payload["prompt"] = prompt.render()
        except (FileNotFoundError, KeyError):
            pass

        response = model.complete_structured(
            task=TASK_RECOMMENDATION_CONFLICT,
            payload=payload,
            response_schema=RECOMMENDATION_CONFLICT_RESPONSE_SCHEMA,
        )
        if cache is not None:
            cache.put(key, response)
        if not response.ok:
            return ConflictDetectionResult(
                warnings=(
                    f"rec_conflict: model {response.status.value}: "
                    f"{response.error}; conflict detection skipped",
                ),
                model_status=response.status.value,
            )
        raw_groups = response.payload.get("conflict_groups") or []

    conflicts: list[RecommendationConflict] = []
    warnings: list[str] = []

    for group in raw_groups:
        ids = sorted({str(i) for i in (group.get("rec_ids") or [])})
        kind = str(group.get("kind") or "")
        if len(ids) < 2:
            warnings.append(f"rec_conflict: group smaller than 2 rec_ids: {ids}")
            continue
        bad = [i for i in ids if i not in by_id]
        if bad:
            warnings.append(f"rec_conflict: hallucinated rec_id: {bad}")
            continue
        if kind not in CONFLICT_KINDS:
            warnings.append(f"rec_conflict: unknown conflict kind: {kind!r}")
            continue
        conflicts.append(RecommendationConflict(
            group_id=_group_id(ids),
            rec_ids=tuple(ids),
            kind=kind,
            rationale=str(group.get("rationale") or ""),
            gtm_dimensions=tuple(
                str(d) for d in (group.get("gtm_dimensions") or []) if str(d)
            ),
        ))

    conflicts.sort(key=lambda c: c.group_id)
    return ConflictDetectionResult(
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        model_status="success",
    )
