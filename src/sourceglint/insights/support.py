"""Phase 6A §16 — support_strength diagnostics.

support_strength is an INTERNAL diagnostics metric (§16) that estimates
how well supported an insight is from structural quantities — never a
frozen-schema field. It deliberately does NOT equal confidence: a model
may be confident while resting on a thin evidence base, and vice versa.

Formula (deterministic; constants are policy, tune via eval):
  FACT      = 0.40 * min(1, n_signals/2)
            + 0.30 * min(1, n_evidence/3)
            + 0.30 * min(1, n_sources/3)
  INFERENCE = 0.35 * min(1, n_signals/2)
            + 0.35 * min(1, n_facts/2)
            + 0.30 * min(1, n_sources/3)
  -0.10 when the insight preserves a contradiction (§17: mixed support)
  -0.10 when any cited signal is weak/emerging (§18)
  clamped to [0.0, 1.0], rounded to 3 decimals.

n_sources counts DISTINCT source identities (url, else source name)
across the insight's cited evidence.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


def _cap(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def distinct_source_count(
    evidence_ids: Iterable[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    """Use the same copied-report/domain rules as the signal layer."""
    from ..intelligence.features import count_reporting_origins
    from ..intelligence.preparation import prepare_evidence
    records = []
    for eid in evidence_ids:
        ev = evidence_by_id.get(eid)
        if ev and (ev.get("url") or ev.get("source")):
            records.append({**ev, "evidence_id": eid})
    return count_reporting_origins(prepare_evidence(records))



def compute_support_strength(
    *,
    insight_type: str,
    n_signals: int,
    n_evidence: int,
    n_sources: int,
    n_facts: int = 0,
    contradiction_preserved: bool = False,
    weak_signal: bool = False,
) -> float:
    """Compute the internal support_strength diagnostic (§16)."""
    strength = 0.0
    if insight_type == "INFERENCE":
        strength += 0.35 * min(1.0, max(0, n_signals) / 2.0)
        strength += 0.35 * min(1.0, max(0, n_facts) / 2.0)
    else:
        strength += 0.40 * min(1.0, max(0, n_signals) / 2.0)
        strength += 0.30 * min(1.0, max(0, n_evidence) / 3.0)
    strength += 0.30 * min(1.0, max(0, n_sources) / 3.0)
    if contradiction_preserved:
        strength -= 0.10
    if weak_signal:
        strength -= 0.10
    return _cap(strength)
