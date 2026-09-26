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
    assert json.loads(outgoing.getvalue())["type"] == "source_request"
