"""Broad source discovery catalog and deterministic host-search routing.

``config/sources.yaml`` remains the truth for built-in runtime adapters.
``config/source_catalog.yaml`` is broader: it records where useful evidence may
exist, the legal/technical access route, and whether the route is usable now.

The separation is intentional. Listing a platform in the catalog must never be
interpreted as claiming a working API connector.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
import yaml
from referencing import Registry, Resource

from .errors import ConfigValidationError
from .resources import data_path


DEFAULT_CATALOG_PATH = data_path("config", "source_catalog.yaml")
_SCHEMA_PATH = data_path("schemas", "source_catalog.schema.json")
_COMMON_SCHEMA_PATH = data_path("schemas", "common.schema.json")


@dataclass(frozen=True)
class SourceTarget:
    name: str
    family: str
    routes: tuple[str, ...]
    availability: str
    credentials: tuple[str, ...]
    modes: tuple[str, ...]
    markets: tuple[str, ...]
    languages: tuple[str, ...]
    domains: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    priority: int
    notes: str = ""
    docs_url: str = ""

    def to_host_request(self) -> dict[str, object]:
        """Small, secret-free payload suitable for the JSON-lines bridge."""
        return {
            "name": self.name,
            "domains": list(self.domains),
            "availability": self.availability,
            "routes": list(self.routes),
            "evidence_roles": list(self.evidence_roles),
        }


def _validator() -> jsonschema.Draft202012Validator:
    common = json.loads(_COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [("common.schema.json", Resource.from_contents(common))]
    )
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _coerce(raw: Mapping[str, Any]) -> SourceTarget:
    return SourceTarget(
        name=str(raw["name"]),
        family=str(raw["family"]),
        routes=tuple(str(x) for x in raw["routes"]),
        availability=str(raw["availability"]),
        credentials=tuple(str(x) for x in (raw.get("credentials") or [])),
        modes=tuple(str(x) for x in raw["modes"]),
        markets=tuple(str(x) for x in raw["markets"]),
        languages=tuple(str(x) for x in raw["languages"]),
        domains=tuple(str(x) for x in raw["domains"]),
        evidence_roles=tuple(str(x) for x in raw["evidence_roles"]),
        priority=int(raw["priority"]),
        notes=str(raw.get("notes") or ""),
        docs_url=str(raw.get("docs_url") or ""),
    )


def load_source_catalog(path: Path | str | None = None) -> tuple[SourceTarget, ...]:
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    errors = sorted(_validator().iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(x) for x in first.path) or "<root>"
        raise ConfigValidationError(
            f"source catalog schema invalid at {where}: {first.message}"
        )
    names = [str(item["name"]) for item in data]
    if len(names) != len(set(names)):
        raise ConfigValidationError("source catalog source names must be unique")
    return tuple(_coerce(item) for item in data)


def select_host_search_targets(
    catalog: Sequence[SourceTarget],
    *,
    mode: str,
    market: str,
    language: str,
    budget: int = 10,
    covered_direct_sources: Sequence[str] = (),
) -> list[SourceTarget]:
    """Select a diverse, bounded set of public-web targets for one run.

    Exclude a direct source only when the caller explicitly reports it covered
    in this run. Catalog readiness alone is not evidence of execution; the
    first-run host-only profile must retain Reddit, HN and GitHub fallback.
    At most two targets per family are selected before a second fill pass.
    """
    if budget <= 0:
        return []

    candidates: list[SourceTarget] = []
    for target in catalog:
        if "host_web_search" not in target.routes:
            continue
        if target.name in covered_direct_sources:
            continue
        if target.availability == "unavailable":
            continue
        if mode not in target.modes:
            continue
        if "global" not in target.markets and market not in target.markets:
            continue
        if language not in target.languages and "en" not in target.languages:
            continue
        candidates.append(target)

    candidates.sort(
        key=lambda item: (
            -(item.priority + (10 if market != "global" and market in item.markets else 0)),
            item.name,
        )
    )

    selected: list[SourceTarget] = []
    family_counts: dict[str, int] = {}
    selected_names: set[str] = set()
    for target in candidates:
        if family_counts.get(target.family, 0) >= 2:
            continue
        selected.append(target)
        selected_names.add(target.name)
        family_counts[target.family] = family_counts.get(target.family, 0) + 1
        if len(selected) >= budget:
            return selected

    for target in candidates:
        if target.name in selected_names:
            continue
        selected.append(target)
        if len(selected) >= budget:
            break
    return selected


__all__ = [
    "DEFAULT_CATALOG_PATH",
    "SourceTarget",
    "load_source_catalog",
    "select_host_search_targets",
]
