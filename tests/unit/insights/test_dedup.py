"""Phase 6A §22 — insight deduplication.

Detects semantic duplicates via:
1. structural overlap (same signal_ids + evidence_ids)
2. signal overlap (>50% signal_id overlap)
3. model semantic judgment (optional, code-validated)

Not string similarity only (§22). For MVP, structural + signal overlap
is the primary mechanism; model semantic dedup is optional.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.dedup import (
    deduplicate_insights,
    _signal_overlap,
    DedupResult,
)


def _insight(ins_id, *, type="FACT", signal_ids=("sig_a",), evidence_ids=("ev_1",),
             statement="test", confidence=0.8):
    return {
        "insight_id": ins_id,
        "type": type,
        "statement": statement,
        "signal_ids": list(signal_ids),
        "evidence_ids": list(evidence_ids),
        "confidence": confidence,
    }


class TestSignalOverlap:
    def test_no_overlap(self):
        assert _signal_overlap(("sig_a",), ("sig_b",)) == 0.0

    def test_full_overlap(self):
        assert _signal_overlap(("sig_a",), ("sig_a",)) == 1.0

    def test_partial_overlap(self):
        overlap = _signal_overlap(("sig_a", "sig_b"), ("sig_a", "sig_c"))
        assert 0 < overlap < 1

    def test_empty(self):
        assert _signal_overlap((), ("sig_a",)) == 0.0


class TestDeduplicateInsights:
    def test_no_duplicates(self):
        insights = [
            _insight("ins_1", signal_ids=("sig_a",)),
            _insight("ins_2", signal_ids=("sig_b",)),
        ]
        result = deduplicate_insights(insights)
        assert len(result.kept) == 2
        assert result.removed == ()

    def test_structural_duplicate_removed(self):
        """Same signal_ids + evidence_ids → duplicate (same insight_id)."""
        insights = [
            _insight("ins_1", signal_ids=("sig_a",), evidence_ids=("ev_1",)),
            _insight("ins_1", signal_ids=("sig_a",), evidence_ids=("ev_1",)),
        ]
        result = deduplicate_insights(insights)
        assert len(result.kept) == 1
        assert len(result.removed) == 1

    def test_same_signal_distinct_evidence_is_not_duplicate(self):
        """One cluster may contain separately supportable user complaints."""
        insights = [
            _insight("ins_1", signal_ids=("sig_a",), evidence_ids=("ev_1",),
                     statement="One user rechecks the summary."),
            _insight("ins_2", signal_ids=("sig_a",), evidence_ids=("ev_2",),
                     statement="Another user wants clearer takeaways."),
        ]
        result = deduplicate_insights(insights)
        assert len(result.kept) == 2
        assert result.removed == ()

    def test_same_signal_and_evidence_distinct_statement_is_not_duplicate(self):
        insights = [
            _insight("ins_1", statement="Summary is readable."),
            _insight("ins_2", statement="Summary needs checking."),
        ]
        assert len(deduplicate_insights(insights).kept) == 2

    def test_same_claim_with_different_ids_keeps_higher_confidence(self):
        insights = [
            _insight("ins_1", statement="Same fact", confidence=0.7),
            _insight("ins_2", statement="same  FACT", confidence=0.9),
        ]
        result = deduplicate_insights(insights)
        assert [item["insight_id"] for item in result.kept] == ["ins_2"]

    def test_different_types_not_deduped(self):
        """FACT and INFERENCE with same signals are different insights."""
        insights = [
            _insight("ins_1", type="FACT", signal_ids=("sig_a",)),
            _insight("ins_2", type="INFERENCE", signal_ids=("sig_a",)),
        ]
        result = deduplicate_insights(insights)
        assert len(result.kept) == 2

    def test_empty_input(self):
        result = deduplicate_insights([])
        assert result.kept == ()
        assert result.removed == ()

    def test_keeps_first_on_duplicate(self):
        """On structural duplicate, the first insight is kept (canonical)."""
        insights = [
            _insight("ins_1", statement="First", signal_ids=("sig_a",)),
            _insight("ins_1", statement="Second", signal_ids=("sig_a",)),
        ]
        result = deduplicate_insights(insights)
        assert len(result.kept) == 1
        assert result.kept[0]["statement"] == "First"

    def test_warnings_for_removed(self):
        insights = [
            _insight("ins_1", signal_ids=("sig_a",), evidence_ids=("ev_1",)),
            _insight("ins_1", signal_ids=("sig_a",), evidence_ids=("ev_1",)),
        ]
        result = deduplicate_insights(insights)
        assert any("ins_1" in w for w in result.warnings)
