"""Live Hacker News adapter test (skipped by default).

Set `RUN_LIVE_TESTS=1` to enable. No credentials required — Algolia's
HN search API is public.

The test exercises ONE live call against the real search endpoint to
confirm the mapping that the offline fixture tests use still matches
the live response shape. NEVER expect this to pass in an environment
that doesn't have network egress.
"""


def test_hacker_news_search_live_returns_well_formed_results():
    """Live boundary: real Algolia search returns hits that the adapter
    can map to RawSourceResult without raising."""

    # Imported lazily so the module is not even loaded when this file
    # is collected under the offline default.
    from sourceglint.connectors._http import StdlibHttpClient
    from sourceglint.connectors.hacker_news import (
        HackerNewsAdapter,
        HN_SEARCH_URL,
    )
    from urllib.parse import urlencode

    http = StdlibHttpClient(default_timeout=15.0)
    # Hit the real Algolia endpoint directly (small payload, fewer
    # surprises than the full adapter pipeline).
    url = f"{HN_SEARCH_URL}?{urlencode({'query': 'show hn', 'hitsPerPage': 3, 'tags': 'story'})}"
    response = http.request(url)
    assert response.status == 200, f"algolia returned {response.status}"

    import json

    payload = json.loads(response.body.decode("utf-8"))
    hits = payload.get("hits") or []
    assert isinstance(hits, list), "hits must be a list"

    adapter = HackerNewsAdapter(http_client=http)
    plan = {"topic": "live", "mode": "general", "time_window": {"days": 30}}
    request = {
        "query": "show hn",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    results = adapter.retrieve(plan=plan, request=request)
    # We don't pin specific results — we just verify the structure
    # matches what the offline tests assert.
    for raw in results:
        assert raw.source == "hacker_news"
        assert raw.url.startswith("http")
        assert raw.title
