"""Contract Drift Gate (Phase 3 §29).

This is a SHIPPING gate, not a single test. It runs:

  * Every normalized Evidence payload — schema-valid against evidence.schema.json.
  * Every Research Plan shape we accept — schema-valid against research_plan.schema.json.
  * Every Source Registry we accept — schema-valid against source_registry.schema.json.

If any of these drift (e.g. a pipeline consumer adds a field, or a future
phase secretly mutates the contract), this gate catches it before commit.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from sourceglint.normalization import normalize_raw, validate_evidence_payload
from sourceglint.pipeline.adapters import FakeSourceAdapter, RawSourceResult
from sourceglint.pipeline.adapters import SourceAdapter
from sourceglint.pipeline.orchestrator import PipelineConfig, ResearchPipeline
from sourceglint.ledger import EvidenceLedger


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _evidence_validator():
    reg = (
        Registry()
        .with_resources(
            [("common.schema.json", Resource.from_contents(_load_schema("common.schema.json")))]
        )
    )
    return jsonschema.Draft202012Validator(
        _load_schema("evidence.schema.json"), registry=reg
    )


def _plan_validator():
    reg = (
        Registry()
        .with_resources(
            [("common.schema.json", Resource.from_contents(_load_schema("common.schema.json")))]
        )
    )
    return jsonschema.Draft202012Validator(
        _load_schema("research_plan.schema.json"), registry=reg
    )


def _registry_validator():
    reg = (
        Registry()
        .with_resources(
            [("common.schema.json", Resource.from_contents(_load_schema("common.schema.json")))]
        )
    )
    return jsonschema.Draft202012Validator(
        _load_schema("source_registry.schema.json"), registry=reg
    )


# ---------- evidence schema compliance ------------------------------------


def test_normalize_raw_evidence_passes_schema():
    validator = _evidence_validator()
    raws = [
        RawSourceResult(
            source="reddit",
            source_type="post",
            source_native_id="1",
            url="https://reddit.com/r/x/1",
            title="t",
            text="b",
            published_at="2026-08-30T00:00:00Z",
        ),
        RawSourceResult(
            source="official_web",
            source_type="page",
            source_native_id="2",
            url="https://example.com/p",
            title="Notion 値上げ",
            text="日本語のテスト",
            language="ja",
            market="jp",
            locale="ja-JP",
        ),
        RawSourceResult(
            source="github",
            source_type="release",
            source_native_id="3",
            url="https://github.com/foo/bar/releases/tag/v1",
            title="v1",
            text="release notes",
        ),
    ]
    for raw in raws:
        ev = normalize_raw(raw, as_of="2026-09-06T10:00:00Z")
        # validate() raises ValidationError on schema violation.
        validator.validate(ev)


def test_normalize_rejects_extra_field_via_validator():
    """Even if a consumer smuggles an extra field, the schema rejects it."""
    validator = _evidence_validator()
    r = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="1",
        url="https://reddit.com/r/x/1",
        title="t",
        text="b",
    )
    ev = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    ev["__leaked_field"] = "x"  # simulate a bad consumer
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(ev)


def test_validate_evidence_payload_helper_rejects_extra():
    r = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="1",
        url="https://reddit.com/r/x/1",
        title="t",
        text="b",
    )
    ev = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    ev["secret_field"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validate_evidence_payload(ev)


# ---------- research plan schema compliance ------------------------------


def test_research_plan_shape_minimal_passes_schema():
    validator = _plan_validator()
    plan = {
        "topic": "Notion AI",
        "mode": "competitor",
        "time_window": {"days": 30},
        "languages": ["en"],
        "market": "global",
    }
    validator.validate(plan)


def test_research_plan_shape_full_passes_schema():
    validator = _plan_validator()
    plan = {
        "topic": "Notion AI",
        "mode": "competitor",
        "time_window": {"days": 30},
        "languages": ["en", "ja"],
        "market": "jp",
        "locale": "ja-JP",
        "entities": ["Notion"],
        "decision_context": "watch pricing",
        "queries": ["Notion 値上げ"],
        "source_priorities": ["reddit", "github"],
    }
    validator.validate(plan)


def test_research_plan_unknown_mode_rejected():
    validator = _plan_validator()
    plan = {
        "topic": "x",
        "mode": "wrong_mode",
        "time_window": {"days": 30},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(plan)


# ---------- source registry schema compliance ----------------------------


def test_source_registry_passes_schema():
    validator = _registry_validator()
    registry = [
        {
            "name": "reddit",
            "enabled": True,
            "type": "community",
            "cost": "free",
            "auth_required": False,
            "credentials": [],
            "priority": 80,
            "capabilities": ["search", "comments"],
            "markets": ["global"],
            "languages": ["en"],
            "cache_ttl": 900,
        },
    ]
    validator.validate(registry)


def test_source_registry_rejects_secret_credential():
    validator = _registry_validator()
    registry = [
        {
            "name": "github",
            "enabled": True,
            "type": "official",
            "cost": "free",
            "auth_required": True,
            "credentials": ["token=ghp_abc123"],  # secret-looking string
            "priority": 80,
            "capabilities": ["search"],
            "markets": ["global"],
            "languages": ["en"],
        },
    ]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(registry)


# ---------- end-to-end drift gate ----------------------------------------


def test_pipeline_output_every_evidence_passes_schema(tmp_path):
    """Run the golden pipeline; every normalized output is schema-valid."""
    validator = _evidence_validator()

    FIX_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pipeline"
    fixtures = {
        "official_web": FIX_DIR / "golden_official_web.jsonl",
        "reddit": FIX_DIR / "golden_reddit.jsonl",
        "hacker_news": FIX_DIR / "golden_hacker_news.jsonl",
        "github": FIX_DIR / "golden_github.jsonl",
        "host_web_search": FIX_DIR / "golden_host_web_search.jsonl",
    }
    from sourceglint.pipeline.adapters import (
        AdapterUnavailable,
        FakeSourceAdapter,
        FixtureSourceAdapter,
    )
    from sourceglint.pipeline.degradation import SourceStatus

    plan = {
        "topic": "AI Meeting Assistant",
        "mode": "competitor",
        "market": "jp",
        "locale": "ja-JP",
        "languages": ["en", "ja"],
        "time_window": {"days": 30},
        "entities": ["Notion AI"],
        "decision_context": "watch JP pricing",
        "queries": ["Notion 値上げ"],
        "source_priorities": ["reddit", "github", "official_web", "host_web_search"],
    }
    sources = [
        {
            "name": "official_web",
            "enabled": True,
            "type": "official",
            "cost": "free",
            "auth_required": False,
            "credentials": [],
            "priority": 90,
            "capabilities": ["fetch"],
            "markets": ["global", "jp"],
            "languages": ["en"],
            "cache_ttl": 3600,
        },
        {
            "name": "reddit",
            "enabled": True,
            "type": "community",
            "cost": "free",
            "auth_required": False,
            "credentials": [],
            "priority": 80,
            "capabilities": ["search", "comments"],
            "markets": ["global", "jp"],
            "languages": ["en", "ja"],
            "cache_ttl": 900,
        },
        {
            "name": "github",
            "enabled": True,
            "type": "official",
            "cost": "free",
            "auth_required": False,
            "credentials": [],
            "priority": 85,
            "capabilities": ["search", "releases"],
            "markets": ["global", "jp"],
            "languages": ["en"],
            "cache_ttl": 3600,
        },
        {
            "name": "host_web_search",
            "enabled": True,
            "type": "web",
            "cost": "free",
            "auth_required": False,
            "credentials": [],
            "priority": 60,
            "capabilities": ["search"],
            "markets": ["global", "jp"],
            "languages": ["en"],
            "cache_ttl": 900,
        },
    ]

    def factory(name, plan):
        if name in fixtures:
            return FixtureSourceAdapter(name=name, path=fixtures[name])
        return FakeSourceAdapter(name=name)

    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=factory,
    )
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # Every evidence in the ledger must pass schema validation.
    for rec in ledger.all():
        validator.validate(rec.to_payload())


def test_phase1_evidence_schema_unmodified():
    """Phase 3 must NOT have altered the Phase 1 evidence schema."""
    schema_text = (SCHEMA_DIR / "evidence.schema.json").read_text(encoding="utf-8")
    # additionalProperties:false is the key drift guard.
    assert '"additionalProperties": false' in schema_text


def test_phase1_research_plan_schema_unmodified():
    schema_text = (SCHEMA_DIR / "research_plan.schema.json").read_text(encoding="utf-8")
    assert '"additionalProperties": false' in schema_text


def test_phase1_source_registry_schema_unmodified():
    schema_text = (SCHEMA_DIR / "source_registry.schema.json").read_text(encoding="utf-8")
    assert '"additionalProperties": false' in schema_text