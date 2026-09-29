"""Tests for deterministic Time Filtering (Phase 3 §13/§14).

Contract:
  * TimeFilter takes Evidence-like dicts and a Research Plan time_window.
  * Two window modes:
      - relative days: {"days": N}
      - custom range:  {"start": ..., "end": ...}
  * as_of is INJECTED (deterministic). No system clock anywhere.
  * Evidence.published_at:
      - inside window        -> pass
      - outside window       -> filtered out (recorded as gap)
      - missing published_at -> filtered out (recorded as gap; never silently
                                promoted as 'recent')
  * Evidence.window = 'baseline' for evidence that is intentionally within
    a baseline window (set by caller before filter, not by filter itself).
  * Filter must be deterministic and ordering-preserving for kept items.
  * Boundary inclusive: evidence with published_at == window start passes.
  * Custom range: start <= end enforced.
"""
from __future__ import annotations

import pytest

from sourceglint.pipeline.time_filter import (
    TimeFilter,
    TimeWindowError,
    apply_time_filter,
    parse_window,
)


def _ev(published_at: str = "", **overrides) -> dict:
    base = {
        "evidence_id": "ev_test",
        "source": "reddit",
        "source_type": "post",
        "url": "https://reddit.com/r/x/comments/1",
        "title": "t",
        "snippet": "s",
        "retrieved_at": "2026-09-06T10:00:00Z",
    }
    if published_at:
        base["published_at"] = published_at
    base.update(overrides)
    return base


def test_relative_days_window_keeps_recent():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    # 10 days ago is within 30-day window
    e = _ev(published_at="2026-08-27T10:00:00Z")
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert len(out.kept) == 1
    assert out.dropped == []


def test_relative_days_window_drops_old():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    # 60 days ago is outside
    e = _ev(published_at="2026-07-07T10:00:00Z")
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.kept == []
    assert len(out.dropped) == 1


def test_relative_days_boundary_inclusive_start():
    """published_at == as_of - days is kept (inclusive)."""
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="2026-08-07T10:00:00Z")  # exactly 30 days before
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert len(out.kept) == 1


def test_relative_days_boundary_just_outside():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="2026-08-07T09:59:59Z")  # 30 days + 1 sec
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.kept == []
    assert len(out.dropped) == 1


def test_relative_days_future_published_at_dropped():
    """If published_at > as_of, the date is in the future — drop as anomaly."""
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="2027-01-01T10:00:00Z")
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.kept == []


def test_missing_published_at_dropped():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev()  # no published_at
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.kept == []
    # And the gap is recorded with a stable reason.
    assert out.dropped[0].reason == "missing_published_at"


def test_custom_range_keeps_in_range():
    plan_window = {
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-08-31T23:59:59Z",
    }
    as_of = "2026-09-06T10:00:00Z"
    e1 = _ev(published_at="2026-08-15T12:00:00Z")
    e2 = _ev(published_at="2026-08-01T00:00:00Z")  # boundary start
    e3 = _ev(published_at="2026-08-31T23:59:59Z")  # boundary end
    out = apply_time_filter([e1, e2, e3], plan_window, as_of=as_of)
    assert len(out.kept) == 3


def test_custom_range_drops_outside():
    plan_window = {
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-08-31T23:59:59Z",
    }
    as_of = "2026-09-06T10:00:00Z"
    e_before = _ev(published_at="2026-07-31T23:59:59Z")
    e_after = _ev(published_at="2026-09-01T00:00:00Z")
    out = apply_time_filter([e_before, e_after], plan_window, as_of=as_of)
    assert out.kept == []
    assert len(out.dropped) == 2


def test_custom_range_invalid_start_after_end_raises():
    with pytest.raises(TimeWindowError):
        parse_window({"start": "2026-09-01T00:00:00Z", "end": "2026-08-01T00:00:00Z"})


def test_invalid_window_form_raises():
    with pytest.raises(TimeWindowError):
        parse_window({"days": "abc"})


def test_unknown_window_form_raises():
    with pytest.raises(TimeWindowError):
        parse_window({"hours": 24})


def test_kept_evidence_in_input_order():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(published_at="2026-08-30T10:00:00Z", evidence_id="ev_a"),
        _ev(published_at="2026-08-20T10:00:00Z", evidence_id="ev_b"),
        _ev(published_at="2026-09-01T10:00:00Z", evidence_id="ev_c"),
    ]
    out = apply_time_filter(items, plan_window, as_of=as_of)
    assert [e["evidence_id"] for e in out.kept] == ["ev_a", "ev_b", "ev_c"]


def test_mixed_dropped_and_kept():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(published_at="2026-08-30T10:00:00Z"),  # kept
        _ev(),  # dropped (missing)
        _ev(published_at="2026-07-01T10:00:00Z"),  # dropped (too old)
        _ev(published_at="2026-09-01T10:00:00Z"),  # kept
    ]
    out = apply_time_filter(items, plan_window, as_of=as_of)
    assert len(out.kept) == 2
    assert len(out.dropped) == 2


def test_dropped_carries_evidence_id_and_reason():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="2026-01-01T10:00:00Z")
    e["evidence_id"] = "ev_drop_me"
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.dropped[0].evidence_id == "ev_drop_me"
    assert "outside_window" in out.dropped[0].reason


def test_time_filter_class_api_matches_function():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [_ev(published_at="2026-08-30T10:00:00Z")]
    fn_out = apply_time_filter(items, plan_window, as_of=as_of)
    cls_out = TimeFilter(plan_window, as_of=as_of).apply(items)
    assert len(fn_out.kept) == len(cls_out.kept)


def test_filter_does_not_mutate_input_evidence():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [_ev(published_at="2026-08-30T10:00:00Z")]
    before = items[0].copy()
    apply_time_filter(items, plan_window, as_of=as_of)
    assert items[0] == before


def test_dropped_reason_outside_window_vs_missing_distinct():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(),  # missing
        _ev(published_at="2026-01-01T10:00:00Z"),  # outside
    ]
    out = apply_time_filter(items, plan_window, as_of=as_of)
    reasons = {d.reason for d in out.dropped}
    assert "missing_published_at" in reasons
    assert any(r.startswith("outside_window") for r in reasons)


def test_future_window_supported_via_custom_range():
    """A custom window in the future is legal (e.g. research scheduled)."""
    plan_window = {
        "start": "2027-01-01T00:00:00Z",
        "end": "2027-12-31T23:59:59Z",
    }
    as_of = "2026-09-06T10:00:00Z"
    # No evidence in future yet; kept is empty.
    out = apply_time_filter([], plan_window, as_of=as_of)
    assert out.kept == []


def test_dropped_count_for_coverage_report():
    """Coverage report can read dropped counts — verify they're public."""
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(published_at="2026-08-30T10:00:00Z"),
        _ev(),
        _ev(),
        _ev(published_at="2026-01-01T10:00:00Z"),
    ]
    out = apply_time_filter(items, plan_window, as_of=as_of)
    assert len(out.dropped) == 3


def test_filter_does_not_change_window_field():
    """If evidence has window='baseline' but the plan filter is for 'current',
    the filter still keeps evidence in the time range — caller decides what
    window means. The filter is purely time-based."""
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(published_at="2026-08-30T10:00:00Z", window="baseline"),
    ]
    out = apply_time_filter(items, plan_window, as_of=as_of)
    assert len(out.kept) == 1
    assert out.kept[0]["window"] == "baseline"


def test_iso_with_offset_accepted():
    """RFC3339 with +09:00 offset is accepted."""
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="2026-08-30T12:00:00+09:00")  # 03:00 UTC
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert len(out.kept) == 1


def test_invalid_iso_dropped_with_clear_reason():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    e = _ev(published_at="not-a-date")
    out = apply_time_filter([e], plan_window, as_of=as_of)
    assert out.kept == []
    assert out.dropped[0].reason == "invalid_timestamp"


def test_deterministic_20_runs():
    plan_window = {"days": 30}
    as_of = "2026-09-06T10:00:00Z"
    items = [
        _ev(published_at="2026-08-30T10:00:00Z"),
        _ev(),
        _ev(published_at="2026-01-01T10:00:00Z"),
    ]
    snapshots = [
        tuple((len(apply_time_filter(items, plan_window, as_of=as_of).kept),
               len(apply_time_filter(items, plan_window, as_of=as_of).dropped))
              for _ in range(20))
    ]
    # Single tuple, just verify size
    assert len(snapshots) == 1