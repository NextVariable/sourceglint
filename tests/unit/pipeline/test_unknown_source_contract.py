"""Tests for unknown-source tier/quality defaulting (Phase 3 Closeout §3).

Evidence contract: source_tier and evidence_quality are OPTIONAL fields.
Per PRD §3 closeout rule, an UNKNOWN source MUST NOT be assigned a
synthetic neutral value (T3 / 0.5). The phases are:
  - known source (in source registry / tier map) -> derive deterministic
    source_tier + evidence_quality.
  - unknown source -> OMIT both fields. Schema validation must still pass
    because both are optional.
"""
from __future__ import annotations

import pytest

from sourceglint.normalization import (
    normalize_raw,
    validate_evidence_payload,
)
from sourceglint.pipeline.adapters import RawSourceResult


# Tier map is hardcoded into normalizer for MVP (Phase 3).
KNOWN_SOURCES = {
    "official_web": 1,
    "github": 1,
    "reddit": 2,
    "hacker_news": 2,
    "host_web_search": 4,
}


def _raw(source: str = "reddit") -> RawSourceResult:
    return RawSourceResult(
        source=source,
        source_type="post",
        source_native_id="x",
        url=f"https://example.com/{source}/x",
        title="t",
        text="b",
        published_at="2026-08-25T00:00:00Z",
        language="en",
        market="global",
    )


@pytest.mark.parametrize("source", sorted(KNOWN_SOURCES.keys()))
def test_known_source_has_source_tier_and_quality(source):
    ev = normalize_raw(_raw(source), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert "source_tier" in ev
    assert "evidence_quality" in ev
    assert ev["source_tier"] == KNOWN_SOURCES[source]
    # v0.2 §9: T1=1.0, T2=0.6, T3=0.8, T4=0.3
    expected_quality = {1: 1.0, 2: 0.6, 3: 0.8, 4: 0.3}[KNOWN_SOURCES[source]]
    assert ev["evidence_quality"] == expected_quality


@pytest.mark.parametrize(
    "source",
    [
        "unknown_site",
        "brandnewshiny",
        "mystery_source",
        "x",
    ],
)
def test_unknown_source_omits_source_tier_and_quality(source):
    """Per closeout §3: unknown source MUST NOT have synthetic defaults."""
    ev = normalize_raw(_raw(source), as_of="2026-09-06T10:00:00Z")
    # Schema validation should still pass (both fields are optional).
    validate_evidence_payload(ev)
    assert "source_tier" not in ev, f"{source} leaked synthetic source_tier"
    assert "evidence_quality" not in ev, f"{source} leaked synthetic evidence_quality"


def test_unknown_source_extra_provenance():
    """Unknown sources still get source/source_type/retrieved_at — what was
    preserved before normalization."""
    ev = normalize_raw(_raw("cryptic_aggregator"), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert ev["source"] == "cryptic_aggregator"
    assert ev["source_type"] == "post"
    assert ev["retrieved_at"] == "2026-09-06T10:00:00Z"


def test_unknown_source_does_not_set_quality_05():
    """The legacy 0.5 fallback must be gone — no score laundering."""
    ev = normalize_raw(_raw("cryptic_aggregator"), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    # absence is what matters
    assert "evidence_quality" not in ev


def test_unknown_source_omission_does_not_break_schema():
    """Golden regression: schema evidence.schema.json accepts optional absence."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    import json as _json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    schema = _json.loads(
        (repo_root / "schemas" / "evidence.schema.json").read_text()
    )
    common = _json.loads(
        (repo_root / "schemas" / "common.schema.json").read_text()
    )
    validator = Draft202012Validator(
        schema,
        registry=Registry().with_resources(
            [("common.schema.json", Resource.from_contents(common))]
        ),
    )
    ev = normalize_raw(_raw("cryptic_aggregator"), as_of="2026-09-06T10:00:00Z")
    # Must not raise.
    validator.validate(ev)
