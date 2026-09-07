"""Phase 5 §38, §47 — end-to-end intelligence pipeline (unit level)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gtm_intelligence.intelligence import pipeline
from gtm_intelligence.intelligence.cache import SemanticCache
from gtm_intelligence.intelligence.model import (
    FakeClusterScript,
    FakeIntelligenceModel,
)
from gtm_intelligence.intelligence.signals import validate_signal_contract

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _record(
    eid: str,
    *,
    source: str = "reddit",
    tier: int = 2,
    url: str = "",
    window: str = "current",
    days_ago: int = 1,
    snippet: str = "some text",
    engagement: dict | None = None,
) -> dict:
    return {
        "evidence_id": eid,
        "source": source,
        "source_type": "comment",
        "url": url or f"https://reddit.com/r/x/{eid}",
        "retrieved_at": "2026-09-07T00:00:00Z",
        "published_at": (NOW - __import__("datetime").timedelta(days=days_ago)).isoformat(),
        "title": f"title {eid}",
        "snippet": snippet,
        "window": window,
        "language": "en",
        "market": "global",
        "source_tier": tier,
        "evidence_quality": 0.8,
        "engagement": dict(engagement or {}),
    }


def _current_pair(prefix: str = "ev"):
    """Two current-window items on independent hosts."""
    return [
        _record(f"{prefix}-1", source="official_web", tier=1,
                url=f"https://a.example.com/{prefix}1", engagement={"upvotes": 30}),
        _record(f"{prefix}-2", source="reddit", tier=2,
                url=f"https://b.example.com/{prefix}2", engagement={"upvotes": 10}),
    ]


def _model(*scripts: FakeClusterScript) -> FakeIntelligenceModel:
    return FakeIntelligenceModel(scripts=scripts)


def _cross_source_scripts() -> tuple[FakeClusterScript, ...]:
    return (
        FakeClusterScript(
            label="Pricing shift", claim="vendors are changing pricing",
            evidence_ids=("ev-1", "ev-2"),
            decision_relevance=0.8, semantic_novelty=0.6,
        ),
    )


# --- happy path -------------------------------------------------------------


def test_end_to_end_builds_ordered_signals():
    result = pipeline.run_intelligence_pipeline(
        _current_pair(),
        _model(*_cross_source_scripts()),
        as_of=NOW,
    )
    assert len(result.signals) == 1
    sig = result.signals[0]
    assert sig["signal_type"] == "cross_source"
    assert sig["evidence_ids"] == ["ev-1", "ev-2"]
    assert sig["signal_id"].startswith("sig_")
    assert validate_signal_contract(sig) == []
    assert result.clusters and result.clusters[0].cluster_id.startswith("cl_")
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].signal_id == sig["signal_id"]
    assert result.model_status["clustering"] == "success"


def test_pipeline_is_deterministic_across_runs():
    records = _current_pair()
    scripts = _cross_source_scripts()

    def run():
        return pipeline.run_intelligence_pipeline(
            records, _model(*scripts), as_of=NOW
        ).to_dict()

    assert run() == run()


def test_result_carries_no_insight_recommendation_fields():
    result = pipeline.run_intelligence_pipeline(
        _current_pair(), _model(*_cross_source_scripts()), as_of=NOW
    )
    d = result.to_dict()
    assert set(d) == {"signals", "clusters", "diagnostics", "warnings", "model_status"}
    for sig in result.signals:
        assert set(sig) == {
            "signal_id", "topic", "evidence_ids", "representative_evidence_ids",
            "source_diversity", "volume", "recency", "signal_type", "novelty",
            "score", "confidence", "supporting_evidence_ids",
            "counter_evidence_ids",
        }


def test_multiple_signals_sorted_by_score_desc_then_id():
    a = _record("a-1", url="https://a.example.com/1", snippet="alpha topic")
    b = _record("b-1", url="https://b.example.com/1", snippet="beta topic")
    scripts = (
        FakeClusterScript(label="Alpha", claim="c", evidence_ids=("a-1",),
                          decision_relevance=0.9),
        FakeClusterScript(label="Beta", claim="c", evidence_ids=("b-1",),
                          decision_relevance=0.3),
    )
    result = pipeline.run_intelligence_pipeline(
        [a, b], _model(*scripts), as_of=NOW
    )
    topics = [s["topic"] for s in result.signals]
    assert topics == ["Alpha", "Beta"]  # 0.9-score cluster first
    scores = [s["score"] for s in result.signals]
    assert scores == sorted(scores, reverse=True)


# --- edge inputs ------------------------------------------------------------


def test_empty_records_yields_empty_result_with_warning():
    result = pipeline.run_intelligence_pipeline([], _model(), as_of=NOW)
    assert result.signals == ()
    assert result.warnings
    assert result.clusters == ()


def test_empty_input_returns_without_model_calls():
    model = _model()
    pipeline.run_intelligence_pipeline([], model, as_of=NOW)
    assert model.calls == []


# --- baseline window semantics ----------------------------------------------


def test_baseline_only_cluster_dropped_by_default():
    cur = _record("ev-1", url="https://a.example.com/1")
    base = _record("ev-b", url="https://b.example.com/b", window="baseline",
                   days_ago=45)
    scripts = (
        FakeClusterScript(label="Cur", claim="c", evidence_ids=("ev-1",)),
        FakeClusterScript(label="Base", claim="c", evidence_ids=("ev-b",)),
    )
    result = pipeline.run_intelligence_pipeline(
        [cur, base], _model(*scripts), as_of=NOW
    )
    topics = [s["topic"] for s in result.signals]
    assert topics == ["Cur"]
    assert any("baseline" in w for w in result.warnings)


def test_baseline_only_cluster_included_when_requested():
    cur = _record("ev-1", url="https://a.example.com/1")
    base = _record("ev-b", url="https://b.example.com/b", window="baseline",
                   days_ago=45)
    scripts = (
        FakeClusterScript(label="Cur", claim="c", evidence_ids=("ev-1",)),
        FakeClusterScript(label="Base", claim="c", evidence_ids=("ev-b",)),
    )
    result = pipeline.run_intelligence_pipeline(
        [cur, base], _model(*scripts), as_of=NOW, drop_baseline_only=False
    )
    assert {s["topic"] for s in result.signals} == {"Cur", "Base"}


def test_repeated_signal_when_topic_spans_windows():
    cur = _record("ev-1", url="https://a.example.com/1", window="current")
    base = _record("ev-2", url="https://a.example.com/2", window="baseline",
                   days_ago=40)
    scripts = (
        FakeClusterScript(label="Ongoing", claim="c", evidence_ids=("ev-1", "ev-2")),
    )
    result = pipeline.run_intelligence_pipeline(
        [cur, base], _model(*scripts), as_of=NOW
    )
    assert result.signals[0]["signal_type"] == "repeated"
    assert result.signals[0]["novelty"] == pytest.approx(0.5)


def test_emerging_signal_with_global_baseline_present():
    cur_a = _record("ev-1", url="https://a.example.com/1", window="current")
    cur_b = _record("ev-2", url="https://b.example.com/2", window="current")
    base = _record("ev-b", url="https://c.example.com/b", window="baseline",
                   days_ago=50)
    scripts = (
        FakeClusterScript(label="Fresh", claim="c", evidence_ids=("ev-1",)),
        FakeClusterScript(label="Other", claim="c", evidence_ids=("ev-2",)),
        FakeClusterScript(label="Old", claim="c", evidence_ids=("ev-b",)),
    )
    result = pipeline.run_intelligence_pipeline(
        [cur_a, cur_b, base], _model(*scripts), as_of=NOW
    )
    by_topic = {s["topic"]: s for s in result.signals}
    assert by_topic["Fresh"]["signal_type"] == "emerging"
    assert by_topic["Fresh"]["novelty"] == pytest.approx(1.0)


# --- contradiction end-to-end -----------------------------------------------


def test_contradiction_signal_end_to_end():
    a = _record("ev-1", url="https://a.example.com/1", snippet="price increased")
    b = _record("ev-2", url="https://a.example.com/2", snippet="price unchanged")
    scripts = (
        FakeClusterScript(
            label="Price", claim="price is changing",
            evidence_ids=("ev-1", "ev-2"),
            supporting_evidence_ids=("ev-1",),
            counter_evidence_ids=("ev-2",),
            contradiction_kind="factual",
            decision_relevance=0.7,
        ),
    )
    result = pipeline.run_intelligence_pipeline(
        [a, b], _model(*scripts), as_of=NOW
    )
    sig = result.signals[0]
    assert sig["signal_type"] == "contradictory"
    assert sig["counter_evidence_ids"] == ["ev-2"]
    assert sig["supporting_evidence_ids"] == ["ev-1"]


# --- cache integration (PRD §28) --------------------------------------------


def test_cache_skips_repeated_model_calls_on_second_run():
    """A populated semantic cache means the second run never calls the
    model again — clustering, contradiction and semantic factors all hit."""
    records = _current_pair()
    scripts = _cross_source_scripts()

    cache = SemanticCache()
    first = pipeline.run_intelligence_pipeline(
        records, _model(*scripts), as_of=NOW, cache=cache
    )
    assert first.signals

    model = _model(*scripts)
    pipeline.run_intelligence_pipeline(records, model, as_of=NOW, cache=cache)
    assert model.calls == []  # everything served from cache
    assert cache.size >= 3  # clustering + contradiction + semantic_factors


# --- model failure propagation ----------------------------------------------


def test_clustering_failure_raises():
    from gtm_intelligence.intelligence.model import (
        FailingIntelligenceModel,
        IntelligencePipelineError,
    )

    with pytest.raises(IntelligencePipelineError):
        pipeline.run_intelligence_pipeline(
            _current_pair(), FailingIntelligenceModel(), as_of=NOW
        )
