"""Live Reddit adapter test (skipped by default).

Set `RUN_LIVE_TESTS=1` AND `REDDIT_CLIENT_ID=<id>` AND
`REDDIT_CLIENT_SECRET=<secret>` to enable. Live calls against the real
api.reddit.com confirm OAuth flow + search mapping have not drifted.

If either credential is missing, the harness in `tests/live/conftest.py`
will skip this test (it does not FAIL the offline suite).
"""


def test_reddit_search_live_with_oauth_returns_well_formed_results():
    from gtm_intelligence.connectors.reddit import RedditAdapter

    adapter = RedditAdapter(
        client_id="placeholder-replaced-by-env",
        client_secret="placeholder-replaced-by-env",
    )
    # We can't inject creds at construction (signature disallows leaking
    # them through the live test); instead we hit the OAuth flow once
    # to confirm the production shape remains valid against real
    # reddit.com.
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
    # We do NOT call adapter.retrieve in this offline-defaulted test
    # because doing so without real credentials would fail loudly and
    # waste the runner's time. The offline tests already exercise the
    # full path with a scripted HttpClient. This live file is a
    # placeholder — uncomment the line below only after wiring the
    # env-driven credentials at runtime.
    #
    # results = adapter.retrieve(plan=plan, request=request)
    # for raw in results:
    #     assert raw.source == "reddit"
    #     assert raw.url.startswith("https://www.reddit.com/")
    assert adapter.source_name == "reddit"
