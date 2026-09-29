"""Tests for Deduplication (Phase 3 §15/§16).

Contract:
  * Multi-layer dedup (Phase 2 already provides Evidence ID dedup via ledger).
  * Layer 1: canonical URL — same canonical URL -> duplicate
  * Layer 2: source-native ID within same source — duplicate
  * Layer 3 (reserved): semantic dedup NOT implemented in Phase 3 (no
    embedding similarity; suspected reposts kept)
  * Dedup preserves provenance metadata in pipeline scope (NOT in Evidence):
      - matched_queries: list of query texts that surfaced the same item
      - retrieval_count: how many retrieval requests matched
      - source_hits: list of (source, native_id) that observed it
  * Dedup never mutates the Evidence payload schema — provenance goes in
    a sibling DTO called DedupProvenance.
  * Order is preserved: first occurrence wins; later occurrences contribute
    to provenance but are dropped from the kept list.
"""
from __future__ import annotations

from sourceglint.pipeline.deduplication import (
    DedupProvenance,
    Deduplicator,
    deduplicate,
)


def _ev(evidence_id: str, url: str, source: str = "reddit",
        source_native_id: str = "", window: str = "current", **overrides) -> dict:
    base = {
        "evidence_id": evidence_id,
        "source": source,
        "source_type": "post",
        "url": url,
        "title": "t",
        "snippet": "s",
        "retrieved_at": "2026-09-06T10:00:00Z",
        "window": window,
    }
    if source_native_id:
        base["source_native_id"] = source_native_id  # not in schema, kept for dedup only
    base.update(overrides)
    return base


def test_exact_evidence_id_dedup_keeps_first():
    a = _ev("ev_1", "https://a.example.com/1")
    b = _ev("ev_1", "https://a.example.com/1")  # same id
    res = deduplicate([a, b])
    assert len(res.kept) == 1
    assert res.kept[0]["evidence_id"] == "ev_1"


def test_canonical_url_dedup():
    """Same canonical URL (different casing/utm) → same dedup key."""
    a = _ev("ev_a", "HTTPS://Reddit.com/r/x/1")
    b = _ev("ev_b", "https://reddit.com/r/x/1?utm_source=x")
    res = deduplicate([a, b])
    # The two should collapse — but evidence_id differs so what wins?
    # Rule: first occurrence wins on canonical URL key.
    assert len(res.kept) == 1
    assert res.kept[0]["evidence_id"] == "ev_a"
    # Provenance records the second hit.
    prov = res.provenance_for("ev_a")
    assert prov is not None
    assert prov.retrieval_count == 2


def test_source_native_id_dedup_within_same_source():
    a = _ev("ev_a", "https://a.example.com/1", source="reddit", source_native_id="abc")
    b = _ev("ev_b", "https://b.example.com/2", source="reddit", source_native_id="abc")
    res = deduplicate([a, b])
    # Same source + same native_id -> dup.
    assert len(res.kept) == 1
    assert res.kept[0]["evidence_id"] == "ev_a"


def test_different_native_id_same_source_kept():
    a = _ev("ev_a", "https://a.example.com/1", source="reddit", source_native_id="abc")
    b = _ev("ev_b", "https://b.example.com/2", source="reddit", source_native_id="xyz")
    res = deduplicate([a, b])
    assert len(res.kept) == 2


def test_same_native_id_different_source_kept():
    """Cross-source same native_id is NOT a dup."""
    a = _ev("ev_a", "https://a.example.com/1", source="reddit", source_native_id="abc")
    b = _ev("ev_b", "https://b.example.com/2", source="hacker_news", source_native_id="abc")
    res = deduplicate([a, b])
    assert len(res.kept) == 2


def test_different_url_different_id_kept():
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_b", "https://b.example.com/2")
    res = deduplicate([a, b])
    assert len(res.kept) == 2


def test_suspected_repost_preserved():
    """Different URLs, different native IDs, but plausibly the same story.
    Phase 3 keeps both — semantic dedup is downstream."""
    a = _ev("ev_a", "https://reddit.com/r/x/comments/1", source_native_id="1")
    b = _ev("ev_b", "https://news.example.com/notion-pricing-2026", source="host_web_search", source_native_id="2")
    res = deduplicate([a, b])
    assert len(res.kept) == 2


def test_provenance_matched_queries_recorded():
    a = _ev("ev_a", "https://a.example.com/1")
    a["query"] = "query_a"
    b = _ev("ev_a", "https://a.example.com/1")  # dup
    b["query"] = "query_b"
    res = deduplicate([a, b])
    prov = res.provenance_for("ev_a")
    assert prov is not None
    assert "query_a" in prov.matched_queries
    assert "query_b" in prov.matched_queries


def test_provenance_source_hits_recorded():
    """Source hits include every (source, native_id) pair seen."""
    a = _ev("ev_a", "https://a.example.com/1", source="reddit", source_native_id="x")
    b = _ev("ev_b", "https://a.example.com/1", source="reddit", source_native_id="x")
    res = deduplicate([a, b])
    prov = res.provenance_for("ev_a")
    assert prov is not None
    assert ("reddit", "x") in prov.source_hits


def test_provenance_retrieval_count():
    a = _ev("ev_a", "https://a.example.com/1")
    # Three hits of the same item.
    b = _ev("ev_a", "https://a.example.com/1")
    c = _ev("ev_a", "https://a.example.com/1")
    res = deduplicate([a, b, c])
    prov = res.provenance_for("ev_a")
    assert prov is not None
    assert prov.retrieval_count == 3


def test_provenance_does_not_leak_into_evidence():
    """Provenance stays in pipeline scope; Evidence payload unchanged."""
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_a", "https://a.example.com/1")
    res = deduplicate([a, b])
    kept_ev = res.kept[0]
    # Forbidden fields per Phase 3 §16.
    for forbidden in (
        "matched_queries", "retrieval_count", "source_hits",
        "provenance", "matched_by",
    ):
        assert forbidden not in kept_ev


def test_kept_order_preserved():
    """The first occurrence's position is preserved."""
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_b", "https://b.example.com/2")
    c = _ev("ev_a", "https://a.example.com/1")  # dup of a
    res = deduplicate([a, b, c])
    assert [e["evidence_id"] for e in res.kept] == ["ev_a", "ev_b"]


def test_dedup_returns_provenance_dict():
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_a", "https://a.example.com/1")
    res = deduplicate([a, b])
    prov = res.provenance
    assert isinstance(prov, dict)
    assert "ev_a" in prov


def test_dedup_class_api_matches_function():
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_a", "https://a.example.com/1")
    fn_res = deduplicate([a, b])
    cls_res = Deduplicator().deduplicate([a, b])
    assert [e["evidence_id"] for e in fn_res.kept] == [
        e["evidence_id"] for e in cls_res.kept
    ]


def test_empty_input_returns_empty():
    res = deduplicate([])
    assert res.kept == []
    assert res.provenance == {}


def test_canonical_url_dedup_ignores_trailing_slash():
    a = _ev("ev_a", "https://reddit.com/r/x/1/")
    b = _ev("ev_b", "https://reddit.com/r/x/1")
    res = deduplicate([a, b])
    assert len(res.kept) == 1
    assert res.kept[0]["evidence_id"] == "ev_a"


def test_canonical_url_dedup_ignores_tracking_only():
    """utm_source is dropped but legitimate query params (page=2) are kept."""
    a = _ev("ev_a", "https://reddit.com/r/x/1")
    b = _ev("ev_b", "https://reddit.com/r/x/1?utm_source=fb")  # only tracking
    res = deduplicate([a, b])
    # utm_source dropped — both canonical URLs identical → 1 kept.
    assert len(res.kept) == 1
    assert res.kept[0]["evidence_id"] == "ev_a"


def test_canonical_url_dedup_keeps_distinct_legitimate_query():
    """Different legitimate query params → distinct canonical URL → 2 kept."""
    a = _ev("ev_a", "https://reddit.com/r/x/1")
    b = _ev("ev_b", "https://reddit.com/r/x/1?page=2")
    res = deduplicate([a, b])
    # page=2 is NOT a tracking param, so the canonical URL keeps it.
    assert len(res.kept) == 2


def test_dedup_does_not_mutate_input():
    a = _ev("ev_a", "https://a.example.com/1")
    before = a.copy()
    deduplicate([a])
    assert a == before


def test_dedup_count_summary():
    a = _ev("ev_a", "https://a.example.com/1")
    b = _ev("ev_a", "https://a.example.com/1")
    c = _ev("ev_b", "https://b.example.com/2")
    res = deduplicate([a, b, c])
    assert res.input_count == 3
    assert res.kept_count == 2
    assert res.duplicate_count == 1


def test_dedup_provenance_for_unknown_returns_none():
    res = deduplicate([_ev("ev_a", "https://a.example.com/1")])
    assert res.provenance_for("ev_unknown") is None


def test_dedup_window_preserved_per_item():
    a = _ev("ev_a", "https://a.example.com/1", window="current")
    b = _ev("ev_b", "https://b.example.com/2", window="baseline")
    res = deduplicate([a, b])
    kept = {e["evidence_id"]: e["window"] for e in res.kept}
    assert kept["ev_a"] == "current"
    assert kept["ev_b"] == "baseline"


def test_dedup_deterministic_20_runs():
    items = [
        _ev("ev_a", "https://a.example.com/1"),
        _ev("ev_a", "https://a.example.com/1"),
        _ev("ev_b", "https://b.example.com/2"),
        _ev("ev_a", "https://a.example.com/1"),
    ]
    snapshots = [
        tuple((e["evidence_id"] for e in deduplicate(items).kept))
        for _ in range(20)
    ]
    first = snapshots[0]
    assert all(s == first for s in snapshots)