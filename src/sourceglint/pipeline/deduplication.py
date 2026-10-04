"""Deduplication (Phase 3 §15/§16).

Phase 2 already provides deterministic Evidence ID dedup at the ledger
level. This module adds two more layers BEFORE the ledger:

  1. Canonical URL dedup (URL canonicalization collapses utm_, trailing
     slash, casing, etc. — same physical item).
  2. Source-native ID dedup within the SAME source (different URLs but
     same platform-internal identifier — e.g. two Reddit comments that
     got permalinked twice).

Semantic / embedding dedup is intentionally NOT implemented in Phase 3.
Suspected reposts are kept and passed downstream.

Provenance (matched_queries, retrieval_count, source_hits) is collected in
pipeline scope. We do NOT mutate the Evidence payload — Phase 1 schema is
strict (additionalProperties:false).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from ..ids import canonicalize_url


@dataclass(frozen=True)
class DedupProvenance:
    """Pipeline-scope metadata for a kept Evidence after dedup.

    Not part of Phase 1 Evidence schema — kept in pipeline metadata for the
    Coverage Report and for downstream clustering.
    """

    evidence_id: str
    matched_queries: tuple[str, ...] = field(default_factory=tuple)
    source_hits: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    retrieval_count: int = 1


@dataclass(frozen=True)
class DedupResult:
    kept: list[dict]
    provenance: dict[str, DedupProvenance]
    input_count: int = 0
    kept_count: int = 0
    duplicate_count: int = 0

    def provenance_for(self, evidence_id: str) -> DedupProvenance | None:
        return self.provenance.get(evidence_id)


class Deduplicator:
    """Stateless multi-layer deduplicator."""

    def deduplicate(self, items: Iterable[Mapping[str, object]]) -> DedupResult:
        return deduplicate(items)


def _dedup_keys(item: Mapping[str, object]) -> tuple[str, str]:
    """Return (canonical_url_key, source_native_id_key) for an Evidence item.

    Keys are stable strings suitable for set/dict membership. Empty strings
    are returned when the field is absent (key not eligible for that layer).
    """
    url_key = canonicalize_url(str(item.get("url") or ""))
    source = str(item.get("source") or "")
    native = str(item.get("source_native_id") or "")
    if source and native:
        native_key = f"{source}::{native}"
    else:
        native_key = ""
    return url_key, native_key


def deduplicate(items: Iterable[Mapping[str, object]]) -> DedupResult:
    """Multi-layer dedup, preserving first-occurrence order."""
    items_list = list(items)
    kept: list[dict] = []
    provenance: dict[str, DedupProvenance] = {}

    # First seen -> canonical url -> evidence_id mapping.
    by_url: dict[str, str] = {}
    # First seen -> (source, native_id) -> evidence_id mapping.
    by_native: dict[str, str] = {}

    kept_by_id = {}
    dup_count = 0
    for item in items_list:
        if not isinstance(item, Mapping):
            continue
        eid = str(item.get("evidence_id") or "")
        if not eid:
            continue
        url_key, native_key = _dedup_keys(item)

        # First check exact evidence_id collision with kept items.
        canonical_owner = by_url.get(url_key)
        native_owner = by_native.get(native_key) if native_key else None
        owner = eid if eid in kept_by_id else canonical_owner or native_owner

        if owner is None:
            # First occurrence — keep.
            record = dict(item)
            kept.append(record)
            kept_by_id[eid] = record
            if url_key:
                by_url[url_key] = eid
            if native_key:
                by_native[native_key] = eid
            provenance[eid] = _make_provenance(item)
        elif owner == eid:
            # Same evidence_id seen again — provenance bump, no second kept.
            dup_count += 1
            provenance[eid] = _bump_provenance(provenance[eid], item)
            _merge_body(kept_by_id[eid], item)
        else:
            # Different evidence_id, same url or native_id — collapse to owner.
            dup_count += 1
            provenance[owner] = _bump_provenance(provenance[owner], item)
            _merge_body(kept_by_id[owner], item)

        # Register all aliases, including URLs/native IDs first observed on
        # a duplicate, so later host fetches cannot reintroduce the same item.
        kept_owner = owner or eid
        if url_key:
            by_url[url_key] = kept_owner
        if native_key:
            by_native[native_key] = kept_owner

    return DedupResult(
        kept=kept,
        provenance=provenance,
        input_count=len(items_list),
        kept_count=len(kept),
        duplicate_count=dup_count,
    )


def _make_provenance(item: Mapping[str, object]) -> DedupProvenance:
    eid = str(item.get("evidence_id") or "")
    source = str(item.get("source") or "")
    native = str(item.get("source_native_id") or "")
    query = str(item.get("query") or "")
    matched_queries = (query,) if query else ()
    source_hits = ((source, native),) if source and native else ()
    return DedupProvenance(
        evidence_id=eid,
        matched_queries=matched_queries,
        source_hits=source_hits,
        retrieval_count=1,
    )


def _bump_provenance(prov: DedupProvenance, item: Mapping[str, object]) -> DedupProvenance:
    """Return a NEW DedupProvenance with one more hit recorded."""
    source = str(item.get("source") or "")
    native = str(item.get("source_native_id") or "")
    query = str(item.get("query") or "")

    new_matched = prov.matched_queries
    if query and query not in prov.matched_queries:
        new_matched = prov.matched_queries + (query,)

    new_hits = prov.source_hits
    if source and native and (source, native) not in prov.source_hits:
        new_hits = prov.source_hits + ((source, native),)

    return DedupProvenance(
        evidence_id=prov.evidence_id,
        matched_queries=new_matched,
        source_hits=new_hits,
        retrieval_count=prov.retrieval_count + 1,
    )

def _merge_body(kept, incoming):
    """Keep canonical identity/quote/date; enrich only compatible source bodies."""
    for key in ("published_at", "author"):
        if kept.get(key) and incoming.get(key) and kept[key] != incoming[key]:
            return
    body = str(incoming.get("content") or "")
    current = str(kept.get("content") or "")
    if len(body) > len(current):
        quote = str(kept.get("snippet") or "").strip()
        if not quote or quote in body or (current and current in body):
            kept["content"] = body
