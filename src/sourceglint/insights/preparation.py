"""Phase 6A §10 — deterministic signal preparation for insight synthesis.

Everything here is CODE (PRD §6): stable ordering, evidence summary
extraction, code-computed counts (PRD §37), weak-signal flag injection.

The model never sees: score, confidence, engagement, URL, raw_metadata.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .dtos import PreparedSignal

WINDOW_CURRENT = "current"
WINDOW_BASELINE = "baseline"


def _extract_summary(ev: Mapping[str, Any] | None) -> str:
    """Extract the best available text summary from an evidence item."""
    if ev is None:
        return ""
    content = str(ev.get("content") or "")
    if content:
        from ..excerpts import select_excerpt
        return select_excerpt(content, str(ev.get("query") or ev.get("title") or ""), 6000)
    snippet = str(ev.get("snippet") or "")
    if snippet:
        return snippet
    title = str(ev.get("title") or "")
    return title


def _count_windows(
    evidence_ids: Iterable[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    """Count current vs baseline evidence (code-computed, PRD §37)."""
    current = 0
    baseline = 0
    for eid in evidence_ids:
        ev = evidence_by_id.get(eid)
        if ev is None:
            continue
        window = str(ev.get("window") or "")
        if window == WINDOW_BASELINE:
            baseline += 1
        else:
            current += 1
    return current, baseline


def prepare_signals(
    signals: Iterable[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    weak_signal_ids: set[str] | None = None,
    with_warnings: bool = True,
) -> tuple[list[PreparedSignal], list[str]]:
    """Turn Phase 5 signal dicts into minimal PreparedSignal DTOs.

    Signals are sorted by signal_id for determinism (same input → same
    order → same model call sequence → same cache key).

    Returns `(prepared_list, warnings)`.
    """
    weak_ids = weak_signal_ids or set()
    warnings: list[str] = []
    prepared: list[PreparedSignal] = []

    ordered = sorted(
        signals, key=lambda s: str(s.get("signal_id") or "")
    )

    for sig in ordered:
        signal_id = str(sig.get("signal_id") or "")
        if not signal_id:
            warnings.append("signal without signal_id skipped")
            continue

        if sig.get("contradiction_assessed") is False:
            warnings.append(f"signal {signal_id}: contradiction unassessed; excluded from fact synthesis")
            continue
        evidence_ids = tuple(str(eid) for eid in sig.get("evidence_ids") or [])
        supporting_ids = [str(eid) for eid in (sig["supporting_evidence_ids"] if "supporting_evidence_ids" in sig else evidence_ids)]
        counter_ids = [str(eid) for eid in sig.get("counter_evidence_ids") or []]

        supporting_summaries = tuple(
            s for s in (_extract_summary(evidence_by_id.get(eid)) for eid in supporting_ids)
            if s
        )
        counter_summaries = tuple(
            s for s in (_extract_summary(evidence_by_id.get(eid)) for eid in counter_ids)
            if s
        )

        # Warn about missing evidence
        missing = [eid for eid in evidence_ids if eid not in evidence_by_id]
        for eid in missing:
            warnings.append(f"signal {signal_id}: evidence {eid} not found in ledger")

        current_count, baseline_count = _count_windows(evidence_ids, evidence_by_id)

        # Derive market/language from first available evidence
        market = ""
        language = ""
        for eid in evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev is not None:
                market = str(ev.get("market") or "")
                language = str(ev.get("language") or "")
                break

        prepared.append(PreparedSignal(
            signal_id=signal_id,
            signal_type=str(sig.get("signal_type") or "single_source"),
            claim=str(sig.get("topic") or ""),
            score=float(sig.get("score") or 0.0),
            confidence=float(sig.get("confidence") or 0.0),
            evidence_ids=evidence_ids,
            supporting_evidence_summaries=supporting_summaries,
            counter_evidence_summaries=counter_summaries,
            market=market,
            language=language,
            current_count=current_count,
            baseline_count=baseline_count,
            weak_signal=signal_id in weak_ids,
        ))

    if not with_warnings:
        return prepared, warnings
    return prepared, warnings
