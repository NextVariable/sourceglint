"""Phase 6A §4, §23 — insight schema validation unit tests (Gate B).

Two layers:
  * validate_insight_schema()                 — fast code-side mirror
  * validate_insight_against_frozen_schema()  — authoritative jsonschema
                                                check against the real
                                                schemas/insight.schema.json
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.validation import (
    INSIGHT_SCHEMA_KEYS,
    validate_insight_against_frozen_schema,
    validate_insight_schema,
)

FACT = {
    "insight_id": "ins_ab12cd34",
    "type": "FACT",
    "statement": "The vendor's pricing page lists the Team plan at $20 per user per month.",
    "signal_ids": ["sig_pricing"],
    "evidence_ids": ["ev_1"],
    "confidence": 0.9,
    "rationale": "First-party pricing page",
    "gtm_implications": {"pricing": "The official price anchor moved upward"},
}

INFERENCE = {
    "insight_id": "ins_ef56gh78",
    "type": "INFERENCE",
    "statement": "Value pressure may be increasing among individual users.",
    "signal_ids": ["sig_pricing", "sig_alternatives"],
    "evidence_ids": ["ev_1", "ev_3"],
    "confidence": 0.55,
    "rationale": "Price complaints plus free-alternative mentions",
}


class TestValidInsights:
    def test_fact_passes(self):
        assert validate_insight_schema(FACT) == []

    def test_inference_passes(self):
        assert validate_insight_schema(INFERENCE) == []

    def test_minimal_insight_passes(self):
        minimal = {
            "insight_id": "ins_1",
            "type": "FACT",
            "statement": "One source reports a change.",
            "confidence": 0.5,
        }
        assert validate_insight_schema(minimal) == []

    def test_null_gtm_implication_passes(self):
        """§25: null = dimension assessed, no implication."""
        ins = dict(FACT, gtm_implications={"pricing": None, "icp": None})
        assert validate_insight_schema(ins) == []


class TestActionBoundary:
    def test_fact_with_action_rejected(self):
        ins = dict(FACT, action={"action": "Lower the price", "priority": "now"})
        violations = validate_insight_schema(ins)
        assert any("must not carry action" in v for v in violations)

    def test_inference_with_action_rejected(self):
        ins = dict(INFERENCE, action={"action": "Target enterprise", "priority": "next"})
        violations = validate_insight_schema(ins)
        assert any("must not carry action" in v for v in violations)

    def test_recommendation_without_action_rejected(self):
        ins = {
            "insight_id": "ins_rec1",
            "type": "RECOMMENDATION",
            "statement": "We should launch a cheaper tier.",
            "confidence": 0.8,
        }
        violations = validate_insight_schema(ins)
        assert any("RECOMMENDATION must carry action" in v for v in violations)

    def test_recommendation_with_action_passes_structure(self):
        """RECOMMENDATION is out of Phase 6A scope but schema-legal."""
        ins = {
            "insight_id": "ins_rec2",
            "type": "RECOMMENDATION",
            "statement": "Launch a cheaper tier.",
            "confidence": 0.8,
            "action": {"action": "Launch a $9 tier", "priority": "now"},
        }
        assert validate_insight_schema(ins) == []


class TestStructuralViolations:
    def test_missing_required_keys(self):
        violations = validate_insight_schema({"type": "FACT"})
        assert any("missing required key" in v for v in violations)

    def test_unknown_key_rejected(self):
        ins = dict(FACT, recommended_actions=["do thing"])
        violations = validate_insight_schema(ins)
        assert any("keys outside insight.schema.json" in v for v in violations)

    def test_bad_insight_id(self):
        violations = validate_insight_schema(dict(FACT, insight_id="BAD ID!"))
        assert any("ins_ pattern" in v for v in violations)

    def test_unknown_type(self):
        violations = validate_insight_schema(dict(FACT, type="OPINION"))
        assert any("unknown type" in v for v in violations)

    def test_confidence_out_of_range(self):
        assert validate_insight_schema(dict(FACT, confidence=1.5))
        assert validate_insight_schema(dict(FACT, confidence=-0.1))

    def test_confidence_not_a_number(self):
        violations = validate_insight_schema(dict(FACT, confidence="high"))
        assert any("confidence not a number" in v for v in violations)

    def test_empty_statement_rejected(self):
        violations = validate_insight_schema(dict(FACT, statement="   "))
        assert any("statement must be non-empty" in v for v in violations)

    def test_unknown_gtm_dimension_rejected(self):
        ins = dict(FACT, gtm_implications={"vibes": "Something"})
        violations = validate_insight_schema(ins)
        assert any("unknown GTM dimension" in v for v in violations)

    def test_schema_keys_match_frozen_set(self):
        assert INSIGHT_SCHEMA_KEYS == frozenset({
            "insight_id", "type", "statement", "signal_ids", "evidence_ids",
            "confidence", "gtm_implications", "rationale", "action",
        })


class TestFrozenJsonSchema:
    """Authoritative Gate B: real schemas/insight.schema.json."""

    def test_fact_passes_real_schema(self):
        assert validate_insight_against_frozen_schema(FACT) == []

    def test_inference_passes_real_schema(self):
        assert validate_insight_against_frozen_schema(INFERENCE) == []

    def test_recommendation_without_action_fails_real_schema(self):
        ins = {
            "insight_id": "ins_rec3",
            "type": "RECOMMENDATION",
            "statement": "Launch a cheaper tier.",
            "confidence": 0.8,
        }
        assert validate_insight_against_frozen_schema(ins)

    def test_fact_with_action_fails_real_schema(self):
        ins = dict(FACT, action={"action": "Lower price", "priority": "now"})
        assert validate_insight_against_frozen_schema(ins)

    def test_unknown_key_fails_real_schema(self):
        ins = dict(FACT, recommended_actions=["x"])
        assert validate_insight_against_frozen_schema(ins)

    def test_bad_gtm_dimension_fails_real_schema(self):
        ins = dict(FACT, gtm_implications={"vibes": "x"})
        assert validate_insight_against_frozen_schema(ins)

    def test_confidence_above_one_fails_real_schema(self):
        assert validate_insight_against_frozen_schema(dict(FACT, confidence=2.0))

    def test_identical_signal_ids_fail_unique_items(self):
        ins = dict(FACT, signal_ids=["sig_1", "sig_1"])
        assert validate_insight_against_frozen_schema(ins)


if __name__ == "__main__":
    pytest.main([__file__])
