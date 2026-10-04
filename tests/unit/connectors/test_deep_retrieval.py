"""Regression cases for previously lost bodies, child identities and freshness."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from sourceglint.connectors._http import HttpResponse
from sourceglint.connectors._deep import issue_results, reddit_archive
from sourceglint.connectors._captions import caption_body
from sourceglint.pipeline.adapters import RawSourceResult
from sourceglint.normalization import normalize_raw, validate_evidence_payload
from sourceglint.intelligence.preparation import prepare_evidence
from sourceglint.insights.preparation import _extract_summary
from sourceglint.ids import canonicalize_url

PLAN = {"time_window": {"start": "2026-09-04T00:00:00Z", "end": "2026-10-04T00:00:00Z"}}
REQUEST = {"query": "Claude Code workflows", "query_language": "en", "market": "global"}


def response(payload):
    return HttpResponse(200, body=json.dumps(payload).encode())


def test_source_tail_survives_normalization_ledger_and_model(tmp_path):
    from sourceglint.ledger import EvidenceLedger

    body = "Intro. " * 100 + "Run the verifier after restarting the failing session."
    raw = RawSourceResult(
        "github",
        "post",
        "1",
        "https://github.com/a/b/issues/1",
        "Session retry",
        body,
        published_at="2026-09-20T00:00:00Z",
    )
    normalized = normalize_raw(raw, as_of="2026-10-04T00:00:00Z")
    validate_evidence_payload(normalized)
    assert len(normalized["snippet"]) <= 280
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl")
    ledger.add(normalized)
    restored = EvidenceLedger(tmp_path / "evidence.jsonl")
    model = prepare_evidence(restored)[0].to_model_payload()
    assert "verifier" in model["content"]
    assert "verifier" in _extract_summary(normalized)


def test_long_body_is_bounded_and_raw_unchanged():
    raw = RawSourceResult(
        "reddit", "post", "1", "https://reddit.com/r/a/comments/1", "Long", "x" * 20000
    )
    normalized = normalize_raw(raw, as_of="2026-10-04T00:00:00Z")
    assert len(normalized["content"]) == 12000
    assert len(prepare_evidence([normalized])[0].to_model_payload()["content"]) == 6000
    assert len(raw.text) == 20000


def test_github_comment_anchors_are_separate_evidence():
    parent = "https://github.com/a/b/issues/1"
    assert canonicalize_url(parent + "#issuecomment-123") != canonicalize_url(
        parent + "#issuecomment-124"
    )
    assert canonicalize_url(parent + "#navigation") == canonicalize_url(parent)


def test_github_comment_own_date_and_old_comment_filtered():
    parent = "https://github.com/a/b/issues/1"

    class Client:
        def request(self, url, **kwargs):
            if "/search/issues?" in url:
                return response(
                    {
                        "items": [
                            {
                                "id": 1,
                                "html_url": parent,
                                "title": "Claude Code workflow",
                                "body": "A concrete recipe",
                                "created_at": "2026-09-10T00:00:00Z",
                                "comments": 2,
                            }
                        ]
                    }
                )
            return response(
                [
                    {
                        "id": 2,
                        "html_url": parent + "#issuecomment-2",
                        "body": "Recent reproduction steps",
                        "created_at": "2026-09-12T00:00:00Z",
                    },
                    {
                        "id": 3,
                        "html_url": parent + "#issuecomment-3",
                        "body": "Old steps",
                        "created_at": "2026-08-12T00:00:00Z",
                    },
                ]
            )

    rows = issue_results(Client(), REQUEST["query"], PLAN, REQUEST, {}, [])
    assert len(rows) == 2
    assert rows[1].published_at == "2026-09-12T00:00:00Z"
    assert rows[1].source_type == "comment"


def test_failed_comments_keep_parent_and_report_gap():
    class Client:
        def request(self, url, **kwargs):
            if "/search/issues?" in url:
                return response(
                    {
                        "items": [
                            {
                                "id": 1,
                                "html_url": "https://github.com/a/b/issues/1",
                                "title": "Claude Code Workflow",
                                "created_at": "2026-09-10T00:00:00Z",
                                "comments": 2,
                            }
                        ]
                    }
                )
            raise TimeoutError()

    gaps = []
    assert len(issue_results(Client(), REQUEST["query"], PLAN, REQUEST, {}, gaps)) == 1
    assert any("comments incomplete" in gap for gap in gaps)


def test_archive_preserves_original_comment_url_and_date():
    stamp = int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp())

    class Client:
        def request(self, url, **kwargs):
            if "/posts/search?" in url:
                return response(
                    {
                        "data": [
                            {
                                "id": "abc",
                                "title": "Claude Code workflow",
                                "selftext": "A long recipe",
                                "author": "maker",
                                "permalink": "/r/ClaudeCode/comments/abc/workflow/",
                                "created_utc": stamp,
                                "num_comments": 2,
                            }
                        ]
                    }
                )
            return response(
                {
                    "data": [
                        {
                            "id": "xyz",
                            "body": "My verified workaround",
                            "author": "user",
                            "created_utc": stamp + 86400,
                        }
                    ]
                }
            )

    rows = reddit_archive(Client(), REQUEST["query"], PLAN, REQUEST, [], [])
    assert len(rows) == 2
    assert rows[1].url.endswith("/abc/workflow/xyz/")
    assert rows[1].published_at == "2026-09-16T00:00:00Z"
    assert rows[1].raw_metadata["archive_observation_not_live_reddit"]


def test_archive_does_not_enrich_unrelated_or_future_rss_items():
    class Client:
        def request(self, url, **kwargs):
            assert "/comments/search" not in url
            return response({"data": []})

    raw = RawSourceResult(
        "reddit",
        "post",
        "t3_abc",
        "https://reddit.com/r/a/comments/abc/",
        "Unrelated",
        "No subject here",
        published_at="2026-10-05T00:00:00Z",
    )
    assert reddit_archive(Client(), REQUEST["query"], PLAN, REQUEST, [raw], []) == []


def test_captions_keep_time_offsets_and_remove_adjacent_repeats():
    body = json.dumps(
        {
            "events": [
                {"tStartMs": 12000, "segs": [{"utf8": "Run tests before merge."}]},
                {"tStartMs": 13000, "segs": [{"utf8": "Run tests before merge."}]},
                {"tStartMs": 14500, "segs": [{"utf8": "Review the diff."}]},
            ]
        }
    ).encode()
    text, segments = caption_body(body, "json3")
    assert text == "[12s] Run tests before merge.\n[14.5s] Review the diff."
    assert len(segments) == 2


def test_recent_comment_on_old_thread_is_retained_without_redating_parent():
    parent = "https://github.com/a/b/issues/1"

    class Client:
        def request(self, url, **kwargs):
            if "/search/issues?" in url:
                if "updated%3A" in url:
                    return response(
                        {
                            "items": [
                                {
                                    "id": 1,
                                    "html_url": parent,
                                    "title": "Claude Code workflow",
                                    "created_at": "2026-08-10T00:00:00Z",
                                    "comments": 91,
                                }
                            ]
                        }
                    )
                return response({"items": []})
            assert "page=4" in url
            return response(
                [
                    {
                        "id": 2,
                        "html_url": parent + "#issuecomment-2",
                        "body": "A new reproducible failure",
                        "created_at": "2026-09-12T00:00:00Z",
                    }
                ]
            )

    rows = issue_results(Client(), REQUEST["query"], PLAN, REQUEST, {}, [])
    assert len(rows) == 1
    assert rows[0].source_type == "comment"
    assert rows[0].published_at == "2026-09-12T00:00:00Z"


def test_popular_but_unrelated_github_thread_gets_no_comment_budget():
    class Client:
        def request(self, url, **kwargs):
            assert "/search/issues?" in url
            return response(
                {
                    "items": [
                        {
                            "id": 1,
                            "html_url": "https://github.com/a/b/issues/1",
                            "title": "Game crash",
                            "body": "An unrelated popular report.",
                            "created_at": "2026-09-10T00:00:00Z",
                            "comments": 300,
                        }
                    ]
                }
            )

    assert issue_results(Client(), REQUEST["query"], PLAN, REQUEST, {}, []) == []


def test_research_topic_reaches_semantic_context():
    from sourceglint.application.orchestrator import build_research_context

    context = build_research_context(
        {"topic": "Claude Code workflows", "mode": "general"}
    )
    assert context.to_dict()["topic"] == "Claude Code workflows"
    assert context.decision_context == ""


def test_batch_model_body_budget_is_bounded_and_omission_explicit():
    from sourceglint.intelligence.dtos import PreparedEvidence
    from sourceglint.intelligence.preparation import model_payloads

    items = [
        PreparedEvidence(
            str(n),
            "github",
            "post",
            "current",
            content="Intro " * 2000 + "Verify before merging.",
        )
        for n in range(100)
    ]
    payloads = model_payloads(items)
    assert sum(len(x["content"]) for x in payloads) <= 48000
    assert all("middle omitted" in x["content"] for x in payloads)
    assert all("Verify before merging." in x["content"] for x in payloads)


def test_month_sampling_keeps_older_posts_when_latest_day_is_busy():
    from urllib.parse import parse_qs, urlparse
    seen = []

    class Client:
        def request(self, url, **kwargs):
            if '/subreddits/search?' in url:
                return response({'data': [{'subreddit': 'ClaudeCode'}]})
            if '/comments/search?' in url:
                return response({'data': []})
            params = parse_qs(urlparse(url).query)
            seen.append(params)
            start = datetime.fromisoformat(params['after'][0].replace('Z', '+00:00'))
            stamp = int(start.timestamp()) + 86400
            return response({'data': [{'id': str(stamp), 'title': 'Claude Code workflow', 'selftext': 'Run a test before review', 'author': 'maker', 'permalink': '/r/ClaudeCode/comments/' + str(stamp) + '/', 'created_utc': stamp, 'num_comments': 100 if start.day > 20 else 1}]})

    rows = reddit_archive(Client(), REQUEST['query'], PLAN, REQUEST, [], [], limit=4)
    assert len(rows) == 4
    assert len({r.published_at[:10] for r in rows}) == 4
    assert any(r.published_at < '2026-09-12' for r in rows)
    assert all('after' in p and 'before' in p for p in seen)


def test_hn_topic_filter_rejects_search_hits_without_visible_subject():
    from sourceglint.connectors.hacker_news import HackerNewsAdapter

    class Client:
        def request(self, url, **kwargs):
            return response({'hits': [
                {'objectID': '1', 'title': 'Obsidian plugin for notes', 'created_at_i': 1789603200},
                {'objectID': '2', 'title': 'Pizza Bot for agents', 'created_at_i': 1789603200},
            ]})

    rows = HackerNewsAdapter(http_client=Client(), require_topic_match=True).retrieve(PLAN, {'query': 'Obsidian plugins'})
    assert [r.source_native_id for r in rows] == ['1']


def test_archive_keyword_timeout_falls_back_within_requested_window():
    from urllib.parse import parse_qs, urlparse
    from sourceglint.connectors._http import HttpPermanentError
    calls = []

    class Client:
        def request(self, url, **kwargs):
            if '/subreddits/search?' in url:
                return response({'data': [{'subreddit': 'ObsidianMD'}]})
            if '/comments/search?' in url:
                return response({'data': []})
            params = parse_qs(urlparse(url).query)
            calls.append(params)
            if 'query' in params:
                raise HttpPermanentError(422, url)
            stamp = int(datetime.fromisoformat(params['after'][0].replace('Z', '+00:00')).timestamp()) + 86400
            return response({'data': [{'id': str(stamp), 'title': 'Obsidian plugins', 'author': 'maker', 'permalink': '/r/ObsidianMD/comments/' + str(stamp) + '/', 'created_utc': stamp}]})

    gaps = []
    rows = reddit_archive(Client(), 'Obsidian plugins', PLAN, {'query': 'Obsidian plugins'}, [], gaps, limit=4)
    assert len(rows) == 4
    assert any('filtered community sample' in gap for gap in gaps)
    assert any('query' not in p for p in calls)
    assert all('after' in p and 'before' in p for p in calls)


def test_exact_observed_community_is_not_displaced_by_broader_prefix_matches():
    from urllib.parse import parse_qs, urlparse
    queried = []

    class Client:
        def request(self, url, **kwargs):
            if '/subreddits/search?' in url:
                return response({'data': [{'subreddit': x} for x in ['ClaudeAI', 'ClaudeMCP', 'ClaudeGTM']]})
            if '/posts/search?' in url:
                queried.extend(parse_qs(urlparse(url).query)['subreddit'])
            return response({'data': []})

    raw = RawSourceResult('reddit', 'post', 't3_a', 'https://reddit.com/r/ClaudeCode/comments/a/', 'Claude Code workflow', 'Review and test', published_at='2026-09-15T00:00:00Z', raw_metadata={'subreddit': 'ClaudeCode'})
    reddit_archive(Client(), REQUEST['query'], PLAN, REQUEST, [raw], [])
    assert 'ClaudeCode' in queried
    assert len(set(queried)) <= 3


def test_month_selection_does_not_spend_all_slots_on_one_busy_day():
    from urllib.parse import parse_qs, urlparse

    class Client:
        def request(self, url, **kwargs):
            if '/subreddits/search?' in url or '/comments/search?' in url:
                return response({'data': []})
            p = parse_qs(urlparse(url).query)
            start = int(datetime.fromisoformat(p['after'][0].replace('Z', '+00:00')).timestamp())
            return response({'data': [
                {'id': str(start) + str(i), 'title': 'Claude Code workflow', 'author': 'user',
                 'created_utc': start + (86400 if i < 3 else 172800),
                 'permalink': '/r/ClaudeCode/comments/' + str(start) + str(i) + '/',
                 'num_comments': 100 if i < 3 else 1}
                for i in range(4)
            ]})

    rows = reddit_archive(Client(), REQUEST['query'], PLAN, REQUEST, [], [], limit=8)
    assert len(rows) == 8
    assert len({r.published_at[:10] for r in rows}) == 8


def test_community_prefix_collision_does_not_query_minecraft_for_mcp():
    from urllib.parse import parse_qs, urlparse
    queried = []

    class Client:
        def request(self, url, **kwargs):
            if '/subreddits/search?' in url:
                return response({'data': [
                    {'subreddit': 'MCPE', 'description': 'Minecraft Pocket Edition'},
                    {'subreddit': 'MCPServers', 'description': 'MCP model context protocol servers'},
                ]})
            if '/posts/search?' in url:
                queried.extend(parse_qs(urlparse(url).query)['subreddit'])
            return response({'data': []})

    reddit_archive(Client(), 'MCP security', PLAN, {'query': 'MCP security'}, [], [])
    assert 'MCPE' not in queried
    assert 'MCP' in queried
    assert 'MCPServers' in queried
