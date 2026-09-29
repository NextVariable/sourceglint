"""Tests for the Reddit adapter (Phase 4 §9).

Phase 4 PRD §9 is explicit: if a Reddit connector cannot be implemented
robustly within legal/policy bounds, the final state is acceptable as
'contract-complete but disabled/auth-required'. We chose to implement
the official OAuth2 client_credentials path against
https://www.reddit.com/api/v1/access_token, which is the LEGITIMATE flow
described as priority #1 in PRD §9.

We FORBID and DO NOT implement:
  * cookie extraction / browser-session stealing
  * login automation
  * undocumented anti-bot circumvention
  * rotating proxies
  * CAPTCHA bypass
  * user credential storage

Required scenarios from PRD §29:
  * authenticated success (synthetic token)
  * no token (auth missing) → AdapterAuthMissing BEFORE any HTTP call
  * token refresh on expiry
  * rate limit → AdapterRateLimited
  * deleted content (deleted body) silently dropped
  * malformed JSON → AdapterInvalidResponse
  * 401 (token revoked) → AdapterAuthMissing
  * 5xx → AdapterUnavailable

Adapter shape (Phase 4 §9):
  * credentials passed in via constructor (no env reads in module).
  * token cache kept in-memory only (not disk, not in Evidence).
  * token is never logged, never echoed in error repr.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import pytest

from gtm_intelligence.connectors._http import (
    HttpPermanentError,
    HttpResponse,
    HttpTimeoutError,
    HttpTransientError,
)
from gtm_intelligence.connectors.reddit import (
    DEFAULT_MAX_PER_QUERY,
    REDDIT_ACCESS_TOKEN_URL,
    REDDIT_SEARCH_URL,
    RedditAdapter,
    SOURCE_NAME,
)
from gtm_intelligence.pipeline.adapters import (
    AdapterAuthMissing,
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)


# ---- fake HTTP client --------------------------------------------------


class _ScriptedHttpClient:
    def __init__(self, script):
        self._script = list(script)
        self._idx = 0
        self.calls: list[dict] = []

    @property
    def user_agent(self):
        return "gtm-intelligence/test"

    def request(self, url, *, headers=None, timeout=15.0):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        if self._idx >= len(self._script):
            raise AssertionError(f"unexpected extra HTTP call to {url}")
        op, payload, status = self._script[self._idx]
        self._idx += 1
        if op == "json":
            return HttpResponse(status=status or 200, body=json.dumps(payload).encode("utf-8"), url=url)
        if op == "form":
            return HttpResponse(status=status or 200, body=payload.encode("utf-8"), url=url)
        if op == "raise":
            raise payload
        raise AssertionError(f"unknown op {op}")


def _plan() -> dict:
    return {"topic": "Reddit test", "mode": "voc", "time_window": {"days": 30}}


def _request(**overrides) -> dict:
    base = {
        "query": "ai meeting assistant",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    base.update(overrides)
    return base


# ---- auth-missing path is enforced BEFORE network ----------------------


def test_no_token_uses_public_rss_route():
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>AI meeting assistant feedback</title>
      <link href="https://www.reddit.com/r/SaaS/comments/abc123/example/" />
      <updated>2026-09-05T10:00:00+00:00</updated>
      <author><name>/u/tester</name></author><category term="SaaS" />
      <content type="html">&lt;p&gt;Useful feedback&lt;/p&gt;</content>
    </entry></feed>'''
    cap = _ScriptedHttpClient([("form", atom, 200)])
    adapter = RedditAdapter(
        http_client=cap, client_id=None, client_secret=None,
        allow_keyless_rss=True,
    )
    out = adapter.retrieve(plan=_plan(), request=_request())
    assert out[0].source_native_id == "t3_abc123"
    assert out[0].raw_metadata["route"] == "public_rss"
    assert out[0].engagement == {}
    assert "search.rss" in cap.calls[0]["url"]


def test_empty_string_credentials_also_use_rss():
    cap = _ScriptedHttpClient([("form", '<feed xmlns="http://www.w3.org/2005/Atom"/>', 200)])
    adapter = RedditAdapter(
        http_client=cap, client_id="", client_secret="",
        allow_keyless_rss=True,
    )
    assert adapter.retrieve(plan=_plan(), request=_request()) == []
    assert len(cap.calls) == 1


def test_keyless_rss_must_be_enabled_by_host():
    cap = _ScriptedHttpClient([])
    with pytest.raises(AdapterAuthMissing):
        RedditAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())
    assert cap.calls == []


# ---- synthetic successful flow -----------------------------------------


def test_authenticated_success_uses_bearer_token():
    # 1. token endpoint returns a bearer
    token_payload = {"access_token": "synthetic-bearer-xyz", "token_type": "bearer", "expires_in": 3600}
    # 2. search endpoint returns a listing
    listing = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "name": "t3_abc123",
                        "title": "AI meeting assistant feedback",
                        "selftext": "I have been using X for 3 months...",
                        "author": "u/someuser",
                        "subreddit": "productivity",
                        "permalink": "/r/productivity/comments/abc123/ai_meeting_assistant_feedback/",
                        "url": "https://www.reddit.com/r/productivity/comments/abc123/ai_meeting_assistant_feedback/",
                        "created_utc": 1757000000.0,
                        "score": 245,
                        "num_comments": 87,
                        "removed": False,
                    },
                },
            ],
            "after": None,
            "before": None,
        }
    }
    cap = _ScriptedHttpClient([
        ("form", json.dumps(token_payload), 200),
        ("json", listing, 200),
    ])
    adapter = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec")
    out = adapter.retrieve(plan=_plan(), request=_request())

    assert len(out) == 1
    raw = out[0]
    assert raw.source == SOURCE_NAME
    assert raw.source_type == "post"
    assert raw.source_native_id == "t3_abc123"
    assert raw.url.endswith("/comments/abc123/ai_meeting_assistant_feedback/")
    assert raw.title == "AI meeting assistant feedback"
    assert raw.author == "u/someuser"
    assert raw.engagement.get("upvotes") == 245
    assert raw.engagement.get("comments") == 87
    assert raw.published_at.startswith("20")
    assert raw.raw_metadata.get("subreddit") == "productivity"


def test_token_request_uses_basic_auth_with_client_id_secret():
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "x", "expires_in": 3600}), 200),
        ("json", {"data": {"children": []}}, 200),
    ])
    RedditAdapter(http_client=cap, client_id="my-id", client_secret="my-secret").retrieve(
        plan=_plan(), request=_request()
    )

    token_call = cap.calls[0]
    assert token_call["url"] == REDDIT_ACCESS_TOKEN_URL
    auth = token_call["headers"].get("Authorization") or token_call["headers"].get("authorization")
    assert auth is not None
    assert auth.startswith("Basic ")
    # The secret is base64-encoded inside the auth header (not raw), but we
    # also confirm the raw string does NOT appear in headers at all.
    for v in token_call["headers"].values():
        assert "my-secret" not in v


def test_search_request_includes_bearer_token():
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "the-bearer", "expires_in": 3600}), 200),
        ("json", {"data": {"children": []}}, 200),
    ])
    RedditAdapter(http_client=cap, client_id="cid", client_secret="csec").retrieve(
        plan=_plan(), request=_request(query="meeting transcription")
    )
    search_call = cap.calls[1]
    auth = search_call["headers"].get("Authorization") or search_call["headers"].get("authorization")
    assert auth == "Bearer the-bearer"
    parsed = urlparse(search_call["url"])
    assert parsed.netloc.startswith("oauth.reddit.com")
    qs = parse_qs(parsed.query)
    assert qs["q"] == ["meeting transcription"]
    assert qs["limit"] == ["20"]


# ---- failure mapping ---------------------------------------------------


def test_token_endpoint_5xx_maps_to_unavailable():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=502, url="x", body_preview=""), None)])
    adapter = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec")
    with pytest.raises(AdapterUnavailable):
        adapter.retrieve(plan=_plan(), request=_request())


def test_search_429_maps_to_rate_limited():
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "b", "expires_in": 3600}), 200),
        ("raise", HttpTransientError(status=429, url="x", body_preview=""), None),
    ])
    adapter = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec")
    with pytest.raises(AdapterRateLimited):
        adapter.retrieve(plan=_plan(), request=_request())


def test_token_401_maps_to_auth_missing():
    cap = _ScriptedHttpClient([("raise", HttpPermanentError(status=401, url="x"), None)])
    adapter = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec")
    with pytest.raises(AdapterAuthMissing):
        adapter.retrieve(plan=_plan(), request=_request())


def test_search_timeout_maps_to_adapter_timeout():
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "b", "expires_in": 3600}), 200),
        ("raise", HttpTimeoutError(url="x", timeout=10.0), None),
    ])
    adapter = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec")
    with pytest.raises(AdapterTimeout):
        adapter.retrieve(plan=_plan(), request=_request())


def test_search_malformed_json_raises_invalid_response():
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "b", "expires_in": 3600}), 200),
        ("text", "not json", 200),  # uses 'text' branch
    ])
    # Need a body that's not JSON
    class _BadClient(_ScriptedHttpClient):
        def request(self, url, *, headers=None, timeout=15.0):
            self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
            if "access_token" in url:
                return HttpResponse(status=200, body=json.dumps({"access_token": "b", "expires_in": 3600}).encode("utf-8"), url=url)
            return HttpResponse(status=200, body=b"not json", url=url)

    cap2 = _BadClient([])
    adapter = RedditAdapter(http_client=cap2, client_id="cid", client_secret="csec")
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan(), request=_request())


# ---- payload coverage ---------------------------------------------------


def test_deleted_content_is_dropped():
    listing = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "x",
                        "name": "t3_x",
                        "title": "[deleted]",
                        "selftext": "",
                        "author": "[deleted]",
                        "subreddit": "test",
                        "permalink": "/r/test/comments/x/y/",
                        "url": "https://www.reddit.com/r/test/comments/x/y/",
                        "created_utc": 1757000001.0,
                        "score": 1,
                        "num_comments": 0,
                    },
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "y",
                        "name": "t3_y",
                        "title": "Real reddit post",
                        "selftext": "Real content here.",
                        "author": "u/live_user",
                        "subreddit": "test",
                        "permalink": "/r/test/comments/y/r/",
                        "url": "https://www.reddit.com/r/test/comments/y/r/",
                        "created_utc": 1757000002.0,
                        "score": 50,
                        "num_comments": 2,
                    },
                },
            ]
        }
    }
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "b", "expires_in": 3600}), 200),
        ("json", listing, 200),
    ])
    out = RedditAdapter(http_client=cap, client_id="cid", client_secret="csec").retrieve(
        plan=_plan(), request=_request()
    )
    assert [r.source_native_id for r in out] == ["t3_y"]


def test_item_missing_required_field_raises_invalid_response():
    listing = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "z",
                        "title": "No name here",
                        # missing name, url, etc.
                    },
                },
            ]
        }
    }
    cap = _ScriptedHttpClient([
        ("form", json.dumps({"access_token": "b", "expires_in": 3600}), 200),
        ("json", listing, 200),
    ])
    with pytest.raises(AdapterInvalidResponse):
        RedditAdapter(http_client=cap, client_id="cid", client_secret="csec").retrieve(
            plan=_plan(), request=_request()
        )


def test_secret_never_appears_in_error_repr():
    """PRD §14: token never appears in error message."""
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=502, url="x", body_preview=""), None)])
    adapter = RedditAdapter(
        http_client=cap, client_id="cid", client_secret="ultra-secret-value"
    )
    with pytest.raises(AdapterUnavailable) as exc:
        adapter.retrieve(plan=_plan(), request=_request())
    assert "ultra-secret-value" not in str(exc.value)


def test_default_max_per_query_is_twenty():
    assert DEFAULT_MAX_PER_QUERY == 20
