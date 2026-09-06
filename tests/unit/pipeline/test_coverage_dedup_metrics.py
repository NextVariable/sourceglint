"""Tests for CoverageReport dedup metric semantics (Phase 3 Closeout §5).

Phase 3 final report had confusing counts:
  Evidence count  : 7
  Dedup count     : 62

After Closeout §5:
  raw_result_count         — items from adapters (BEFORE normalization)
  normalized_evidence_count — items post-normalize (BEFORE time filter)
  time_filter_dropped_count — items the time-filter stage removed
  duplicate_dropped_count   — items the dedup stage removed
  final_evidence_count      — items KEPT after dedup

Arithmetic:
  normalized_evidence_count
    - time_filter_dropped_count
    - duplicate_dropped_count
  == final_evidence_count

The legacy `deduplicated_count` is kept as a back-compat alias.
"""
from __future__ import annotations

from gtm_intelligence.pipeline.coverage import (
    CoverageReport,
    build_coverage_report,
)


def _minimal_report(**overrides) -> CoverageReport:
    return build_coverage_report(
        requested_sources=overrides.get("requested_sources", ["reddit"]),
        attempted_sources=overrides.get("attempted_sources", ["reddit"]),
        source_statuses=overrides.get("source_statuses", {}),
        expanded_queries=overrides.get("expanded_queries", []),
        raw_results=overrides.get("raw_results", []),
        normalized_evidence=overrides.get("normalized_evidence", []),
        deduplicated_dropped=overrides.get("deduplicated_dropped", 0),
        dropped_by_time_filter=overrides.get("dropped_by_time_filter", 0),
        kept_evidence=overrides.get("kept_evidence", []),
    )


def test_duplicate_dropped_is_dropped_count_not_kept_count():
    """Confusing case from the Phase 3 report.

    7 final + 62 dropped — the 62 is the dropped count, not the kept count.
    """
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[{"evidence_id": f"ev_{i}"} for i in range(7)],
        deduplicated_dropped=2,
        dropped_by_time_filter=0,
        kept_evidence=[{"evidence_id": f"ev_{i}"} for i in range(5)],
    )
    assert rep.duplicate_dropped_count == 2
    assert rep.final_evidence_count == 5


def test_arithmetic_invariant_norm_dropped_final():
    """Y normalized - T time_filter_dropped - D duplicate_dropped = N final."""
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[{"evidence_id": f"ev_{i}"} for i in range(10)],
        deduplicated_dropped=3,
        dropped_by_time_filter=2,
        kept_evidence=[{"evidence_id": f"ev_{i}"} for i in range(5)],
    )
    assert rep.normalized_evidence_count == 10
    assert rep.time_filter_dropped_count == 2
    assert rep.duplicate_dropped_count == 3
    assert rep.final_evidence_count == 5
    assert (
        rep.normalized_evidence_count
        - rep.time_filter_dropped_count
        - rep.duplicate_dropped_count
        == rep.final_evidence_count
    )


def test_deduplicated_count_alias_kept_for_backcompat():
    rep = CoverageReport(duplicate_dropped_count=42)
    assert rep.deduplicated_count == 42
    assert rep.duplicate_dropped_count == 42


def test_zero_dedup_zero_time_drop_yields_final_eq_normalized():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[{"evidence_id": "ev_1"}],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
        kept_evidence=[{"evidence_id": "ev_1"}],
    )
    assert rep.final_evidence_count == 1


def test_dedup_drops_all_yields_zero_final():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[{"evidence_id": "ev_1"}] * 5,
        deduplicated_dropped=5,
        dropped_by_time_filter=0,
        kept_evidence=[],
    )
    assert rep.duplicate_dropped_count == 5
    assert rep.final_evidence_count == 0


def test_to_dict_exposes_all_stage_count_fields():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=2,
        dropped_by_time_filter=3,
        kept_evidence=[],
    )
    d = rep.to_dict()
    assert d["duplicate_dropped_count"] == 2
    assert d["time_filter_dropped_count"] == 3
    assert d["final_evidence_count"] == 0


def test_golden_research_realistic_counts():
    """Realistic Golden research counts.

    69 raw, 69 normalized (no normalize drops), 62 time_filter_dropped
    (out of range), 0 dedup drops (already unique after canonicalize),
    7 final (the canonical-URL survivors)."""
    raw = [{"a": i} for i in range(69)]
    normalized = [{"evidence_id": f"ev_{i}"} for i in range(69)]
    kept = [{"evidence_id": f"ev_{i}"} for i in range(7)]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=raw,
        normalized_evidence=normalized,
        deduplicated_dropped=0,
        dropped_by_time_filter=62,
        kept_evidence=kept,
    )
    assert rep.raw_result_count == 69
    assert rep.normalized_evidence_count == 69
    assert rep.time_filter_dropped_count == 62
    assert rep.duplicate_dropped_count == 0
    assert rep.final_evidence_count == 7
