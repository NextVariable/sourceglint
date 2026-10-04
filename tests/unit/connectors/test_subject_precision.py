"""Reject incidental keyword hits without discarding real topic observations."""
from datetime import datetime, timezone

import pytest

from sourceglint.connectors._deep import reddit_archive, subject_present
from sourceglint.connectors._http import HttpResponse
from sourceglint.pipeline.adapters import RawSourceResult
import json


@pytest.mark.parametrize("query,text,expected", [
    ("AI meeting assistants complaints", "AI meeting assistant misses action items", True),
    ("AI meeting assistants complaints", "AI in football games: assistants attend meetings", True),
    ("AI meeting assistants complaints", "A football manager meeting with a chairman", False),
    ("AI meeting assistants complaints", "Paid assistants and meeting agenda", False),
    ("MCP security", "MCP security scanner reports a finding", True),
    ("MCP security", "MCPE game security", False),
    ("Claude-Code workflows", "Claude Code: a workflow", True),
    ("Claude Code workflows", "Claude coding agent", False),
    ("Obsidian plugins", "Obsidian plugin for daily notes", True),
    ("AI 議事録", "AIで議事録を作る", True),
    ("AI 議事録", "AI assistant for a football game", False),
    ("安全 漏洞", "这是安全漏洞的独立分析", True),
    ("AI meeting assistants complaints", "AI " + "unrelated text " * 80 + "meeting assistants", False),
    ("AI meeting assistants complaints", "AI " + "details " * 8 + "meeting assistants", True),
    ("AI meeting assistants complaints", "AI-managed football clubs " + "simulation " * 30 + "assistant manager meeting", False),
])
def test_subject_match_is_a_lexical_gate(query, text, expected):
    # All words is a lexical floor, not proof of semantic relevance. The
    # deliberately cross-context AI example remains a model-level rejection.
    assert subject_present({"body": text}, query) is expected


def test_reddit_archive_checks_the_whole_subject_on_rss_and_archive_routes():
    stamp = int(datetime(2026, 9, 16, tzinfo=timezone.utc).timestamp())
    rows = [
        {"id": "bad", "title": "Football meeting with AI simulation", "selftext": "No note-taking tools here"},
        {"id": "good", "title": "AI meeting assistant misses action items", "selftext": "One user reports missing tasks."},
        {"id": "cjk", "title": "AI assistant unrelated", "selftext": "No Japanese minutes content"},
    ]
    class Client:
        def request(self, url, **kwargs):
            if "/subreddits/" in url or "/comments/" in url:
                return HttpResponse(200, body=b'{"data":[]}')
            data = [{**row, "author": "user", "created_utc": stamp,
                     "permalink": f"/r/AI/comments/{row['id']}/post/"} for row in rows]
            return HttpResponse(200, body=json.dumps({"data": data}).encode())
    parent = RawSourceResult("reddit", "post", "t3_bad-rss", "https://reddit.com/r/AI/comments/bad-rss/",
                             "Football AI meeting", "Unrelated simulation", published_at="2026-09-16T00:00:00Z")
    result = reddit_archive(Client(), "AI meeting assistants complaints",
                            {"time_window": {"days": 30}},
                            {"retrieved_at": "2026-10-05T00:00:00Z", "subreddits": ["AI"]}, [parent], [])
    assert [r.source_native_id for r in result] == ["t3_good"]


def test_reddit_non_ascii_subject_is_not_reduced_to_ai():
    class Client:
        def request(self, url, **kwargs):
            return HttpResponse(200, body=b'{"data":[]}')
    parent = RawSourceResult("reddit", "post", "t3_bad", "https://reddit.com/r/AI/comments/bad/",
                             "AI football game", "An unrelated assistant", published_at="2026-09-16T00:00:00Z")
    assert reddit_archive(Client(), "AI 議事録", {"time_window": {"days": 30}},
                          {"retrieved_at": "2026-10-05T00:00:00Z"}, [parent], []) == []
