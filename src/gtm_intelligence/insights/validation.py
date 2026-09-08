"""Phase 6A §4 — insight schema validation (code-side guardrails).

Mirrors the frozen `insight.schema.json` invariants so drift fails
loudly instead of silently. Full JSON Schema validation happens at the
contract boundary; this is a fast, dependency-free re-check.

Key invariants (insight.schema.json):
  - required: insight_id, type, statement, confidence
  - type ∈ {FACT, INFERENCE, RECOMMENDATION}
  - FACT/INFERENCE: action forbidden (allOf: not required action)
  - RECOMMENDATION: action required (allOf: required action)
  - gtm_implications: keys ∈ frozen 16-dimension enum
  - confidence: 0.0–1.0
  - additionalProperties: false
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .gtm_implications import GTM_DIMENSIONS
from .ids import is_valid_insight_id

#: Repo root: src/gtm_intelligence/insights/validation.py → parents[3]
_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"

#: insight.schema.json — the ONLY keys an insight dict may carry.
INSIGHT_SCHEMA_KEYS = frozenset({
    "insight_id", "type", "statement", "signal_ids", "evidence_ids",
    "confidence", "gtm_implications", "rationale", "action",
})

#: Allowed insight types (frozen insight.schema.json enum).
INSIGHT_TYPES = frozenset({"FACT", "INFERENCE", "RECOMMENDATION"})


def validate_insight_schema(insight: Mapping[str, Any]) -> list[str]:
    """Code-side insight.schema.json invariants.

    Returns a list of violation strings (empty = valid).
    """
    violations: list[str] = []

    # 1. Required keys
    for k in ("insight_id", "type", "statement", "confidence"):
        if k not in insight:
            violations.append(f"missing required key: {k}")
            return violations  # nothing else is meaningful

    # 2. Allowed keys only (additionalProperties: false)
    extra = sorted(set(insight) - INSIGHT_SCHEMA_KEYS)
    if extra:
        violations.append(f"keys outside insight.schema.json: {', '.join(extra)}")

    # 3. insight_id pattern
    if not is_valid_insight_id(str(insight["insight_id"])):
        violations.append(f"insight_id does not match ins_ pattern: {insight['insight_id']!r}")

    # 4. Type enum
    ins_type = str(insight["type"])
    if ins_type not in INSIGHT_TYPES:
        violations.append(f"unknown type: {ins_type!r}")

    # 5. Action boundary (allOf in insight.schema.json)
    if ins_type in ("FACT", "INFERENCE") and "action" in insight:
        violations.append(f"{ins_type} must not carry action")
    if ins_type == "RECOMMENDATION" and "action" not in insight:
        violations.append("RECOMMENDATION must carry action")

    # 6. Confidence range
    conf = insight.get("confidence")
    if conf is not None:
        try:
            conf_val = float(conf)
            if conf_val < 0.0 or conf_val > 1.0:
                violations.append(f"confidence out of range: {conf_val}")
        except (TypeError, ValueError):
            violations.append(f"confidence not a number: {conf!r}")

    # 7. Statement non-empty
    if not str(insight.get("statement") or "").strip():
        violations.append("statement must be non-empty")

    # 8. GTM implications keys (if present)
    gtm = insight.get("gtm_implications")
    if gtm is not None and isinstance(gtm, Mapping):
        for key in gtm:
            if key not in GTM_DIMENSIONS:
                violations.append(f"unknown GTM dimension: {key}")

    return violations


# --- frozen-schema gate (PRD §4 Gate B) ------------------------------------


def _insight_schema() -> dict:
    return json.loads((_SCHEMAS_DIR / "insight.schema.json").read_text(encoding="utf-8"))


def _common_schema() -> dict:
    return json.loads((_SCHEMAS_DIR / "common.schema.json").read_text(encoding="utf-8"))


def _insight_validator():
    """Draft 2020-12 validator wired with the frozen common.schema.json ref."""
    import jsonschema
    from referencing import Registry, Resource

    reg = Registry().with_resources(
        [("common.schema.json", Resource.from_contents(_common_schema()))]
    )
    return jsonschema.Draft202012Validator(_insight_schema(), registry=reg)


def validate_insight_against_frozen_schema(insight: Mapping[str, Any]) -> list[str]:
    """Validate against the REAL schemas/insight.schema.json (Gate B).

    `validate_insight_schema()` is a fast dependency-free mirror used inside
    the hot loop; this function is the authoritative gate. It is used by the
    contract/eval tests to prove no drift between code and frozen schema.

    Returns a list of violation strings (empty = valid).
    """
    import jsonschema

    try:
        validator = _insight_validator()
    except Exception as exc:  # pragma: no cover - schema packaging broken
        return [f"insight validator unavailable: {exc}"]

    violations: list[str] = []
    for err in sorted(validator.iter_errors(dict(insight)), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        violations.append(f"{loc}: {err.message}")
    return violations
