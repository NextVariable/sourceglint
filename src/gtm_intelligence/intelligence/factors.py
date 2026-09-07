"""Phase 5 §19–§24 — factor derivation for the frozen Phase 2 scorer.

The five score factors and who computes them:

  decision_relevance  — MODEL (semantic_factors:v1), judged against the
                        research context (mode/entities/market/decision).
  evidence_quality    — CODE: mean of member evidence_quality. Members with
                        no quality are skipped; if NONE are known the value
                        is 0.0 with a warning — never 0.5 (Closeout §3).
  recency             — CODE, deterministic (PRD §22): exponential decay
                        over the YOUNGEST member's age at `as_of`
                        (recency = 0.5 ** (age_days / 30)). No published
                        date ⇒ not assessed ⇒ 0.0 + warning.
  market_signal       — CODE (PRD §23): discussion breadth dominates,
                        engagement is a weak contributor only.
                        breadth = min(1, independent_sources / 2)
                        depth   = min(1, log1p(engagement) / log1p(500))
                        ms      = 0.6*breadth + 0.4*depth
  novelty             — CODE, from the baseline window (schema
                        signal.schema.json: "1.0 = absent from baseline"):
                        only_current → 1.0; only_baseline → 0.0;
                        both windows (continuing topic) → 0.5. With NO
                        baseline window anywhere, novelty is not assessed
                        → 0.0 + warning (Closeout §3: unknown ≠ neutral).

The model's `semantic_novelty` is DIAGNOSTIC metadata only (see
prompts/semantic_factors.md: it never overwrites the code-computed
novelty factor); it is carried in `semantic_flags` for weak-signal
detection and the debug trail.

`as_of` is REQUIRED so runs stay deterministic — same input + same
`as_of` ⇒ identical factors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import log1p
from typing import Any, Mapping, Sequence

from .cache import SemanticCache, build_cache_key
from .dtos import (
    WINDOW_BASELINE,
    PreparedEvidence,
    ResearchContext,
    SignalFeatures,
    ValidatedCluster,
)
from .model import (
    IntelligenceModel,
    IntelligencePipelineError,
    ModelResponse,
    SEMANTIC_FACTORS_RESPONSE_SCHEMA,
    ModelStatus,
)
from .preparation import model_payloads
from .prompts import TASK_SEMANTIC_FACTORS, prompt_version

#: Recency half-life: a 30-day-old item scores 0.5, 60-day-old 0.25 ...
HALF_LIFE_DAYS = 30.0

#: Code-computed novelty values (schema semantics, baseline window).
NOVELTY_ONLY_CURRENT = 1.0
NOVELTY_ONLY_BASELINE = 0.0
NOVELTY_BOTH_WINDOWS = 0.5

#: Market-signal mix: breadth (independent origins) dominates engagement.
MS_BREADTH_WEIGHT = 0.6
MS_DEPTH_WEIGHT = 0.4
MS_ENGAGEMENT_SATURATION = 500

#: Required semantic keys.
_DR_KEY = "decision_relevance"


@dataclass(frozen=True)
class FactorSet:
    """All five score factors + diagnostics for one cluster (PRD §24)."""

    cluster_id: str
    decision_relevance: float = 0.0
    evidence_quality: float = 0.0
    recency: float = 0.0
    market_signal: float = 0.0
    novelty: float = 0.0
    semantic_flags: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    degraded: bool = False
    model_status: str = ModelStatus.SUCCESS.value

    @property
    def factors(self) -> dict[str, float]:
        """The exact mapping consumed by scoring.compute_score()."""
        return {
            "decision_relevance": self.decision_relevance,
            "evidence_quality": self.evidence_quality,
            "recency": self.recency,
            "market_signal": self.market_signal,
            "novelty": self.novelty,
        }

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            **self.factors,
            "semantic_flags": dict(self.semantic_flags),
            "warnings": list(self.warnings),
            "degraded": self.degraded,
            "model_status": self.model_status,
        }


# --- pure helpers -----------------------------------------------------------


def _as_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Naive timestamps are treated as UTC — never the host local zone —
        # so recency stays byte-identical across machines (PRD §22).
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(published_at: str, as_of: datetime) -> float | None:
    parsed = _as_utc(published_at)
    if parsed is None:
        return None
    age = (as_of - parsed).total_seconds() / 86400.0
    return max(0.0, age)


def _member_quality(members: Sequence[PreparedEvidence]) -> tuple[float, list[str]]:
    values = [m.evidence_quality for m in members if m.evidence_quality is not None]
    if not values:
        return 0.0, ["evidence quality not assessed (no member quality values)"]
    return sum(values) / len(values), []


def _member_recency(members: Sequence[PreparedEvidence], as_of: datetime) -> tuple[float, list[str]]:
    factors_list = []
    for member in members:
        age = _age_days(member.published_at, as_of)
        if age is None:
            continue
        factors_list.append(0.5 ** (age / HALF_LIFE_DAYS))
    if not factors_list:
        return 0.0, ["recency not assessed (no published_at on any member)"]
    return max(factors_list), []


def code_novelty(features: SignalFeatures) -> tuple[float, list[str]]:
    """Baseline-window novelty (schema semantics). Unknown ⇒ 0.0."""
    if not features.has_baseline_data:
        return 0.0, ["novelty not assessed (no baseline window to compare)"]
    warnings: list[str] = []
    if features.appeared_only_current:
        return NOVELTY_ONLY_CURRENT, warnings
    if features.appeared_only_baseline:
        return NOVELTY_ONLY_BASELINE, warnings
    return NOVELTY_BOTH_WINDOWS, warnings


def market_signal_factor(features: SignalFeatures) -> float:
    """0.6 breadth + 0.4 depth (PRD §23: engagement ≠ market signal).

    Breadth starts only at the SECOND independent origin: one lone
    origin is a single voice, not a market discussion (breadth =
    min(1, max(0, independent_sources - 1)))."""
    breadth = min(1.0, max(0.0, features.independent_source_count - 1))
    depth = min(1.0, log1p(features.engagement_total) / log1p(MS_ENGAGEMENT_SATURATION))
    return MS_BREADTH_WEIGHT * breadth + MS_DEPTH_WEIGHT * depth


# --- semantic assessment ----------------------------------------------------


def _clamp01(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(1.0, max(0.0, float(value)))


def _semantic_assessment(
    cluster: ValidatedCluster,
    members: Sequence[PreparedEvidence],
    *,
    model: IntelligenceModel,
    research_context: ResearchContext,
    cache: SemanticCache | None = None,
) -> tuple[float, dict[str, Any], str, list[str], bool]:
    """One semantic_factors call (cache-aware). Returns
    (decision_relevance, flags, model_status, warnings, degraded)."""
    payload: dict[str, Any] = {
        "cluster_id": cluster.cluster_id,
        "label": cluster.label,
        "claim": cluster.claim,
        "evidence_ids": list(cluster.evidence_ids),
        "evidence_items": model_payloads(members),
        "research_context": research_context.to_dict(),
    }
    cache_key: str | None = None
    if cache is not None:
        cache_key = build_cache_key(
            task=TASK_SEMANTIC_FACTORS,
            prompt_version=prompt_version(TASK_SEMANTIC_FACTORS),
            model_id=model.model_id,
            evidence_ids=cluster.evidence_ids,
            research_context=research_context.to_dict(),
        )
        cached = cache.get(cache_key)
        if cached is not None:
            response = cached
        else:
            response = model.complete_structured(
                task=TASK_SEMANTIC_FACTORS,
                payload=payload,
                response_schema=SEMANTIC_FACTORS_RESPONSE_SCHEMA,
            )
            cache.put(cache_key, response)
    else:
        response = model.complete_structured(
            task=TASK_SEMANTIC_FACTORS,
            payload=payload,
            response_schema=SEMANTIC_FACTORS_RESPONSE_SCHEMA,
        )
    if not response.ok:
        return (
            0.0,
            {},
            response.status.value,
            [
                f"semantic factors unavailable for {cluster.cluster_id}: "
                f"status={response.status.value} error={response.error!r}"
            ],
            True,
        )
    body = response.payload or {}
    warnings: list[str] = []
    degraded = False

    dr = _clamp01(body.get(_DR_KEY))
    if dr is None:
        dr = 0.0
        warnings.append(
            f"decision_relevance missing for {cluster.cluster_id}; not assessed"
        )
        degraded = True

    flags: dict[str, Any] = {}
    rationale = body.get("decision_relevance_rationale")
    if isinstance(rationale, str) and rationale:
        flags["decision_relevance_rationale"] = rationale
    semantic_novelty = _clamp01(body.get("semantic_novelty"))
    if semantic_novelty is not None:
        flags["semantic_novelty"] = semantic_novelty
    commercial_intent = _clamp01(body.get("commercial_intent"))
    if commercial_intent is not None:
        flags["commercial_intent"] = commercial_intent
    if isinstance(body.get("early_signal"), bool):
        flags["early_signal"] = body["early_signal"]
    return dr, flags, ModelStatus.SUCCESS.value, warnings, degraded


# --- top-level --------------------------------------------------------------


def derive_factors(
    cluster: ValidatedCluster,
    features: SignalFeatures,
    evidence_by_id: Mapping[str, PreparedEvidence],
    as_of: datetime,
    *,
    model: IntelligenceModel | None = None,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> FactorSet:
    """Assemble the five-factor payload for `scoring.compute_score`.

    `model=None` is allowed for deterministic-only tests / partial runs:
    decision relevance is then NOT assessed (0.0 + degraded) rather than
    invented. `cache` skips repeated semantic calls (PRD §28).
    """
    members = [
        evidence_by_id[eid] for eid in cluster.evidence_ids if eid in evidence_by_id
    ]
    warnings: list[str] = []
    degraded = False

    quality, quality_warnings = _member_quality(members)
    warnings.extend(quality_warnings)

    recency, recency_warnings = _member_recency(members, as_of)
    warnings.extend(recency_warnings)

    novelty, novelty_warnings = code_novelty(features)
    warnings.extend(novelty_warnings)

    ms = market_signal_factor(features)

    ctx = research_context or ResearchContext()
    if model is None:
        dr, flags, model_status, sem_warnings, sem_degraded = (
            0.0,
            {},
            ModelStatus.UNAVAILABLE.value,
            [f"no model supplied; decision relevance not assessed for {cluster.cluster_id}"],
            True,
        )
    else:
        dr, flags, model_status, sem_warnings, sem_degraded = _semantic_assessment(
            cluster, members, model=model, research_context=ctx, cache=cache
        )
    warnings.extend(sem_warnings)
    degraded = degraded or sem_degraded

    return FactorSet(
        cluster_id=cluster.cluster_id,
        decision_relevance=dr,
        evidence_quality=quality,
        recency=recency,
        market_signal=ms,
        novelty=novelty,
        semantic_flags=flags,
        warnings=tuple(warnings),
        degraded=degraded,
        model_status=model_status,
    )
