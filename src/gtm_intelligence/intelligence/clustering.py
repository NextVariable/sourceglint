"""Phase 5 §7–§11, §33–§34 — semantic clustering and validation.

What the model owns (PRD §4): grouping evidence by semantic equivalence,
choosing a `label` and a `claim`, per-cluster `confidence`.

What CODE owns here:
  * the payload sent to the model (minimal fields, research context only);
  * hallucinated-id rejection   (PRD §11)  — ids not in the input are cut;
  * empty-cluster rejection                — a cluster with no valid id is cut;
  * single-membership enforcement (PRD §33, §34) — each evidence id may
    belong to ONE cluster (first occurrence wins; later duplicates are cut,
    which can empty and thereby drop a secondary cluster);
  * cluster_id derivation (PRD §10) — `cl_<sha256(sorted evidence ids)>`,
    never derived from a model label;
  * deterministic output order — clusters sorted by cluster_id.

The model is never allowed to invent evidence, mint ids, or force every
item into a cluster (precision over recall, PRD §8): unassigned evidence
is legal and silent.

Failure semantics (PRD §27): clustering is a REQUIRED step. If the model
reports anything but SUCCESS, or every emitted cluster is invalid, the
pipeline cannot proceed and `IntelligencePipelineError` is raised. Partial
loss (one bad cluster among several good ones) degrades instead: the bad
cluster is dropped, a warning is recorded, `degraded=True`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .dtos import ClusterDraft, PreparedEvidence, ResearchContext, ValidatedCluster
from .ids import derive_cluster_id
from .model import (
    CLUSTERING_RESPONSE_SCHEMA,
    IntelligenceModel,
    IntelligencePipelineError,
    ModelResponse,
    ModelStatus,
)
from .preparation import model_payloads
from .prompts import TASK_CLUSTERING

#: Keys that must exist on the model payload envelope.
_CLUSTER_KEYS = ("label", "claim", "evidence_ids")


@dataclass(frozen=True)
class ClusteringOutcome:
    """Internal result of the clustering step (not a frozen-schema object)."""

    clusters: tuple[ValidatedCluster, ...]
    warnings: tuple[str, ...] = ()
    degraded: bool = False

    def to_dict(self) -> dict:
        return {
            "clusters": [c.to_dict() for c in self.clusters],
            "warnings": list(self.warnings),
            "degraded": self.degraded,
        }


def _as_draft(item: Mapping[str, Any]) -> ClusterDraft | None:
    """Best-effort conversion of one raw cluster dict into a ClusterDraft.

    Returns None (and the caller records a warning) when the item is too
    malformed to use. The frozen schema already enforces label/claim/
    evidence_ids on a conforming host, but the fake model and defensive
    code paths can still produce junk here.
    """
    label = str(item.get("label") or "").strip()
    claim = str(item.get("claim") or "").strip()
    raw_ids = item.get("evidence_ids")
    if not label or not claim:
        return None
    if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
        return None
    evidence_ids = tuple(str(eid) for eid in raw_ids if str(eid))
    if not evidence_ids:
        return None
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    rationale = str(item.get("rationale") or "")
    return ClusterDraft(
        label=label,
        claim=claim,
        evidence_ids=evidence_ids,
        confidence=confidence,
        rationale=rationale,
    )


def validate_clusters(
    known_evidence_ids: Iterable[str],
    drafts: Iterable[ClusterDraft],
) -> tuple[list[ValidatedCluster], list[str]]:
    """Pure validation: turn model drafts into code-verified clusters.

    Rules (in application order, per draft):
      1. ids not present in `known_evidence_ids` are hallucinated → cut;
      2. a draft left with zero valid ids is dropped;
      3. an id already claimed by an earlier cluster is cut here
         (single-membership / no double count);
      4. a draft left with zero *new* ids is dropped;
      5. two drafts with the SAME evidence set would mint the SAME
         cluster_id → the later one is dropped.

    Returns `(clusters, warnings)`. `clusters` is deterministic: sorted by
    cluster_id. Evidence id tuples inside each cluster are sorted too, so
    membership never depends on model output order.
    """
    known = {str(eid) for eid in known_evidence_ids}
    warnings: list[str] = []
    clusters: list[ValidatedCluster] = []
    claimed: set[str] = set()
    seen_cluster_ids: set[str] = set()

    for draft in drafts:
        if draft.evidence_ids:
            valid = [eid for eid in draft.evidence_ids if eid in known]
            hallucinated = len(draft.evidence_ids) - len(valid)
        else:
            valid = []
            hallucinated = 0
        if hallucinated:
            dropped = [eid for eid in draft.evidence_ids if eid not in known]
            warnings.append(
                f"cluster '{draft.label}' cites unknown evidence ids: "
                f"{', '.join(sorted(dropped))}"
            )
        if not valid:
            warnings.append(f"cluster '{draft.label}' has no valid evidence ids; dropped")
            continue
        new_ids = [eid for eid in valid if eid not in claimed]
        if len(new_ids) != len(valid):
            dup = [eid for eid in valid if eid in claimed]
            warnings.append(
                f"evidence {', '.join(sorted(dup))} already assigned to an earlier "
                f"cluster; removed from '{draft.label}'"
            )
        if not new_ids:
            warnings.append(
                f"cluster '{draft.label}' has no new evidence after overlap removal; dropped"
            )
            continue
        ordered = tuple(sorted(new_ids))
        cluster_id = derive_cluster_id(ordered)
        if cluster_id in seen_cluster_ids:
            warnings.append(
                f"cluster '{draft.label}' duplicates an earlier evidence set; dropped"
            )
            continue
        seen_cluster_ids.add(cluster_id)
        claimed.update(ordered)
        clusters.append(
            ValidatedCluster(
                cluster_id=cluster_id,
                label=draft.label,
                claim=draft.claim,
                evidence_ids=ordered,
                confidence=draft.confidence,
                rationale=draft.rationale,
            )
        )

    clusters.sort(key=lambda c: c.cluster_id)
    return clusters, warnings


def cluster(
    prepared: Iterable[PreparedEvidence],
    model: IntelligenceModel,
    *,
    research_context: ResearchContext | None = None,
) -> ClusteringOutcome:
    """Run the semantic-clustering step for one prepared evidence set.

    `prepared` is sorted by evidence_id by `prepare_evidence`; we re-sort
    defensively so the payload handed to the model (and the derived ids)
    never depend on caller order.
    """
    items = sorted(prepared, key=lambda e: e.evidence_id)
    if not items:
        raise ValueError("no evidence to cluster")
    ctx = research_context or ResearchContext()
    payload: dict[str, Any] = {
        "evidence_items": model_payloads(items),
        "research_context": ctx.to_dict(),
    }
    response: ModelResponse = model.complete_structured(
        task=TASK_CLUSTERING,
        payload=payload,
        response_schema=CLUSTERING_RESPONSE_SCHEMA,
    )
    if not response.ok:
        raise IntelligencePipelineError(
            f"clustering failed: status={response.status.value} "
            f"error={response.error!r}"
        )
    raw_clusters = (response.payload or {}).get("clusters")
    if not isinstance(raw_clusters, list):
        raise IntelligencePipelineError("clustering failed: payload has no clusters list")

    drafts: list[ClusterDraft] = []
    warnings: list[str] = []
    for index, item in enumerate(raw_clusters):
        if not isinstance(item, Mapping):
            warnings.append(f"cluster item #{index} is not an object; dropped")
            continue
        draft = _as_draft(item)
        if draft is None:
            warnings.append(f"cluster item #{index} is malformed (label/claim/ids); dropped")
            continue
        drafts.append(draft)

    clusters, validate_warnings = validate_clusters(
        (e.evidence_id for e in items), drafts
    )
    warnings.extend(validate_warnings)
    if not clusters:
        raise IntelligencePipelineError(
            "clustering failed: no usable clusters after validation"
        )
    return ClusteringOutcome(
        clusters=tuple(clusters),
        warnings=tuple(warnings),
        degraded=bool(warnings),
    )
