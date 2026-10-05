"""Phase 5 §38 — the intelligence pipeline orchestrator.

Evidence Ledger
  → prepare_evidence()        preparation.py   (code)
  → cluster()                 clustering.py    (model groups, code validates)
  → derive_features()         features.py      (code, no model)
  → analyze_contradictions()  contradiction.py (model per cluster, code checks)
  → derive_factors()          factors.py       (code + semantic model per cluster)
  → build_signal()            signals.py       (code; frozen schema dict)
  → validate_signal_contract()                 (code gate)
  → IntelligencePipelineResult

Determinism: evidence ids, cluster ids and signal ids are code-derived;
output ordering is score-desc / signal_id-asc, never model order. The one
time input is `as_of` — REQUIRED so recency (and therefore score) is
reproducible for the same instant.

Failure semantics (PRD §27): clustering is required and raises
IntelligencePipelineError when unusable; every later step degrades with a
stage-prefixed warning instead of raising. A cluster whose evidence only
exists in the baseline window is not a CURRENT signal: it is dropped by
default (`drop_baseline_only=True`) with a warning.

The result carries signals as frozen-schema dicts only — no insight,
recommendation, or brief (PRD §47 stop boundary).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from .. import scoring
from ..ledger import EvidenceLedger
from .cache import SemanticCache
from .clustering import ClusteringOutcome, cluster
from .contradiction import ContradictionAssessment, analyze_contradictions
from .dtos import (
    IntelligencePipelineResult,
    ResearchContext,
    ValidatedCluster,
)
from .factors import FactorSet, derive_factors
from .features import build_evidence_index, derive_all_features
from .preparation import prepare_evidence
from .signals import build_signal, validate_signal_contract

_CLUSTERING_STAGE = "clustering"
_CONTRADICTION_STAGE = "contradiction"
_SEMANTIC_STAGE = "semantic_factors"


def _stage_status(ok_all: bool, degraded_any: bool) -> str:
    if degraded_any:
        return "partial"
    return "success" if ok_all else "partial"


def run_intelligence_pipeline(
    records: Iterable[Mapping[str, object]] | EvidenceLedger,
    model,
    *,
    as_of: datetime,
    research_context: ResearchContext | None = None,
    cache: SemanticCache | None = None,
    cfg: scoring.ScoringConfig | None = None,
    drop_baseline_only: bool = True,
) -> IntelligencePipelineResult:
    """Run the full Evidence → Cluster → Signal pipeline (Phase 5).

    Returns an `IntelligencePipelineResult`; raises `ValueError` for empty
    input and `IntelligencePipelineError` when clustering (the required
    semantic step) cannot produce usable output.
    """
    prepared, prep_warnings = prepare_evidence(records, with_warnings=True)
    warnings: list[str] = [f"prepare: {w}" for w in prep_warnings]
    if not prepared:
        warnings.append("prepare: no evidence to analyse")
        return IntelligencePipelineResult(warnings=tuple(warnings))

    ctx = research_context or ResearchContext()
    clustering_outcome: ClusteringOutcome = cluster(
        prepared, model, research_context=ctx, cache=cache
    )
    warnings.extend(f"cluster: {w}" for w in clustering_outcome.warnings)

    evidence_index = build_evidence_index(prepared)
    clusters: tuple[ValidatedCluster, ...] = clustering_outcome.clusters
    all_features = {
        feat.cluster_id: feat
        for feat in derive_all_features(clusters, prepared)
    }

    contradiction_outcome = analyze_contradictions(
        clusters, model,
        evidence_by_id=evidence_index,
        research_context=ctx,
        cache=cache,
    )
    assessments = {
        a.cluster_id: a for a in contradiction_outcome.assessments
    }
    warnings.extend(
        f"{_CONTRADICTION_STAGE}: {w}" for w in contradiction_outcome.warnings
    )

    signals: list[dict] = []
    diagnostics = []
    factor_sets: list[FactorSet] = []
    semantic_degraded = False

    for cluster_item in clusters:
        features = all_features.get(cluster_item.cluster_id)
        if features is None:
            continue
        # A pure-baseline cluster is not a current signal.
        if drop_baseline_only and features.baseline_count and not features.current_count:
            warnings.append(
                f"signals: cluster {cluster_item.cluster_id} only exists in the "
                "baseline window; not a current signal"
            )
            continue
        assessment = assessments.get(cluster_item.cluster_id)
        if assessment is None:
            # Cannot happen when contradiction ran, but stay total.
            assessment = ContradictionAssessment(cluster_id=cluster_item.cluster_id)
        fset = derive_factors(
            cluster_item, features, evidence_index, as_of,
            model=model, research_context=ctx, cache=cache,
        )
        factor_sets.append(fset)
        semantic_degraded = semantic_degraded or fset.degraded
        signal, diag = build_signal(
            cluster_item, features, assessment, fset,
            evidence_by_id=evidence_index, cfg=cfg,
        )
        violations = validate_signal_contract(signal)
        if violations:
            warnings.append(
                f"signals: contract violation for {signal.get('signal_id')}: "
                f"{'; '.join(violations)}"
            )
            continue
        signals.append(signal)
        diagnostics.append(diag)

    # Deterministic order: score desc, then signal_id asc.
    signals.sort(key=lambda s: (-float(s["score"]), str(s["signal_id"])))
    diagnostics.sort(key=lambda d: (-float(d.score), d.signal_id))

    model_status = {
        _CLUSTERING_STAGE: _stage_status(True, clustering_outcome.degraded),
        _CONTRADICTION_STAGE: _stage_status(
            True, bool(contradiction_outcome.warnings)
        ),
        _SEMANTIC_STAGE: _stage_status(True, semantic_degraded),
    }

    return IntelligencePipelineResult(
        signals=tuple(signals),
        clusters=clusters,
        diagnostics=tuple(diagnostics),
        warnings=tuple(warnings),
        model_status=model_status,
    )
