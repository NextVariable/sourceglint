"""Opt-in X live test requiring an official API bearer token."""

import os
from datetime import datetime, timezone

from sourceglint.connectors.authorized_sources import XAdapter


def test_x_live_with_bearer_token():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = XAdapter(
        bearer_token=os.environ["X_BEARER_TOKEN"],
        max_per_query=2,
    ).retrieve(
        {"time_window": {"days": 7}},
        {
            "query": "AI agent",
            "query_language": "en",
            "market": "global",
            "retrieved_at": now,
            "limit": 2,
        },
    )
    assert results
    assert all(item.source == "x" and item.url.startswith("https://x.com/") for item in results)
