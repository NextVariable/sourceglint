"""Phase 5 §16 — support-vs-contradiction classification per cluster.

What the model owns: which evidence within ONE cluster supports the
cluster claim and which contradicts it, plus the contradiction `kind`
(factual / experience / contextual) and a confidence.

What CODE owns here:
  * the payload boundary — the model only sees this cluster's members,
    never evidence from other clusters, never the full ledger;
  * id hygiene — a counter id that is not a member of THIS cluster
    (hallucinated, or borrowed from another cluster) is cut;
  * the partition — after cutting, `counter` is exactly what the model
    asserted (minus junk) and `support` is its code-computed complement
    (`cluster members − counter`). The two are disjoint by construction;
  * kind consistency — a non-`none` kind with no surviving counter
    evidence collapses to `none` (no counter evidence ⇒ no contradiction);
    `none` with counter evidence present is KEPT (real contradiction may
    exist) but flagged degraded so downstream cannot silently
    under-report. An unknown kind value collapses to `none` — code never
    invents a kind the model did not name;
  * failure semantics (PRD §27) — contradiction is NOT a required step.
    A model failure leaves support and contradiction unassessed
    for that cluster, with a warning; it never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .dtos import (
    CONTRADICTION_CONTEXTUAL,
    CONTRADICTION_EXPERIENCE,
    CONTRADICTION_FACTUAL,
    CONTRADICTION_NONE,
    ContradictionAssessment,
    PreparedEvidence,
    ResearchContext,
    ValidatedCluster,
)
from .cache import SemanticCache, build_cache_key
from .model import (
    CONTRADICTION_RESPONSE_SCHEMA,
    IntelligenceModel,
)
from .preparation import model_payloads
from .prompts import TASK_CONTRADICTION, prompt_version

_VALID_KINDS = {
    CONTRADICTION_NONE,
    CONTRADICTION_FACTUAL,
    CONTRADICTION_EXPERIENCE,
    CONTRADICTION_CONTEXTUAL,
}


@dataclass(frozen=True)
class ContradictionOutcome:
    """Per-cluster contradiction assessments, sorted by cluster_id."""

    assessments: tuple[ContradictionAssessment, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "assessments": [a.to_dict() for a in self.assessments],
            "warnings": list(self.warnings),
        }


def _as_id_list(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(i) for i in raw if str(i)]


def _degraded_assessment(
    cluster: ValidatedCluster,
    reason: str,
) -> ContradictionAssessment:
    """Model unusable → evidence remains unassessed; no support is inferred."""
    return ContradictionAssessment(
        cluster_id=cluster.cluster_id,
        supporting_evidence_ids=(),
        counter_evidence_ids=(),
        kind=CONTRADICTION_NONE,
        confidence=0.0,
        rationale=reason,
        degraded=True,
    )


def analyze_contradictions(
    clusters: Sequence[ValidatedCluster],
    model: IntelligenceModel,
    *,
    evidence_by_id: Mapping[str, PreparedEvidence],
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
) -> ContradictionOutcome:
    """Classify support vs counter for every cluster, one model call each.

    When `cache` is provided, a hit (same task/prompt version/model/
    evidence set/context) skips the model call entirely (PRD §28).
    """
    if not clusters:
        return ContradictionOutcome()
    ctx = research_context or ResearchContext()
    ctx_dict = ctx.to_dict()
    prompt_version_id = prompt_version(TASK_CONTRADICTION)

    assessments: list[ContradictionAssessment] = []
    warnings: list[str] = []

    for cluster in clusters:
        member_ids = tuple(cluster.evidence_ids)
        members = [
            evidence_by_id[eid] for eid in member_ids if eid in evidence_by_id
        ]
        payload: dict[str, Any] = {
            "cluster_id": cluster.cluster_id,
            "claim": cluster.claim,
            "label": cluster.label,
            "evidence_ids": list(member_ids),
            "evidence_items": model_payloads(members, topic=cluster.claim + " " + ctx.topic),
            "research_context": ctx_dict,
        }
        cache_key: str | None = None
        if cache is not None:
            cache_key = build_cache_key(
                task=TASK_CONTRADICTION,
                prompt_version=prompt_version_id,
                model_id=model.model_id,
                evidence_ids=member_ids,
                research_context=ctx_dict,
            input_payload=payload,
            )
            cached = cache.get(cache_key)
            if cached is not None:
                response = cached
            else:
                response = model.complete_structured(
                    task=TASK_CONTRADICTION,
                    payload=payload,
                    response_schema=CONTRADICTION_RESPONSE_SCHEMA,
                )
                cache.put(cache_key, response)
        else:
            response = model.complete_structured(
                task=TASK_CONTRADICTION,
                payload=payload,
                response_schema=CONTRADICTION_RESPONSE_SCHEMA,
            )
        if not response.ok:
            reason = (
                f"contradiction model unavailable for {cluster.cluster_id}: "
                f"status={response.status.value} error={response.error!r}"
            )
            warnings.append(reason)
            assessments.append(_degraded_assessment(cluster, reason))
            continue

        body = response.payload or {}
        local_warnings: list[str] = []
        degraded = False

        # Schema-conformance guard: counter_evidence_ids must be present and
        # a list. A missing/malformed key means the model did not follow the
        # structured-output contract — degrade rather than trust it.
        raw_counter = body.get("counter_evidence_ids")
        if not isinstance(raw_counter, (list, tuple)):
            local_warnings.append(
                f"{cluster.cluster_id}: malformed contradiction payload — "
                "counter_evidence_ids missing or not a list"
            )
            degraded = True
            counter_raw: list[str] = []
        else:
            counter_raw = _as_id_list(raw_counter)
        kind = str(body.get("kind") or CONTRADICTION_NONE)

        # kind vocabulary guard — unknown values collapse to none.
        if kind not in _VALID_KINDS:
            local_warnings.append(
                f"{cluster.cluster_id}: unknown contradiction kind {kind!r}; "
                "treated as none"
            )
            kind = CONTRADICTION_NONE
            degraded = True

        # id hygiene: counters must belong to THIS cluster.
        valid_member = set(member_ids)
        counter_valid = [eid for eid in counter_raw if eid in valid_member]
        cut = [eid for eid in counter_raw if eid not in valid_member]
        if cut:
            local_warnings.append(
                f"{cluster.cluster_id}: counter ids outside cluster dropped: "
                f"{', '.join(sorted(cut))}"
            )
            degraded = True

        # kind consistency.
        if not counter_valid and kind != CONTRADICTION_NONE:
            local_warnings.append(
                f"{cluster.cluster_id}: kind {kind!r} without counter evidence; "
                "collapsed to none"
            )
            kind = CONTRADICTION_NONE
            degraded = True
        if counter_valid and kind == CONTRADICTION_NONE:
            local_warnings.append(
                f"{cluster.cluster_id}: counter evidence present but kind=none; "
                "contradiction may be under-reported"
            )
            degraded = True

        counter = tuple(sorted(counter_valid))
        support = tuple(eid for eid in member_ids if eid not in counter_valid)
        try:
            confidence = float(body.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
            degraded = True
        confidence = min(1.0, max(0.0, confidence))

        rationale = str(body.get("rationale") or "")
        warnings.extend(local_warnings)
        assessments.append(
            ContradictionAssessment(
                cluster_id=cluster.cluster_id,
                supporting_evidence_ids=support,
                counter_evidence_ids=counter,
                kind=kind,
                confidence=confidence,
                rationale=rationale,
                degraded=degraded,
            )
        )

    assessments.sort(key=lambda a: a.cluster_id)
    return ContradictionOutcome(
        assessments=tuple(assessments), warnings=tuple(warnings)
    )
