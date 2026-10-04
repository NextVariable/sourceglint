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
