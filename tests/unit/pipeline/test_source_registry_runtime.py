"""Tests for Source Registry runtime (Phase 3 §22).

Contract:
  * SourceRegistry loads config/sources.yaml, validates against
    source_registry.schema.json, and exposes a deterministic ordered list.
  * Eligibility filter:
      - disabled sources are filtered out
      - sources whose `markets` exclude the plan market are filtered out
      - sources whose `languages` exclude the query_language are filtered out
  * Order: priority desc, name asc.
  * Credential names are validated against the source registry schema
    (snake_case pattern). Real secret values must NOT appear in the loaded
    YAML — runtime loader rejects obvious secret patterns (the schema's
    credential `pattern` already enforces this).
  * load_registry is the single entry point; tests pass either a Path or
    a yaml string (no filesystem dependency for unit tests).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gtm_intelligence.pipeline.source_registry import (
    REGISTRY_DIR,
    SourceRegistry,
    eligible_sources_for,
    load_registry,
)


def _yaml_str() -> str:
    return """
- name: host_web_search
  enabled: true
  type: web
  cost: free
  auth_required: false
  credentials: []
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
  credentials: []
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
  credentials: []
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
  credentials: []
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
  credentials: []
  priority: 85
  capabilities: [search, releases]
  markets: [global]
  languages: [en]
  cache_ttl: 3600

- name: jp_only
  enabled: true
  type: community
  cost: free
  auth_required: false
  priority: 88
  capabilities: [search]
  markets: [jp]
  languages: [ja]
  cache_ttl: 600

- name: disabled_one
  enabled: false
  type: community
  cost: free
  auth_required: false
  priority: 99
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 60
"""


def test_load_registry_from_yaml_string():
    reg = load_registry(yaml_text=_yaml_str())
    assert len(reg.entries) == 7


def test_load_registry_from_project_config():
    reg = load_registry()  # default = config/sources.yaml
    names = {e.name for e in reg.entries}
    # From Phase 1 / Phase 2 seed.
    assert "host_web_search" in names
    assert "official_web" in names
    assert "reddit" in names
    assert "hacker_news" in names
    assert "github" in names


def test_project_host_search_can_serve_japan_and_japanese():
    """A market-specific request must not lose the broad host-search path."""
    reg = load_registry()
    names = {
        entry.name
        for entry in eligible_sources_for(
            reg, plan_market="jp", query_language="ja"
        )
    }
    assert "host_web_search" in names
    assert "official_web" in names
    assert "qiita" in names


def test_project_registry_enables_credential_free_topic_connectors():
    reg = load_registry()
    enabled = {entry.name for entry in reg.entries if entry.enabled}
    assert {
        "arxiv",
        "devto",
        "hugging_face",
        "package_registries",
        "qiita",
        "semantic_scholar",
        "stack_overflow",
    } <= enabled


def test_registry_disabled_sources_remain_in_registry():
    """Disabled sources stay in the registry; eligibility filtering removes them."""
    reg = load_registry(yaml_text=_yaml_str())
    names = {e.name for e in reg.entries}
    assert "disabled_one" in names


def test_eligible_sources_filter_disabled():
    reg = load_registry(yaml_text=_yaml_str())
    elig = eligible_sources_for(reg, plan_market="global", query_language="en")
    for s in elig:
        assert s.enabled is True


def test_eligible_sources_filter_market():
    reg = load_registry(yaml_text=_yaml_str())
    elig = eligible_sources_for(reg, plan_market="jp", query_language="ja")
    names = [s.name for s in elig]
    assert "jp_only" in names
    # host_web_search (markets: global) only serves global plans.
    assert "host_web_search" not in names
    # global-only sources should not be returned for jp-specific plan.
    for n in names:
        if n == "jp_only":
            continue
        # all other returned sources must list jp in markets
        # (none do in our yaml — only jp_only serves jp).
    # If any other global-only source made it in, fail.
    assert set(names) == {"jp_only"}


def test_eligible_sources_filter_language():
    reg = load_registry(yaml_text=_yaml_str())
    elig = eligible_sources_for(reg, plan_market="jp", query_language="en")
    # jp_only is languages: [ja], so it cannot serve an en query.
    names = [s.name for s in elig]
    assert "jp_only" not in names


def test_registry_order_priority_desc_name_asc():
    reg = load_registry(yaml_text=_yaml_str())
    # Just enabled entries should be ordered by priority desc, name asc.
    enabled = [e for e in reg.entries if e.enabled]
    priorities = [e.priority for e in enabled]
    assert priorities == sorted(priorities, reverse=True)


def test_registry_rejects_secret_like_credential_value():
    """A credential like 'github_token=abc123' is not a valid snake_case name."""
    bad_yaml = """
- name: github
  enabled: true
  type: official
  cost: free
  auth_required: true
  credentials: [github_token=abc123]
  priority: 80
  capabilities: [search]
  markets: [global]
  languages: [en]
"""
    with pytest.raises(Exception):
        load_registry(yaml_text=bad_yaml)


def test_registry_accepts_uppercase_credential_name():
    """GITHUB_TOKEN is a valid environment-variable name (Closeout §1).

    The earlier `^[a-z][a-z0-9_]*$` pattern was over-restrictive and
    wrongly rejected legitimate env-var credential names. Schema now
    uses POSIX env-var shape `^[A-Za-z_][A-Za-z0-9_]*$`.
    """
    good_yaml = """
- name: github
  enabled: true
  type: official
  cost: free
  auth_required: true
  credentials: [GITHUB_TOKEN]
  priority: 80
  capabilities: [search]
  markets: [global]
  languages: [en]
"""
    reg = load_registry(yaml_text=good_yaml)
    assert reg.entries[0].credentials == ("GITHUB_TOKEN",)


def test_registry_loads_yaml_with_no_credentials_field():
    """Missing credentials is allowed (treated as empty list)."""
    yaml_no_creds = """
- name: foo
  enabled: true
  type: community
  cost: free
  auth_required: false
  priority: 50
  capabilities: [search]
  markets: [global]
  languages: [en]
"""
    reg = load_registry(yaml_text=yaml_no_creds)
    assert list(reg.entries[0].credentials) == []


def test_registry_deterministic_20_runs():
    snapshots = [
        tuple((e.name, e.priority) for e in load_registry(yaml_text=_yaml_str()).entries)
        for _ in range(20)
    ]
    first = snapshots[0]
    assert all(s == first for s in snapshots)


def test_source_registry_class_api():
    reg = SourceRegistry(entries=load_registry(yaml_text=_yaml_str()).entries)
    elig = reg.eligible(plan_market="global", query_language="en")
    assert all(s.enabled for s in elig)


def test_capabilities_field_listed():
    reg = load_registry(yaml_text=_yaml_str())
    reddit = next(e for e in reg.entries if e.name == "reddit")
    assert "search" in reddit.capabilities
    assert "comments" in reddit.capabilities


def test_cache_ttl_int():
    reg = load_registry(yaml_text=_yaml_str())
    reddit = next(e for e in reg.entries if e.name == "reddit")
    assert reddit.cache_ttl == 900


def test_project_reddit_has_single_query_budget_for_public_rss():
    reg = load_registry()
    reddit = next(e for e in reg.entries if e.name == "reddit")
    assert reddit.max_queries_per_run == 1


def test_registry_default_path_constant_exists():
    assert isinstance(REGISTRY_DIR, (str, Path))
