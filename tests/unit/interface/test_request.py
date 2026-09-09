"""Phase 7 §9–§10 — SkillRequest / ParsedRequest contract tests."""
from __future__ import annotations

import pytest

from gtm_intelligence.interface.request import (
    MODES,
    ParsedRequest,
    SkillRequest,
    window_text_for,
)


class TestSkillRequestValidation:
    def test_query_required(self):
        with pytest.raises(ValueError):
            SkillRequest(query="")
        with pytest.raises(ValueError):
            SkillRequest(query="   ")

    def test_mode_must_be_known(self):
        with pytest.raises(ValueError):
            SkillRequest(query="x", mode="hyperdrive")

    def test_all_modes_constructible(self):
        for mode in MODES:
            SkillRequest(query="q", mode=mode)

    def test_window_days_bounds(self):
        with pytest.raises(ValueError):
            SkillRequest(query="x", window_days=0)
        with pytest.raises(ValueError):
            SkillRequest(query="x", window_days=366)
        SkillRequest(query="x", window_days=30)


class TestParsedRequestPlan:
    def test_plan_shape_minimal(self):
        parsed = ParsedRequest(
            query="What changed recently?",
            mode="general",
            market="global",
            languages=("en",),
            time_window={"days": 30},
            time_window_text="Last 30 days",
            entities=(),
        )
        plan = parsed.to_plan()
        assert plan["topic"] == "What changed recently?"
        assert plan["mode"] == "general"
        assert plan["time_window"] == {"days": 30}
        # only schema-declared keys (§9 — additionalProperties false)
        assert set(plan) <= {
            "topic", "mode", "time_window", "market", "languages",
            "entities", "decision_context", "source_priorities",
        }

    def test_plan_omits_global_market(self):
        parsed = ParsedRequest(
            query="q", mode="market", market="global",
            languages=("en",), time_window={"days": 7},
            time_window_text="Last 7 days", entities=("Notion",),
        )
        plan = parsed.to_plan()
        assert "market" not in plan
        assert plan["entities"] == ["Notion"]

    def test_plan_keeps_market_and_languages(self):
        parsed = ParsedRequest(
            query="q", mode="market", market="jp",
            languages=("en", "ja"), time_window={"days": 30},
            time_window_text="Last 30 days", entities=(),
        )
        plan = parsed.to_plan()
        assert plan["market"] == "jp"
        assert plan["languages"] == ["en", "ja"]

    def test_baseline_not_leaked_into_plan(self):
        # baseline is a signal-layer flag, not a research_plan field (§9).
        parsed = ParsedRequest(
            query="q", mode="general", market="global",
            languages=("en",), time_window={"days": 30},
            time_window_text="Last 30 days", entities=(), baseline=True,
        )
        assert "baseline" not in parsed.to_plan()

    def test_clarification_flag_surface(self):
        parsed = ParsedRequest(
            query="Research competitors.", mode="competitor",
            market="global", languages=("en",), time_window={"days": 30},
            time_window_text="Last 30 days", entities=(),
            needs_clarification=True, clarification_reason="no target",
        )
        assert parsed.clarification_required
        as_clar = parsed.as_clarification("still missing")
        assert as_clar.needs_clarification
        assert as_clar.clarification_reason == "still missing"


class TestWindowText:
    def test_days(self):
        assert window_text_for({"days": 30}) == "Last 30 days"

    def test_custom_range(self):
        out = window_text_for(
            {"start": "2026-01-01T00:00:00Z", "end": "2026-03-31T00:00:00Z"}
        )
        assert out == "2026-01-01 to 2026-03-31"
