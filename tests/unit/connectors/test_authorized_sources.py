from __future__ import annotations

import json
from typing import Mapping

import pytest

from sourceglint.connectors._http import (
    HttpPermanentError,
    HttpResponse,
    HttpTransientError,
)
from sourceglint.connectors.authorized_sources import ProductHuntAdapter, XAdapter
from sourceglint.pipeline.adapters import (
    AdapterAuthMissing,
    AdapterInvalidResponse,
    AdapterRateLimited,
)


class StubHttp:
    user_agent = "test"

    def __init__(self, responses=None, raises=None):
        self.responses = list(responses or [])
        self.raises = list(raises or [])
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout=15.0,
        method="GET",
        json_data=None,
    ):
        self.calls.append({
            "url": url,
            "headers": dict(headers or {}),
            "method": method,
            "json_data": json_data,
        })
        if self.raises:
            error = self.raises.pop(0)
            if error is not None:
                raise error
        payload = self.responses.pop(0) if self.responses else {}
        return HttpResponse(status=200, body=json.dumps(payload).encode(), url=url)


REQUEST = {
    "query": "AI agents",
    "query_language": "en",
    "market": "global",
    "retrieved_at": "2026-09-29T00:00:00Z",
    "limit": 3,
}
PLAN = {"time_window": {"days": 30}}


def test_x_requires_token_before_network():
    http = StubHttp()
    with pytest.raises(AdapterAuthMissing):
        XAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert http.calls == []


def test_x_maps_full_archive_results_and_keeps_token_out_of_url():
    http = StubHttp(responses=[{
        "data": [{
            "id": "123", "text": "AI agents are improving", "author_id": "u1",
            "created_at": "2026-09-28T12:00:00Z", "lang": "en",
            "public_metrics": {
                "like_count": 8, "reply_count": 2,
                "retweet_count": 3, "quote_count": 1,
            },
        }],
        "includes": {"users": [{"id": "u1", "username": "ada"}]},
    }])
    result = XAdapter(bearer_token="secret-token", http_client=http).retrieve(PLAN, REQUEST)
    assert result[0].url == "https://x.com/ada/status/123"
    assert result[0].engagement == {"likes": 8, "comments": 2, "upvotes": 4}
    assert result[0].raw_metadata["route"] == "full_archive"
    assert result[0].raw_metadata["coverage_days"] == 30
    assert "secret-token" not in str(http.calls[0]["url"])
    assert http.calls[0]["headers"]["Authorization"] == "Bearer secret-token"


def test_x_falls_back_to_recent_search_and_discloses_truncated_window():
    full_url = "https://api.x.com/2/tweets/search/all"
    http = StubHttp(
        responses=[{
            "data": [{
                "id": "7", "text": "Recent agent post", "author_id": "u7",
                "created_at": "2026-09-28T00:00:00Z", "lang": "en",
            }],
            "includes": {"users": [{"id": "u7", "username": "recent"}]},
        }],
        raises=[HttpPermanentError(403, full_url), None],
    )
    result = XAdapter(bearer_token="token", http_client=http).retrieve(PLAN, REQUEST)
    assert len(http.calls) == 2
    assert "/tweets/search/recent?" in str(http.calls[1]["url"])
    assert "start_time=2026-09-22T00%3A00%3A00Z" in str(http.calls[1]["url"])
    assert result[0].raw_metadata == {
        "route": "recent", "coverage_days": 7, "author_id": "u7",
    }


def test_x_maps_429_to_rate_limited():
    http = StubHttp(raises=[HttpTransientError(429, "https://api.x.com")])
    with pytest.raises(AdapterRateLimited):
        XAdapter(bearer_token="token", http_client=http).retrieve(PLAN, REQUEST)


def test_product_hunt_requires_token_before_network():
    http = StubHttp()
    with pytest.raises(AdapterAuthMissing):
        ProductHuntAdapter(http_client=http).retrieve(PLAN, REQUEST)
    assert http.calls == []


def test_product_hunt_maps_and_filters_recent_posts_locally():
    http = StubHttp(responses=[{
        "data": {"posts": {"nodes": [
            {
                "id": "p1", "name": "Agent Desk", "tagline": "AI agent workspace",
                "description": "Build AI agents", "url": "https://producthunt.com/posts/agent-desk",
                "website": "https://agent.example", "votesCount": 42, "commentsCount": 5,
                "createdAt": "2026-09-28T00:00:00Z", "user": {"username": "maker"},
            },
            {
                "id": "p2", "name": "Recipe Book", "tagline": "Dinner ideas",
                "description": "Cooking", "url": "https://producthunt.com/posts/recipe-book",
                "createdAt": "2026-09-27T00:00:00Z",
            },
        ]}},
    }])
    result = ProductHuntAdapter(token="ph-secret", http_client=http).retrieve(PLAN, REQUEST)
    assert [item.source_native_id for item in result] == ["p1"]
    assert result[0].engagement == {"upvotes": 42, "comments": 5}
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.producthunt.com/v2/api/graphql"
    assert call["headers"]["Authorization"] == "Bearer ph-secret"
    assert "ph-secret" not in json.dumps(call["json_data"])


def test_product_hunt_rejects_graphql_errors():
    http = StubHttp(responses=[{"errors": [{"message": "not allowed"}]}])
    with pytest.raises(AdapterInvalidResponse):
        ProductHuntAdapter(token="token", http_client=http).retrieve(PLAN, REQUEST)
