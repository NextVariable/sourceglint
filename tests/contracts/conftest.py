"""Phase 1 contract test infrastructure.

Loads JSON Schemas from ../../schemas and validates instances against them.
Also provides helpers to load YAML source registry and fixtures.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
CONFIG_DIR = ROOT / "config"
FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

VALIDATOR_CLASS = jsonschema.validators.validator_for(
    {"$schema": "https://json-schema.org/draft/2020-12/schema"}
)
# Set explicit format checker (jsonschema does not validate formats by default)
FORMAT_CHECKER = jsonschema.FormatChecker()

# All schemas reference shared definitions via stable $id namespaces
# (e.g. https://schemas.gtm-intelligence.dev/common.schema.json).
# Build a referencing registry over every schema in schemas/.
def _build_registry():
    import referencing

    registry = referencing.Registry()
    for schema_file in sorted(SCHEMA_DIR.glob("*.schema.json")):
        with schema_file.open(encoding="utf-8") as fh:
            contents = json.load(fh)
        resource = referencing.Resource.from_contents(contents)
        schema_id = contents.get("$id")
        uri = schema_id if schema_id else str(schema_file.name)
        registry = registry.with_resource(uri=uri, resource=resource)
    return registry


REGISTRY = _build_registry()


def load_schema(name: str) -> dict[str, Any]:
    """Load a JSON Schema by filename (e.g. 'evidence.schema.json')."""
    path = SCHEMA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate(instance: Any, schema: dict[str, Any]) -> None:
    """Validate instance against schema. Raises ValidationError on failure."""
    validator = VALIDATOR_CLASS(schema, registry=REGISTRY, format_checker=FORMAT_CHECKER)
    validator.validate(instance)


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_fixture(relpath: str) -> dict[str, Any]:
    """Load a JSON fixture under tests/fixtures/ by relative path."""
    path = FIXTURE_DIR / relpath
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def evidence_schema():
    return load_schema("evidence.schema.json")


@pytest.fixture
def research_plan_schema():
    return load_schema("research_plan.schema.json")


@pytest.fixture
def signal_schema():
    return load_schema("signal.schema.json")


@pytest.fixture
def insight_schema():
    return load_schema("insight.schema.json")


@pytest.fixture
def source_registry_schema():
    return load_schema("source_registry.schema.json")


@pytest.fixture
def output_schema():
    return load_schema("output.schema.json")
