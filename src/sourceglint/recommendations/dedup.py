"""Phase 6B §28 — semantic recommendation dedup (Phase 6A residual risk).

Phase 6A shipped deterministic structural + signal-overlap dedup only;
the model-assisted semantic duplicate grouping task existed but was not
wired (§28 note). Phase 6B wires it for RECOMMENDATIONs:

  candidate recs
    → structural dedup (same insight_id → identical)
    → semantic duplicate grouping (model, validated by code)
    → deterministic winner selection (§28 rule)

Winner selection order:
  1. higher priority (code-computed)
  2. higher confidence
  3. higher support_strength
  4. shorter clearer action
  5. stable insight_id tie-break

The model only PROPOSES duplicate groups; code validates ids exist,
group size ≥ 2 and picks the winner deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..intelligence.cache import SemanticCache, build_cache_key
from ..intelligence.dtos import ResearchContext
from .assess import AssessedRecommendation
from .model import (
    PROMPT_VERSIONS,
    RECOMMENDATION_DEDUP_RESPONSE_SCHEMA,
    TASK_RECOMMENDATION_DEDUP,
)
from .prompts import get_recommendation_prompt

#: Duplicate group types recognised from the model.
_DEDUP_GROUP_KEY = "duplicate_groups"


@dataclass(frozen=True)
class DedupResult:
    kept: tuple[AssessedRecommendation, ...] = ()
    removed: tuple[AssessedRecommendation, ...] = ()
    collapsed: tuple[tuple[str, ...], ...] = ()  # (winner_id, *dupe_ids)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "kept": [a.to_dict() for a in self.kept],
            "removed": [a.to_dict() for a in self.removed],
            "collapsed": [list(g) for g in self.collapsed],
            "warnings": list(self.warnings),
        }


def _winner_key(a: AssessedRecommendation) -> tuple:
    """Deterministic winner ordering (§28)."""
    return (
        -a.priority,
        -a.confidence,
        -a.support.min_insight_confidence,
        len(a.draft.action),
        a.insight_id,
    )


def _structural_dedup(
    candidates: Sequence[AssessedRecommendation],
) -> tuple[list[AssessedRecommendation], list[AssessedRecommendation], list[str]]:
    """Pass 1: identical insight_id → keep the strongest, drop the rest."""
    by_id: dict[str, list[AssessedRecommendation]] = {}
    for cand in candidates:
        by_id.setdefault(cand.insight_id, []).append(cand)

    kept: list[AssessedRecommendation] = []
    removed: list[AssessedRecommendation] = []
    warnings: list[str] = []
    for ins_id, group in by_id.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        ordered = sorted(group, key=_winner_key)
        winner = ordered[0]
        kept.append(winner)
        for dupe in ordered[1:]:
            removed.append(dupe)
            warnings.append(
                f"rec_dedup: structural duplicate collapsed into {ins_id}: "
                f"{dupe.draft.action[:50]}..."
            )
    return kept, removed, warnings


def _semantic_dedup(
    candidates: Sequence[AssessedRecommendation],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> tuple[list[AssessedRecommendation], list[AssessedRecommendation],
           list[tuple[str, ...]], list[str]]:
    """Pass 2: model proposes duplicate groups; code validates + picks."""
    if len(candidates) < 2:
        return list(candidates), [], [], []

    ctx = research_context or ResearchContext()
    by_id = {c.insight_id: c for c in candidates}
    rec_ids = sorted(by_id)

    key = build_cache_key(
        task=TASK_RECOMMENDATION_DEDUP,
        prompt_version=PROMPT_VERSIONS[TASK_RECOMMENDATION_DEDUP],
        model_id=model.model_id,
        evidence_ids=tuple(rec_ids),
        research_context=ctx.to_dict(),
    )

    cached = None
    if cache is not None:
        cached = cache.get(key)
    if cached is not None and cached.ok:
        raw_groups = cached.payload.get(_DEDUP_GROUP_KEY) or []
    else:
        payload: dict[str, Any] = {
            "candidates": [
                {
                    "rec_id": c.insight_id,
                    "action": c.draft.action,
                    "action_class": c.draft.action_class,
                    "gtm_dimensions": list(c.draft.gtm_dimensions),
                    "priority": c.priority,
                }
                for c in candidates
            ]
        }
        try:
            prompt = get_recommendation_prompt(TASK_RECOMMENDATION_DEDUP)
            payload["prompt"] = prompt.render()
        except (FileNotFoundError, KeyError):
            pass

        response = model.complete_structured(
            task=TASK_RECOMMENDATION_DEDUP,
            payload=payload,
            response_schema=RECOMMENDATION_DEDUP_RESPONSE_SCHEMA,
        )
        if cache is not None:
            cache.put(key, response)
        if not response.ok:
            # Dedup is a quality pass — failure degrades to structural only.
            return list(candidates), [], [], [
                f"rec_dedup: model {response.status.value}: {response.error}; "
                f"semantic dedup skipped"
            ]
        raw_groups = response.payload.get(_DEDUP_GROUP_KEY) or []

    # Validate groups (code): ids exist, group ≥ 2, no hallucinated ids.
    removed: list[AssessedRecommendation] = []
    removed_ids: set[str] = set()
    collapsed: list[tuple[str, ...]] = []
    warnings: list[str] = []

    for group in raw_groups:
        ids = [str(i) for i in group]
        bad = [i for i in ids if i not in by_id]
        if bad:
            warnings.append(f"rec_dedup: hallucinated rec_id in duplicate group: {bad}")
            continue
        uniq = sorted(set(ids))
        if len(uniq) < 2:
            warnings.append(f"rec_dedup: duplicate group smaller than 2: {uniq}")
            continue
        members = [by_id[i] for i in uniq]
        members.sort(key=_winner_key)
        winner = members[0]
        dupe_ids = tuple(m.insight_id for m in members[1:])
        for m in members[1:]:
            if m.insight_id not in removed_ids:
                removed.append(m)
                removed_ids.add(m.insight_id)
        collapsed.append((winner.insight_id, *dupe_ids))
        warnings.append(
            f"rec_dedup: semantic duplicate group → keep {winner.insight_id}"
        )

    kept = [c for c in candidates if c.insight_id not in removed_ids]
    return kept, removed, collapsed, warnings


def deduplicate_recommendations(
    candidates: Sequence[AssessedRecommendation],
    model,
    *,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> DedupResult:
    """Two-pass dedup: structural, then semantic (validated)."""
    if not candidates:
        return DedupResult()

    kept, removed, warnings = _structural_dedup(candidates)
    kept, removed2, collapsed, warnings2 = _semantic_dedup(
        kept, model, research_context=research_context, cache=cache
    )
    all_removed = removed + removed2
    return DedupResult(
        kept=tuple(kept),
        removed=tuple(all_removed),
        collapsed=tuple(collapsed),
        warnings=tuple(warnings + warnings2),
    )
