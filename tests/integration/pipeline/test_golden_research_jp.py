"""Golden Research Case: AI Meeting / Translation Assistant — Japan (Phase 3 §26).

End-to-end Phase 3 pipeline test using fixture-only adapters.
Asserts:
  * Evidence IDs stable across runs.
  * Evidence count stable.
  * Duplicate count stable (canonical URL + Reddit native_id deduplication).
  * Source statuses stable (one UNAVAILABLE).
  * JP / EN metadata preserved through normalization.
  * Current vs baseline window correctness.
  * Unavailable source correctly degraded.
  * Ledger content stable.
  * No Signal / Insight / Recommendation produced.

Fixture files live under tests/fixtures/pipeline/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sourceglint.errors import ConfigValidationError
from sourceglint.ledger import EvidenceLedger
from sourceglint.normalization import validate_evidence_payload
from sourceglint.pipeline.adapters import (
    AdapterUnavailable,
    FakeSourceAdapter,
    FixtureSourceAdapter,
)
from sourceglint.pipeline.degradation import SourceStatus
from sourceglint.pipeline.orchestrator import (
    PipelineConfig,
    ResearchPipeline,
)


FIX_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pipeline"


def _plan() -> dict:
    return json.loads((FIX_DIR / "golden_research_jp_plan.json").read_text(encoding="utf-8"))


def _source(name: str, **overrides) -> dict:
    src = {
        "name": name,
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],
        "priority": 50,
        "capabilities": ["search"],
        "markets": ["global", "jp"],  # Golden case plan is jp.
        "languages": ["en"],
        "cache_ttl": 900,
    }
    if name in {"reddit", "hacker_news"}:
        src["languages"] = ["en", "ja"]
    if name == "github":
        src["type"] = "official"
        src["priority"] = 85
        src["capabilities"] = ["search", "releases"]
    if name == "official_web":
        src["type"] = "official"
        src["priority"] = 90
        src["capabilities"] = ["fetch"]
    if name == "host_web_search":
        src["type"] = "web"
        src["priority"] = 60
        src["capabilities"] = ["search"]
    if name == "failing_source":
        src["priority"] = 40
    src.update(overrides)
    return src


def _pipeline(plan=None, sources=None, as_of="2026-09-06T10:00:00Z"):
    plan = plan or _plan()
    sources = sources or [
        _source("official_web"),
        _source("reddit"),
        _source("hacker_news"),
        _source("github"),
        _source("host_web_search"),
        _source("failing_source"),
    ]
    # Adapter factory — one per source.
    fixtures = {
        "official_web": FIX_DIR / "golden_official_web.jsonl",
        "reddit": FIX_DIR / "golden_reddit.jsonl",
        "hacker_news": FIX_DIR / "golden_hacker_news.jsonl",
        "github": FIX_DIR / "golden_github.jsonl",
        "host_web_search": FIX_DIR / "golden_host_web_search.jsonl",
    }
    factory_calls = {"n": 0}

    def factory(name, plan):
        factory_calls["n"] += 1
        if name == "failing_source":
            return FakeSourceAdapter(
                name="failing_source",
                raises=AdapterUnavailable(source="failing_source", reason="503"),
            )
        if name in fixtures:
            return FixtureSourceAdapter(name=name, path=fixtures[name])
        return FakeSourceAdapter(name=name)

    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of=as_of),
        adapter_factory=factory,
    )
    return pipeline, plan, sources, factory_calls


# ---------- happy path -------------------------------------------------------


def test_golden_jp_pipeline_returns_evidence():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert len(result.evidence_ids) >= 5


def test_golden_jp_pipeline_all_evidence_schema_valid():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    for record in ledger.all():
        # Convert the record's payload back to dict and validate.
        validate_evidence_payload(record.to_payload())


def test_golden_jp_pipeline_japanese_text_preserved():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # Find at least one evidence with Japanese snippet.
    found_ja = False
    for rec in ledger.all():
        snippet = (rec.snippet or "")
        if any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF for c in snippet):
            found_ja = True
            break
    assert found_ja


def test_golden_jp_pipeline_jp_metadata_preserved():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    markets = {rec.extra.get("market") for rec in ledger.all()}
    # JP market present.
    assert "jp" in markets


def test_golden_jp_pipeline_languages_covered():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert "en" in list(result.coverage.languages_covered)
    assert "ja" in list(result.coverage.languages_covered)


def test_golden_jp_pipeline_markets_covered():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # jp must be in the coverage.
    assert "jp" in list(result.coverage.markets_covered)


# ---------- dedup -----------------------------------------------------------


def test_golden_jp_pipeline_canonical_url_dedup():
    """Notion.so/pricing appears in official_web + host_web_search; same id kept."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # Count distinct evidence_ids that point at notion.so/pricing.
    notion_pricing = [
        rec for rec in ledger.all()
        if rec.url.startswith("https://notion.so/pricing")
    ]
    # Only one survives dedup (canonical URL match).
    assert len(notion_pricing) == 1


def test_golden_jp_pipeline_utm_dedup():
    """reddit post + utm_source=fb variant must collapse via canonical URL."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # Only one reddit post per canonical URL.
    posts = [r for r in ledger.all() if r.source == "reddit" and r.source_type == "post"]
    assert len(posts) == 1


# ---------- degradation -----------------------------------------------------


def test_golden_jp_pipeline_failing_source_recorded():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert "failing_source" in list(result.coverage.failed_sources)
    assert result.source_statuses["failing_source"].status == SourceStatus.UNAVAILABLE


def test_golden_jp_pipeline_no_all_sources_failed():
    """Other sources succeed so the pipeline completes."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    # Should NOT raise AllSourcesFailedError.
    pipeline.run(plan=plan, sources=sources, ledger=ledger)


# ---------- determinism -----------------------------------------------------


def test_golden_jp_pipeline_deterministic_20_runs():
    snapshots = []
    for _ in range(20):
        pipeline, plan, sources, _ = _pipeline()
        ledger = EvidenceLedger(":memory:")
        result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
        snapshots.append(tuple(sorted(result.evidence_ids)))
    first = snapshots[0]
    assert all(s == first for s in snapshots)


def test_golden_jp_pipeline_ledger_count_stable():
    counts = []
    for _ in range(20):
        pipeline, plan, sources, _ = _pipeline()
        ledger = EvidenceLedger(":memory:")
        result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
        counts.append(ledger.count())
    assert len(set(counts)) == 1


def test_golden_jp_pipeline_evidence_ids_stable():
    seen_ids = []
    for _ in range(5):
        pipeline, plan, sources, _ = _pipeline()
        ledger = EvidenceLedger(":memory:")
        result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
        seen_ids.append(tuple(sorted(result.evidence_ids)))
    first = seen_ids[0]
    assert all(s == first for s in seen_ids)


# ---------- window correctness ---------------------------------------------


def test_golden_jp_pipeline_default_window_is_current():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    current_count = 0
    for rec in ledger.all():
        if rec.extra.get("window") in (None, "current", ""):
            current_count += 1
    assert current_count == ledger.count()


def test_golden_jp_pipeline_baseline_window_records_baseline():
    """Run with baseline window — all evidence records window='baseline'."""
    plan = _plan()
    sources = [
        _source("official_web"),
        _source("reddit"),
        _source("hacker_news"),
        _source("github"),
        _source("host_web_search"),
        _source("failing_source"),
    ]
    fixtures = {
        "official_web": FIX_DIR / "golden_official_web.jsonl",
        "reddit": FIX_DIR / "golden_reddit.jsonl",
        "hacker_news": FIX_DIR / "golden_hacker_news.jsonl",
        "github": FIX_DIR / "golden_github.jsonl",
        "host_web_search": FIX_DIR / "golden_host_web_search.jsonl",
    }
    def factory(name, plan):
        if name == "failing_source":
            return FakeSourceAdapter(
                name="failing_source",
                raises=AdapterUnavailable(source="failing_source", reason="503"),
            )
        if name in fixtures:
            return FixtureSourceAdapter(name=name, path=fixtures[name])
        return FakeSourceAdapter(name=name)
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z", window="baseline"),
        adapter_factory=factory,
    )
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    baseline_count = sum(
        1 for rec in ledger.all() if rec.extra.get("window") == "baseline"
    )
    assert baseline_count == ledger.count()


# ---------- coverage -------------------------------------------------------


def test_golden_jp_pipeline_coverage_summary():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    summary = result.coverage.summary()
    # New format is `raw=X normalized=Y time_drop=T dedup_drop=D final=N`
    assert "raw=" in summary
    assert "normalized=" in summary
    assert "final=" in summary


def test_golden_jp_pipeline_no_signal_no_insight_no_recommendation():
    """Pipeline returns no signals/insights/recommendations."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    for forbidden in ("signals", "insights", "recommendations", "gtm_actions"):
        assert not hasattr(result, forbidden)


def test_golden_jp_pipeline_duplicate_count_alias():
    """Dedup metric is now `duplicate_dropped_count`. The legacy
    `deduplicated_count` is a back-compat alias (Closeout §5)."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    # New canonical name:
    assert result.coverage.duplicate_dropped_count >= 0
    # Alias still works for back-compat.
    assert result.coverage.deduplicated_count == result.coverage.duplicate_dropped_count


def test_golden_jp_pipeline_arithmetic_invariant():
    """raw -> normalized -> time_filter_dropped -> dedup_dropped -> final
    Y - T - D == N."""
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    cov = result.coverage
    assert (
        cov.normalized_evidence_count
        - cov.time_filter_dropped_count
        - cov.duplicate_dropped_count
        == cov.final_evidence_count
    )


# ---------- schema contract drift ----------------------------------------


def test_golden_jp_pipeline_no_extra_evidence_fields():
    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    pipeline.run(plan=plan, sources=sources, ledger=ledger)
    forbidden_extras = {
        "matched_queries", "source_hits", "retrieval_count",
        "provenance", "score",
    }
    for rec in ledger.all():
        for f in forbidden_extras:
            assert f not in rec.to_payload()


# ---------- plan modes ------------------------------------------------------


def test_golden_jp_pipeline_market_mode_works():
    plan = _plan()
    plan["mode"] = "market"
    pipeline, plan_, sources, _ = _pipeline(plan=plan)
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan_, sources=sources, ledger=ledger)
    assert len(result.evidence_ids) >= 5


def test_golden_jp_pipeline_voc_mode_works():
    plan = _plan()
    plan["mode"] = "voc"
    pipeline, plan_, sources, _ = _pipeline(plan=plan)
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan_, sources=sources, ledger=ledger)
    assert len(result.evidence_ids) >= 5


def test_golden_jp_pipeline_invalid_mode_in_plan_rejected():
    plan = _plan()
    plan["mode"] = "invalid_mode"
    pipeline, plan_, sources, _ = _pipeline(plan=plan)
    ledger = EvidenceLedger(":memory:")
    with pytest.raises(Exception):
        pipeline.run(plan=plan_, sources=sources, ledger=ledger)


def test_golden_jp_pipeline_invalid_source_registry_rejected():
    pipeline, _, _, _ = _pipeline()
    plan = _plan()
    bad_sources = [{"name": "reddit"}]  # missing required fields
    ledger = EvidenceLedger(":memory:")
    with pytest.raises(ConfigValidationError):
        pipeline.run(plan=plan, sources=bad_sources, ledger=ledger)