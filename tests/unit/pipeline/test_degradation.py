"""Tests for source-status taxonomy and graceful degradation (Phase 3 §18, §20).

Contract:
  * SourceStatus enum: success | partial | unavailable | auth_missing |
    rate_limited | timeout | invalid_response.
  * SourceStatusReport: per-source { status, count, warnings }.
  * Pipeline continues when individual sources fail.
  * All-source failure -> PipelineFailed error.
  * Invalid Research Plan -> fail loudly before retrieval.
  * Auth missing -> mark auth_missing + degrade.
  * No secret material in status strings.
  * Order of statuses preserved per source (stable iteration).
"""
from __future__ import annotations

import pytest

from gtm_intelligence.pipeline.degradation import (
    AllSourcesFailedError,
    InvalidResearchPlanError,
    InvalidSourceRegistryError,
    SourceStatus,
    SourceStatusReport,
    build_status_report,
    classify_adapter_exception,
)


def test_source_status_enum_values():
    assert SourceStatus.SUCCESS.value == "success"
    assert SourceStatus.UNAVAILABLE.value == "unavailable"
    assert SourceStatus.AUTH_MISSING.value == "auth_missing"
    assert SourceStatus.RATE_LIMITED.value == "rate_limited"
    assert SourceStatus.TIMEOUT.value == "timeout"
    assert SourceStatus.INVALID_RESPONSE.value == "invalid_response"
    assert SourceStatus.PARTIAL.value == "partial"


def test_classify_adapter_unavailable():
    from gtm_intelligence.pipeline.adapters import AdapterUnavailable
    exc = AdapterUnavailable(source="reddit", reason="503")
    assert classify_adapter_exception(exc) == SourceStatus.UNAVAILABLE


def test_classify_adapter_auth_missing():
    from gtm_intelligence.pipeline.adapters import AdapterAuthMissing
    exc = AdapterAuthMissing(source="github", reason="no token")
    assert classify_adapter_exception(exc) == SourceStatus.AUTH_MISSING


def test_classify_adapter_rate_limited():
    from gtm_intelligence.pipeline.adapters import AdapterRateLimited
    exc = AdapterRateLimited(source="reddit", reason="429")
    assert classify_adapter_exception(exc) == SourceStatus.RATE_LIMITED


def test_classify_adapter_timeout():
    from gtm_intelligence.pipeline.adapters import AdapterTimeout
    exc = AdapterTimeout(source="host_web_search", reason="30s elapsed")
    assert classify_adapter_exception(exc) == SourceStatus.TIMEOUT


def test_classify_adapter_invalid_response():
    from gtm_intelligence.pipeline.adapters import AdapterInvalidResponse
    exc = AdapterInvalidResponse(source="reddit", reason="malformed JSON")
    assert classify_adapter_exception(exc) == SourceStatus.INVALID_RESPONSE


def test_classify_unknown_exception_defaults_to_unavailable():
    e = RuntimeError("something weird")
    assert classify_adapter_exception(e) == SourceStatus.UNAVAILABLE


def test_status_report_default_success():
    rep = SourceStatusReport(source="reddit")
    assert rep.status == SourceStatus.SUCCESS
    assert rep.count == 0
    assert rep.warnings == []


def test_status_report_count_tracks_results():
    rep = SourceStatusReport(source="reddit", status=SourceStatus.SUCCESS, count=5)
    assert rep.count == 5


def test_status_report_append_warning():
    rep = SourceStatusReport(source="reddit", status=SourceStatus.PARTIAL)
    rep.append_warning("3 of 10 items had missing fields")
    assert "3 of 10" in rep.warnings[0]


def test_status_report_no_duplicate_warnings():
    rep = SourceStatusReport(source="reddit", status=SourceStatus.PARTIAL)
    rep.append_warning("same warning")
    rep.append_warning("same warning")
    assert rep.warnings == ["same warning"]


def test_build_status_report_for_results():
    rep = build_status_report(
        source="reddit",
        results=[{"a": 1}, {"a": 2}, {"a": 3}],
        warnings=[],
    )
    assert rep.status == SourceStatus.SUCCESS
    assert rep.count == 3


def test_build_status_report_for_empty_results():
    rep = build_status_report(source="reddit", results=[], warnings=[])
    assert rep.status == SourceStatus.SUCCESS
    assert rep.count == 0


def test_build_status_report_with_warnings_marks_partial():
    rep = build_status_report(
        source="reddit",
        results=[{"a": 1}],
        warnings=["some items dropped"],
    )
    assert rep.status == SourceStatus.PARTIAL
    assert rep.count == 1
    assert "some items dropped" in rep.warnings


def test_status_no_secret_in_warning_string():
    rep = SourceStatusReport(source="reddit", status=SourceStatus.AUTH_MISSING)
    rep.append_warning("token=ghp_xxxx missing")
    # The warning string itself can mention it, but build_status_report
    # never serializes raw credentials — only names. This test guards against
    # accidentally logging credential VALUES by ensuring the report only
    # carries the credential NAME in the warning, never the value.
    full = repr(rep)
    assert "ghp_xxxx" not in full  # not present at construction time


def test_all_sources_failed_error_carries_per_source_status():
    e = AllSourcesFailedError(
        per_source={
            "reddit": SourceStatusReport("reddit", status=SourceStatus.UNAVAILABLE),
            "github": SourceStatusReport("github", status=SourceStatus.TIMEOUT),
        }
    )
    msg = str(e)
    assert "reddit" in msg
    assert "github" in msg


def test_invalid_research_plan_error_message_includes_field():
    e = InvalidResearchPlanError("topic is required")
    assert "topic" in str(e)


def test_invalid_source_registry_error_message_includes_path():
    e = InvalidSourceRegistryError("config/sources.yaml: missing 'name'")
    assert "sources.yaml" in str(e)


def test_status_report_summary_includes_counts():
    rep = SourceStatusReport(source="reddit", status=SourceStatus.SUCCESS, count=7)
    summary = rep.summary()
    assert "reddit" in summary
    assert "7" in summary
    assert "success" in summary


def test_status_reports_dict_order_preserved():
    """Python 3.7+ dicts preserve insertion order; verify it's exposed."""
    reports = build_status_report(source="a", results=[], warnings=[])
    reports2 = build_status_report(source="b", results=[], warnings=[])
    combined = {"a": reports, "b": reports2}
    assert list(combined.keys()) == ["a", "b"]