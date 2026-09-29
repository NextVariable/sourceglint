"""Source Registry runtime loader/validator (Phase 3 §22).

Loads config/sources.yaml, validates against schemas/source_registry.schema.json,
and exposes a deterministic ordered list of SourceEntry records.

The runtime loader does NOT call any source. It is the configuration SoT
read by the orchestrator (Phase 3 §23) and the doctor command (Phase 8).

The schema enforces:
  - source `name` is lowercase snake_case (^[a-z][a-z0-9_]*$) — it is the
    canonical identifier referenced in plans, evidence, and reports.
  - credential items use POSIX env-var name shape
    (^[A-Za-z_][A-Za-z0-9_]*$) — accepts REDDIT_CLIENT_ID / GITHUB_TOKEN etc.
    still rejects '=' / spaces / leading digits / secret-shaped values.
  - additionalProperties:false on every entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ..errors import ConfigValidationError


REGISTRY_DIR = "config"


@dataclass(frozen=True)
class SourceEntry:
    """One source in the registry, post-validation."""

    name: str
    enabled: bool
    type: str
    cost: str
    auth_required: bool
    credentials: tuple[str, ...]
    priority: int
    capabilities: tuple[str, ...]
    markets: tuple[str, ...]
    languages: tuple[str, ...]
    cache_ttl: int
    max_queries_per_run: int


@dataclass(frozen=True)
class SourceRegistry:
    """In-memory registry after schema validation + sort."""

    entries: tuple[SourceEntry, ...]

    def eligible(self, plan_market: str, query_language: str) -> list[SourceEntry]:
        return eligible_sources_for(self, plan_market=plan_market, query_language=query_language)


def _schema_dir() -> Path:
    # src/gtm_intelligence/pipeline/source_registry.py → repo root = parents[3]
    return Path(__file__).resolve().parents[3] / "schemas"


def _load_validators() -> Draft202012Validator:
    """Build a validator anchored on the source_registry schema."""
    schema_dir = _schema_dir()
    registry_files = [
        "common.schema.json",
        "source_registry.schema.json",
    ]
    resources: list[tuple[str, Resource]] = []
    for name in registry_files:
        path = schema_dir / name
        text = path.read_text(encoding="utf-8")
        schema = yaml is not None and None  # noqa  (placeholder for typing)
        import json as _json
        resources.append((name, Resource.from_contents(_json.loads(text))))
    registry = Registry().with_resources(resources)
    import json as _json
    sr = _json.loads((schema_dir / "source_registry.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(sr, registry=registry)


def _coerce_entry(raw: dict) -> SourceEntry:
    return SourceEntry(
        name=str(raw["name"]),
        enabled=bool(raw["enabled"]),
        type=str(raw["type"]),
        cost=str(raw["cost"]),
        auth_required=bool(raw["auth_required"]),
        credentials=tuple(str(c) for c in (raw.get("credentials") or [])),
        priority=int(raw.get("priority", 50)),
        capabilities=tuple(str(c) for c in (raw.get("capabilities") or [])),
        markets=tuple(str(m) for m in (raw.get("markets") or [])),
        languages=tuple(str(l) for l in (raw.get("languages") or [])),
        cache_ttl=int(raw.get("cache_ttl", 0)),
        max_queries_per_run=int(raw.get("max_queries_per_run", 24)),
    )


def load_registry(
    *,
    path: Path | str | None = None,
    yaml_text: str | None = None,
) -> SourceRegistry:
    """Load + validate + sort the source registry.

    Exactly one of (path, yaml_text) is required. If neither is provided,
    defaults to <repo>/config/sources.yaml.

    Sort order: priority desc, name asc — fully deterministic.
    """
    if path is not None and yaml_text is not None:
        raise ConfigValidationError(
            "load_registry accepts at most one of path/yaml_text"
        )
    if yaml_text is not None:
        data = yaml.safe_load(yaml_text)
    else:
        p = Path(path) if path is not None else (
            Path(__file__).resolve().parents[3] / REGISTRY_DIR / "sources.yaml"
        )
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

    if not isinstance(data, list):
        raise ConfigValidationError(
            "sources.yaml top-level must be a list of source entries"
        )

    validator = _load_validators()
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        # Surface first error with a stable path so tests can assert.
        first = errors[0]
        path_str = "/".join(str(p) for p in first.path) or "<root>"
        raise ConfigValidationError(
            f"source registry schema invalid at {path_str}: {first.message}"
        )

    entries = tuple(
        sorted(
            (_coerce_entry(e) for e in data),
            key=lambda s: (-s.priority, s.name),
        )
    )
    return SourceRegistry(entries=entries)


def eligible_sources_for(
    registry: SourceRegistry,
    *,
    plan_market: str,
    query_language: str,
) -> list[SourceEntry]:
    """Return registry entries eligible for (plan_market, query_language).

    Filter rules:
      1. enabled == True
      2. market compatibility (matches retrieval_plan._market_compatible)
      3. language compatibility — source lists query_language, or no languages
         declared (treated as compatible with English only — most permissive)
    """
    from .retrieval_plan import _language_compatible, _market_compatible

    out: list[SourceEntry] = []
    for e in registry.entries:
        if not e.enabled:
            continue
        if not _market_compatible(list(e.markets), plan_market):
            continue
        if not _language_compatible(list(e.languages), query_language):
            continue
        out.append(e)
    return out
