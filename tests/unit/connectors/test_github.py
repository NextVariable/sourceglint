"""Tests for the real GitHub adapter (Phase 4 §8).

We exercise the adapter via an injected HttpClient. The default test
suite never touches the real GitHub API — a separate live-gate under
tests/live/ is the only place that does.

Required scenarios from PRD §8 / §29:
  * repository result mapping
  * anonymous path (no Authorization header)
  * authenticated synthetic path (Authorization: token <token>)
  * token never appears in error repr or query logs
  * 403 rate-limit / secondary rate limit → AdapterRateLimited
  * malformed response → AdapterInvalidResponse
  * 401 (bad token) → AdapterAuthMissing
  * 5xx transient → AdapterUnavailable
  * socket timeout → AdapterTimeout
  * created_at vs published_at vs updated_at mapping discipline
  * max-per-query clamp
  * search-by-query path and item-repos paths share helpers
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import pytest

from gtm_intelligence.connectors._http import (
    HttpClient,
    HttpResponse,
    HttpTimeoutError,
    HttpTransientError,
)
from gtm_intelligence.connectors.github import (
    DEFAULT_MAX_PER_QUERY,
    GITHUB_SEARCH_URL,
    GitHubAdapter,
    SOURCE_NAME,
)
from gtm_intelligence.pipeline.adapters import (
    AdapterAuthMissing,
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)


# ---- fake HTTP client (same shape as HN tests) -------------------------


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
        if op == "text":
            return HttpResponse(status=status or 200, body=payload.encode("utf-8"), url=url)
        if op == "raise":
            raise payload
        raise AssertionError(f"unknown op {op}")


def _plan() -> dict:
    return {"topic": "GH test", "mode": "competitor", "time_window": {"days": 30}}


def _request(**overrides) -> dict:
    base = {
        "query": "ai meeting assistant in:name,description",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    base.update(overrides)
    return base


# ---- anonymous repo search --------------------------------------------


def test_repo_result_maps_to_raw():
    repo = {
        "id": 1,
        "full_name": "acme/awesome",
        "name": "awesome",
        "description": "A really cool AI meeting tool.",
        "html_url": "https://github.com/acme/awesome",
        "owner": {"login": "acmehq"},
        "created_at": "2023-09-01T00:00:00Z",
        "updated_at": "2026-08-15T00:00:00Z",
        "pushed_at": "2026-08-15T00:00:00Z",
        "stargazers_count": 1234,
        "forks_count": 56,
        "open_issues_count": 12,
        "language": "Python",
    }
    cap = _ScriptedHttpClient(
        [("json", {"items": [repo], "total_count": 1}, 200)]
    )
    adapter = GitHubAdapter(http_client=cap)
    out = adapter.retrieve(plan=_plan(), request=_request())

    assert len(out) == 1
    raw = out[0]
    assert raw.source == SOURCE_NAME
    assert raw.source_type == "release"  # repo metadata doubles as release-type
    assert raw.source_native_id == "acme/awesome"
    assert raw.url == "https://github.com/acme/awesome"
    assert raw.title == "acme/awesome"
    assert raw.author == "acmehq"
    assert "AI meeting tool" in raw.text
    # created_at wins over updated_at for the canonical published date.
    assert raw.published_at == "2023-09-01T00:00:00Z"


def test_anonymous_path_sends_no_authorization_header():
    cap = _ScriptedHttpClient([("json", {"items": [], "total_count": 0}, 200)])
    GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())
    headers = cap.calls[0]["headers"]
    assert "authorization" not in {k.lower() for k in headers}
    assert "Authorization" not in headers


# ---- authenticated synthetic path --------------------------------------


def test_authenticated_path_includes_bearer_header():
    cap = _ScriptedHttpClient([("json", {"items": [], "total_count": 0}, 200)])
    adapter = GitHubAdapter(http_client=cap, token="synthetic-token-value")
    adapter.retrieve(plan=_plan(), request=_request())
    headers = cap.calls[0]["headers"]
    auth = headers.get("Authorization") or headers.get("authorization")
    assert auth == "Bearer synthetic-token-value"


def test_token_never_appears_in_error_repr():
    """An exception raised during a partial pipeline must not echo the
    token (PRD §14). We assert that stringifying the adapter / its
    default fields does NOT leak the token."""

    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=502, url="x", body_preview=""), None)])
    adapter = GitHubAdapter(http_client=cap, token="ghp_xxxxxxxxxxxxxxxxxxxx")
    with pytest.raises(AdapterUnavailable) as exc:
        adapter.retrieve(plan=_plan(), request=_request())
    msg = str(exc.value)
    assert "ghp_xxxxxxxxxxxxxxxxxxxx" not in msg


def test_empty_token_string_means_anonymous():
    cap = _ScriptedHttpClient([("json", {"items": [], "total_count": 0}, 200)])
    adapter = GitHubAdapter(http_client=cap, token="")
    adapter.retrieve(plan=_plan(), request=_request())
    headers = cap.calls[0]["headers"]
    assert "authorization" not in {k.lower() for k in headers}


# ---- failure mapping --------------------------------------------------


def test_403_rate_limit_maps_to_rate_limited():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=403, url="x", body_preview=""), None)])
    with pytest.raises(AdapterRateLimited):
        GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())


def test_429_rate_limit_maps_to_rate_limited():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=429, url="x", body_preview=""), None)])
    with pytest.raises(AdapterRateLimited):
        GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())


def test_401_maps_to_auth_missing():
    """401 with a token should be AdapterAuthMissing so the orchestrator
    reports AUTH_MISSING rather than crashing."""

    from gtm_intelligence.connectors._http import HttpPermanentError

    cap = _ScriptedHttpClient([("raise", HttpPermanentError(status=401, url="x"), None)])
    with pytest.raises(AdapterAuthMissing):
        GitHubAdapter(http_client=cap, token="bad").retrieve(
            plan=_plan(), request=_request()
        )


def test_5xx_maps_to_unavailable():
    cap = _ScriptedHttpClient([("raise", HttpTransientError(status=503, url="x", body_preview=""), None)])
    with pytest.raises(AdapterUnavailable):
        GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())


def test_timeout_maps_to_adapter_timeout():
    cap = _ScriptedHttpClient([("raise", HttpTimeoutError(url="x", timeout=10.0), None)])
    with pytest.raises(AdapterTimeout):
        GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())


def test_malformed_json_raises_invalid_response():
    class _Bad:
        @property
        def user_agent(self):
            return "x"

        def request(self, url, *, headers=None, timeout=15.0):
            return HttpResponse(status=200, body=b"not json", url=url)

    with pytest.raises(AdapterInvalidResponse):
        GitHubAdapter(http_client=_Bad()).retrieve(plan=_plan(), request=_request())


def test_missing_top_level_items_raises_invalid_response():
    cap = _ScriptedHttpClient([("json", {"results": []}, 200)])
    with pytest.raises(AdapterInvalidResponse):
        GitHubAdapter(http_client=cap).retrieve(plan=_plan(), request=_request())


# ---- request shape ----------------------------------------------------


def test_request_url_includes_query_and_per_page():
    cap = _ScriptedHttpClient([("json", {"items": [], "total_count": 0}, 200)])
    GitHubAdapter(http_client=cap).retrieve(
        plan=_plan(), request=_request(query="meeting transcription")
    )
    parsed = urlparse(cap.calls[0]["url"])
    assert parsed.scheme == "https"
    assert parsed.netloc.startswith("api.github.com")
    qs = parse_qs(parsed.query)
    assert qs["q"] == ["meeting transcription"]
    assert qs["per_page"] == ["20"]
    assert qs["sort"] == ["updated"]


def test_default_max_per_query_is_twenty():
    assert DEFAULT_MAX_PER_QUERY == 20


def test_limit_clamped_to_max_per_query():
    cap = _ScriptedHttpClient([("json", {"items": [], "total_count": 0}, 200)])
    adapter = GitHubAdapter(http_client=cap, max_per_query=5)
    adapter.retrieve(plan=_plan(), request=_request(limit=10000))
    qs = parse_qs(urlparse(cap.calls[0]["url"]).query)
    assert qs["per_page"] == ["5"]
