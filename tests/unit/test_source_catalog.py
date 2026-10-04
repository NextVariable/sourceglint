from __future__ import annotations

from sourceglint.source_catalog import (
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


def test_host_search_router_is_bounded_and_skips_only_reported_coverage():
    targets = select_host_search_targets(
        load_source_catalog(),
        mode="voc",
        market="global",
        language="en",
        budget=8,
        covered_direct_sources=("reddit", "hacker_news", "github"),
    )
    assert 1 <= len(targets) <= 8
    assert len({target.family for target in targets}) >= 3
    assert all("host_web_search" in target.routes for target in targets)
    assert "reddit" not in {target.name for target in targets}


def test_host_only_first_run_keeps_reddit_hn_and_github():
    targets = select_host_search_targets(
        load_source_catalog(), mode="general", market="global", language="en",
    )
    names = {target.name for target in targets}
    assert {"reddit", "hacker_news", "github"} <= names


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
