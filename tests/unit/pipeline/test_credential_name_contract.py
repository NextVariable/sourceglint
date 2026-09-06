"""Tests for credential NAME contract (Phase 3 Closeout §1).

PRD §21 requires credentials block to declare NAMES only — real secret
values must NEVER appear. The schema pattern `^[a-z][a-z0-9_]*$` is over-
restrictive: standard env var names like REDDIT_CLIENT_ID / GITHUB_TOKEN
are rejected even though they are valid names (no '=' / ' ' / leading
digit / uppercase secret).

Per architecture decision in closeout §1: keep source `name` lowercase
(referenced in plan/evidence/registry lookups), expand `credentials[]`
pattern to standard environment-variable NAME shape:

    ^[A-Za-z_][A-Za-z0-9_]*$

This still rejects '=' / spaces / leading digits / the secret values
themselves; it accepts conventional env-var names.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.errors import ConfigValidationError
from gtm_intelligence.pipeline.source_registry import load_registry


def _src(credentials):
    return f"""
- name: foo
  enabled: true
  type: community
  cost: free
  auth_required: true
  credentials: {credentials!r}
  priority: 50
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 900
""".replace(
        "'", "\""
    )


@pytest.mark.parametrize(
    "name",
    [
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "_PRIVATE_TOKEN_NAME",
        "reddit_client_id",
        "github_token",
        "A",
        "_",
    ],
)
def test_valid_credential_names_accepted(name):
    reg = load_registry(yaml_text=_src([name]))
    assert reg.entries[0].credentials == (name,)


@pytest.mark.parametrize(
    "name",
    [
        "REDDIT-CLIENT-ID",          # '-'
        "REDDIT CLIENT ID",          # space
        "123TOKEN",                  # leading digit
        "GITHUB_TOKEN=abc123",       # contains '=' (looks like a k=v)
        "a=b",                       # explicit secret shape
        "x.y",                       # dot
        "x y z",                     # space
        "",                          # empty
    ],
)
def test_invalid_credential_names_rejected(name):
    with pytest.raises(ConfigValidationError):
        load_registry(yaml_text=_src([name]))


def test_multiple_valid_names_pass_through_in_order():
    creds_yaml = (
        "- name: foo\n"
        "  enabled: true\n"
        "  type: community\n"
        "  cost: free\n"
        "  auth_required: true\n"
        '  credentials: ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"]\n'
        "  priority: 50\n"
        "  capabilities: [search]\n"
        "  markets: [global]\n"
        "  languages: [en]\n"
        "  cache_ttl: 900\n"
    )
    reg = load_registry(yaml_text=creds_yaml)
    assert reg.entries[0].credentials == ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")


def test_source_name_pattern_remains_lowercase():
    """`name` (the source identifier) is NOT a credential name and must
    stay lowercase per the existing convention (referenced in plans, evidence,
    etc.). This test is regression-only — do not relax the source-name pattern."""
    invalid_name_yaml = """
- name: Reddit
  enabled: true
  type: community
  cost: free
  auth_required: false
  credentials: []
  priority: 50
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 900
"""
    with pytest.raises(ConfigValidationError):
        load_registry(yaml_text=invalid_name_yaml)
