"""Phase 6B §13 — code-computed support metrics + confidence ceiling."""
from __future__ import annotations

import pytest

from sourceglint.recommendations.support import (
    compute_support,
    recommendation_confidence_ceiling,
    resolve_support_chain,
)

from ._support_recs import (
    evidence,
    evidence_by_id,
    insight_by_id,
    insight_fact,
)


def _insights():
    a = insight_fact(
        insight_id="ins_fact_1",
        signal_ids=("sig_a",),
        evidence_ids=("ev_1", "ev_2"),
        confidence=0.8,
    )
    b = insight_inf()
    return a, b


def insight_inf():
    return {
        "insight_id": "ins_inf_1",
        "type": "INFERENCE",
        "statement": "individual users appear price sensitive",
        "signal_ids": ["sig_b"],
        "evidence_ids": ["ev_3"],
        "confidence": 0.6,
    }


class TestResolveSupportChain:
    def test_unions_signals_and_evidence(self):
        a, b = _insights()
        ib = insight_by_id(a, b)
        sig, evi = resolve_support_chain(("ins_fact_1", "ins_inf_1"), ib)
        assert set(sig) == {"sig_a", "sig_b"}
        assert set(evi) == {"ev_1", "ev_2", "ev_3"}

    def test_missing_insight_skipped(self):
        a, _ = _insights()
        sig, evi = resolve_support_chain(("ins_fact_1", "ins_missing"), insight_by_id(a))
        assert set(sig) == {"sig_a"}
        assert set(evi) == {"ev_1", "ev_2"}


class TestComputeSupport:
    def test_counts(self):
        a, b = _insights()
        evs = evidence_by_id(
            evidence("ev_1", url="https://a.com/"),
            evidence("ev_2", url="https://a.com/"),
            evidence("ev_3", url="https://b.com/"),
        )
        s = compute_support(("ins_fact_1", "ins_inf_1"), insight_by_id(a, b), evs)
        assert s.supporting_insight_count == 2
        assert s.supporting_signal_count == 2
        assert s.supporting_evidence_count == 3
        # two distinct sources across the chain
        assert s.independent_source_count == 2
        assert s.min_insight_confidence == pytest.approx(0.6)
        assert s.mean_insight_confidence == pytest.approx(0.7)
        assert s.contradiction_present is False
        assert s.weak_signal_present is False

    def test_flags_propagate(self):
        a, b = _insights()
        s = compute_support(
            ("ins_fact_1", "ins_inf_1"),
            insight_by_id(a, b),
            {},
            contradiction_present=True,
            weak_signal_present=True,
        )
        assert s.contradiction_present is True
        assert s.weak_signal_present is True


class TestConfidenceCeiling:
    def test_min_support_times_discount(self):
        c = recommendation_confidence_ceiling([0.8, 0.6], 1)
        assert c == pytest.approx(0.6 * (1 - 0.15))

    def test_higher_distance_lower_ceiling(self):
        assert recommendation_confidence_ceiling([0.8], 2) < recommendation_confidence_ceiling(
            [0.8], 0
        )

    def test_empty_returns_none(self):
        assert recommendation_confidence_ceiling([], 1) is None
