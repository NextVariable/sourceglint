"""Opt-in Product Hunt live test requiring an API token."""

import os
from datetime import datetime, timezone

from sourceglint.connectors.authorized_sources import ProductHuntAdapter


def test_product_hunt_live_with_token():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = ProductHuntAdapter(
        token=os.environ["PRODUCT_HUNT_TOKEN"],
        max_per_query=3,
    ).retrieve(
        {"time_window": {"days": 30}},
        {
            "query": "AI",
            "query_language": "en",
            "market": "global",
            "retrieved_at": now,
            "limit": 3,
        },
    )
    assert results
    assert all(item.source == "product_hunt" for item in results)
