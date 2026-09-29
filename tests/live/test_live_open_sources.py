"""Opt-in real calls for credential-free public API connectors."""

import pytest

from sourceglint.connectors.open_sources import (
    ArxivAdapter,
    DevToAdapter,
    HuggingFaceAdapter,
    PackageRegistriesAdapter,
    QiitaAdapter,
    StackOverflowAdapter,
)


@pytest.mark.parametrize(
    ("adapter", "query", "language", "market"),
    [
        (StackOverflowAdapter(max_per_query=2), "python", "en", "global"),
        (DevToAdapter(max_per_query=2), "python", "en", "global"),
        (HuggingFaceAdapter(max_per_query=2), "text generation", "en", "global"),
        (PackageRegistriesAdapter(max_per_query=2), "ai agent", "en", "global"),
        (QiitaAdapter(max_per_query=2), "Python", "ja", "jp"),
        (ArxivAdapter(max_per_query=2), "large language model", "en", "global"),
    ],
)
def test_public_topic_search_live(adapter, query, language, market):
    results = adapter.retrieve(
        {"time_window": {"days": 365}},
        {
            "query": query,
            "query_language": language,
            "market": market,
            "retrieved_at": "2026-09-29T00:00:00Z",
            "limit": 2,
        },
    )
    assert results
    for item in results:
        assert item.source == adapter.name
        assert item.url.startswith("https://")
        assert item.title
        assert item.published_at
