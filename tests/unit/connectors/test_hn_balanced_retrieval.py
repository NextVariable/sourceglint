"""Regressions from the live workflow comparison: stories must survive comments."""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from sourceglint.connectors._http import HttpResponse, HttpTransientError
from sourceglint.connectors.hacker_news import HackerNewsAdapter
from sourceglint.pipeline.adapters import AdapterRateLimited


PLAN = {"topic": "Claude Code workflows", "time_window": {"days": 30}}
REQUEST = {"query": "Claude Code workflows", "retrieved_at": "2026-10-05T00:00:00Z"}


def hit(n, comment=False, title="Claude Code workflow"):
    row = {"objectID": str(n), "title": title, "created_at_i": 1790294400}
    if comment:
        row.update(story_title=title, comment_text="Claude Code workflows: plan, implement, review", story_id=9)
    return row


class Client:
    def __init__(self, stories, comments):
        self.lanes = {"story": stories, "comment": comments}
        self.calls = []

    def request(self, url, **kwargs):
        params = parse_qs(urlparse(url).query)
        self.calls.append(params)
        lane = params["tags"][0]
        if lane == "(story,comment)":
            # Replay the comparison's comment-heavy combined ranking too.
            payload = self.lanes["comment"] + self.lanes["story"]
        else:
            payload = self.lanes[lane]
        if isinstance(payload, Exception):
            raise payload
        return HttpResponse(status=200, body=json.dumps({"hits": payload}).encode(), url=url)


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 20])
def test_reserves_story_room_without_losing_comment_dates(limit):
    client = Client([hit(i) for i in range(20)], [hit(i + 100, True) for i in range(60)])
    rows = HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, {**REQUEST, "limit": limit})
    assert len(rows) == limit
    assert sum(r.source_type == "post" for r in rows) == (limit + 1) // 2
    assert all(r.published_at == "2026-09-25T00:00:00Z" for r in rows)
    assert all(r.query == REQUEST["query"] for r in rows)
    assert all(p["query"] == ["Claude Code"] for p in client.calls)
    assert all("numericFilters" in p for p in client.calls)


@pytest.mark.parametrize("story_count,comment_count", [(0, 20), (20, 0), (1, 20), (20, 1)])
def test_unused_lane_quota_is_filled(story_count, comment_count):
    client = Client([hit(i) for i in range(story_count)], [hit(i + 100, True) for i in range(comment_count)])
    rows = HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, REQUEST)
    assert len(rows) == min(20, story_count + comment_count)
    assert len({r.source_native_id for r in rows}) == len(rows)


def test_partial_lane_failure_keeps_other_lane_with_disclosure():
    client = Client(HttpTransientError(429, "limited"), [hit(101, True)])
    adapter = HackerNewsAdapter(http_client=client, require_topic_match=True)
    rows = adapter.retrieve(PLAN, REQUEST)
    assert [r.source_native_id for r in rows] == ["101"]
    assert adapter.limitations == ["HN story search failed: AdapterRateLimited"]


def test_both_lanes_rate_limited_preserves_status():
    client = Client(HttpTransientError(429, "limited"), HttpTransientError(429, "limited"))
    with pytest.raises(AdapterRateLimited):
        HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, REQUEST)


@pytest.mark.parametrize("title", ["Ask HN: Who is hiring? (October 2026)", "Ask HN: Who wants to be hired? (October 2026)", "Ask HN: Freelancer? Seeking freelancer? (October 2026)"])
def test_canonical_hiring_noise_is_excluded_for_research(title):
    adapter = HackerNewsAdapter(http_client=Client([], [hit(101, True, title)]), require_topic_match=True)
    assert adapter.retrieve(PLAN, REQUEST) == []
    assert "excluded 1 canonical hiring" in adapter.limitations[0]


def test_explicit_job_intent_retains_hiring_and_ordinary_freelancer_story():
    client = Client([hit(1, title="Ask HN: Freelancer tools with Claude Code")], [hit(101, True, "Ask HN: Who is hiring? (October 2026)")])
    client.lanes["comment"][0]["comment_text"] += "; hiring jobs"
    client.lanes["story"][0]["story_text"] = "Claude Code hiring jobs"
    rows = HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, {**REQUEST, "query": "Claude Code hiring jobs"})
    assert {r.source_native_id for r in rows} == {"1", "101"}


def test_duplicate_cross_lane_hits_do_not_use_two_slots():
    client = Client([hit(1)], [hit(1), hit(101, True)])
    rows = HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, REQUEST)
    assert [r.source_native_id for r in rows] == ["1", "101"]


def test_broader_subject_discovery_keeps_workflow_intent_priority():
    client = Client([hit(1, title="Claude Code in political news"),
                     hit(2, title="Claude Code workflow: plan then review")],
                    [hit(101, True)])
    rows = HackerNewsAdapter(http_client=client, require_topic_match=True).retrieve(PLAN, {**REQUEST, "limit": 2})
    assert rows[0].source_native_id == "2"
    assert rows[1].source_type == "comment"
