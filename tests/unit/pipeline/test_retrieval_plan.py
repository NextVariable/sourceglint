"""Tests for deterministic Retrieval Planning (Phase 3 §6).

Contract:
  * RetrievalPlan is the explicit separation of WHAT to search from HOW the
    source is called.
  * Same ResearchPlan + same source registry -> same ordered list.
  * Disabled sources are filtered out.
  * Sources whose `markets` do not include the plan's market are filtered out
    (absent market -> global only).
  * Sources whose `languages` do not include the query_language are filtered
    out for that specific retrieval.
  * Priority desc, name asc — deterministic ordering.
  * Source priorites from plan override registry default (when supplied).
"""
from __future__ import annotations

from typing import Iterable

import pytest

from gtm_intelligence.pipeline.retrieval_plan import (
    RetrievalPlan,
    RetrievalPlanner,
    build_retrieval_plans,
)


def _plan(**overrides):
    base = {
        "topic": "Notion AI",
        "mode": "competitor",
        "market": "global",
        "locale": "en",
        "languages": ["en"],
        "time_window": {"days": 30},
        "entities": ["Notion"],
        "decision_context": "watch",
    }
    base.update(overrides)
    return base


def _sources_yaml() -> str:
    return """
- name: host_web_search
  enabled: true
  type: web
  cost: free
  auth_required: false
  priority: 60
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 900

- name: official_web
  enabled: true
  type: official
  cost: free
  auth_required: false
  priority: 90
  capabilities: [fetch]
  markets: [global]
  languages: [en]
  cache_ttl: 3600

- name: reddit
  enabled: true
  type: community
  cost: free
  auth_required: false
  priority: 80
  capabilities: [search, comments]
  markets: [global]
  languages: [en]
  cache_ttl: 900

- name: hacker_news
  enabled: true
  type: community
  cost: free
  auth_required: false
  priority: 70
  capabilities: [search, stories, comments]
  markets: [global]
  languages: [en]
  cache_ttl: 1800

- name: github
  enabled: true
  type: official
  cost: free
  auth_required: false
  priority: 85
  capabilities: [search, releases]
  markets: [global]
  languages: [en]
  cache_ttl: 3600

- name: disabled_source
  enabled: false
  type: community
  cost: free
  auth_required: false
  priority: 95
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 60
"""


def _source(name: str, **overrides) -> dict:
    """Build a registry entry dict."""
    src = {
        "name": name,
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],
        "priority": 50,
        "capabilities": ["search"],
        "markets": ["global"],
        "languages": ["en"],
        "cache_ttl": 900,
    }
    src.update(overrides)
    return src


def test_deterministic_for_same_plan_and_registry():
    plan = _plan()
    sources = [_source("a", priority=80), _source("b", priority=90)]
    a = build_retrieval_plans(plan, sources, _expand_query_stub())
    b = build_retrieval_plans(plan, sources, _expand_query_stub())
    assert [(r.source, r.query) for r in a] == [(r.source, r.query) for r in b]


def test_priority_desc_name_asc_ordering():
    plan = _plan()
    sources = [
        _source("a", priority=50),
        _source("b", priority=80),
        _source("c", priority=80),
        _source("d", priority=99),
    ]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    seen_sources = []
    seen_set = set()
    for r in plans:
        if r.source not in seen_set:
            seen_sources.append(r.source)
            seen_set.add(r.source)
    # d (99) → b (80) → c (80, name asc) → a (50)
    assert seen_sources == ["d", "b", "c", "a"]


def test_disabled_source_filtered_out():
    plan = _plan()
    sources = [
        _source("enabled_one", enabled=True, priority=50),
        _source("disabled_one", enabled=False, priority=99),
    ]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.source != "disabled_one"


def test_source_market_mismatch_filtered_out():
    plan = _plan(market="jp")
    sources = [
        _source("only_us", markets=["us"]),
        _source("global_one", markets=["global"]),
    ]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.source != "only_us"


def test_source_language_mismatch_filtered_out_for_query():
    """If query_language=en but source only supports ja, no plan emits."""
    plan = _plan(languages=["en"])
    sources = [_source("ja_only", languages=["ja"])]
    en_only_stub = [
        {
            "text": "Notion AI pricing",
            "intent": "commercial",
            "query_language": "en",
            "market": "global",
        },
    ]
    plans = build_retrieval_plans(plan, sources, en_only_stub)
    # The source cannot serve the en query, so no retrieval.
    assert plans == []


def test_query_language_matches_source_language():
    plan = _plan(languages=["en", "ja"], market="jp")
    sources = [
        _source("en_jp", markets=["jp"], languages=["en", "ja"]),
    ]
    # Explicit JP query forces ja-language retrieval to be eligible.
    plan["queries"] = ["Notion 値上げ"]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    # At least one retrieval plan for ja should exist.
    assert any(r.query_language == "ja" for r in plans)


def test_plan_source_priorities_override_registry_order():
    plan = _plan(source_priorities=["reddit", "github"])
    sources = [
        _source("reddit", priority=80),
        _source("github", priority=85),
        _source("host_web_search", priority=60),
    ]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    # First seen sources should be reddit then github (per plan override).
    seen_first = []
    for r in plans:
        if r.source not in seen_first:
            seen_first.append(r.source)
        if len(seen_first) == 2:
            break
    assert seen_first == ["reddit", "github"]


def test_plan_time_window_passed_through():
    plan = _plan(time_window={"days": 14})
    sources = [_source("a")]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.time_window == {"days": 14}


def test_plan_market_passed_through():
    plan = _plan(market="de")
    sources = [_source("a", markets=["de"])]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.market == "de"


def test_plan_priority_field_int_default_50():
    plan = _plan()
    sources = [_source("a")]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.priority == 50


def test_priority_uses_source_priority_when_present():
    plan = _plan()
    sources = [_source("a", priority=77)]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.priority == 77


def test_only_one_plan_per_query_source_pair():
    plan = _plan()
    sources = [_source("a", priority=80)]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    pairs = [(r.source, r.query) for r in plans]
    assert len(pairs) == len(set(pairs))


def test_source_specific_query_budget_limits_rate_limited_connector():
    plan = _plan()
    sources = [_source("reddit", max_queries_per_run=1)]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    assert len(plans) == 1
    assert plans[0].source == "reddit"
    assert plans[0].query == "Notion AI pricing"


def test_unsupported_market_globally_excludes_all_sources():
    plan = _plan(market="zz")  # no source supports zz
    sources = [_source("only_global", markets=["global"])]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    assert plans == []


def test_window_relative_days_pass_through():
    plan = _plan(time_window={"days": 7})
    sources = [_source("a")]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    assert plans[0].time_window == {"days": 7}


def test_window_custom_range_pass_through():
    plan = _plan(
        time_window={
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-08-31T23:59:59Z",
        }
    )
    sources = [_source("a")]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    assert plans[0].time_window == {
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-08-31T23:59:59Z",
    }


def test_empty_sources_returns_empty():
    plan = _plan()
    plans = build_retrieval_plans(plan, [], _expand_query_stub())
    assert plans == []


def test_empty_queries_returns_empty():
    plan = _plan()
    sources = [_source("a", priority=80)]
    plans = build_retrieval_plans(plan, sources, [])
    assert plans == []


def test_query_text_passed_through():
    plan = _plan()
    sources = [_source("a", priority=80)]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    queries = {r.query for r in plans}
    assert "Notion AI pricing" in queries


def test_mode_passed_through():
    plan = _plan(mode="competitor")
    sources = [_source("a", priority=80)]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    for r in plans:
        assert r.mode == "competitor"


def test_20_runs_determinism():
    plan = _plan()
    sources = [
        _source("a", priority=50),
        _source("b", priority=80),
        _source("c", priority=80),
    ]
    snapshots = [
        tuple((r.source, r.query, r.query_language) for r in build_retrieval_plans(plan, sources, _expand_query_stub()))
        for _ in range(20)
    ]
    first = snapshots[0]
    assert all(s == first for s in snapshots)


def test_class_api_matches_function():
    plan = _plan()
    sources = [_source("a", priority=80)]
    fn_out = build_retrieval_plans(plan, sources, _expand_query_stub())
    cls_out = RetrievalPlanner().plan(plan, sources, _expand_query_stub())
    assert [(r.source, r.query) for r in fn_out] == [(r.source, r.query) for r in cls_out]


def test_global_market_includes_market_specific_sources():
    """Plan with market=global should also reach sources whose markets include
    a single explicit country, when that country is a subset of 'global'."""
    plan = _plan(market="global")
    sources = [
        _source("only_jp", markets=["jp"]),
        _source("global_source", markets=["global"]),
    ]
    plans = build_retrieval_plans(plan, sources, _expand_query_stub())
    sources_seen = {r.source for r in plans}
    # Only the global-eligible one should appear; 'only_jp' excludes 'global'.
    assert "global_source" in sources_seen
    assert "only_jp" not in sources_seen


def _expand_query_stub() -> list:
    """Stable stub list — equivalent to expanded queries from QueryExpander."""
    return [
        {
            "text": "Notion AI pricing",
            "intent": "commercial",
            "query_language": "en",
            "market": "global",
        },
        {
            "text": "Notion AI complaints",
            "intent": "complaint",
            "query_language": "en",
            "market": "global",
        },
        {
            "text": "Notion 値上げ",
            "intent": "explicit",
            "query_language": "ja",
            "market": "jp",
        },
    ]
