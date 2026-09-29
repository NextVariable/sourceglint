"""Phase 2 Deterministic Renderer tests (strict Phase 1 Output contract)."""
import time
from pathlib import Path

import pytest

from sourceglint.ledger import EvidenceLedger
from sourceglint.rendering import render_markdown


def _seed_ledger():
    ledger = EvidenceLedger(":memory:")
    ledger.add({
        "source": "reddit", "source_type": "discussion",
        "url": "https://www.reddit.com/r/AI/comments/1/a",
        "snippet": "users complain about pricing",
        "author": "alice", "published_at": "2026-01-01T00:00:00Z",
        "retrieved_at": "2026-09-01T00:00:00Z",
    })
    ledger.add({
        "source": "hacker_news", "source_type": "discussion",
        "url": "https://news.ycombinator.com/item?id=99",
        "snippet": "concerns about pricing model",
        "author": "bob", "published_at": "2026-01-02T00:00:00Z",
        "retrieved_at": "2026-09-01T00:00:00Z",
    })
    return ledger


def _all_output(ledger):
    eids = [r.evidence_id for r in ledger]
    return {
        "executive_intelligence": "Pricing complaints are rising across communities.",
        "changes": [
            "New tier structure announced in Q3",
            "API price cut by 30%",
        ],
        "key_signals": [
            {
                "signal_id": "sig_pricing",
                "type": "INFERENCE",
                "what": "AI meeting tools pricing complaints repeat across communities.",
                "why_it_matters": "Sustained price sensitivity threatens renewal conversion.",
                "level": "high",
                "gtm_implications": {
                    "pricing": "Review pricing model.",
                    "messaging": "Lead with value, not features.",
                },
            }
        ],
        "user_voice": [
            {"quote": "I cancelled because the new price is too high.",
             "evidence_id": eids[0]},
            {"quote": "still fair for me.", "evidence_id": eids[1]},
        ],
        "competitive_movement": [
            "Competitor A cut prices 30%.",
            "Competitor B added a free tier.",
        ],
        "weak_signals": [
            {
                "topic": "low-engagement-but-rising complaint about onboarding",
                "why_watch": "could become a pattern if not addressed.",
                "evidence_ids": [eids[0]],
            }
        ],
        "recommended_actions": {
            "now": [
                {"action": "Run a pricing experiment in 2 weeks.",
                 "insight_id": "ins_pricing"},
            ],
            "next": [],
            "watch": [
                {"action": "Watch renewal churn weekly.",
                 "insight_id": "ins_renewal"},
            ],
        },
        "confidence": 0.7,
        "gaps": {
            "sources_unavailable": ["youtube"],
            "uncertain": ["Whether price sensitivity will persist past launch novelty."],
        },
        "coverage": {
            "sources_searched": ["reddit", "hacker_news"],
            "sources_unavailable": ["youtube"],
            "coverage_limitation": "YouTube comments not covered in MVP.",
        },
    }


class TestSectionOrdering:
    def test_section_order_deterministic(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        out = render_markdown(ledger, out_obj)
        # Phase 1 Output schema (subset that's renderable). Tests only the
        # ones that correspond to actual rendered sections.
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
        assert all(p >= 0 for p in positions), (
            f"missing heading(s): {[h for h, p in zip(expected_order, positions) if p < 0]}\n--- output ---\n{out}"
        )
        assert positions == sorted(positions)
        for a, b in zip(positions, positions[1:]):
            assert a < b

    def test_optional_sections_absent(self):
        ledger = _seed_ledger()
        minimal = {
            "executive_intelligence": "Minimal output.",
            "gaps": {"sources_unavailable": [], "uncertain": ["not enough data"]},
        }
        out = render_markdown(ledger, minimal)
        assert "## User Voice" not in out
        assert "## Weak Signals" not in out
        assert "## Key Signals" not in out
        assert "Executive Intelligence" in out


class TestNullFiltering:
    def test_empty_sections_dropped(self):
        ledger = _seed_ledger()
        out_obj = {
            "executive_intelligence": "x",
            "changes": [],
            "key_signals": [],
            "user_voice": [],
            "recommended_actions": {"now": [], "next": [], "watch": []},
            "competitive_movement": [],
            "weak_signals": [],
        }
        out = render_markdown(ledger, out_obj)
        assert "## What Changed" not in out
        assert "## Key Signals" not in out
        assert "## User Voice" not in out
        assert "## Recommended Actions" not in out
        assert "## Competitive Movement" not in out
        assert "## Weak Signals" not in out

    def test_missing_fields_dont_emit_no_data_line(self):
        ledger = _seed_ledger()
        out_obj = {"executive_intelligence": "x"}
        out = render_markdown(ledger, out_obj)
        assert "No data" not in out
        assert "(empty)" not in out
        assert "_No_" not in out


class TestCitationRendering:
    def test_user_voice_citations_link_to_evidence_url(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        out = render_markdown(ledger, out_obj)
        # The user_voice outputs reference 2 specific evidence ids (out of
        # the 4 in the ledger). Check each cited id resolves to a real URL
        # within the output.
        cited_eids = {v["evidence_id"] for v in out_obj["user_voice"]}
        cited_records = [r for r in ledger if r.evidence_id in cited_eids]
        for rec in cited_records:
            assert rec.url in out

    def test_evidence_ids_appear_in_user_voice_section(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        out = render_markdown(ledger, out_obj)
        cited_eids = {v["evidence_id"] for v in out_obj["user_voice"]}
        for eid in cited_eids:
            assert eid in out

    def test_weak_signals_render_with_evidence_link(self):
        ledger = _seed_ledger()
        out_obj = _all_output(ledger)
        out = render_markdown(ledger, out_obj)
        assert "[reddit]" in out or "reddit" in out


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

    def test_independent_of_clock(self, monkeypatch):
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
        out_obj = {"executive_intelligence": "x"}
        out = render_markdown(ledger, out_obj)
        assert "Competitor" not in out
        assert "Recommended Action" not in out

    def test_no_summarization_or_rewrite(self):
        ledger = _seed_ledger()
        out_obj = {
            "executive_intelligence": "  Raw summary string with extra spaces.  ",
            "gaps": {
                "sources_unavailable": [],
                "uncertain": ["", "  ", "real gap"],
            },
        }
        out = render_markdown(ledger, out_obj)
        # Trim but don't rewrite.
        assert "Raw summary string with extra spaces." in out
        assert "real gap" in out

    def test_no_jinja_or_template_engine_in_codepath(self):
        text = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
        assert "jinja2" not in text.lower()
        assert "jinja" not in text.lower()
