from __future__ import annotations

from gtm_intelligence.source_catalog import (
    load_source_catalog,
    select_host_search_targets,
)


def test_catalog_is_valid_unique_and_broad():
    catalog = load_source_catalog()
    names = [item.name for item in catalog]
    assert len(names) == len(set(names))
    assert len(names) >= 50
    for expected in (
        "x", "instagram", "youtube", "tiktok", "linkedin", "reddit",
        "discord", "product_hunt", "threads", "github", "kickstarter",
        "makuake", "green_funding", "facebook", "app_store", "google_play",
    ):
        assert expected in names


def test_host_search_router_is_bounded_diverse_and_skips_direct_connectors():
    targets = select_host_search_targets(
        load_source_catalog(),
        mode="voc",
        market="global",
        language="en",
        budget=8,
    )
    assert 1 <= len(targets) <= 8
    assert len({target.family for target in targets}) >= 3
    assert all("host_web_search" in target.routes for target in targets)
    assert all(
        not ("direct_connector" in target.routes and target.availability == "ready")
        for target in targets
    )
    assert "reddit" not in {target.name for target in targets}


def test_japan_routing_prefers_local_sources_without_querying_everything():
    targets = select_host_search_targets(
        load_source_catalog(),
        mode="market",
        market="jp",
        language="ja",
        budget=10,
    )
    names = {target.name for target in targets}
    assert {"makuake", "green_funding"} & names
    assert len(targets) == 10


def test_zero_budget_selects_nothing():
    assert select_host_search_targets(
        load_source_catalog(),
        mode="general",
        market="global",
        language="en",
        budget=0,
    ) == []
