"""Phase 5 §14–§15, §24–§26 — signal construction from a validated cluster.

A signal is the per-cluster object that reaches the FROZEN
`schemas/signal.schema.json` (additionalProperties: false). Code builds it
from cluster + features + contradiction + factors; the model never mints
signal fields.

signal_type is a SINGLE enum (user-confirmed decision, PRD §3), decided
in this priority order:

  contradictory — the contradiction assessment found counter evidence
                  (counter_evidence_ids non-empty);
  cross_source  — two or more INDEPENDENT reporting origins (features);
  repeated      — a single origin (below cross-source bar) whose topic
                  appears in BOTH windows (still being discussed);
  emerging      — single origin, topic absent from the baseline window
                  (only inferred when a baseline window exists at all —
                  no baseline ⇒ no claim of emergence, Closeout §3);
  single_source — the deterministic fallback.

The dict a builder emits is schema-shaped by construction: only the keys
that exist on signal.schema.json are ever written, evidence ids are the
cluster's own (already code-validated), and contradictory ⇒ counter ids.
validate_signal_contract() re-checks those invariants so any future drift
fails loudly instead of silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .. import scoring
from .contradiction import ContradictionAssessment
from .dtos import (
    PreparedEvidence,
    SignalDiagnostics,
    SignalFeatures,
    ValidatedCluster,
    WeakSignalAssessment,
)
from .factors import FactorSet
from .ids import derive_signal_id, is_valid_signal_id
from .weak_signal import assess as assess_weak_signal

#: signal.schema.json — the ONLY keys a signal dict may carry.
SIGNAL_SCHEMA_KEYS = (
    "signal_id",
    "topic",
    "evidence_ids",
    "representative_evidence_ids",
    "source_diversity",
    "volume",
    "recency",
    "signal_type",
    "novelty",
    "score",
    "confidence",
    "supporting_evidence_ids",
    "counter_evidence_ids",
    "contradiction_assessed",
)

SIGNAL_TYPES = ("single_source", "cross_source", "repeated", "emerging", "contradictory")

CROSS_SOURCE_MIN_ORIGINS = 2
MAX_REPRESENTATIVES = 3


def classify_signal_type(
    features: SignalFeatures,
    assessment: ContradictionAssessment,
) -> str:
    """Single-enum classification (priority order, see module docstring)."""
    if assessment.counter_evidence_ids:
        return "contradictory"
    if features.independent_source_count >= CROSS_SOURCE_MIN_ORIGINS:
        return "cross_source"
    if features.baseline_count and features.current_count:
        return "repeated"
    if features.appeared_only_current:
        return "emerging"
    return "single_source"


def _representative_ids(
    cluster: ValidatedCluster,
    evidence_by_id: Mapping[str, PreparedEvidence],
) -> tuple[str, ...]:
    """Deterministic code-side subset: text-bearing members first (sorted),
    capped at MAX_REPRESENTATIVES; falls back to plain sorted ids."""
    with_text = sorted(
        eid for eid in cluster.evidence_ids
        if evidence_by_id.get(eid) is not None and evidence_by_id[eid].has_text
    )
    if with_text:
        return tuple(with_text[:MAX_REPRESENTATIVES])
    return tuple(cluster.evidence_ids[:MAX_REPRESENTATIVES])


def _reason_map(
    factor_set: FactorSet,
    cluster: ValidatedCluster,
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    rationale = factor_set.semantic_flags.get("decision_relevance_rationale")
    if isinstance(rationale, str) and rationale:
        reasons["decision_relevance"] = rationale
    for warning in factor_set.warnings:
        for name in ("evidence quality", "recency", "novelty", "decision_relevance"):
            if name in warning:
                reasons.setdefault(name.replace(" ", "_"), warning)
    return reasons


def build_signal(
    cluster: ValidatedCluster,
    features: SignalFeatures,
    assessment: ContradictionAssessment,
    factor_set: FactorSet,
    *,
    evidence_by_id: Mapping[str, PreparedEvidence],
    cfg: scoring.ScoringConfig | None = None,
) -> tuple[dict, SignalDiagnostics]:
    """Build one frozen-schema signal dict + its full diagnostics trail."""
    signal_type = classify_signal_type(features, assessment)
    breakdown = scoring.compute_score(factor_set.factors, cfg=cfg)

    raw_factors = dict(factor_set.factors)
    effective = {
        name: comp["clamped_value"]
        for name, comp in breakdown.components.items()
    }
    clamped = {
        name: bool(comp["was_clamped"])
        for name, comp in breakdown.components.items()
    }

    weak: WeakSignalAssessment = assess_weak_signal(
        features=features,
        decision_relevance=factor_set.decision_relevance,
        semantic_novelty=factor_set.semantic_flags.get("semantic_novelty"),
        code_novelty=factor_set.novelty,
    )

    signal_id = derive_signal_id(cluster.cluster_id)
    diagnostics = SignalDiagnostics(
        signal_id=signal_id,
        cluster_id=cluster.cluster_id,
        raw_factors=raw_factors,
        effective_factors=effective,
        clamped_factors=clamped,
        score=float(breakdown.score),
        reasons=_reason_map(factor_set, cluster),
        warnings=factor_set.warnings,
        weak_signal=weak,
        semantic_flags=dict(factor_set.semantic_flags),
    )

    signal: dict[str, Any] = {
        "signal_id": signal_id,
        "topic": cluster.label,
        "evidence_ids": list(cluster.evidence_ids),
        "representative_evidence_ids": list(
            _representative_ids(cluster, evidence_by_id)
        ),
        "source_diversity": max(1, int(features.independent_source_count)),
        "volume": int(features.evidence_count),
        "recency": float(factor_set.recency),
        "signal_type": signal_type,
        "novelty": float(factor_set.novelty),
        "score": float(breakdown.score),
        "confidence": 0.0 if assessment.degraded else float(cluster.confidence),
        "supporting_evidence_ids": [] if assessment.degraded else list(assessment.supporting_evidence_ids),
        "contradiction_assessed": not assessment.degraded,
        "counter_evidence_ids": list(assessment.counter_evidence_ids),
    }
    # schema-shaped by construction: no key outside SIGNAL_SCHEMA_KEYS.
    assert set(signal) <= set(SIGNAL_SCHEMA_KEYS)
    return signal, diagnostics


def validate_signal_contract(signal: Mapping[str, Any]) -> list[str]:
    """Code-side invariants mirroring signal.schema.json + semantic rules.

    Full JSON Schema validation happens at the pipeline boundary; this is a
    fast, dependency-free re-check of the rules that are easiest to drift:
    required keys, allowed keys, id pattern, contradictory ⇒ counter ids.
    Returns a list of violations (empty = OK).
    """
    violations: list[str] = []
    missing = [k for k in ("signal_id", "topic", "evidence_ids", "signal_type") if k not in signal]
    if missing:
        violations.append(f"missing required keys: {', '.join(missing)}")
        return violations
    extra = sorted(set(signal) - set(SIGNAL_SCHEMA_KEYS))
    if extra:
        violations.append(f"keys outside signal.schema.json: {', '.join(extra)}")
    if not is_valid_signal_id(str(signal["signal_id"])):
        violations.append(f"signal_id does not match sig_ pattern: {signal['signal_id']!r}")
    if not signal["evidence_ids"]:
        violations.append("evidence_ids must not be empty")
    signal_type = signal["signal_type"]
    if signal_type not in SIGNAL_TYPES:
        violations.append(f"unknown signal_type: {signal_type!r}")
    if signal_type == "contradictory" and not signal.get("counter_evidence_ids"):
        violations.append("contradictory signal must carry counter_evidence_ids")
    return violations
