"""Integration: normalize_raw respects raw_metadata.official (Phase 4 §20).

The official-classifier sits between an arbitrary adapter (e.g. Host Web
Search, GitHub) and the normalizer. When raw_metadata declares
`{"official": True, "official_owner": "acme"}` (produced by
connectors.official_web), the normalizer MUST promote that item to T1
quality = 1.0 regardless of which adapter emitted it. Sibling rules:

  * raw_metadata absent                 → existing tier map applies.
  * raw_metadata.official = False       → existing tier map applies.
  * raw_metadata.official = True        → tier=1, evidence_quality=1.0
                                          (first-party evidence, regardless
                                          of source — verified domain wins
                                          over source-tier heuristic).
  * raw_metadata.official = True but
    source is unknown to _TIER_MAP      → still tier=1, quality=1.0
                                          (the official flag IS the
                                          verification of the source).

Frozen Decision boundary check:
  * No new Evidence schema field is added (tier and quality are both
    optional, so the existing pipeline accepts them).
  * No source-registry-schema change.
  * No pipeline-stage reordering. The only edit is local to normalize_raw's
    tier resolution, which is implementation detail.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.pipeline.adapters import RawSourceResult
from gtm_intelligence.normalization import normalize_raw


AS_OF = "2026-09-06T00:00:00Z"


def _base_raw(source: str = "host_web_search", **overrides) -> RawSourceResult:
    payload = dict(
        source=source,
        source_type="page",
        source_native_id="https://acme.com/pricing",
        url="https://acme.com/pricing",
        title="Pricing",
        text="Our plans start at...",
        published_at="2026-09-01T00:00:00Z",
        language="en",
        query="acme pricing",
    )
    payload.update(overrides)
    return RawSourceResult(**payload)


def test_normalize_promotes_to_t1_when_metadata_official_true():
    raw = _base_raw(
        raw_metadata={"official": True, "official_owner": "acme", "official_kind": "domain"},
    )
    ev = normalize_raw(raw, as_of=AS_OF)
    assert ev["source_tier"] == 1
    assert ev["evidence_quality"] == 1.0


def test_normalize_uses_default_tier_when_metadata_absent():
    """Regression guard: legacy behavior is unchanged when metadata is absent."""

    raw = _base_raw(source="host_web_search")  # default T4 path
    ev = normalize_raw(raw, as_of=AS_OF)
    assert ev["source_tier"] == 4
    assert ev["evidence_quality"] == 0.3


def test_normalize_uses_default_tier_when_metadata_official_false():
    raw = _base_raw(source="host_web_search", raw_metadata={"official": False})
    ev = normalize_raw(raw, as_of=AS_OF)
    assert ev["source_tier"] == 4
    assert ev["evidence_quality"] == 0.3


def test_normalize_official_promotion_overrides_unknown_source():
    """If the source is unknown to _TIER_MAP AND metadata says official,
    upgrade to T1. The official flag IS the verification."""

    raw = _base_raw(
        source="some_unknown_search_backend",
        raw_metadata={"official": True, "official_owner": "acme"},
    )
    ev = normalize_raw(raw, as_of=AS_OF)
    assert ev["source_tier"] == 1
    assert ev["evidence_quality"] == 1.0


def test_normalize_non_official_unknown_source_omits_tier():
    """Unknown source + no official flag → tier omitted (Closeout §3
    invariant: unknown ≠ neutral)."""
    raw = _base_raw(
        source="some_unknown_search_backend",
    )
    ev = normalize_raw(raw, as_of=AS_OF)
    assert "source_tier" not in ev
    assert "evidence_quality" not in ev


def test_normalize_official_promotion_overrides_default_community_tier():
    """Community-sourced (T2) raw + official metadata → T1.

    A GitHub repo owned by a verified owner is still first-party signal,
    so the first-party tier wins over the community default.
    """
    raw = _base_raw(
        source="reddit",  # would default to T2 / 0.6
        source_native_id="reddit-post-1",
        url="https://reddit.com/r/test/comments/1/x/",
        raw_metadata={"official": True, "official_owner": "acme"},
    )
    ev = normalize_raw(raw, as_of=AS_OF)
    assert ev["source_tier"] == 1
    assert ev["evidence_quality"] == 1.0
