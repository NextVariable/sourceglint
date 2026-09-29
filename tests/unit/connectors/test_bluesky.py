from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from sourceglint.connectors._http import (
    HttpResponse,
    HttpTimeoutError,
    HttpTransientError,
)
from sourceglint.connectors.bluesky import BlueskyAdapter
from sourceglint.pipeline.adapters import (
    AdapterAuthMissing,
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

    def request(self, url, *, headers=None, timeout=15.0, method="GET", json_data=None):
        self.calls.append({"url": url, "headers": headers, "method": method, "json_data": json_data})
        if self.error:
            raise self.error
        if method == "POST":
            payload = {"accessJwt": "test-token"}
        else:
            payload = self.payload
        return HttpResponse(
            status=200,
            body=json.dumps(payload).encode("utf-8"),
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
    out = BlueskyAdapter(
        http_client=http, handle="maker.example", app_password="app-password"
    ).retrieve({}, _request())
    assert len(out) == 1
    assert out[0].source == "bluesky"
    assert out[0].url == "https://bsky.app/profile/maker.example/post/xyz"
    assert out[0].engagement == {"likes": 12, "comments": 3, "upvotes": 4}
    assert http.calls[0]["method"] == "POST"
    assert http.calls[0]["json_data"]["identifier"] == "maker.example"
    assert http.calls[1]["headers"] == {"Authorization": "Bearer test-token"}
    params = parse_qs(urlparse(http.calls[1]["url"]).query)
    assert params["q"] == ["AI video"]
    assert params["lang"] == ["en"]


def test_missing_posts_is_invalid():
    with pytest.raises(AdapterInvalidResponse):
        BlueskyAdapter(
            http_client=_Http({"feed": []}), handle="maker.example", app_password="pw"
        ).retrieve({}, _request())


def test_rate_limit_and_timeout_are_classified():
    with pytest.raises(AdapterRateLimited):
        BlueskyAdapter(http_client=_Http(error=HttpTransientError(429, "x")), handle="h", app_password="p").retrieve({}, _request())
    with pytest.raises(AdapterTimeout):
        BlueskyAdapter(http_client=_Http(error=HttpTimeoutError("x", 1)), handle="h", app_password="p").retrieve({}, _request())


def test_missing_app_password_fails_before_network():
    http = _Http({"posts": []})
    with pytest.raises(AdapterAuthMissing):
        BlueskyAdapter(http_client=http, handle="maker.example", app_password="").retrieve(
            {}, _request()
        )
    assert http.calls == []
