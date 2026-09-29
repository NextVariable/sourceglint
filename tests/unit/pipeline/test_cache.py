"""Tests for local retrieval cache (Phase 3 §17).

Contract:
  * Key = (source, normalized_query, query_language, market, time_window).
  * Cache stores JSON-serializable values (list of dicts).
  * Cache respects TTL — expired entries are misses.
  * Cache hit returns the exact bytes stored.
  * Cache miss returns None and the caller is expected to retrieve + store.
  * Corrupt cache files: deleted, treated as miss (no exception raised
    that aborts retrieval).
  * No secrets stored. URL params carrying secrets are NOT recorded in the
    cache key (key is normalized).
  * Cache is local (file-based). Disposable. Not committed (under .cache/).
  * Time injection — no system clock.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sourceglint.pipeline.cache import (
    CacheMiss,
    RetrievalCache,
    cache_key_for,
    make_cache,
)


def test_cache_key_deterministic():
    a = cache_key_for(
        source="reddit",
        query="Notion AI pricing",
        query_language="en",
        market="global",
        time_window={"days": 30},
    )
    b = cache_key_for(
        source="reddit",
        query="Notion AI pricing",
        query_language="en",
        market="global",
        time_window={"days": 30},
    )
    assert a == b


def test_cache_key_differs_by_source():
    a = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    b = cache_key_for(source="hacker_news", query="q", query_language="en", market="global", time_window={})
    assert a != b


def test_cache_key_differs_by_query_language():
    a = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    b = cache_key_for(source="reddit", query="q", query_language="ja", market="global", time_window={})
    assert a != b


def test_cache_key_differs_by_market():
    a = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    b = cache_key_for(source="reddit", query="q", query_language="en", market="jp", time_window={})
    assert a != b


def test_cache_key_differs_by_query():
    a = cache_key_for(source="reddit", query="q1", query_language="en", market="global", time_window={})
    b = cache_key_for(source="reddit", query="q2", query_language="en", market="global", time_window={})
    assert a != b


def test_cache_key_differs_by_time_window():
    a = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    b = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 7})
    assert a != b


def test_cache_key_query_whitespace_normalized():
    """Leading/trailing whitespace collapses."""
    a = cache_key_for(source="reddit", query="  notion  ", query_language="en", market="global", time_window={})
    b = cache_key_for(source="reddit", query="notion", query_language="en", market="global", time_window={})
    assert a == b


def test_cache_hit_returns_stored_value(tmp_path):
    cache = make_cache(tmp_path / "cache")
    key = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    payload = [{"a": 1}, {"b": 2}]
    cache.set(key, payload, ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    assert cache.get(key, as_of="2026-09-06T10:00:05Z") == payload


def test_cache_miss_returns_none(tmp_path):
    cache = make_cache(tmp_path / "cache")
    key = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    assert cache.get(key, as_of="2026-09-06T10:00:00Z") is None


def test_cache_expired_returns_none(tmp_path):
    cache = make_cache(tmp_path / "cache")
    key = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    cache.set(key, [{"a": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    # 90 seconds later — expired.
    assert cache.get(key, as_of="2026-09-06T10:01:30Z") is None


def test_cache_not_expired_within_ttl(tmp_path):
    cache = make_cache(tmp_path / "cache")
    key = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    cache.set(key, [{"a": 1}], ttl_seconds=300, as_of="2026-09-06T10:00:00Z")
    # 299 seconds later — still valid.
    assert cache.get(key, as_of="2026-09-06T10:04:59Z") == [{"a": 1}]


def test_cache_corrupt_file_treated_as_miss(tmp_path):
    cache = make_cache(tmp_path / "cache")
    key = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={"days": 30})
    cache_file = cache._path_for(key)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("not valid json{", encoding="utf-8")
    # Cache should silently treat as miss (no exception).
    assert cache.get(key, as_of="2026-09-06T10:00:00Z") is None


def test_cache_key_no_secrets_in_key_string():
    """The cache key string itself must not embed raw values, just hashes."""
    k = cache_key_for(
        source="reddit",
        query="very-secret-query-text-should-not-leak-into-key",
        query_language="en",
        market="global",
        time_window={"days": 30},
    )
    assert "very-secret-query-text-should-not-leak-into-key" not in k


def test_cache_distinct_queries_get_distinct_files(tmp_path):
    cache = make_cache(tmp_path / "cache")
    k1 = cache_key_for(source="reddit", query="q1", query_language="en", market="global", time_window={})
    k2 = cache_key_for(source="reddit", query="q2", query_language="en", market="global", time_window={})
    cache.set(k1, [{"x": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    cache.set(k2, [{"x": 2}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    p1 = cache._path_for(k1)
    p2 = cache._path_for(k2)
    assert p1 != p2
    assert p1.exists()
    assert p2.exists()


def test_cache_file_inside_root(tmp_path):
    """All cache files must live under the configured cache_root."""
    root = tmp_path / "cache"
    cache = make_cache(root)
    k = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    cache.set(k, [{"x": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    p = cache._path_for(k)
    assert str(p).startswith(str(root))


def test_cache_overwrite_on_set(tmp_path):
    cache = make_cache(tmp_path / "cache")
    k = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    cache.set(k, [{"x": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    cache.set(k, [{"x": 2}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    assert cache.get(k, as_of="2026-09-06T10:00:00Z") == [{"x": 2}]


def test_cache_invalidate_specific_key(tmp_path):
    cache = make_cache(tmp_path / "cache")
    k = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    cache.set(k, [{"x": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    cache.invalidate(k)
    assert cache.get(k, as_of="2026-09-06T10:00:00Z") is None


def test_cache_deterministic_set_get_round_trip(tmp_path):
    """Round-trip 20 times: byte-stable read of same data."""
    cache = make_cache(tmp_path / "cache")
    k = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    payload = [{"a": 1, "b": [1, 2, 3]}, {"c": "hello"}]
    cache.set(k, payload, ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    snapshots = [cache.get(k, as_of="2026-09-06T10:00:00Z") for _ in range(20)]
    assert all(s == payload for s in snapshots)


def test_cache_returns_none_for_zero_ttl_expired(tmp_path):
    cache = make_cache(tmp_path / "cache")
    k = cache_key_for(source="reddit", query="q", query_language="en", market="global", time_window={})
    cache.set(k, [{"x": 1}], ttl_seconds=0, as_of="2026-09-06T10:00:00Z")
    # Even 1 second later is past TTL=0.
    assert cache.get(k, as_of="2026-09-06T10:00:01Z") is None


def test_cache_japanese_query_round_trip(tmp_path):
    cache = make_cache(tmp_path / "cache")
    k = cache_key_for(
        source="reddit",
        query="Notion 値上げ",
        query_language="ja",
        market="jp",
        time_window={"days": 30},
    )
    payload = [{"title": "値上げ", "text": "Notionの値上げ"}]
    cache.set(k, payload, ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    out = cache.get(k, as_of="2026-09-06T10:00:05Z")
    assert out == payload


def test_cache_class_api_matches_function():
    cache = make_cache("/tmp/_gtm_cache_test")
    k = cache_key_for(source="x", query="y", query_language="en", market="global", time_window={})
    cache.set(k, [{"v": 1}], ttl_seconds=60, as_of="2026-09-06T10:00:00Z")
    out = cache.get(k, as_of="2026-09-06T10:00:05Z")
    assert out == [{"v": 1}]
    cache.invalidate(k)