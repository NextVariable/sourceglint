"""Tests for the HTTP client abstraction (Phase 4 §10-§14, §29).

Covers PRD §29's HTTP matrix: timeout, retry on transient, no retry on
permanent, User-Agent.

These tests use a fake socket-path by monkey-patching StdlibHttpClient's
underlying urllib call. We do NOT make real network calls — every
test exercises a recorded Request + response.
"""
from __future__ import annotations

import json
import socket
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import pytest

from sourceglint.connectors._http import (
    DEFAULT_USER_AGENT,
    HttpPermanentError,
    HttpResponse,
    StdlibHttpClient,
    HttpTimeoutError,
    HttpTransientError,
)


# ---- monkey-patch boundary ---------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, status: int, body: bytes = b"", headers: Mapping[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self._headers: dict[str, str] = dict(headers or {})

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    @property
    def headers(self):
        return self._headers


def _patched_urlopen(monkeypatch, response_factory):
    """Replace urllib.request.urlopen with one driven by `response_factory`.

    `response_factory` is called as response_factory(url, request, timeout)
    and must return one of:
      * _FakeHTTPResponse — becomes HttpResponse
      * raises urllib.error.HTTPError(...) — becomes HttpTransientError /
        HttpPermanentError based on status
      * raises urllib.error.URLError(...) — becomes HttpTransientError
      * raises socket.timeout — becomes HttpTimeoutError
    """

    def fake(url, *args, **kwargs):
        # urllib.request.urlopen(req, timeout=None) style; test uses the
        # Request object as the first arg too.
        if hasattr(url, "full_url"):
            return response_factory(url.full_url, url)
        return response_factory(url, None)

    monkeypatch.setattr(urllib_request, "urlopen", fake)
    return fake


# ---- PRD §12 User-Agent -----------------------------------------------


def test_user_agent_header_is_attached(monkeypatch):
    seen: dict[str, str] = {}

    def factory(url, req):
        for k, v in req.header_items():
            seen[k.lower()] = v
        return _FakeHTTPResponse(200, b"{}", {"Content-Type": "application/json"})

    _patched_urlopen(monkeypatch, factory)

    client = StdlibHttpClient()
    client.request("https://example.com/api")
    assert seen["user-agent"] == DEFAULT_USER_AGENT


def test_user_agent_caller_override_is_ignored(monkeypatch):
    seen: dict[str, str] = {}

    def factory(url, req):
        for k, v in req.header_items():
            seen[k.lower()] = v
        return _FakeHTTPResponse(200, b"{}", {})

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient()
    client.request(
        "https://example.com/api",
        headers={"User-Agent": "sneaky/1.0"},
    )
    assert seen["user-agent"] == DEFAULT_USER_AGENT  # never overwritten


def test_post_json_request_is_encoded_without_exposing_payload(monkeypatch):
    seen: dict[str, object] = {}

    def factory(url, req):
        seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["content_type"] = req.get_header("Content-type")
        return _FakeHTTPResponse(200, b'{}', {})

    _patched_urlopen(monkeypatch, factory)
    StdlibHttpClient().request(
        "https://example.com/session",
        method="POST",
        json_data={"identifier": "user.example", "password": "secret"},
    )
    assert seen == {
        "method": "POST",
        "body": {"identifier": "user.example", "password": "secret"},
        "content_type": "application/json",
    }


# ---- PRD §11 retry on transient ---------------------------------------


def test_429_is_retried_then_propagates(monkeypatch):
    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        raise urllib_error.HTTPError(
            url, 429, "Too Many Requests", {}, None
        )

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=3, backoff_seconds=0, sleep=lambda s: None)

    with pytest.raises(HttpTransientError) as exc:
        client.request("https://example.com/api")
    assert exc.value.status == 429
    assert calls["n"] == 3  # 1 + 2 retries


def test_5xx_is_retried_then_propagates(monkeypatch):
    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        raise urllib_error.HTTPError(url, 503, "Service Unavailable", {}, None)

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=2, backoff_seconds=0, sleep=lambda s: None)

    with pytest.raises(HttpTransientError) as exc:
        client.request("https://example.com/api")
    assert exc.value.status == 503
    assert calls["n"] == 2


def test_500_then_success_within_budget(monkeypatch):
    """One transient failure then success — both invocations counted."""

    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib_error.HTTPError(url, 502, "Bad Gateway", {}, None)
        return _FakeHTTPResponse(200, b"{}", {})

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=3, backoff_seconds=0, sleep=lambda s: None)
    resp = client.request("https://example.com/api")
    assert resp.status == 200
    assert calls["n"] == 2


# ---- PRD §11 no retry on permanent ------------------------------------


def test_400_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        raise urllib_error.HTTPError(url, 400, "Bad Request", {}, None)

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=5, backoff_seconds=0, sleep=lambda s: None)
    with pytest.raises(HttpPermanentError) as exc:
        client.request("https://example.com/api")
    assert exc.value.status == 400
    assert calls["n"] == 1


def test_403_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        raise urllib_error.HTTPError(url, 403, "Forbidden", {}, None)

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=5, backoff_seconds=0, sleep=lambda s: None)
    with pytest.raises(HttpPermanentError):
        client.request("https://example.com/api")
    assert calls["n"] == 1


# ---- PRD §11 timeout --------------------------------------------------


def test_socket_timeout_raises_http_timeout(monkeypatch):
    def factory(url, req):
        raise socket.timeout("simulated timeout")

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(default_timeout=1.5, max_attempts=2, sleep=lambda s: None)
    with pytest.raises(HttpTimeoutError) as exc:
        client.request("https://example.com/api")
    assert exc.value.timeout == 1.5


def test_urlerror_with_timeout_reason_raises_timeout(monkeypatch):
    class _reason:
        def __str__(self):
            return "timed out"

    def factory(url, req):
        raise urllib_error.URLError(_reason())

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(default_timeout=2.0, max_attempts=1)
    with pytest.raises(HttpTimeoutError):
        client.request("https://example.com/api")


# ---- status + body parsing --------------------------------------------


def test_response_body_parsed_as_text():
    resp = HttpResponse(status=200, body=b"hello", url="u")
    assert resp.text() == "hello"


def test_response_body_parsed_as_json():
    resp = HttpResponse(status=200, body=b'{"a":1}', url="u")
    assert resp.json() == {"a": 1}


# ---- PRD §14 secrets never echoed -------------------------------------


def test_transient_error_message_does_not_include_body(monkeypatch):
    """Even if the body contains a token-shaped string, the error repr
    must surface only the byte count (PRD §14)."""

    sentinel = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

    def factory(url, req):
        raise urllib_error.HTTPError(
            url, 502, "Bad Gateway", {}, io_with(sentinel)
        )

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=1)

    import io

    def io_with(text):
        return io.BytesIO(text.encode("utf-8"))

    with pytest.raises(HttpTransientError) as exc:
        client.request("https://example.com/api")
    msg = str(exc.value)
    assert sentinel not in msg


# ---- retry exhaustion on timeout --------------------------------------


def test_timeout_is_retried(monkeypatch):
    calls = {"n": 0}

    def factory(url, req):
        calls["n"] += 1
        raise socket.timeout("slow")

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(default_timeout=0.1, max_attempts=2, sleep=lambda s: None)
    with pytest.raises(HttpTimeoutError):
        client.request("https://example.com/api")
    assert calls["n"] == 2


# ---- unrelated: status only is exposed (no body in repr) --------------


def test_4xx_error_message_does_not_leak_body(monkeypatch):
    def factory(url, req):
        raise urllib_error.HTTPError(
            url,
            401,
            "Unauthorized",
            {},
            io_with('{"detail":"BAD TOKEN ghp_yyyyyy"}'),
        )

    _patched_urlopen(monkeypatch, factory)
    client = StdlibHttpClient(max_attempts=1)
    import io

    def io_with(t):
        return io.BytesIO(t.encode("utf-8"))

    with pytest.raises(HttpPermanentError) as exc:
        client.request("https://example.com/api")
    assert "ghp_yyyyyy" not in str(exc.value)
