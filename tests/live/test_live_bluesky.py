"""Opt-in smoke test for Bluesky's documented public AppView endpoint."""


def test_bluesky_public_search_live_returns_well_formed_results():
    from gtm_intelligence.connectors.bluesky import BlueskyAdapter

    results = BlueskyAdapter(max_per_query=3).retrieve(
        plan={"topic": "artificial intelligence"},
        request={
            "query": "artificial intelligence",
            "query_language": "en",
            "market": "global",
        },
    )
    for item in results:
        assert item.source == "bluesky"
        assert item.url.startswith("https://bsky.app/profile/")
        assert item.published_at
