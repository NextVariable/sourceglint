"""Adversarial research-quality checks; synthetic cases are not live acceptance."""
from dataclasses import replace
import itertools

import pytest

from sourceglint.excerpts import MARKER, select_excerpt
from sourceglint.pipeline.deduplication import deduplicate
from sourceglint.intelligence.cache import SemanticCache
from sourceglint.intelligence.clustering import cluster
from sourceglint.intelligence.contradiction import analyze_contradictions
from sourceglint.intelligence.dtos import PreparedEvidence, ResearchContext, ValidatedCluster
from sourceglint.intelligence.features import derive_features
from sourceglint.intelligence.model import FakeClusterScript, FakeIntelligenceModel, ModelResponse, ModelStatus
from sourceglint.insights.preparation import prepare_signals
from sourceglint.connectors._captions import fetch_captions
from sourceglint.connectors._http import HttpResponse


def evidence(eid="ev-1", **changes):
    return PreparedEvidence(evidence_id=eid, source="reddit", source_type="post",
                            window="current", url="https://a.example/1", **changes)


def group(*ids, claim="MCP security"):
    return ValidatedCluster("cl-test", "Security", claim, tuple(ids), 0.8)


@pytest.mark.parametrize("prefix,subject,budget,position", list(itertools.product(
    ["x", "ß", "İ", "中🙂"], ["MCP security", "Obsidian plugins", "安全漏洞", "会議要約", "安全", "会議", "AI", "Straße", "İstanbul"],
    [120, 300, 1200, 6000], [0.25, 0.75])))
def test_excerpt_retains_topic_and_literal_offsets(prefix, subject, budget, position):
    length = budget * 6
    before = prefix * int(length * position)
    after = prefix * int(length * (1 - position))
    body = before + " " + subject + " is the relevant observation. " + after
    excerpt = select_excerpt(body, subject, budget)
    assert len(excerpt) <= budget
    assert subject in excerpt
    assert MARKER in excerpt
    assert all(part in body for part in excerpt.split(MARKER))


@pytest.mark.parametrize("budget", [-1, 0, 1, 2, 30, 60, 70, 100])
def test_tiny_excerpt_budget_never_expands_text(budget):
    assert len(select_excerpt("topic " * 100, "topic", budget)) <= max(0, budget)


def test_topic_not_displaced_by_generic_question_words():
    body = "What people are saying recently about tools " * 1000
    body += " MCP security has a specific authorization finding. " + "x" * 10000
    excerpt = select_excerpt(body, "What are people saying about MCP security recently?", 1200)
    assert "specific authorization finding" in excerpt


def test_dedup_registers_alias_seen_only_on_duplicate():
    rows = [
        {"evidence_id": "ev-1", "url": "https://a.example/1", "source": "reddit", "source_native_id": "x"},
        {"evidence_id": "ev-2", "url": "https://b.example/2", "source": "reddit", "source_native_id": "x"},
        {"evidence_id": "ev-3", "url": "https://b.example/2", "source": "host_web_search"},
    ]
    out = deduplicate(rows)
    assert out.kept_count == 1
    assert out.provenance["ev-1"].retrieval_count == 3


def test_dedup_exact_id_even_without_shared_url_or_native_id():
    rows = [{"evidence_id": "ev-1", "url": url} for url in ("https://a.example/1", "https://b.example/2")]
    assert deduplicate(rows).kept_count == 1


@pytest.mark.parametrize("field,value", [("author", "different"), ("published_at", "2026-09-28T00:00:00Z")])
def test_body_enrichment_rejects_conflicting_identity(field, value):
    a = {"evidence_id": "ev-1", "url": "https://a.example/1", "snippet": "Actual quote",
         "author": "author", "published_at": "2026-09-27T00:00:00Z"}
    b = {**a, field: value, "content": "Actual quote followed by extra observations"}
    out = deduplicate([a, b])
    assert "content" not in out.kept[0]
    assert "content" not in a


def test_body_enrichment_keeps_quote_and_does_not_mutate_input():
    a = {"evidence_id": "ev-1", "url": "https://a.example/1", "snippet": "Actual quote"}
    b = {**a, "content": "Actual quote followed by more context"}
    assert deduplicate([a, b]).kept[0]["content"] == b["content"]
    assert "content" not in a
    assert "content" not in deduplicate([a, {**b, "content": "An unrelated long replacement body"}]).kept[0]


@pytest.mark.parametrize("change", ["content", "snippet", "title", "published_at"])
def test_clustering_cache_invalidates_changed_model_input(change):
    cache = SemanticCache()
    item = evidence(content="Original source body", snippet="Original quote", title="MCP security")
    model = FakeIntelligenceModel(scripts=(FakeClusterScript("Security", "A bounded claim", ("ev-1",)),))
    cluster([item], model, cache=cache)
    model.calls.clear()
    cluster([replace(item, **{change: "New source material"})], model, cache=cache)
    assert len(model.calls) == 1


def test_contradiction_cache_invalidates_changed_claim():
    cache = SemanticCache()
    item = evidence(content="A report about safety")
    model = FakeIntelligenceModel(scripts=(FakeClusterScript("Security", "claim", ("ev-1",)),))
    analyze_contradictions([group("ev-1")], model, evidence_by_id={"ev-1": item}, cache=cache)
    model.calls.clear()
    analyze_contradictions([group("ev-1", claim="The opposite claim")], model,
                           evidence_by_id={"ev-1": item}, cache=cache)
    assert len(model.calls) == 1


@pytest.mark.parametrize("status", [ModelStatus.UNAVAILABLE, ModelStatus.TIMEOUT, ModelStatus.INVALID_OUTPUT])
def test_failed_contradiction_does_not_infer_support(status):
    class Unusable:
        model_id = "failure-test"
        def complete_structured(self, **kwargs):
            return ModelResponse(task=kwargs["task"], status=status)
    out = analyze_contradictions([group("ev-1")], Unusable(), evidence_by_id={"ev-1": evidence()})
    assert out.assessments[0].degraded
    assert out.assessments[0].supporting_evidence_ids == ()
    assert out.warnings


def test_unassessed_signal_cannot_reach_fact_synthesis():
    sig = {"signal_id": "sig-test", "evidence_ids": ["ev-1"], "contradiction_assessed": False}
    out, warnings = prepare_signals([sig], {"ev-1": {"snippet": "A claim"}})
    assert not out
    assert any("unassessed" in w for w in warnings)


def test_empty_support_does_not_promote_counter_evidence():
    sig = {"signal_id": "sig-test", "evidence_ids": ["ev-1"], "supporting_evidence_ids": [],
           "counter_evidence_ids": ["ev-1"]}
    out, _ = prepare_signals([sig], {"ev-1": {"snippet": "The contrary observation"}})
    assert out[0].supporting_evidence_summaries == ()
    assert out[0].counter_evidence_summaries == ("The contrary observation",)


@pytest.mark.parametrize("formatting", [str.upper, lambda s: " \n".join(s.split()), lambda s: s])
def test_copied_reporting_not_independent(formatting):
    body = "A maker reports an unverified improvement for one particular workflow. " * 3
    items = [evidence(content=body), evidence("ev-2", content=formatting(body))]
    items[1] = replace(items[1], url="https://b.example/2")
    out = derive_features(group("ev-1", "ev-2"), {i.evidence_id: i for i in items})
    assert out.independent_source_count == 1
    assert out.evidence_count == 2
    assert len(out.unique_domains) == 2


def test_distinct_reporting_stays_independent():
    items = [evidence(content="A maker reports one new release. " * 5),
             replace(evidence("ev-2", content="A user reports a different experience. " * 5), url="https://b.example/2")]
    assert derive_features(group("ev-1", "ev-2"), {i.evidence_id: i for i in items}).independent_source_count == 2


def test_caption_failure_can_retain_alternate_format():
    class Client:
        def request(self, url, **kwargs):
            if url.endswith("bad"):
                raise TimeoutError("transient")
            return HttpResponse(200, body=b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nActual observation\n")
    item = {"subtitles": {"en": [{"url": "https://www.youtube.com/bad", "ext": "json3"},
                                  {"url": "https://www.youtube.com/good", "ext": "vtt"}]}}
    body, meta = fetch_captions(Client(), item)
    assert "Actual observation" in body
    assert len(meta["caption_failures"]) == 1


@pytest.mark.parametrize("tracks", [None, 1, "broken", {"not": "a list"}])
def test_malformed_caption_tracks_degrade(tracks):
    body, meta = fetch_captions(None, {"subtitles": {"en": tracks}})
    assert body == ""
    assert meta["transcript_status"] == "unavailable"
