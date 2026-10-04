"""Phase 5 §6 — deterministic evidence preparation.

Everything here is CODE (PRD §4): stable ordering, duplicate suppression,
window defaulting, size bounding, and the minimal model payload. The model
is never shown `raw_metadata`, never shown the full ledger, and never shown
URLs.

Unknown-semantics invariant (Phase 3 Closeout §3): a field the ledger does
not carry is OMITTED or `None` — never synthesised to a neutral middle
value. An evidence item with no `published_at` yields `published_at == ""`,
not "some date". An evidence item with no `evidence_quality` yields `None`,
not 0.5.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from ..ledger import EvidenceLedger
from .dtos import (
    MAX_SNIPPET_CHARS,
    MAX_TITLE_CHARS,
    WINDOW_BASELINE,
    WINDOW_CURRENT,
    PreparedEvidence,
)

_ENGAGEMENT_KEYS = ("upvotes", "comments", "likes", "views", "points")


def _clean_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _read_engagement(payload: Mapping[str, object]) -> dict[str, int]:
    raw = payload.get("engagement")
    if not isinstance(raw, Mapping):
        return {}
    return {
        key: _clean_int(raw.get(key))
        for key in _ENGAGEMENT_KEYS
        if key in raw
    }


def _read_optional_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _read_optional_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def prepare_evidence(
    records: Iterable[Mapping[str, object]] | EvidenceLedger,
    *,
    with_warnings: bool = False,
    max_title_chars: int = MAX_TITLE_CHARS,
    max_snippet_chars: int = MAX_SNIPPET_CHARS,
):
    """Turn ledger records into a stable, size-bounded prepared list.

    Ordering is by `evidence_id` ascending: cluster ids and signal ids are
    derived from these lists, so they must never depend on retrieval order,
    insertion order, or timestamps (PRD §10).

    Returns `list[PreparedEvidence]`, or `(list, warnings)` when
    `with_warnings=True`.
    """
    if isinstance(records, EvidenceLedger):
        records = [record.to_payload() for record in records.all()]

    warnings: list[str] = []
    seen: set[str] = set()
    prepared: list[PreparedEvidence] = []

    # Sort FIRST so duplicate suppression is itself deterministic.
    ordered = sorted(
        records, key=lambda payload: str(payload.get("evidence_id") or "")
    )

    for payload in ordered:
        evidence_id = str(payload.get("evidence_id") or "")
        if not evidence_id:
            warnings.append("record without evidence_id skipped")
            continue
        if evidence_id in seen:
            warnings.append(f"duplicate evidence id dropped: {evidence_id}")
            continue
        seen.add(evidence_id)

        window = str(payload.get("window") or "")
        if window not in (WINDOW_CURRENT, WINDOW_BASELINE):
            # Evidence contract: absent == current.
            window = WINDOW_CURRENT

        title = str(payload.get("title") or "")
        snippet = str(payload.get("snippet") or "")

        prepared.append(
            PreparedEvidence(
                evidence_id=evidence_id,
                source=str(payload.get("source") or ""),
                source_type=str(payload.get("source_type") or ""),
                window=window,
                title=title,
                snippet=snippet,
                published_at=str(payload.get("published_at") or ""),
                market=str(payload.get("market") or ""),
                language=str(payload.get("language") or ""),
                source_tier=_read_optional_int(payload, "source_tier"),
                evidence_quality=_read_optional_float(payload, "evidence_quality"),
                engagement=_read_engagement(payload),
                url=str(payload.get("url") or ""),
                has_text=bool(title or snippet),
                content=str(payload.get("content") or ""),
            )
        )

    if with_warnings:
        return prepared, warnings
    return prepared


def model_payloads(
    prepared: Iterable[PreparedEvidence],
    *,
    max_title_chars: int = MAX_TITLE_CHARS,
    max_snippet_chars: int = MAX_SNIPPET_CHARS,
) -> list[dict]:
    """Convenience helper: the exact list handed to the semantic model."""
    items = list(prepared)
    bodies = sum(bool(item.content) for item in items)
    content_cap = min(6000, 48000 // max(1, bodies))
    return [
        item.to_model_payload(
            max_title_chars=max_title_chars,
            max_snippet_chars=max_snippet_chars,
            max_content_chars=content_cap,
        )
        for item in items
    ]
