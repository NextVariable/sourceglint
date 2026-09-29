import io
import json

from gtm_intelligence.host_stdio import StdioHostModel, StdioHostSource
from gtm_intelligence.intelligence.model import ModelStatus


SCHEMA = {
    "type": "object",
    "required": ["clusters"],
    "properties": {"clusters": {"type": "array"}},
}


def test_host_bridge_round_trip_and_schema_gate():
    incoming = io.StringIO(json.dumps({
        "type": "model_response", "task": "clustering", "payload": {"clusters": []},
    }) + "\n")
    outgoing = io.StringIO()
    response = StdioHostModel(incoming, outgoing).complete_structured(
        task="clustering", payload={"evidence_items": []}, response_schema=SCHEMA,
    )
    assert response.status is ModelStatus.SUCCESS
    assert response.payload == {"clusters": []}
    request = json.loads(outgoing.getvalue())
    assert request["type"] == "model_request"
    assert request["task"] == "clustering"
    assert request["response_schema"] == SCHEMA


def test_host_bridge_rejects_wrong_task_or_invalid_payload():
    for answer in (
        {"type": "model_response", "task": "other", "payload": {"clusters": []}},
        {"type": "model_response", "task": "clustering", "payload": {}},
    ):
        response = StdioHostModel(
            io.StringIO(json.dumps(answer) + "\n"), io.StringIO()
        ).complete_structured(task="clustering", payload={}, response_schema=SCHEMA)
        assert response.status is ModelStatus.INVALID_OUTPUT


def test_host_bridge_closed_input_is_unavailable():
    response = StdioHostModel(io.StringIO(), io.StringIO()).complete_structured(
        task="clustering", payload={}, response_schema=SCHEMA,
    )
    assert response.status is ModelStatus.UNAVAILABLE


def test_host_source_round_trip():
    incoming = io.StringIO(json.dumps({
        "type": "source_response", "source": "official_web",
        "results": [{"source_type": "page", "source_native_id": "pricing",
                     "url": "https://example.com/pricing", "title": "Pricing",
                     "text": "The official pricing page lists a Team plan."}],
    }) + "\n")
    outgoing = io.StringIO()
    results = StdioHostSource("official_web", incoming, outgoing).retrieve(
        {"topic": "Example pricing"}, {"query": "Example pricing", "query_language": "en"}
    )
    assert len(results) == 1
    assert results[0].source == "official_web"
    assert results[0].raw_metadata["official"] is True
    request = json.loads(outgoing.getvalue())
    assert request["type"] == "source_request"
    assert request["allowed_source_types"] == [
        "post", "comment", "review", "page", "release",
    ]


def test_host_source_rejects_unknown_source_type():
    import pytest
    from gtm_intelligence.pipeline.adapters import AdapterInvalidResponse

    incoming = io.StringIO(json.dumps({
        "type": "source_response", "source": "host_web_search",
        "results": [{"source_type": "paper", "source_native_id": "p1",
                     "url": "https://example.com/paper", "title": "Paper",
                     "text": "Abstract", "published_at": "2026-09-01T00:00:00Z"}],
    }) + "\n")
    with pytest.raises(AdapterInvalidResponse):
        StdioHostSource("host_web_search", incoming, io.StringIO()).retrieve(
            {"topic": "paper"}, {"query": "paper", "query_language": "en"}
        )


def test_host_web_search_request_contains_bounded_platform_targets():
    incoming = io.StringIO(json.dumps({
        "type": "source_response", "source": "host_web_search", "results": [],
    }) + "\n")
    outgoing = io.StringIO()
    StdioHostSource("host_web_search", incoming, outgoing).retrieve(
        {"topic": "AI video", "mode": "trend", "market": "global"},
        {"query": "AI video emerging", "query_language": "en"},
    )
    request = json.loads(outgoing.getvalue())
    assert 1 <= len(request["targets"]) <= 10
    assert all("domains" in target for target in request["targets"])
    assert all("availability" in target for target in request["targets"])
