"""Live GitHub adapter test (skipped by default).

Set `RUN_LIVE_TESTS=1` to enable. The smoke test intentionally exercises
GitHub's anonymous REST route so a missing token cannot create a false skip.

We deliberately issue ONE small search query — no fan-out, no
destructive deletes.
"""


def test_github_search_live_returns_well_formed_results():
    from gtm_intelligence.connectors._http import StdlibHttpClient
    from gtm_intelligence.connectors.github import GitHubAdapter
    from urllib.parse import quote_plus

    http = StdlibHttpClient(default_timeout=15.0)
    adapter = GitHubAdapter(http_client=http, token=None)

    # A benign query that always returns something on the live API.
    results = adapter.retrieve(
        plan={
            "topic": "live",
            "mode": "general",
            "time_window": {"days": 365},
        },
        request={
            "query": "language:python stars:>1000",
            "query_language": "en",
            "market": "global",
            "retrieved_at": "2026-09-06T00:00:00Z",
        },
    )
    # Anonymous path works at 60 req/h; this is one shot.
    for raw in results:
        assert raw.source == "github"
        assert raw.url.startswith("https://github.com/")
        assert "/" in raw.source_native_id  # full_name shape
