from __future__ import annotations

import json
from typing import Mapping

import pytest

from gtm_intelligence.connectors._http import HttpResponse, HttpTransientError
from gtm_intelligence.connectors.open_sources import (
    ArxivAdapter,
    DevToAdapter,
    HuggingFaceAdapter,
    PackageRegistriesAdapter,
    QiitaAdapter,
    SemanticScholarAdapter,
    StackOverflowAdapter,
)
from gtm_intelligence.pipeline.adapters import AdapterInvalidResponse, AdapterRateLimited


class StubHttp:
    user_agent = "test"

    def __init__(self, payload=None, *, body: bytes | None = None, raises=None):
        self.payload = payload
        self.body = body
        self.raises = raises
        self.calls = []

    def request(self, url: str, *, headers: Mapping[str, str] | None = None, timeout=15.0, method="GET", json_data=None):
        self.calls.append(url)
        if self.raises:
            raise self.raises
        body = self.body if self.body is not None else json.dumps(self.payload).encode()
        return HttpResponse(status=200, body=body, url=url)


REQUEST = {
    "query": "AI agents",
    "query_language": "en",
    "market": "global",
    "retrieved_at": "2026-09-29T00:00:00Z",
    "limit": 3,
}
PLAN = {"time_window": {"days": 30}}


def test_stack_overflow_maps_search_result_and_time_window():
    http = StubHttp({"items": [{
        "question_id": 123, "title": "AI agents", "link": "https://stackoverflow.com/q/123",
        "creation_date": 1780000000, "score": 4, "answer_count": 2, "view_count": 40,
        "owner": {"display_name": "Ada"}, "tags": ["python"], "is_answered": True,
    }]})
    out = StackOverflowAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert out[0].source == "stack_overflow"
    assert out[0].engagement == {"points": 4, "comments": 2, "views": 40}
    assert "fromdate=" in http.calls[0]


def test_devto_uses_real_search_endpoint_and_maps_engagement():
    http = StubHttp([{
        "id": 9, "title": "Agent workflows", "url": "https://dev.to/a/agent-workflows",
        "description": "A practical workflow", "published_timestamp": "2026-09-20T10:00:00Z",
        "public_reactions_count": 12, "comments_count": 3, "user": {"username": "a"},
        "tag_list": ["ai"],
    }])
    out = DevToAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert out[0].source_native_id == "9"
    assert out[0].engagement == {"likes": 12, "comments": 3}
    assert "/api/articles/search?" in http.calls[0]


def test_hugging_face_maps_model_search():
    http = StubHttp([{
        "modelId": "org/model", "lastModified": "2026-09-28T09:00:00Z",
        "pipeline_tag": "text-generation", "likes": 8, "downloads": 99, "tags": ["transformers"],
    }])
    out = HuggingFaceAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert out[0].url == "https://huggingface.co/org/model"
    assert out[0].raw_metadata["downloads"] == 99


def test_package_registries_maps_npm_search():
    http = StubHttp({"objects": [{
        "package": {
            "name": "agent-kit", "version": "1.2.3", "date": "2026-09-28T00:00:00Z",
            "description": "Agent toolkit", "links": {"npm": "https://www.npmjs.com/package/agent-kit"},
            "author": {"name": "Ada"},
        },
        "score": {"final": 0.9},
    }]})
    out = PackageRegistriesAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert out[0].source_native_id == "npm:agent-kit@1.2.3"
    assert out[0].author == "Ada"
    assert out[0].raw_metadata["registry"] == "npm"


def test_semantic_scholar_requires_real_publication_date():
    http = StubHttp({"data": [{
        "paperId": "abc", "title": "Agent systems", "url": "https://example.org/paper",
        "abstract": "Evidence", "publicationDate": "2026-09-01", "citationCount": 5,
        "authors": [{"name": "A"}], "externalIds": {"ArXiv": "1"},
    }, {"paperId": "missing-date", "title": "Unknown date"}]})
    out = SemanticScholarAdapter(http_client=http, api_key="test-key").retrieve(PLAN, REQUEST)
    assert [x.source_native_id for x in out] == ["abc"]
    assert out[0].published_at == "2026-09-01T00:00:00Z"


def test_qiita_maps_japanese_post_and_date_query():
    http = StubHttp([{
        "id": "q1", "title": "AIエージェント", "url": "https://qiita.com/u/items/q1",
        "body": "本文", "created_at": "2026-09-25T00:00:00+09:00", "likes_count": 7,
        "comments_count": 1, "page_views_count": 20, "stocks_count": 2,
        "user": {"id": "u"}, "tags": [{"name": "AI"}],
    }])
    out = QiitaAdapter(http_client=http).retrieve(PLAN, {**REQUEST, "query_language": "ja", "market": "jp"})
    assert out[0].language == "ja"
    assert out[0].published_at == "2026-09-24T15:00:00Z"
    assert "created%3A%3E%3D2026-08-30" in http.calls[0]


def test_arxiv_maps_atom_entries():
    atom = b'''<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>http://arxiv.org/abs/2609.12345v1</id><title> Agent Research </title>
      <summary> A useful paper. </summary><published>2026-09-20T12:00:00Z</published>
      <author><name>Ada</name></author>
    </entry></feed>'''
    http = StubHttp(body=atom)
    out = ArxivAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert out[0].source_native_id == "2609.12345v1"
    assert out[0].url == "https://arxiv.org/abs/2609.12345v1"


@pytest.mark.parametrize("adapter_type", [StackOverflowAdapter, DevToAdapter, HuggingFaceAdapter, PackageRegistriesAdapter, QiitaAdapter])
def test_json_adapters_reject_wrong_payload_shape(adapter_type):
    with pytest.raises(AdapterInvalidResponse):
        adapter_type(http_client=StubHttp("wrong")).retrieve(PLAN, REQUEST)


def test_public_adapter_maps_429_to_rate_limited():
    http = StubHttp(raises=HttpTransientError(429, "https://example.test"))
    with pytest.raises(AdapterRateLimited):
        StackOverflowAdapter(http_client=http).retrieve(PLAN, REQUEST)


def test_semantic_scholar_requires_key_before_network():
    from gtm_intelligence.pipeline.adapters import AdapterAuthMissing
    http = StubHttp({"data": []})
    with pytest.raises(AdapterAuthMissing):
        SemanticScholarAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert http.calls == []
