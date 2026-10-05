"""Exercise the real urllib request boundary, not permissive adapter doubles."""
import io
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib import request
from urllib.parse import parse_qs

import pytest

from sourceglint.connectors._http import StdlibHttpClient
from sourceglint.connectors.reddit import RedditAdapter


class Response(io.BytesIO):
    status = 200
    headers = {}


def test_reddit_application_auth_sends_form_post(monkeypatch):
    seen = []

    def open_request(req, **kwargs):
        seen.append(req)
        return Response(b'{"access_token":"test-token","expires_in":3600}')

    monkeypatch.setattr(request, "urlopen", open_request)
    adapter = RedditAdapter(client_id="test-id", client_secret="test-secret")
    token = adapter._ensure_token("test-id", "test-secret")
    assert token.access_token == "test-token"
    assert seen[0].get_method() == "POST"
    assert seen[0].get_header("Content-type") == "application/x-www-form-urlencoded"
    assert parse_qs(seen[0].data.decode()) == {"grant_type": ["client_credentials"]}
    assert "grant_type" not in seen[0].full_url


def test_parallel_requests_keep_individual_timeouts(monkeypatch):
    original = socket.getdefaulttimeout()
    barrier = Barrier(2)
    observed = []

    def open_request(req, **kwargs):
        barrier.wait(timeout=5)
        observed.append((req.full_url, kwargs.get("timeout"), socket.getdefaulttimeout()))
        return Response(b"{}")

    monkeypatch.setattr(request, "urlopen", open_request)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(StdlibHttpClient().request, f"https://example.com/{seconds}", timeout=seconds) for seconds in (2.0, 7.0)]
            for future in futures:
                future.result(timeout=10)
        assert sorted((url.rsplit("/", 1)[1], timeout) for url, timeout, _ in observed) == [("2.0", 2.0), ("7.0", 7.0)]
        assert all(default == original for _, _, default in observed)
        assert socket.getdefaulttimeout() == original
    finally:
        socket.setdefaulttimeout(original)


def test_form_and_json_payloads_cannot_be_silently_combined(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("ambiguous body must fail before network access")

    monkeypatch.setattr(request, "urlopen", unexpected)
    with pytest.raises(ValueError, match="form_data.*json_data|json_data.*form_data"):
        StdlibHttpClient().request("https://example.com", method="POST", json_data={"a": 1}, form_data={"b": "2"})
