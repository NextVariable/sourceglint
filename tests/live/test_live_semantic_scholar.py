"""Opt-in Semantic Scholar live test requiring the provider's API key."""

import os

from gtm_intelligence.connectors.open_sources import SemanticScholarAdapter


def test_semantic_scholar_live_with_api_key():
    results = SemanticScholarAdapter(
        api_key=os.environ["SEMANTIC_SCHOLAR_API_KEY"],
        max_per_query=2,
    ).retrieve(
        {"time_window": {"days": 365}},
        {
            "query": "large language model",
            "query_language": "en",
            "market": "global",
            "retrieved_at": "2026-09-29T00:00:00Z",
            "limit": 2,
        },
    )
    assert results
    assert all(item.source == "semantic_scholar" for item in results)
