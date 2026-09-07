"""Phase 5 integration test support — JSON Schema registry + fixture loaders.

NOT named conftest.py: tests/contracts tests do `from conftest import ...` and a
second top-level conftest module would shadow it under the rootdir import
mode when both trees run in one pytest session.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import referencing
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures"


def _build_registry():
    registry = referencing.Registry()
    for schema_file in sorted(SCHEMA_DIR.glob("*.schema.json")):
        with schema_file.open(encoding="utf-8") as fh:
            contents = json.load(fh)
        registry = registry.with_resource(
            uri=contents.get("$id") or str(schema_file.name),
            resource=referencing.Resource.from_contents(contents),
        )
    return registry


REGISTRY = _build_registry()
VALIDATOR_CLASS = jsonschema.validators.validator_for(
    {"$schema": "https://json-schema.org/draft/2020-12/schema"}
)
FORMAT_CHECKER = jsonschema.FormatChecker()


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate(instance: Any, schema: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError when instance is not schema-valid."""
    validator = VALIDATOR_CLASS(
        schema, registry=REGISTRY, format_checker=FORMAT_CHECKER
    )
    validator.validate(instance)


def load_jsonl(name: str) -> list[dict]:
    with (FIXTURE_DIR / "phase5" / name).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_json(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def signal_schema():
    return load_schema("signal.schema.json")
