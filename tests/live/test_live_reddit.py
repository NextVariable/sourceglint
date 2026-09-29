"""Live keyless Reddit RSS discovery test (skipped by default)."""


def test_reddit_search_live_returns_well_formed_results():
    from gtm_intelligence.connectors.reddit import RedditAdapter

    adapter = RedditAdapter(max_per_query=3, allow_keyless_rss=True)
    plan = {
        "topic": "live",
        "mode": "general",
        "time_window": {"days": 30},
    }
    request = {
        "query": "python",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    results = adapter.retrieve(plan=plan, request=request)
    assert results
    for raw in results:
        assert raw.source == "reddit"
        assert raw.url.startswith("https://www.reddit.com/")
        assert raw.published_at
