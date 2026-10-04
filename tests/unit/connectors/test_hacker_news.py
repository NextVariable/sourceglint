"""Tests for Hacker News real adapter (Phase 4 §7).

We exercise the adapter via an injected HttpClient — no real network in
the default pytest run. A separate live-gate lives in tests/live/.

Required scenarios from PRD §29:
  * story with external URL
  * Ask HN without external URL (uses HN item URL as fallback)
  * deleted item
  * dead item
  * missing title
  * invalid timestamp
  * API error (4xx permanent → AdapterInvalidResponse)
  * timeout (HttpTimeoutError → AdapterTimeout)
  * rate limit (HttpTransientError 429 → AdapterRateLimited)
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import pytest

from sourceglint.connectors._http import (
    HttpClient,
    HttpResponse,
    HttpTimeoutError,
    HttpTransientError,
)
from sourceglint.connectors.hacker_news import (
    DEFAULT_MAX_PER_QUERY,
    HN_ITEM_BASE,
    HN_SEARCH_URL,
    HackerNewsAdapter,
    SOURCE_NAME,
)
from sourceglint.pipeline.adapters import (
    AdapterAuthMissing,
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)


# ---- fake HTTP client --------------------------------------------------


class _ScriptedHttpClient:
    """Drives the adapter through a list of canned responses.

    Each entry is either:
      * ("json", dict_or_payload, status=200) — return HttpResponse
      * ("raise", HttpTimeoutError|HttpTransientError|...)
    """

    def __init__(self, script: list[tuple[str, Any, int | None]]) -> None:
        self._script = list(script)
        self._idx = 0
        # Captured request URLs / headers
        self.calls: list[dict] = []

    @property
    def user_agent(self) -> str:
        return "sourceglint/test"

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15.0,
    ):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        if self._idx >= len(self._script):
            raise AssertionError(
                f"unexpected extra HTTP call #{self._idx + 1} to {url}"
            )
        op, payload, status = self._script[self._idx]
        self._idx += 1
        if op == "json":
            body = json.dumps(payload).encode("utf-8")
            return HttpResponse(status=status or 200, body=body, url=url)
        if op == "raise":
            raise payload
        raise AssertionError(f"unknown scripted op: {op}")


def _request(**overrides) -> dict:
    base = {
        "query": "ai meeting assistant",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    base.update(overrides)
    return base


def _plan() -> dict:
    return {"topic": "HN test", "mode": "general", "time_window": {"days": 30}}


# ---- normal story with external URL -----------------------------------


def test_comment_body_date_and_thread_provenance_are_preserved():
    hit = {"objectID": "77", "story_title": "Claude Code workflows", "story_id": 66,
           "comment_text": "I use hooks to wait for approval.", "created_at_i": 1789084800}
    cap = _ScriptedHttpClient([("json", {"hits": [hit]}, 200)])
    raw = HackerNewsAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())[0]
    assert raw.source_type == "comment"
    assert raw.text == hit["comment_text"]
    assert raw.url == f"{HN_ITEM_BASE}77"
    assert raw.raw_metadata["hn_story_id"] == 66
    query = parse_qs(urlparse(cap.calls[0]["url"]).query)
    assert "comment" in query["tags"][0]
    assert "created_at_i>=" in query["numericFilters"][0]


def test_story_with_external_url_maps_to_raw():
    hit = {
        "objectID": "111",
        "title": "Show HN: AI Meeting Assistant",
        "url": "https://example.com/x",
        "author": "user_a",
        "created_at_i": 1757000000,  # unix seconds
        "points": 240,
        "num_comments": 87,
    }
    cap = _ScriptedHttpClient([("json", {"hits": [hit]}, 200)])
    adapter = HackerNewsAdapter(http_client=cap)

    out = adapter.retrieve(plan=_plan(), request=_request())

    assert len(out) == 1
    raw = out[0]
    assert raw.source == SOURCE_NAME
    assert raw.source_native_id == "111"
    assert raw.url == f"{HN_ITEM_BASE}111"
    assert raw.title == "Show HN: AI Meeting Assistant"
    assert raw.author == "user_a"
    assert raw.published_at and raw.published_at.startswith("20")  # RFC3339 prefix
    assert raw.engagement.get("points") == 240
    assert raw.engagement.get("comments") == 87
    assert raw.query == "ai meeting assistant"
    assert raw.query_language == "en"


# ---- Ask HN without external URL --------------------------------------


def test_story_without_external_url_falls_back_to_hn_item():
    hit = {
        "objectID": "222",
        "title": "Ask HN: How do you record meeting notes?",
        "url": None,
        "author": "user_b",
        "created_at_i": 1757000200,
        "points": 30,
        "num_comments": 12,
    }
    cap = _ScriptedHttpClient([("json", {"hits": [hit]}, 200)])
    adapter = HackerNewsAdapter(http_client=cap)

    out = adapter.retrieve(plan=_plan(), request=_request())

    assert len(out) == 1
    raw = out[0]
    assert raw.url == f"{HN_ITEM_BASE}222"
    assert raw.source_native_id == "222"


def test_story_with_empty_string_url_also_falls_back():
    hit = {
        "objectID": "223",
        "title": "Ask HN: …",
        "url": "",
        "author": "user_c",
        "created_at_i": 1757000201,
        "points": 0,
        "num_comments": 0,
    }
    cap = _ScriptedHttpClient([("json", {"hits": [hit]}, 200)])
    out = HackerNewsAdapter(http_client=cap).retrieve(
        plan=_plan(), request=_request()
    )
    assert out[0].url == f"{HN_ITEM_BASE}223"


# ---- deleted item ------------------------------------------------------


def test_deleted_item_is_skipped():
    """A deleted item has objectID present but title/author stripped."""

    payload = {
        "hits": [
            {"objectID": "333", "title": None, "url": "https://x", "author": None, "deleted": True},
            {
                "objectID": "334",
                "title": "Real HN item",
                "url": "https://example.com/y",
                "author": "u",
                "created_at_i": 1757000001,
                "points": 5,
                "num_comments": 1,
            },
        ]
    }
    cap = _ScriptedHttpClient([("json", payload, 200)])
    out = HackerNewsAdapter(http_client=cap).retrieve(
        plan=_plan(), request=_request()
    )
    assert len(out) == 1
    assert out[0].source_native_id == "334"


def test_dead_item_is_skipped():
    payload = {
        "hits": [
            {
                "objectID": "444",
                "title": "Dead Item",
                "url": "https://x",
                "author": "u",
                "dead": True,
                "created_at_i": 1757000002,
            },
            {
                "objectID": "445",
                "title": "Alive Item",
                "url": "https://example.com/z",
                "author": "u",
                "created_at_i": 1757000003,
                "points": 1,
                "num_comments": 0,
            },
        ]
    }
    cap = _ScriptedHttpClient([("json", payload, 200)])
    out = HackerNewsAdapter(http_client=cap).retrieve(
        plan=_plan(), request=_request()
    )
    assert [r.source_native_id for r in out] == ["445"]


# ---- missing required fields ------------------------------------------


def test_hit_without_object_id_is_rejected():
    payload = {
        "hits": [
            {"title": "No id", "url": "https://x", "author": "u"},
        ]
    }
    cap = _ScriptedHttpClient([("json", payload, 200)])
    with pytest.raises(AdapterInvalidResponse):
        HackerNewsAdapter(http_client=cap).retrieve(
            plan=_plan(), request=_request()
        )


def test_missing_top_level_hits_key_is_rejected():
    cap = _ScriptedHttpClient([("json", {"results": []}, 200)])
    with pytest.raises(AdapterInvalidResponse):
        HackerNewsAdapter(http_client=cap).retrieve(
            plan=_plan(), request=_request()
        )


# ---- invalid timestamp → soft -----------------------------------------


def test_invalid_timestamp_is_set_to_empty_string():
    """created_at_i is OPTIONAL — when missing or non-int, published_at is
    left empty (Closeout §3 invariant: unknown ≠ neutral)."""

    payload = {
        "hits": [
            {
                "objectID": "555",
                "title": "No ts",
                "url": "https://x",
                "author": "u",
                "created_at_i": "not-a-number",
                "points": 1,
                "num_comments": 0,
            },
        ]
    }
    cap = _ScriptedHttpClient([("json", payload, 200)])
    out = HackerNewsAdapter(http_client=cap).retrieve(
        plan=_plan(), request=_request()
    )
    assert out[0].published_at == ""


# ---- API error / timeout / rate limit ---------------------------------


def test_5xx_maps_to_unavailable():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=502, url="x", body_preview=""), None)])
    adapter = HackerNewsAdapter(http_client=cap)
    with pytest.raises(AdapterUnavailable):
        adapter.retrieve(plan=_plan(), request=_request())


def test_429_maps_to_rate_limited():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=429, url="x", body_preview=""), None)])
    adapter = HackerNewsAdapter(http_client=cap)
    with pytest.raises(AdapterRateLimited):
        adapter.retrieve(plan=_plan(), request=_request())


def test_http_timeout_maps_to_adapter_timeout():
    cap = _ScriptedHttpClient([("raise", HttpTimeoutError(url="x", timeout=10.0), None)])
    adapter = HackerNewsAdapter(http_client=cap)
    with pytest.raises(AdapterTimeout):
        adapter.retrieve(plan=_plan(), request=_request())


def test_malformed_json_raises_invalid_response():
    class _BadJsonClient:
        @property
        def user_agent(self) -> str:
            return "x"

        def request(self, url, *, headers=None, timeout=15.0):
            return HttpResponse(status=200, body=b"not json", url=url)

    adapter = HackerNewsAdapter(http_client=_BadJsonClient())
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan(), request=_request())


# ---- request shape -----------------------------------------------------


def test_request_url_includes_query_and_limit():
    cap = _ScriptedHttpClient([("json", {"hits": []}, 200)])
    adapter = HackerNewsAdapter(http_client=cap, max_per_query=5)
    adapter.retrieve(plan=_plan(), request=_request(query="graph databases"))

    assert len(cap.calls) == 1
    parsed = urlparse(cap.calls[0]["url"])
    assert parsed.scheme == "https"
    assert parsed.netloc.startswith("hn.algolia.com")
    qs = parse_qs(parsed.query)
    assert qs["query"] == ["graph databases"]
    assert qs.get("hitsPerPage") == ["5"]


def test_default_max_per_query_is_twenty():
    assert DEFAULT_MAX_PER_QUERY == 20


def test_limit_clamped_to_max_per_query():
    cap = _ScriptedHttpClient([("json", {"hits": []}, 200)])
    adapter = HackerNewsAdapter(http_client=cap, max_per_query=10)
    adapter.retrieve(plan=_plan(), request=_request(limit=10000))
    qs = parse_qs(urlparse(cap.calls[0]["url"]).query)
    assert qs.get("hitsPerPage") == ["10"]


def test_comment_markup_is_readable_and_original_is_kept():
    markup = "I&#x27;m using plan mode.<p>Then <i>review</i> before implementation."
    cap = _ScriptedHttpClient([("json", {"hits": [{"objectID": "88", "story_title": "Workflow", "comment_text": markup, "created_at_i": 1789084800}]}, 200)])
    raw = HackerNewsAdapter(http_client=cap).retrieve(plan={"time_window": {"days": 30}}, request=_request())[0]
    assert raw.text == "I'm using plan mode. Then review before implementation."
    assert raw.raw_metadata["hn_comment_html"] == markup
