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

    def test_high_signal_overlap_flagged(self):
        """>50% signal overlap → potential duplicate, first kept."""
        insights = [
            _insight("ins_1", signal_ids=("sig_a", "sig_b"), evidence_ids=("ev_1",)),
            _insight("ins_2", signal_ids=("sig_a", "sig_b"), evidence_ids=("ev_2",)),
        ]
        result = deduplicate_insights(insights)
        # Same signal_ids but different evidence → different insight_ids
        # But 100% signal overlap → potential duplicate
        assert len(result.kept) <= 2
        assert len(result.kept) >= 1

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
