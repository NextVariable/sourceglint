"""Contract tests for signal.schema.json.

A Signal Cluster is the unit formed AFTER dedup + semantic clustering.
Expresses: single-source / cross-source / repeated / emerging / contradictory.

signal_type is a single enum classification (user-confirmed decision):
  single_source | cross_source | repeated | emerging | contradictory
Contradictory signals MUST carry counter_evidence_ids (test-locked semantics).
"""

from __future__ import annotations

import pytest

from conftest import validate


def _minimal_signal(**overrides):
    sig = {
        "signal_id": "sig_reddit_pricing_complaint",
        "topic": "notion pricing too high",
        "evidence_ids": ["ev_reddit_a1b2c3", "ev_hn_9f8e7d"],
        "representative_evidence_ids": ["ev_reddit_a1b2c3"],
        "source_diversity": 2,
        "volume": 14,
        "recency": 0.8,
        "signal_type": "cross_source",
        "novelty": 0.4,
        "score": 0.72,
        "confidence": 0.85,
        "supporting_evidence_ids": ["ev_reddit_a1b2c3", "ev_hn_9f8e7d"],
        "counter_evidence_ids": [],
    }
    sig.update(overrides)
    return sig


# ---------------------------------------------------------------- valid cases

class TestSignalValid:
    def test_full_signal(self, signal_schema):
        validate(_minimal_signal(), signal_schema)

    def test_minimal_required(self, signal_schema):
        sig = {
            "signal_id": "sig_single_1",
            "topic": "new launch",
            "evidence_ids": ["ev_web_a1b2c3d4e5f6"],
            "signal_type": "single_source",
        }
        validate(sig, signal_schema)

    def test_single_source(self, signal_schema):
        validate(_minimal_signal(signal_type="single_source", source_diversity=1),
                 signal_schema)

    def test_repeated(self, signal_schema):
        validate(_minimal_signal(signal_type="repeated", source_diversity=1, volume=42),
                 signal_schema)

    def test_emerging(self, signal_schema):
        validate(_minimal_signal(signal_type="emerging", novelty=1.0), signal_schema)

    def test_contradictory_with_counter(self, signal_schema):
        """Contradictory REQUIRES counter evidence (semantic rule)."""
        validate(
            _minimal_signal(
                signal_type="contradictory",
                counter_evidence_ids=["ev_web_counter1"],
            ),
            signal_schema,
        )

    def test_no_representative_ids(self, signal_schema):
        sig = _minimal_signal()
        del sig["representative_evidence_ids"]
        validate(sig, signal_schema)


# --------------------------------------------------------------- invalid cases

class TestSignalInvalid:
    def test_missing_signal_id(self, signal_schema):
        sig = _minimal_signal()
        del sig["signal_id"]
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_missing_topic(self, signal_schema):
        sig = _minimal_signal()
        del sig["topic"]
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_missing_evidence_ids(self, signal_schema):
        sig = _minimal_signal()
        del sig["evidence_ids"]
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_empty_evidence_ids(self, signal_schema):
        sig = _minimal_signal(evidence_ids=[])
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_contradictory_without_counter(self, signal_schema):
        """signal_type=contradictory with empty counter_evidence_ids is invalid."""
        sig = _minimal_signal(signal_type="contradictory", counter_evidence_ids=[])
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_invalid_signal_type(self, signal_schema):
        sig = _minimal_signal(signal_type="viral")  # not in enum
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_score_out_of_range(self, signal_schema):
        sig = _minimal_signal(score=1.2)
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_negative_volume(self, signal_schema):
        sig = _minimal_signal(volume=-1)
        with pytest.raises(Exception):
            validate(sig, signal_schema)

    def test_unknown_property_rejected(self, signal_schema):
        sig = _minimal_signal()
        sig["extra"] = True
        with pytest.raises(Exception):
            validate(sig, signal_schema)


# -------------------------------------------------------------- boundary cases

class TestSignalBoundary:
    def test_zero_score(self, signal_schema):
        validate(_minimal_signal(score=0.0), signal_schema)

    def test_zero_volume(self, signal_schema):
        validate(_minimal_signal(volume=0), signal_schema)

    def test_no_counter_field_absent_ok(self, signal_schema):
        """Absent counter_evidence_ids means 'no counter found' (not contradictory)."""
        sig = _minimal_signal()
        del sig["counter_evidence_ids"]
        validate(sig, signal_schema)

    def test_no_supporting_field_absent_ok(self, signal_schema):
        sig = _minimal_signal()
        del sig["supporting_evidence_ids"]
        validate(sig, signal_schema)

    def test_evidence_id_cross_reference_not_schema_checkable(self, signal_schema):
        """evidence_ids pointing to non-existent ledger entries is a validator
        concern (Phase 2), NOT a schema concern. Documents the boundary."""
        sig = _minimal_signal(evidence_ids=["ev_nonexistent_zzz"])
        validate(sig, signal_schema)  # passes schema by design
