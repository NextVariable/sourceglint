from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from gtm_intelligence.connectors._http import (
    HttpResponse,
    HttpTimeoutError,
    HttpTransientError,
)
from gtm_intelligence.connectors.bluesky import BlueskyAdapter
from gtm_intelligence.pipeline.adapters import (
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
)


class _Http:
    user_agent = "test"

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def request(self, url, *, headers=None, timeout=15.0):
        self.calls.append(url)
        if self.error:
            raise self.error
        return HttpResponse(
            status=200,
            body=json.dumps(self.payload).encode("utf-8"),
            url=url,
        )


def _request():
    return {"query": "AI video", "query_language": "en", "market": "global"}


def test_public_search_maps_post_and_engagement():
    http = _Http({
        "posts": [{
            "uri": "at://did:plc:abc/app.bsky.feed.post/xyz",
            "cid": "bafy-post",
            "author": {"handle": "maker.example"},
            "record": {"text": "A new AI video workflow", "createdAt": "2026-09-20T12:00:00Z"},
            "likeCount": 12,
            "replyCount": 3,
            "repostCount": 4,
        }]
    })
    out = BlueskyAdapter(http_client=http).retrieve({}, _request())
    assert len(out) == 1
    assert out[0].source == "bluesky"
    assert out[0].url == "https://bsky.app/profile/maker.example/post/xyz"
    assert out[0].engagement == {"likes": 12, "comments": 3, "upvotes": 4}
    params = parse_qs(urlparse(http.calls[0]).query)
    assert params["q"] == ["AI video"]
    assert params["lang"] == ["en"]


def test_missing_posts_is_invalid():
    with pytest.raises(AdapterInvalidResponse):
        BlueskyAdapter(http_client=_Http({"feed": []})).retrieve({}, _request())


def test_rate_limit_and_timeout_are_classified():
    with pytest.raises(AdapterRateLimited):
        BlueskyAdapter(http_client=_Http(error=HttpTransientError(429, "x"))).retrieve({}, _request())
    with pytest.raises(AdapterTimeout):
        BlueskyAdapter(http_client=_Http(error=HttpTimeoutError("x", 1))).retrieve({}, _request())
