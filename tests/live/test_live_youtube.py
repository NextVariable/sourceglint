"""Opt-in smoke test for local yt-dlp YouTube metadata search."""

import shutil

import pytest


def test_youtube_ytdlp_live_returns_well_formed_results():
    if not shutil.which("yt-dlp"):
        pytest.skip("yt-dlp not installed")
    from gtm_intelligence.connectors.youtube import YouTubeAdapter

    results = YouTubeAdapter(max_per_query=1).retrieve(
        plan={"topic": "artificial intelligence"},
        request={
            "query": "artificial intelligence",
            "query_language": "en",
            "market": "global",
            "limit": 1,
        },
    )
    assert results
    assert results[0].source == "youtube"
    assert results[0].url.startswith("https://www.youtube.com/watch?v=")
    assert results[0].published_at
