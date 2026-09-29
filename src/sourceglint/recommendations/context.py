"""Phase 6B §9 — deterministic decision-context preparation.

Turns validated Phase 6A FACT/INFERENCE insight dicts into minimal
PreparedInsight objects for the recommendation model. Everything here
is CODE: stable ordering, weak/contradiction flag injection from the
6A diagnostics, GTM implication extraction.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .dtos import PreparedInsight

#: Weak/contradiction keys accepted in an optional diagnostics mapping
#: keyed by insight_id (6A InsightDiagnostics.to_dict() shape).
_WEAK_KEY = "weak_signal"
_CONTRA_KEY = "contradiction_preserved"


def _flag(diag: Mapping[str, Any] | None, key: str) -> bool:
    if diag is None:
        return False
    value = diag.get(key)
    return bool(value) if isinstance(value, (bool, int)) else False


def _as_gtm(insight: Mapping[str, Any]) -> Mapping[str, str | None]:
    gtm = insight.get("gtm_implications")
    if isinstance(gtm, Mapping):
        return {str(k): (v if v is None else str(v)) for k, v in gtm.items()}
    return {}


def prepare_decision_context(
    insights: Iterable[Mapping[str, Any]],
    *,
    insight_diagnostics: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[PreparedInsight], list[str]]:
    """Build the model-facing decision context (§9).

    Input insights are validated FACT/INFERENCE dicts (6A output).
    Diagnostics carry weak/contradiction flags per insight; when absent
    both default to False (code is conservative — no invented flags).

    Returns (prepared sorted by insight_id, warnings).
    """
    diags = insight_diagnostics or {}
    warnings: list[str] = []
    prepared: list[PreparedInsight] = []

    ordered = sorted(
        insights, key=lambda i: str(i.get("insight_id") or "")
    )
    for ins in ordered:
        ins_id = str(ins.get("insight_id") or "")
        if not ins_id:
            warnings.append("insight without insight_id skipped")
            continue
        ins_type = str(ins.get("type") or "")
        if ins_type not in ("FACT", "INFERENCE"):
            warnings.append(f"non FACT/INFERENCE insight skipped: {ins_id} ({ins_type})")
            continue
        prepared.append(PreparedInsight(
            insight_id=ins_id,
            type=ins_type,
            statement=str(ins.get("statement") or ""),
            confidence=float(ins.get("confidence") or 0.0),
            gtm_implications=_as_gtm(ins),
            weak_signal=_flag(diags.get(ins_id), _WEAK_KEY),
            contradiction_preserved=_flag(diags.get(ins_id), _CONTRA_KEY),
        ))

    return prepared, warnings
