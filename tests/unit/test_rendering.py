"""Phase 2 Deterministic Renderer tests (TDD)."""
import re
import time

import pytest

from gtm_intelligence.ledger import EvidenceLedger
from gtm_intelligence.rendering import render_markdown


def _seed_ledger():
    ledger = EvidenceLedger(":memory:")
    ledger.add(
        {
            "source": "reddit",
            "source_type": "discussion",
            "url": "https://www.reddit.com/r/AI/comments/1/a",
            "snippet": "users complain about pricing",
            "author": "alice",
            "published_at": "2026-01-01T00:00:00Z",
            "retrieved_at": "2026-09-01T00:00:00Z",
        }
    )
    ledger.add(
        {
            "source": "hacker_news",
            "source_type": "discussion",
            "url": "https://news.ycombinator.com/item?id=99",
            "snippet": "concerns about pricing model",
            "author": "bob",
            "published_at": "2026-01-02T00:00:00Z",
            "retrieved_at": "2026-09-01T00:00:00Z",
        }
    )
    return ledger


def _all_output(ledger):
    eids = [r.evidence_id for r in ledger]
    return {
        "summary": "Pricing complaints are rising across communities.",
        "changes": [
            {"change": "New tier structure in Q3", "evidence_ids": [eids[0]]},
            {"change": "API price cut by 30%", "evidence_ids": [eids[1]]},
        ],
        "key_signals": [
            {
                "signal_id": "sig_pricing",
                "topic": "AI meeting tools pricing complaints",
                "evidence_ids": eids,
                "score": 0.81,
                "novelty": 0.6,
                "gtm_implications": {"pricing": "Review pricing model."},
                "supporting_evidence_ids": [eids[0]],
                "counter_evidence_ids": [eids[1]],
            }
        ],
        "user_voice": [
            {"text": "I cancelled because the new price is too high.",
             "evidence_id": eids[0], "sentiment": "negative"},
            {"text": "still fair for me.", "evidence_id": eids[1],
             "sentiment": "positive"},
        ],
        "competitive_movement": {
            "summary": "Competitor A cut prices 30%.",
            "evidence_ids": [eids[1]],
        },
        "weak_signals": [
            {
                "topic": "low-engagement-but-rising complaint about onboarding",
                "evidence_ids": [eids[0]],
            }
        ],
        "recommended_actions": [
            {
                "action": "Run a pricing experiment in 2 weeks.",
                "horizon": "Now",
                "priority": "P0",
                "evidence_ids": [eids[0], eids[1]],
            }
        ],
        "confidence": {
            "overall": 0.7,
            "rationale": "Cross-source repetition across 7 days.",
        },
        "gaps": ["No Japanese-market evidence in this run."],
        "coverage": {
            "sources_searched": ["reddit", "hacker_news"],
            "sources_unavailable": [],
        },
    }


class TestSectionOrdering:
    def test_section_order_deterministic(self):
        out = render_markdown(_seed_ledger(), _all_output(_seed_ledger()))
        # Heading order must follow the schema:
        expected_order = [
            "# Executive Intelligence",
            "## What Changed",
            "## Key Signals",
            "## User Voice",
            "## Competitive Movement",
            "## Weak Signals",
            "## Recommended Actions",
            "## Confidence & Gaps",
        ]
        positions = [out.find(h) for h in expected_order]
        # All headings present and sorted ascending.
        assert all(p >= 0 for p in positions)
        assert positions == sorted(positions)
        for a, b in zip(positions, positions[1:]):
            assert a < b

    def test_optional_sections_absent(self):
        ledger = _seed_ledger()
        minimal = {
            "summary": "Minimal output.",
            "gaps": ["Some"],
        }
        out = render_markdown(ledger, minimal)
        assert "## User Voice" not in out
        assert "## Weak Signals" not in out
        assert "## Key Signals" not in out
        # summary still rendered
        assert "Minimal output." in out


class TestNullFiltering:
    def test_empty_sections_dropped(self):
        ledger = _seed_ledger()
        out_obj = {
            "summary": "x",
            "changes": [],          # empty -> dropped
            "key_signals": [],      # empty -> dropped
            "user_voice": [],       # empty -> dropped
            "recommended_actions": [],
        }
        out = render_markdown(ledger, out_obj)
        assert "## What Changed" not in out
        assert "## Key Signals" not in out
        assert "## User Voice" not in out
        assert "## Recommended Actions" not in out

    def test_missing_fields_dont_emit_no_data_line(self):
        ledger = _seed_ledger()
        out_obj = {"summary": "x"}
        out = render_markdown(ledger, out_obj)
        # No "No data" filler text produced by the renderer:
        assert "No data" not in out
        assert "(empty)" not in out
        assert "_No_" not in out


class TestCitationRendering:
    def test_user_voice_citations_link_to_evidence_url(self):
        ledger = _seed_ledger()
        out = render_markdown(ledger, _all_output(ledger))
        rec_url = "https://www.reddit.com/r/AI/comments/1/a"
        # Each user_voice line should carry a markdown link to the URL.
        assert rec_url in out
        assert "https://news.ycombinator.com/item?id=99" in out

    def test_evidence_ids_appear_alongside_changes(self):
        ledger = _seed_ledger()
        out = render_markdown(ledger, _all_output(ledger))
        eids = [r.evidence_id for r in ledger]
        # Citations render the Evidence IDs in markdown.
        for eid in eids:
            assert eid in out


class TestDeterminism:
    def test_byte_stable_on_repeat(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        a = render_markdown(ledger, out_obj)
        b = render_markdown(ledger, out_obj)
        assert a == b

    def test_byte_stable_across_30_runs(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        first = render_markdown(ledger, out_obj)
        for _ in range(30):
            assert render_markdown(ledger, out_obj) == first

    def test_independent_of_clock_and_pid(self, monkeypatch):
        # Renderer MUST NOT touch clock or process id (Phase 2 §22).
        monkeypatch.setattr(time, "time", lambda: 1_700_000_000)
        monkeypatch.setattr(time, "perf_counter", lambda: 1_700_000_000)
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        a = render_markdown(ledger, out_obj)
        monkeypatch.setattr(time, "time", lambda: 9_999_999_999)
        b = render_markdown(ledger, out_obj)
        assert a == b


class TestSemanticNonMutation:
    def test_renderer_does_not_invent_section_evidence(self):
        ledger = _seed_ledger()
        out_obj = {"summary": "x"}
        out = render_markdown(ledger, out_obj)
        # No fake competitive movement when no data.
        assert "Competitor" not in out
        # No fake recommendations when no actions.
        assert "Recommended Action" not in out

    def test_no_summarization_or_rewrite(self):
        ledger = _seed_ledger()
        out_obj = {
            "summary": "  Raw summary string with extra spaces.  ",
            "gaps": ["", "  ", "real gap"],
        }
        out = render_markdown(ledger, out_obj)
        # Trim but don't rewrite content.
        assert "Raw summary string with extra spaces." in out
        # Empty/whitespace gaps dropped; real gap kept.
        assert "real gap" in out

    def test_no_jinja_or_template_engine_in_codepath(self):
        # Implementation must be plain Python (no Jinja2 dependency,
        # none in pyproject.toml deps).
        text = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
        assert "jinja2" not in text.lower()
        assert "jinja" not in text.lower()


# Local hack to avoid pathlib import at module level just for the last test.
from pathlib import Path  # noqa: E402
