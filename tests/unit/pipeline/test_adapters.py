"""Tests for Source Adapter interface and RawSourceResult DTO (Phase 3 §7, §8).

Contract:
  * SourceAdapter is a Protocol that any concrete adapter must satisfy.
  * SourceAdapter.retrieve(plan, request) -> list[RawSourceResult]
  * Concrete adapters: FakeSourceAdapter, FixtureSourceAdapter.
  * Adapter MUST NOT write to EvidenceLedger, MUST NOT derive evidence_id,
    MUST NOT score, MUST NOT call LLM.
  * RawSourceResult is an internal DTO. It is NOT Phase 1 Evidence — Normalizer
    converts RawSourceResult -> Evidence downstream.
  * Result ordering is preserved as returned by adapter (no implicit shuffle).
  * Errors during retrieval must surface as exceptions; orchestrator decides
    whether to degrade (Phase 3 §18).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from gtm_intelligence.pipeline.adapters import (
    AdapterError,
    AdapterUnavailable,
    AdapterAuthMissing,
    AdapterRateLimited,
    AdapterInvalidResponse,
    AdapterTimeout,
    FakeSourceAdapter,
    FixtureSourceAdapter,
    RawSourceResult,
    SourceAdapter,
)


# ---------- DTO shape ------------------------------------------------------


def test_raw_source_result_required_fields():
    r = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="abc123",
        url="https://reddit.com/r/x/comments/abc",
        title="hi",
        text="body",
    )
    assert r.source == "reddit"
    assert r.source_type == "post"
    assert r.url == "https://reddit.com/r/x/comments/abc"


def test_raw_source_result_optional_fields_default_to_empty():
    r = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="abc123",
        url="https://reddit.com/r/x",
        title="hi",
        text="body",
    )
    assert r.author == ""
    assert r.published_at == ""
    assert r.retrieved_at == ""
    assert r.language == ""
    assert r.locale == ""
    assert r.market == ""
    assert r.query == ""
    assert r.query_language == ""
    assert r.engagement == {}
    assert r.raw_metadata == {}


def test_raw_source_result_serializable_dict():
    r = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="abc123",
        url="https://reddit.com/r/x/comments/abc",
        title="hi",
        text="body",
    )
    d = r.to_dict()
    assert d["source"] == "reddit"
    assert d["url"] == "https://reddit.com/r/x/comments/abc"


# ---------- Adapter exception taxonomy ------------------------------------


def test_adapter_error_is_base():
    assert issubclass(AdapterUnavailable, AdapterError)
    assert issubclass(AdapterAuthMissing, AdapterError)
    assert issubclass(AdapterRateLimited, AdapterError)
    assert issubclass(AdapterTimeout, AdapterError)
    assert issubclass(AdapterInvalidResponse, AdapterError)


def test_adapter_errors_carry_source_name():
    e = AdapterUnavailable(source="reddit", reason="503")
    assert e.source == "reddit"
    assert "503" in str(e)


# ---------- FakeSourceAdapter ---------------------------------------------


def test_fake_adapter_returns_configured_results():
    adapter = FakeSourceAdapter(
        name="reddit",
        results=[
                {
                    "source": "reddit",
                    "source_type": "post",
                    "source_native_id": "1",
                    "url": "https://reddit.com/r/x/comments/1",
                    "title": "t1",
                    "text": "b1",
                },
            ],
        )
    results = adapter.retrieve(plan={}, request={})
    assert len(results) == 1
    assert results[0].source == "reddit"
    assert results[0].title == "t1"


def test_fake_adapter_returns_empty_list_when_not_configured():
    adapter = FakeSourceAdapter(name="reddit")
    assert adapter.retrieve(plan={}, request={}) == []


def test_fake_adapter_name_attribute():
    adapter = FakeSourceAdapter(name="reddit")
    assert adapter.name == "reddit"


def test_fake_adapter_satisfies_protocol():
    """FakeSourceAdapter must satisfy SourceAdapter Protocol."""
    adapter = FakeSourceAdapter(name="reddit")
    assert isinstance(adapter, SourceAdapter)


# ---------- FixtureSourceAdapter ------------------------------------------


def test_fixture_adapter_loads_jsonl_results(tmp_path):
    fixture = tmp_path / "reddit.jsonl"
    fixture.write_text(
        '{"source":"reddit","source_type":"post","source_native_id":"1",'
        '"url":"https://reddit.com/r/x/1","title":"t1","text":"b1"}\n'
        '{"source":"reddit","source_type":"comment","source_native_id":"2",'
        '"url":"https://reddit.com/r/x/2","title":"t2","text":"b2"}\n',
        encoding="utf-8",
    )
    adapter = FixtureSourceAdapter(name="reddit", path=fixture)
    out = adapter.retrieve(plan={}, request={})
    assert len(out) == 2
    assert out[0].source_native_id == "1"
    assert out[1].source_native_id == "2"


def test_fixture_adapter_skips_blank_lines(tmp_path):
    fixture = tmp_path / "x.jsonl"
    fixture.write_text(
        '\n'
        '{"source":"x","source_type":"post","source_native_id":"1",'
        '"url":"https://x/1","title":"t","text":"b"}\n'
        '\n',
        encoding="utf-8",
    )
    adapter = FixtureSourceAdapter(name="x", path=fixture)
    out = adapter.retrieve(plan={}, request={})
    assert len(out) == 1


def test_fixture_adapter_raises_on_malformed_json(tmp_path):
    fixture = tmp_path / "x.jsonl"
    fixture.write_text("{not valid json}\n", encoding="utf-8")
    adapter = FixtureSourceAdapter(name="x", path=fixture)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan={}, request={})


# ---------- Adapter scope discipline ---------------------------------------


def test_adapter_does_not_derive_evidence_id():
    """Adapters do not derive evidence_id — that's the Normalizer's job."""
    adapter = FakeSourceAdapter(
        name="reddit",
        results=[
            {
                "source": "reddit",
                "source_type": "post",
                "source_native_id": "1",
                "url": "https://reddit.com/r/x/1",
                "title": "t1",
                "text": "b1",
            },
        ],
    )
    out = adapter.retrieve(plan={}, request={})
    for r in out:
        # No evidence_id field exposed to adapters.
        assert not hasattr(r, "evidence_id") or r.to_dict().get("evidence_id", "") == ""


def test_adapter_returns_results_in_supplied_order():
    raw = [
        {
            "source": "reddit",
            "source_type": "post",
            "source_native_id": str(i),
            "url": f"https://reddit.com/r/x/{i}",
            "title": f"t{i}",
            "text": f"b{i}",
        }
        for i in range(5)
    ]
    adapter = FakeSourceAdapter(name="reddit", results=raw)
    out = adapter.retrieve(plan={}, request={})
    assert [r.source_native_id for r in out] == ["0", "1", "2", "3", "4"]


def test_adapter_query_passed_through_into_results():
    adapter = FakeSourceAdapter(
        name="reddit",
        results=[
            {
                "source": "reddit",
                "source_type": "post",
                "source_native_id": "1",
                "url": "https://reddit.com/r/x/1",
                "title": "t",
                "text": "b",
                "query": "Notion AI pricing",
                "query_language": "en",
            },
        ],
    )
    request = {"query": "Notion AI pricing", "query_language": "en"}
    out = adapter.retrieve(plan={}, request=request)
    assert out[0].query == "Notion AI pricing"
    assert out[0].query_language == "en"


def test_japanese_text_preserved_in_raw_result():
    """Japanese text must survive adapter round-trip byte-stable."""
    text = "Notion 値上げが高すぎる"
    adapter = FakeSourceAdapter(
        name="reddit",
        results=[
            {
                "source": "reddit",
                "source_type": "post",
                "source_native_id": "1",
                "url": "https://reddit.com/r/x/1",
                "title": "値上げ",
                "text": text,
            },
        ],
    )
    out = adapter.retrieve(plan={}, request={})
    assert out[0].text == text
    assert out[0].title == "値上げ"


# ---------- AdapterError usage in real adapters ---------------------------


def test_fixture_adapter_missing_file_raises_adapter_invalid_response(tmp_path):
    path = tmp_path / "does-not-exist.jsonl"
    adapter = FixtureSourceAdapter(name="x", path=path)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan={}, request={})


def test_fake_adapter_name_pinned_in_exception():
    adapter = FakeSourceAdapter(
        name="reddit",
        results=[],
        raises=AdapterUnavailable(source="reddit", reason="forced"),
    )
    with pytest.raises(AdapterUnavailable) as exc_info:
        adapter.retrieve(plan={}, request={})
    assert exc_info.value.source == "reddit"


# ---------- Protocol structural conformance ------------------------------


def test_protocol_concrete_via_subclass():
    class MyAdapter:
        name = "my"

        def retrieve(self, plan, request):
            return []

    # Adapters don't need to inherit from SourceAdapter — Protocol is structural.
    adapter = MyAdapter()
    assert hasattr(adapter, "retrieve")
    assert adapter.name == "my"
