"""Contract tests for source_registry.schema.json.

Validates config/sources.yaml structure.
credentials field: ONLY names of required credentials, NEVER real secrets.
Schema additionalProperties=false catches accidental secret leakage into entries.
"""

from __future__ import annotations

import pytest

from conftest import validate


def _entry(**overrides):
    e = {
        "name": "reddit",
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],  # no credentials needed
        "priority": 80,
        "capabilities": ["search", "comments"],
        "rate_limit": {"rpm": 30},
        "markets": ["global"],
        "languages": ["en"],
        "cache_ttl": 900,
    }
    e.update(overrides)
    return e


# ---------------------------------------------------------------- valid cases

class TestRegistryValid:
    def test_entry_full(self, source_registry_schema):
        validate([_entry()], source_registry_schema)

    def test_multiple_entries(self, source_registry_schema):
        validate(
            [
                _entry(),
                _entry(
                    name="github",
                    type="official",
                    cost="free",
                    auth_required=True,
                    credentials=["github_token"],
                    capabilities=["search", "releases"],
                ),
            ],
            source_registry_schema,
        )

    def test_credential_names_are_strings(self, source_registry_schema):
        """Credentials is an array of NAMES (strings), not key-value objects."""
        validate(
            [_entry(credentials=["reddit_client_id", "reddit_secret"])],
            source_registry_schema,
        )

    def test_mvp_five_sources(self, source_registry_schema):
        entries = [
            _entry(name="host_web_search", type="web", capabilities=["search"]),
            _entry(name="official_web", type="official", capabilities=["fetch"]),
            _entry(name="reddit", type="community", capabilities=["search", "comments"]),
            _entry(name="hacker_news", type="community", capabilities=["search"]),
            _entry(name="github", type="official", capabilities=["search", "releases"]),
        ]
        validate(entries, source_registry_schema)


# --------------------------------------------------------------- invalid cases

class TestRegistryInvalid:
    def test_missing_name(self, source_registry_schema):
        e = _entry()
        del e["name"]
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_missing_enabled(self, source_registry_schema):
        e = _entry()
        del e["enabled"]
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_secret_in_entry_field(self, source_registry_schema):
        """Leaking a real secret as an extra field must be schema-invalid."""
        e = _entry()
        e["api_key"] = "sk-live-abcdef1234567890"
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_credentials_holding_secret_value(self, source_registry_schema):
        """Credential VALUE smuggled inside credentials array: item pattern rejects
        values that look like secrets (contains '=' or long token)."""
        e = _entry(credentials=["client_id=1234567890abcdef"])
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_invalid_cost(self, source_registry_schema):
        e = _entry(cost="enterprise")
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_invalid_priority_range(self, source_registry_schema):
        e = _entry(priority=101)
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_invalid_rate_limit_shape(self, source_registry_schema):
        e = _entry(rate_limit={"rpm": "thirty"})
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_invalid_type(self, source_registry_schema):
        e = _entry(type="search_engine_aggregator_marketplace")
        with pytest.raises(Exception):
            validate([e], source_registry_schema)

    def test_empty_registry_allowed(self, source_registry_schema):
        """An empty registry is structurally valid (all sources disabled/deleted)."""
        validate([], source_registry_schema)


# -------------------------------------------------------------- boundary cases

class TestRegistryBoundary:
    def test_credentials_absent(self, source_registry_schema):
        e = _entry()
        del e["credentials"]
        validate([e], source_registry_schema)

    def test_unknown_extra_field_rejected(self, source_registry_schema):
        e = _entry()
        e["secret_token_2"] = "ghp_abc123"
        with pytest.raises(Exception):
            validate([e], source_registry_schema)
