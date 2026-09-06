"""Contract tests for insight.schema.json.

Insight is the unit AFTER reasoning. Structural isolation of:
  FACT | INFERENCE | RECOMMENDATION  (user-confirmed decision)

GTM dimensions expressed as gtm_implications map: key in finite enum
(v0.2 §12.1 frozen example {dimension: text|null}), value string or null.

RECOMMENDATION carries action + priority + optional horizon.
Confidence is canonical 0.0-1.0 across ALL schemas.
"""

from __future__ import annotations

import pytest

from conftest import validate


def _fact(**overrides):
    ins = {
        "insight_id": "ins_fact_1",
        "type": "FACT",
        "statement": "Notion raised Team plan price 20% on 2026-08-01.",
        "signal_ids": ["sig_pricing_1"],
        "evidence_ids": ["ev_web_official1", "ev_reddit_a1b2c3"],
        "confidence": 0.9,
        "gtm_implications": {"pricing": "price anchor raised by competitor"},
        "rationale": "Official pricing page + community confirmation",
    }
    ins.update(overrides)
    return ins


def _inference(**overrides):
    ins = {
        "insight_id": "ins_inf_1",
        "type": "INFERENCE",
        "statement": "Price sensitivity is rising among SMB users.",
        "signal_ids": ["sig_pricing_1", "sig_churn_2"],
        "evidence_ids": ["ev_reddit_a1b2c3", "ev_hn_9f8e7d"],
        "confidence": 0.6,
        "gtm_implications": {
            "pricing": "test SMB tier before next renewal cycle",
            "messaging": None,  # null = assessed, no implication
        },
        "rationale": "Multiple communities report churn after price hike",
    }
    ins.update(overrides)
    return ins


def _recommendation(**overrides):
    ins = {
        "insight_id": "ins_rec_1",
        "type": "RECOMMENDATION",
        "statement": "Run a grandfathering promo for existing SMB plans.",
        "signal_ids": ["sig_pricing_1"],
        "confidence": 0.7,
        "action": {
            "action": "Launch 20% SMB retention promo",
            "priority": "next",
            "horizon": "30d",
        },
        "rationale": "Prevent churn while price delta is salient",
    }
    ins.update(overrides)
    return ins


# ---------------------------------------------------------------- valid cases

class TestInsightValid:
    def test_fact(self, insight_schema):
        validate(_fact(), insight_schema)

    def test_inference(self, insight_schema):
        validate(_inference(), insight_schema)

    def test_recommendation(self, insight_schema):
        validate(_recommendation(), insight_schema)

    def test_minimal_fact(self, insight_schema):
        ins = {
            "insight_id": "ins_fact_min",
            "type": "FACT",
            "statement": "X released feature Y.",
            "confidence": 0.95,
        }
        validate(ins, insight_schema)

    def test_minimal_recommendation(self, insight_schema):
        ins = {
            "insight_id": "ins_rec_min",
            "type": "RECOMMENDATION",
            "statement": "Watch this space.",
            "confidence": 0.5,
            "action": {"action": "Monitor weekly", "priority": "watch"},
        }
        validate(ins, insight_schema)

    def test_gtm_implications_null_value(self, insight_schema):
        """null = dimension assessed but no implication (matches v0.2 example)."""
        validate(_inference(), insight_schema)

    def test_all_dimensions_valid_keys(self, insight_schema):
        """Every frozen GTM dimension key must be expressible."""
        dims = [
            "market", "icp", "pain_point", "product", "positioning",
            "messaging", "pricing", "competitor", "channel", "creator",
            "content", "launch", "localization", "distribution",
            "conversion", "retention",
        ]
        for d in dims:
            validate(_inference(gtm_implications={d: "impact text"}), insight_schema)


# --------------------------------------------------------------- invalid cases

class TestInsightInvalid:
    def test_missing_type(self, insight_schema):
        ins = _fact()
        del ins["type"]
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_invalid_type(self, insight_schema):
        ins = _fact(type="OPINION")
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_recommendation_missing_action(self, insight_schema):
        """RECOMMENDATION without action is structurally incomplete."""
        ins = _recommendation()
        del ins["action"]
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_fact_carrying_action(self, insight_schema):
        """FACT must not carry action (structural isolation)."""
        ins = _fact()
        ins["action"] = {"action": "should not exist", "priority": "now"}
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_confidence_out_of_range(self, insight_schema):
        ins = _fact(confidence=1.5)
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_invalid_gtm_dimension_key(self, insight_schema):
        ins = _inference(gtm_implications={"fiscal_policy": "x"})
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_gtm_implication_non_string_value(self, insight_schema):
        ins = _inference(gtm_implications={"pricing": 123})
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_invalid_action_priority(self, insight_schema):
        ins = _recommendation()
        ins["action"]["priority"] = "someday"
        with pytest.raises(Exception):
            validate(ins, insight_schema)

    def test_unknown_property_rejected(self, insight_schema):
        ins = _fact()
        ins["bogus"] = True
        with pytest.raises(Exception):
            validate(ins, insight_schema)


# -------------------------------------------------------------- boundary cases

class TestInsightBoundary:
    def test_empty_gtm_implications(self, insight_schema):
        """Insufficient-evidence insights may carry no implications."""
        ins = _fact(gtm_implications={})
        validate(ins, insight_schema)

    def test_absent_gtm_implications(self, insight_schema):
        ins = _fact()
        del ins["gtm_implications"]
        validate(ins, insight_schema)

    def test_absent_signal_and_evidence_ids(self, insight_schema):
        ins = _fact()
        del ins["signal_ids"]
        del ins["evidence_ids"]
        validate(ins, insight_schema)

    def test_confidence_zero_and_one(self, insight_schema):
        validate(_fact(confidence=0.0), insight_schema)
        validate(_fact(confidence=1.0), insight_schema)

    def test_evidence_ids_reference_not_schema_checkable(self, insight_schema):
        """insight.evidence_ids existing in ledger = Phase 2 validator concern."""
        ins = _fact(evidence_ids=["ev_missing_zzz"])
        validate(ins, insight_schema)  # passes schema by design (boundary doc)
