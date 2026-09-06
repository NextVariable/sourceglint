"""Contract tests for output.schema.json.

Final structure the Deterministic Renderer receives (v0.2 §12.2 + PRD §16).
ALL sections are optional — renderer skips empty sections; the schema does NOT
force completeness (an insufficient-evidence run emits a minimal document).
"""

from __future__ import annotations

import pytest

from conftest import validate


def _minimal_output(**overrides):
    out = {
        "executive_intelligence": "Notion price hike is driving SMB churn discussion.",
        "changes": ["Notion raised Team plan price 20%"],
        "key_signals": [
            {
                "signal_id": "sig_pricing_1",
                "type": "INFERENCE",
                "what": "SMB users increasingly mention switching.",
                "why_it_matters": "Price delta is a live churn trigger.",
                "level": "high",
                "gtm_implications": {"pricing": "test SMB retention promo"},
            }
        ],
        "user_voice": [
            {
                "quote": "Too expensive now, looking at alternatives.",
                "evidence_id": "ev_reddit_a1b2c3",
            }
        ],
        "recommended_actions": {
            "now": [{"action": "Verify churn cohort", "insight_id": "ins_rec_1"}],
            "next": [{"action": "Launch SMB promo", "insight_id": "ins_rec_2"}],
            "watch": [],
        },
        "confidence": 0.6,
        "gaps": {
            "sources_unavailable": ["x_api"],
            "uncertain": ["whether price delta persists past 30d"],
        },
        "coverage": {
            "sources_searched": ["reddit", "hackernews", "official_web"],
            "coverage_limitation": "X not reachable this run",
        },
    }
    out.update(overrides)
    return out


# ---------------------------------------------------------------- valid cases

class TestOutputValid:
    def test_full_output(self, output_schema):
        validate(_minimal_output(), output_schema)

    def test_empty_sections_allowed(self, output_schema):
        """v0.2 §12.2: empty chapters are simply not rendered."""
        out = _minimal_output()
        out["user_voice"] = []
        out["recommended_actions"] = {"now": [], "next": [], "watch": []}
        validate(out, output_schema)

    def test_insufficient_evidence_minimal(self, output_schema):
        """The 'Insufficient evidence' path emits an almost-empty document."""
        out = {
            "executive_intelligence": "Insufficient evidence to answer.",
            "confidence": 0.1,
            "gaps": {"uncertain": ["no sources returned usable data"]},
            "coverage": {
                "sources_searched": [],
                "coverage_limitation": "all free sources rate-limited",
            },
        }
        validate(out, output_schema)

    def test_minimal_all_optional_sections_absent(self, output_schema):
        out = {}
        validate(out, output_schema)

    def test_no_competitive_movement_section(self, output_schema):
        """Competitive Movement only present when relevant (no forced sections)."""
        out = _minimal_output()
        del out["key_signals"]
        validate(out, output_schema)


# --------------------------------------------------------------- invalid cases

class TestOutputInvalid:
    def test_wrong_recommended_actions_shape(self, output_schema):
        out = _minimal_output()
        out["recommended_actions"] = {"someday": [{"action": "x"}]}
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_recommended_action_missing_action(self, output_schema):
        out = _minimal_output()
        out["recommended_actions"]["now"] = [{"insight_id": "ins_rec_1"}]
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_user_voice_quote_missing(self, output_schema):
        out = _minimal_output()
        out["user_voice"] = [{"evidence_id": "ev_reddit_a1b2c3"}]
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_user_voice_evidence_id_missing(self, output_schema):
        out = _minimal_output()
        out["user_voice"] = [{"quote": "raw quote without evidence id"}]
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_invalid_signal_level(self, output_schema):
        out = _minimal_output()
        out["key_signals"][0]["level"] = "critical"
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_confidence_out_of_range(self, output_schema):
        out = _minimal_output(confidence=2.0)
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_unknown_property_rejected(self, output_schema):
        out = _minimal_output()
        out["marketing_fluff"] = "unstructured"
        with pytest.raises(Exception):
            validate(out, output_schema)

    def test_executive_intelligence_not_string(self, output_schema):
        out = _minimal_output(executive_intelligence={"nested": True})
        with pytest.raises(Exception):
            validate(out, output_schema)


# -------------------------------------------------------------- boundary cases

class TestOutputBoundary:
    def test_key_signal_minimal(self, output_schema):
        """Key signal without full gtm map is acceptable."""
        out = _minimal_output()
        out["key_signals"] = [
            {"signal_id": "sig_x", "type": "FACT", "what": "X happened.", "level": "medium"}
        ]
        validate(out, output_schema)

    def test_recommended_actions_partial_buckets(self, output_schema):
        out = _minimal_output()
        del out["recommended_actions"]["watch"]
        validate(out, output_schema)

    def test_signal_level_enum(self, output_schema):
        for lvl in ["high", "medium", "weak"]:
            out = _minimal_output()
            out["key_signals"][0]["level"] = lvl
            validate(out, output_schema)

    def test_cross_reference_not_schema_checkable(self, output_schema):
        """user_voice.evidence_id existing in ledger = Phase 2 validator."""
        out = _minimal_output()
        out["user_voice"] = [{"quote": "q", "evidence_id": "ev_missing_zzz"}]
        validate(out, output_schema)  # passes schema by design (boundary doc)
