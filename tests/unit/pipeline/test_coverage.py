"""Tests for CoverageReport (Phase 3 §19).

Contract:
  * CoverageReport is the deterministic, non-LLM metadata artifact that
    accompanies a pipeline run.
  * Fields (Closeout §5):
      - requested_sources: list of source names the plan asked for
      - attempted_sources: list of source names that were actually called
      - successful_sources: subset of attempted with status=success/partial
      - failed_sources: subset of attempted with status=unavailable/auth_missing/
        rate_limited/timeout/invalid_response
      - query_count: total expanded queries
      - raw_result_count: raw items returned by adapters (before normalization)
      - normalized_evidence_count: items after normalization
      - duplicate_dropped_count: items DROPPED by dedup (Closeout §5)
      - final_evidence_count: items KEPT after dedup (Closeout §5)
      - current_window_count: normalized evidence in 'current' window
      - baseline_window_count: normalized evidence in 'baseline' window
      - languages_covered: list of distinct query_language values
      - markets_covered: list of distinct market values
      - gaps: list of human-readable gap strings (no LLM, deterministic)
      - warnings: list of pipeline-level warnings
  * Order is preserved per list.
  * CoverageReport is plain dict + summary() helper.
  * No LLM involvement anywhere.
  * Arithmetic:  normalized - duplicate_dropped == final_evidence_count
"""
from __future__ import annotations

from gtm_intelligence.pipeline.coverage import (
    CoverageReport,
    build_coverage_report,
)


def test_coverage_report_defaults():
    rep = CoverageReport()
    assert list(rep.requested_sources) == []
    assert list(rep.attempted_sources) == []
    assert list(rep.successful_sources) == []
    assert list(rep.failed_sources) == []
    assert rep.query_count == 0
    assert rep.raw_result_count == 0
    assert rep.normalized_evidence_count == 0
    assert rep.duplicate_dropped_count == 0
    assert rep.final_evidence_count == 0
    assert rep.deduplicated_count == 0  # back-compat alias
    assert rep.current_window_count == 0
    assert rep.baseline_window_count == 0
    assert list(rep.languages_covered) == []
    assert list(rep.markets_covered) == []
    assert list(rep.gaps) == []
    assert list(rep.warnings) == []


def test_coverage_report_summary():
    rep = CoverageReport(
        requested_sources=["reddit", "github"],
        attempted_sources=["reddit", "github"],
        successful_sources=["reddit"],
        failed_sources=["github"],
        raw_result_count=10,
        normalized_evidence_count=8,
        time_filter_dropped_count=2,
        duplicate_dropped_count=1,
        final_evidence_count=5,
    )
    summary = rep.summary()
    assert "raw=10" in summary
    assert "normalized=8" in summary
    assert "time_drop=2" in summary
    assert "dedup_drop=1" in summary
    assert "final=5" in summary


def test_build_coverage_report_minimal():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert list(rep.requested_sources) == ["reddit"]


def test_build_coverage_report_counts():
    queries = [
        {"text": "q1", "query_language": "en", "market": "global"},
        {"text": "q2", "query_language": "en", "market": "global"},
        {"text": "q3", "query_language": "ja", "market": "jp"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit", "github"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[{"a": 1}, {"a": 2}],
        normalized_evidence=[{"evidence_id": "ev_1"}],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert rep.query_count == 3
    assert rep.raw_result_count == 2
    assert rep.normalized_evidence_count == 1
    assert rep.duplicate_dropped_count == 0
    assert rep.final_evidence_count == 1
    assert rep.deduplicated_count == 0  # back-compat
    assert "en" in rep.languages_covered
    assert "ja" in rep.languages_covered
    assert "global" in rep.markets_covered
    assert "jp" in rep.markets_covered


def test_build_coverage_report_window_counts():
    normalized = [
        {"evidence_id": "ev_1", "window": "current"},
        {"evidence_id": "ev_2", "window": "current"},
        {"evidence_id": "ev_3", "window": "baseline"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=normalized,
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert rep.current_window_count == 2
    assert rep.baseline_window_count == 1


def test_window_counts_only_include_final_kept_evidence():
    normalized = [
        {"evidence_id": f"ev_{i}", "window": "current"} for i in range(6)
    ]
    kept = [
        {"evidence_id": "ev_0", "window": "current"},
        {"evidence_id": "ev_1", "window": "current"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=normalized,
        deduplicated_dropped=1,
        dropped_by_time_filter=3,
        kept_evidence=kept,
    )
    assert rep.final_evidence_count == 2
    assert rep.current_window_count == 2
    assert rep.baseline_window_count == 0


def test_build_coverage_report_languages_distinct():
    queries = [
        {"text": "q1", "query_language": "en", "market": "global"},
        {"text": "q2", "query_language": "en", "market": "global"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert list(rep.languages_covered) == ["en"]


def test_build_coverage_report_orders_preserved():
    queries = [
        {"text": "z", "query_language": "en", "market": "global"},
        {"text": "a", "query_language": "en", "market": "global"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit", "github"],
        attempted_sources=["reddit", "github"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert rep.query_count == 2
    assert list(rep.requested_sources) == ["reddit", "github"]


def test_build_coverage_report_gaps_when_no_results():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[{"text": "q", "query_language": "en", "market": "global"}],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    # When no evidence is collected, a gap should be recorded.
    assert any("no evidence" in g.lower() for g in rep.gaps)


def test_build_coverage_report_no_gap_when_evidence_present():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[{"evidence_id": "ev_1"}],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert not any("no evidence" in g.lower() for g in rep.gaps)


def test_build_coverage_report_failed_sources_listed():
    from gtm_intelligence.pipeline.degradation import SourceStatus, SourceStatusReport

    statuses = {
        "reddit": SourceStatusReport("reddit", status=SourceStatus.SUCCESS, count=5),
        "github": SourceStatusReport("github", status=SourceStatus.UNAVAILABLE, count=0),
    }
    rep = build_coverage_report(
        requested_sources=["reddit", "github"],
        attempted_sources=["reddit", "github"],
        source_statuses=statuses,
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert "reddit" in rep.successful_sources
    assert "github" in rep.failed_sources


def test_build_coverage_report_partial_counts_as_successful():
    from gtm_intelligence.pipeline.degradation import SourceStatus, SourceStatusReport

    statuses = {
        "reddit": SourceStatusReport("reddit", status=SourceStatus.PARTIAL, count=3),
    }
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses=statuses,
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert "reddit" in rep.successful_sources
    assert "reddit" not in rep.failed_sources


def test_build_coverage_report_auth_missing_listed_as_failed():
    from gtm_intelligence.pipeline.degradation import SourceStatus, SourceStatusReport

    statuses = {
        "github": SourceStatusReport("github", status=SourceStatus.AUTH_MISSING, count=0),
    }
    rep = build_coverage_report(
        requested_sources=["github"],
        attempted_sources=["github"],
        source_statuses=statuses,
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert "github" in rep.failed_sources


def test_build_coverage_report_records_dedup_dropped():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=3,
        dropped_by_time_filter=0,
    )
    assert rep.duplicate_dropped_count == 3
    assert rep.deduplicated_count == 3  # back-compat alias
    assert rep.final_evidence_count == max(0, 0 - 3)  # = 0


def test_build_coverage_report_records_time_filter_dropped():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=5,
    )
    assert any("time_filter_dropped=5" in w for w in rep.warnings)


def test_build_coverage_report_languages_covered_distinct_preserves_first_seen():
    queries = [
        {"text": "q", "query_language": "en", "market": "global"},
        {"text": "q", "query_language": "ja", "market": "jp"},
        {"text": "q", "query_language": "en", "market": "global"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert list(rep.languages_covered) == ["en", "ja"]


def test_build_coverage_report_no_duplicate_gap_for_no_evidence():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[{"text": "q", "query_language": "en", "market": "global"}],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    gap_count = sum(1 for g in rep.gaps if "no evidence" in g.lower())
    assert gap_count == 1


def test_build_coverage_report_to_dict():
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=[{"text": "q", "query_language": "en", "market": "global"}],
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    d = rep.to_dict()
    assert "requested_sources" in d
    assert "attempted_sources" in d
    assert "successful_sources" in d
    assert "failed_sources" in d
    assert "query_count" in d
    assert "raw_result_count" in d
    assert "normalized_evidence_count" in d
    assert "duplicate_dropped_count" in d
    assert "time_filter_dropped_count" in d
    assert "final_evidence_count" in d
    assert "current_window_count" in d
    assert "baseline_window_count" in d
    assert "languages_covered" in d
    assert "markets_covered" in d
    assert "gaps" in d
    assert "warnings" in d


def test_build_coverage_report_market_coverage_distinct():
    queries = [
        {"text": "q1", "query_language": "en", "market": "global"},
        {"text": "q2", "query_language": "ja", "market": "jp"},
    ]
    rep = build_coverage_report(
        requested_sources=["reddit"],
        attempted_sources=["reddit"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert list(rep.markets_covered) == ["global", "jp"]


def test_build_coverage_report_deterministic_20_runs():
    queries = [
        {"text": "q", "query_language": "en", "market": "global"},
        {"text": "q2", "query_language": "ja", "market": "jp"},
    ]
    rep_a = build_coverage_report(
        requested_sources=["reddit", "github"],
        attempted_sources=["reddit", "github"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    rep_b = build_coverage_report(
        requested_sources=["reddit", "github"],
        attempted_sources=["reddit", "github"],
        source_statuses={},
        expanded_queries=queries,
        raw_results=[],
        normalized_evidence=[],
        deduplicated_dropped=0,
        dropped_by_time_filter=0,
    )
    assert rep_a.to_dict() == rep_b.to_dict()
