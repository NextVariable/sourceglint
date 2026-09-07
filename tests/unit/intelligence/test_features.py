"""Phase 5 §12–§13, §18 — code-computed cross-source & baseline features."""
from __future__ import annotations

import pytest

from gtm_intelligence.intelligence import features
from gtm_intelligence.intelligence.dtos import (
    WINDOW_BASELINE,
    WINDOW_CURRENT,
    PreparedEvidence,
    SignalFeatures,
    ValidatedCluster,
)


def _ev(
    eid: str,
    *,
    source: str = "reddit",
    source_type: str = "post",
    tier: int = 2,
    url: str = "",
    window: str = WINDOW_CURRENT,
    engagement: dict | None = None,
    language: str = "en",
    market: str = "US",
) -> PreparedEvidence:
    if not url:
        resolved_url = ""
    else:
        resolved_url = url
    return PreparedEvidence(
        evidence_id=eid,
        source=source,
        source_type=source_type,
        window=window,
        title=f"title {eid}",
        snippet=f"snippet {eid}",
        published_at="2026-09-01",
        market=market,
        language=language,
        source_tier=tier,
        evidence_quality=0.7,
        engagement=dict(engagement or {}),
        url=resolved_url,
        has_text=True,
    )


def _cluster(evidence_ids: tuple[str, ...], label: str = "L") -> ValidatedCluster:
    from gtm_intelligence.intelligence.ids import derive_cluster_id

    return ValidatedCluster(
        cluster_id=derive_cluster_id(evidence_ids),
        label=label,
        claim="c",
        evidence_ids=evidence_ids,
        confidence=0.8,
    )


def _index(*items: PreparedEvidence) -> dict[str, PreparedEvidence]:
    return {e.evidence_id: e for e in items}


# --- canonical domain -------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://news.ycombinator.com/item?id=1", "news.ycombinator.com"),
        ("https://www.example.com/path?q=1", "example.com"),
        ("https://EXAMPLE.com:8080/x", "example.com"),
        ("http://blog.acme.io/", "blog.acme.io"),
        ("", ""),
        ("not-a-url", ""),
    ],
)
def test_canonical_domain(url: str, expected: str):
    assert features.canonical_domain(url) == expected


# --- single-cluster basics --------------------------------------------------


def test_single_evidence_features():
    ev = _ev("ev-1", source="hacker_news", source_type="comment", tier=2,
             url="https://example.com/item/1",
             engagement={"points": 10, "comments": 3})
    out = features.derive_features(_cluster(("ev-1",)), _index(ev))
    assert isinstance(out, SignalFeatures)
    assert out.evidence_count == 1
    assert out.unique_sources == ("hacker_news",)
    assert out.unique_source_types == ("comment",)
    assert out.source_tiers == (2,)
    assert out.unique_domains == ("example.com",)
    assert out.independent_source_count == 1
    assert out.engagement_total == 13
    assert out.first_party_count == 0
    assert out.community_count == 1
    assert out.current_count == 1
    assert out.baseline_count == 0


def test_engagement_total_sums_across_members():
    a = _ev("ev-1", engagement={"upvotes": 5})
    b = _ev("ev-2", engagement={"upvotes": 7, "comments": 2})
    out = features.derive_features(_cluster(("ev-1", "ev-2")), _index(a, b))
    assert out.engagement_total == 14


def test_zero_engagement_is_zero():
    ev = _ev("ev-1", engagement={})
    out = features.derive_features(_cluster(("ev-1",)), _index(ev))
    assert out.engagement_total == 0


def test_sorted_unique_aux_tuples():
    a = _ev("ev-1", language="ja", market="JP")
    b = _ev("ev-2", language="en", market="US")
    out = features.derive_features(_cluster(("ev-2", "ev-1")), _index(a, b))
    assert out.languages == ("en", "ja")
    assert out.markets == ("JP", "US")


# --- tier buckets -----------------------------------------------------------


def test_tier_buckets_first_party_and_community():
    t1 = _ev("ev-1", source="official_web", tier=1)
    t2 = _ev("ev-2", source="reddit", tier=2)
    t3 = _ev("ev-3", source="marketplace", tier=3)
    t4 = _ev("ev-4", source="aggregator", tier=4)
    out = features.derive_features(
        _cluster(("ev-1", "ev-2", "ev-3", "ev-4")), _index(t1, t2, t3, t4)
    )
    assert out.first_party_count == 1
    assert out.community_count == 1
    assert out.source_tiers == (1, 2, 3, 4)


def test_missing_tier_counts_nowhere():
    import dataclasses

    ev = _ev("ev-1", tier=2)
    no_tier = dataclasses.replace(ev, source_tier=None)
    out = features.derive_features(_cluster(("ev-1",)), _index(no_tier))
    assert out.first_party_count == 0
    assert out.community_count == 0


# --- source independence (PRD §13) ------------------------------------------


def test_distinct_domains_count_as_independent():
    a = _ev("ev-1", url="https://techcrunch.com/a", source="official_web", tier=1)
    b = _ev("ev-2", url="https://reddit.com/b", source="reddit", tier=2)
    out = features.derive_features(_cluster(("ev-1", "ev-2")), _index(a, b))
    assert out.independent_source_count == 2
    assert "multi_origin" in out.independence_kinds


def test_same_domain_different_urls_not_independent():
    """Two threads on the same host are one reporting origin (PRD §13)."""
    a = _ev("ev-1", url="https://news.ycombinator.com/item?id=1", source="hacker_news")
    b = _ev("ev-2", url="https://news.ycombinator.com/item?id=2", source="hacker_news")
    out = features.derive_features(_cluster(("ev-1", "ev-2")), _index(a, b))
    assert out.independent_source_count == 1
    assert "single_origin" in out.independence_kinds
    assert "multi_origin" not in out.independence_kinds


def test_url_missing_falls_back_to_source_name():
    a = _ev("ev-1", url="https://a.example.com/1", source="s1")
    b = _ev("ev-2", url="", source="s1")  # no url → origin key is source name
    out = features.derive_features(_cluster(("ev-1", "ev-2")), _index(a, b))
    assert out.independent_source_count == 2
    assert "origin_fallback" in out.independence_kinds


# --- windows / baseline (PRD §18) -------------------------------------------


def test_current_and_baseline_counts():
    cur = _ev("ev-1", window=WINDOW_CURRENT)
    base = _ev("ev-2", window=WINDOW_BASELINE)
    out = features.derive_features(_cluster(("ev-1", "ev-2")), _index(cur, base))
    assert out.current_count == 1
    assert out.baseline_count == 1
    assert out.has_baseline_data is True
    assert out.appeared_only_current is False
    assert out.appeared_only_baseline is False


def test_appeared_only_current_requires_global_baseline_present():
    """Without ANY baseline evidence in the ledger, 'only current' must not
    be inferred — there is nothing to compare against (PRD §18)."""
    a = _ev("ev-1")
    b = _ev("ev-2")
    out = features.derive_features(_cluster(("ev-1",)), _index(a, b))
    assert out.current_count == 1
    assert out.has_baseline_data is False
    assert out.appeared_only_current is False


def test_appeared_only_current_when_baseline_exists_elsewhere():
    cur = _ev("ev-1", window=WINDOW_CURRENT)
    base = _ev("ev-2", window=WINDOW_BASELINE)
    out = features.derive_features(_cluster(("ev-1",)), _index(cur, base))
    assert out.has_baseline_data is True
    assert out.appeared_only_current is True


def test_appeared_only_baseline():
    a = _ev("ev-1", window=WINDOW_BASELINE)
    b = _ev("ev-2", window=WINDOW_CURRENT)  # baseline exists globally
    out = features.derive_features(_cluster(("ev-1",)), _index(a, b))
    assert out.appeared_only_baseline is True
    assert out.appeared_only_current is False


# --- empty / robustness -----------------------------------------------------


def test_all_members_missing_from_index_yields_zero_features():
    out = features.derive_features(_cluster(("ghost-1", "ghost-2")), {})
    assert out.evidence_count == 0
    assert out.independent_source_count == 0
    assert out.engagement_total == 0


def test_member_missing_from_index_is_ignored():
    ev = _ev("ev-1")
    out = features.derive_features(_cluster(("ev-1", "ghost")), _index(ev))
    assert out.evidence_count == 1


# --- batch helper -----------------------------------------------------------


def test_derive_all_features_returns_same_order_as_clusters():
    a = _ev("ev-1", url="https://x.example.com/1")
    b = _ev("ev-2", url="https://y.example.com/2")
    clusters = [_cluster(("ev-1",)), _cluster(("ev-2",))]
    out = features.derive_all_features(clusters, [a, b])
    assert [f.cluster_id for f in out] == [c.cluster_id for c in clusters]
    assert out[0].evidence_count == 1
    assert out[1].evidence_count == 1
