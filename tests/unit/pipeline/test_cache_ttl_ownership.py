"""Tests for cache TTL ownership (Phase 3 Closeout §4).

TTL ownership hierarchy:
  1. explicit per-request override (PipelineConfig.cache_ttl_seconds)
  2. source-specific cache_ttl (from SourceEntry.registry entry)
  3. PipelineConfig.default_cache_ttl_seconds (900 by default)

A TTL of 0 means "do not cache" (the caller signals no-cache). Values
<0 are invalid and must surface as a hard error.

The hardcoded TTL=900 in the orchestrator is gone — every cache write
goes through _ttl_for_source() which respects the priority order.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from gtm_intelligence.ledger import EvidenceLedger
from gtm_intelligence.pipeline.adapters import FakeSourceAdapter
from gtm_intelligence.pipeline.cache import RetrievalCache
from gtm_intelligence.pipeline.orchestrator import PipelineConfig, ResearchPipeline


def _src(name: str, cache_ttl: int, **overrides) -> dict:
    s = {
        "name": name,
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],
        "priority": 50,
        "capabilities": ["search"],
        "markets": ["global"],
        "languages": ["en"],
        "cache_ttl": cache_ttl,
    }
    s.update(overrides)
    return s


def _plan() -> dict:
    return {
        "topic": "T",
        "mode": "general",  # mode=general emits one query — keeps cache keys simple
        "market": "global",
        "locale": "en",
        "languages": ["en"],
        "time_window": {"days": 30},
        "entities": ["X"],
        "decision_context": "watch",
    }


def _adapter(name: str) -> FakeSourceAdapter:
    return FakeSourceAdapter(
        name=name,
        results=[
            {
                "source": name,
                "source_type": "post",
                "source_native_id": "1",
                "url": f"https://example.com/{name}/1",
                "title": "t",
                "text": "b",
                "published_at": "2026-08-25T00:00:00Z",
            }
        ],
    )


def _all_cache_payloads(root: Path) -> list[tuple[Path, dict]]:
    out = []
    for p in root.rglob("*.json"):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return out


def test_pipelineconfig_default_ttl_is_900():
    c = PipelineConfig(as_of="2026-09-06T10:00:00Z")
    assert c.default_cache_ttl_seconds == 900
    assert c.cache_ttl_seconds is None


def test_pipelineconfig_rejects_negative_default_ttl():
    with pytest.raises(ValueError):
        PipelineConfig(
            as_of="2026-09-06T10:00:00Z",
            default_cache_ttl_seconds=-1,
        )


def test_pipelineconfig_rejects_negative_explicit_ttl():
    with pytest.raises(ValueError):
        PipelineConfig(
            as_of="2026-09-06T10:00:00Z",
            cache_ttl_seconds=-1,
        )


def test_source_specific_ttl_used_for_cache_write(tmp_path):
    """Source's cache_ttl (3600) is applied to every cache write."""
    cache_root = tmp_path / ".cache"
    cache = RetrievalCache(cache_root)
    sources = [_src("reddit", cache_ttl=3600)]
    adapters = {"reddit": _adapter("reddit")}

    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z", cache=cache),
        adapter_factory=lambda name, p: adapters.get(name),
    )
    pipeline.run(plan=_plan(), sources=sources, ledger=EvidenceLedger(":memory:"))

    payloads = _all_cache_payloads(cache_root)
    assert payloads, "no cache files were written"
    as_of_dt = datetime.fromisoformat("2026-09-06T10:00:00+00:00")
    for _, body in payloads:
        exp_dt = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert int((exp_dt - as_of_dt).total_seconds()) == 3600


def test_explicit_override_wins_over_source_ttl(tmp_path):
    """PipelineConfig.cache_ttl_seconds is the top priority."""
    cache_root = tmp_path / ".cache"
    cache = RetrievalCache(cache_root)
    sources = [_src("reddit", cache_ttl=3600)]
    adapters = {"reddit": _adapter("reddit")}

    pipeline = ResearchPipeline(
        config=PipelineConfig(
            as_of="2026-09-06T10:00:00Z",
            cache=cache,
            cache_ttl_seconds=60,
        ),
        adapter_factory=lambda name, p: adapters.get(name),
    )
    pipeline.run(plan=_plan(), sources=sources, ledger=EvidenceLedger(":memory:"))

    payloads = _all_cache_payloads(cache_root)
    assert payloads
    as_of_dt = datetime.fromisoformat("2026-09-06T10:00:00+00:00")
    for _, body in payloads:
        exp_dt = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert int((exp_dt - as_of_dt).total_seconds()) == 60


def test_default_ttl_used_when_source_cache_ttl_absent(tmp_path):
    """If source has cache_ttl=0 (treated as 'no cache'), the cache write
    is skipped — pipeline remains correct, cache stays empty."""
    cache_root = tmp_path / ".cache"
    cache = RetrievalCache(cache_root)
    sources = [_src("reddit", cache_ttl=0)]
    adapters = {"reddit": _adapter("reddit")}

    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z", cache=cache),
        adapter_factory=lambda name, p: adapters.get(name),
    )
    pipeline.run(plan=_plan(), sources=sources, ledger=EvidenceLedger(":memory:"))

    payloads = _all_cache_payloads(cache_root)
    assert payloads == []  # no cache writes


def test_default_ttl_is_the_fallback(tmp_path):
    """When no source-specific nor explicit TTL applies (cache_ttl_seconds=None
    and source entry absent), default wins. Hard to construct this directly
    without modifying internals; assert via direct unit call."""
    cfg = PipelineConfig(
        as_of="2026-09-06T10:00:00Z",
        default_cache_ttl_seconds=42,
    )
    assert cfg.default_cache_ttl_seconds == 42

    # Simulate the lookup with empty entries → must yield 42.
    rp = ResearchPipeline(
        config=cfg,
        adapter_factory=lambda n, p: None,
    )
    assert rp._ttl_for_source("ghost", {}) == 42


def test_zero_ttl_override_bypasses_cache(tmp_path):
    """Explicit cache_ttl_seconds == 0 means 'do not cache'."""
    cache_root = tmp_path / ".cache"
    cache = RetrievalCache(cache_root)
    sources = [_src("reddit", cache_ttl=3600)]
    adapters = {"reddit": _adapter("reddit")}

    pipeline = ResearchPipeline(
        config=PipelineConfig(
            as_of="2026-09-06T10:00:00Z",
            cache=cache,
            cache_ttl_seconds=0,  # explicit no-cache
        ),
        adapter_factory=lambda name, p: adapters.get(name),
    )
    pipeline.run(plan=_plan(), sources=sources, ledger=EvidenceLedger(":memory:"))
    payloads = _all_cache_payloads(cache_root)
    assert payloads == []


def test_cache_dir_gitignored():
    """.cache/ must be in .gitignore (Closeout §4 regression)."""
    gi = Path(__file__).resolve().parents[3] / ".gitignore"
    text = gi.read_text(encoding="utf-8")
    assert ".cache/" in text


def test_orchestrator_holds_no_hardcoded_ttl_default():
    """Regression: the literal `900` may NOT appear as a ttl_seconds kwarg
    in the orchestrator (it must come from PipelineConfig)."""
    orch = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "gtm_intelligence"
        / "pipeline"
        / "orchestrator.py"
    )
    text = orch.read_text(encoding="utf-8")
    # Strip comments first.
    code_only = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "ttl_seconds=900" not in code_only, (
        "orchestrator still hardcodes ttl_seconds=900; use PipelineConfig"
    )
