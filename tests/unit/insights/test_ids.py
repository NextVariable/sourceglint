"""Phase 6A §21 — deterministic Insight IDs.

Insight identity is derived by CODE from structural inputs — never from
a model statement. Two runs that build an insight from the same type +
signal set + evidence set get the same insight_id even if the model words
the statement differently (PRD §21).

ID composition (PRD §21):
  type           — FACT and INFERENCE are different identities
  sorted signal_ids
  sorted evidence_ids

Statement text is deliberately excluded so that minor wording variation
does not cause ID drift.
"""
from __future__ import annotations

import re

import pytest

from gtm_intelligence.insights.ids import (
    derive_insight_id,
    is_valid_insight_id,
)

_ID_RE = re.compile(r"^ins_[a-z0-9_]{1,64}$")


class TestDeriveInsightId:
    def test_basic_fact_id(self):
        sid = derive_insight_id(
            type="FACT",
            signal_ids=["sig_abc"],
            evidence_ids=["ev_001", "ev_002"],
        )
        assert sid.startswith("ins_")
        assert _ID_RE.match(sid)

    def test_basic_inference_id(self):
        sid = derive_insight_id(
            type="INFERENCE",
            signal_ids=["sig_abc", "sig_def"],
            evidence_ids=["ev_001"],
        )
        assert sid.startswith("ins_")
        assert _ID_RE.match(sid)

    def test_deterministic_same_inputs(self):
        kwargs = dict(
            type="FACT",
            signal_ids=["sig_b", "sig_a"],
            evidence_ids=["ev_002", "ev_001"],
        )
        assert derive_insight_id(**kwargs) == derive_insight_id(**kwargs)

    def test_order_independent(self):
        """Signal/evidence ordering must not affect the ID (PRD §21)."""
        a = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a", "sig_b"],
            evidence_ids=["ev_1", "ev_2"],
        )
        b = derive_insight_id(
            type="FACT",
            signal_ids=["sig_b", "sig_a"],
            evidence_ids=["ev_2", "ev_1"],
        )
        assert a == b

    def test_different_type_different_id(self):
        """FACT and INFERENCE over the same evidence are different insights."""
        fact = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        inf = derive_insight_id(
            type="INFERENCE",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        assert fact != inf

    def test_different_signal_ids_different_id(self):
        a = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        b = derive_insight_id(
            type="FACT",
            signal_ids=["sig_b"],
            evidence_ids=["ev_1"],
        )
        assert a != b

    def test_different_evidence_ids_different_id(self):
        a = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        b = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_2"],
        )
        assert a != b

    def test_statement_not_in_hash(self):
        """Statement wording variation must NOT change the ID.

        The model may rephrase; the structural identity is stable.
        (PRD §21: 'if statement varies slightly, prefer stable
        structural inputs')
        """
        base = dict(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        # The function does not even accept a statement parameter.
        id1 = derive_insight_id(**base)
        id2 = derive_insight_id(**base)
        assert id1 == id2

    def test_empty_signal_ids_raises(self):
        with pytest.raises(ValueError):
            derive_insight_id(
                type="FACT",
                signal_ids=[],
                evidence_ids=["ev_1"],
            )

    def test_empty_evidence_ids_raises(self):
        with pytest.raises(ValueError):
            derive_insight_id(
                type="FACT",
                signal_ids=["sig_a"],
                evidence_ids=[],
            )

    def test_dedup_of_duplicate_signal_ids(self):
        """Duplicate signal_ids are deduped before hashing."""
        a = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a", "sig_a"],
            evidence_ids=["ev_1"],
        )
        b = derive_insight_id(
            type="FACT",
            signal_ids=["sig_a"],
            evidence_ids=["ev_1"],
        )
        assert a == b

    def test_id_body_length_within_schema(self):
        """common.schema.json: ins_[a-z0-9_]{1,64}."""
        sid = derive_insight_id(
            type="INFERENCE",
            signal_ids=["sig_" + "x" * 30, "sig_" + "y" * 30],
            evidence_ids=["ev_" + "z" * 30],
        )
        body = sid[len("ins_"):]
        assert 1 <= len(body) <= 64


class TestIsValidInsightId:
    def test_valid(self):
        assert is_valid_insight_id("ins_abc123")

    def test_valid_underscore(self):
        assert is_valid_insight_id("ins_a_b_c_1")

    def test_missing_prefix(self):
        assert not is_valid_insight_id("abc123")

    def test_wrong_prefix(self):
        assert not is_valid_insight_id("sig_abc")

    def test_empty(self):
        assert not is_valid_insight_id("")

    def test_uppercase_rejected(self):
        assert not is_valid_insight_id("ins_Abc")
