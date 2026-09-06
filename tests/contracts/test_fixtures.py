"""Fixture sweep: every tests/fixtures/<scenario>.<contract>.json must validate
against its contract schema. Also validates config/sources.yaml against the
source_registry schema.

Naming convention: <scenario>.<contract>.json where contract ∈
{research_plan, evidence, signal, insight, output}.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from conftest import CONFIG_DIR, FIXTURE_DIR, validate  # noqa: E402
from conftest import load_schema  # noqa: E402

CONTRACT_TO_SCHEMA = {
    "research_plan": "research_plan.schema.json",
    "evidence": "evidence.schema.json",
    "signal": "signal.schema.json",
    "insight": "insight.schema.json",
    "output": "output.schema.json",
}

FIXTURE_FILES = sorted(
    str(p.relative_to(FIXTURE_DIR))
    for p in FIXTURE_DIR.glob("*.json")
    if "." in p.name and p.name.split(".")[1] in CONTRACT_TO_SCHEMA
)


@pytest.mark.parametrize("relpath", FIXTURE_FILES)
def test_fixture_validates_against_contract(relpath):
    """Each fixture validates against its declared contract schema."""
    import json

    schema_name = CONTRACT_TO_SCHEMA[relpath.split(".")[1]]
    schema = load_schema(schema_name)
    with (FIXTURE_DIR / relpath).open(encoding="utf-8") as fh:
        instance = json.load(fh)
    validate(instance, schema)


def test_sources_yaml_validates_against_registry_schema():
    """config/sources.yaml conforms to source_registry.schema.json."""
    import yaml

    schema = load_schema("source_registry.schema.json")
    with (CONFIG_DIR / "sources.yaml").open(encoding="utf-8") as fh:
        registry = yaml.safe_load(fh)
    validate(registry, schema)
    names = [e["name"] for e in registry]
    assert len(names) == len(set(names)), "source names must be unique"


def test_sources_yaml_has_no_real_secrets():
    """Seed registry contains no credential values (contract hygiene)."""
    import yaml

    with (CONFIG_DIR / "sources.yaml").open(encoding="utf-8") as fh:
        registry = yaml.safe_load(fh)
    for entry in registry:
        for cred in entry.get("credentials", []):
            assert cred == cred.lower(), f"credential name not snake_case: {cred}"
            assert "=" not in cred and " " not in cred
