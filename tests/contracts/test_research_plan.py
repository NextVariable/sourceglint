"""Contract tests for research_plan.schema.json.

Derived from v0.2 §7 (Research Pipeline) + PRD §4/§14 + D3 language fields.

A Research Plan describes ONE research task: topic / entities / market / languages /
time window / decision context / mode / evidence types / queries / source priorities.
Modes: general | trend | competitor | market | voc | launch | channel.
Time window must support custom (start/end ISO timestamps).
"""

from __future__ import annotations

import pytest

from conftest import validate


def _minimal_plan(**overrides):
    plan = {
        "topic": "AI meeting note products",
        "entities": ["notion", "granola"],
        "market": "global",
        "locale": "en-US",
        "languages": ["en"],
        "time_window": {"days": 30},
        "decision_context": "evaluating whether to enter meeting-notes category",
        "mode": "trend",
        "required_evidence_types": ["T2_community", "T1_official"],
        "queries": ["notion ai meeting notes", "granola launch"],
        "source_priorities": ["reddit", "hackernews", "official_web"],
    }
    plan.update(overrides)
    return plan


# ---------------------------------------------------------------- valid cases

class TestPlanValid:
    def test_full_plan(self, research_plan_schema):
        validate(_minimal_plan(), research_plan_schema)

    def test_minimal_required_only(self, research_plan_schema):
        plan = {
            "topic": "notion pricing",
            "mode": "competitor",
            "time_window": {"days": 14},
        }
        validate(plan, research_plan_schema)

    def test_custom_time_window_start_end(self, research_plan_schema):
        plan = _minimal_plan(
            time_window={
                "start": "2026-07-01T00:00:00Z",
                "end": "2026-09-01T00:00:00Z",
            }
        )
        validate(plan, research_plan_schema)

    def test_all_seven_modes(self, research_plan_schema):
        for mode in ["general", "trend", "competitor", "market", "voc", "launch", "channel"]:
            validate(_minimal_plan(mode=mode), research_plan_schema)

    def test_multilingual_plan(self, research_plan_schema):
        """D3: bilingual research for Japan market."""
        plan = _minimal_plan(
            market="jp",
            locale="ja-JP",
            languages=["en", "ja"],
            queries=["AI translation app", "AI翻訳 アプリ"],
        )
        validate(plan, research_plan_schema)

    def test_single_entity(self, research_plan_schema):
        plan = _minimal_plan(entities=["notion"])
        validate(plan, research_plan_schema)

    def test_no_entities(self, research_plan_schema):
        """Topic-only research (open market scan) is allowed."""
        plan = _minimal_plan()
        del plan["entities"]
        validate(plan, research_plan_schema)


# --------------------------------------------------------------- invalid cases

class TestPlanInvalid:
    def test_missing_topic(self, research_plan_schema):
        plan = _minimal_plan()
        del plan["topic"]
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)

    def test_invalid_mode(self, research_plan_schema):
        plan = _minimal_plan(mode="social_listening")
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)

    def test_invalid_time_window_days_zero(self, research_plan_schema):
        plan = _minimal_plan(time_window={"days": 0})
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)

    def test_invalid_time_window_both_forms(self, research_plan_schema):
        """days and start/end are mutually exclusive by schema shape."""
        plan = _minimal_plan(
            time_window={"days": 30, "start": "2026-07-01T00:00:00Z"}
        )
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)

    def test_custom_window_end_before_start_not_schema_checkable(self, research_plan_schema):
        """Ordering semantics belong to validator (Phase 2), not schema."""
        plan = _minimal_plan(
            time_window={
                "start": "2026-09-01T00:00:00Z",
                "end": "2026-07-01T00:00:00Z",
            }
        )
        validate(plan, research_plan_schema)  # passes schema; validator catches later

    def test_unknown_property_rejected(self, research_plan_schema):
        plan = _minimal_plan()
        plan["hallucinated_param"] = True
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)

    def test_invalid_required_evidence_type(self, research_plan_schema):
        plan = _minimal_plan(required_evidence_types=["T5_meme"])  # tier 5 does not exist
        with pytest.raises(Exception):
            validate(plan, research_plan_schema)


# -------------------------------------------------------------- boundary cases

class TestPlanBoundary:
    def test_long_custom_window(self, research_plan_schema):
        plan = _minimal_plan(time_window={"days": 365})
        validate(plan, research_plan_schema)

    def test_empty_queries_allowed(self, research_plan_schema):
        """Query expansion has not run yet; queries may be empty."""
        plan = _minimal_plan(queries=[])
        validate(plan, research_plan_schema)

    def test_empty_source_priorities_allowed(self, research_plan_schema):
        """Source priorities default to sources.yaml order."""
        plan = _minimal_plan()
        del plan["source_priorities"]
        validate(plan, research_plan_schema)
