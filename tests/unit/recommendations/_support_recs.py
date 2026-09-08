"""Shared fixtures for Phase 6B recommendation tests (offline).

Mirrors the insight-layer _support pattern but lives under
tests/unit/recommendations (no cross-tree shadowing — unit dirs have
__init__.py in this project, but keep the import explicit anyway).
"""
from __future__ import annotations

from typing import Any, Mapping

from gtm_intelligence.insights.ids import derive_insight_id


def insight_fact(
    *,
    insight_id: str | None = None,
    signal_ids: tuple[str, ...] = ("sig_a",),
    evidence_ids: tuple[str, ...] = ("ev_1",),
    statement: str = "The official pricing page lists the Team plan at $15.",
    confidence: float = 0.8,
    gtm_implications: Mapping[str, str] | None = None,
) -> dict:
    iid = insight_id or derive_insight_id(
        type="FACT", signal_ids=signal_ids, evidence_ids=evidence_ids
    )
    ins: dict[str, Any] = {
        "insight_id": iid,
        "type": "FACT",
        "statement": statement,
        "signal_ids": list(signal_ids),
        "evidence_ids": list(evidence_ids),
        "confidence": confidence,
    }
    if gtm_implications:
        ins["gtm_implications"] = dict(gtm_implications)
    return ins


def insight_inference(
    *,
    insight_id: str | None = None,
    signal_ids: tuple[str, ...] = ("sig_b",),
    evidence_ids: tuple[str, ...] = ("ev_2",),
    statement: str = "Individual users appear more price-sensitive than enterprise buyers.",
    confidence: float = 0.6,
    gtm_implications: Mapping[str, str] | None = None,
) -> dict:
    iid = insight_id or derive_insight_id(
        type="INFERENCE", signal_ids=signal_ids, evidence_ids=evidence_ids
    )
    ins: dict[str, Any] = {
        "insight_id": iid,
        "type": "INFERENCE",
        "statement": statement,
        "signal_ids": list(signal_ids),
        "evidence_ids": list(evidence_ids),
        "confidence": confidence,
    }
    if gtm_implications:
        ins["gtm_implications"] = dict(gtm_implications)
    return ins


def evidence(
    evidence_id: str,
    *,
    url: str = "https://example.com/",
    snippet: str = "",
    title: str = "",
    source: str = "example",
    market: str = "jp",
    language: str = "ja",
    window: str = "current",
) -> dict:
    ev: dict[str, Any] = {
        "evidence_id": evidence_id,
        "url": url,
        "source": source,
        "market": market,
        "language": language,
        "window": window,
    }
    if snippet:
        ev["snippet"] = snippet
    if title:
        ev["title"] = title
    return ev


def diagnostics_map(
    *,
    weak: tuple[str, ...] = (),
    contradiction: tuple[str, ...] = (),
) -> dict[str, dict]:
    """insight_id → diag-dict map keyed like 6A InsightDiagnostics."""
    out: dict[str, dict] = {}
    for iid in weak:
        d = out.setdefault(iid, {})
        d["weak_signal"] = True
    for iid in contradiction:
        d = out.setdefault(iid, {})
        d["contradiction_preserved"] = True
    return out


def evidence_by_id(*items: dict) -> dict[str, dict]:
    return {e["evidence_id"]: e for e in items}


def insight_by_id(*insights: dict) -> dict[str, dict]:
    return {i["insight_id"]: i for i in insights}
