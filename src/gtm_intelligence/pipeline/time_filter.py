"""Deterministic Time Filtering (Phase 3 §13/§14).

The filter is purely time-based — caller controls whether the window is
'current' or 'baseline' by setting Evidence.window upstream. The filter
itself does not mutate window semantics.

Determinism: as_of is INJECTED. No system clock. No timezones read from
the environment. UTC-preferred; offsets accepted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from rfc3339_validator import validate_rfc3339


# A tiny set of recognized drop reasons — used by Coverage Report (Phase 3 §19).
DROP_REASON_MISSING = "missing_published_at"
DROP_REASON_INVALID_TS = "invalid_timestamp"
DROP_REASON_OUTSIDE_PREFIX = "outside_window"
DROP_REASON_FUTURE = "outside_window:future"


class TimeWindowError(ValueError):
    """A research-plan time_window is malformed."""


@dataclass(frozen=True)
class DroppedItem:
    evidence_id: str
    reason: str
    published_at: str = ""


@dataclass(frozen=True)
class TimeFilterResult:
    kept: list[dict] = field(default_factory=list)
    dropped: list[DroppedItem] = field(default_factory=list)


@dataclass(frozen=True)
class TimeFilter:
    """Pre-parsed window with injected as_of. apply(items) -> TimeFilterResult."""

    window: dict
    as_of: str

    def apply(self, items: Iterable[Mapping[str, object]]) -> TimeFilterResult:
        return apply_time_filter(items, self.window, as_of=self.as_of)


def parse_window(window: Mapping[str, object]) -> tuple[datetime, datetime]:
    """Parse a Phase 1 research_plan time_window into (start, end) UTC datetimes.
    Raises TimeWindowError on bad shape.
    """
    if not isinstance(window, Mapping):
        raise TimeWindowError(f"time_window must be an object; got {type(window).__name__}")
    if "days" in window:
        return _parse_relative_days(window)
    if "start" in window and "end" in window:
        return _parse_custom_range(window)
    raise TimeWindowError(
        "time_window must have either {days: N} or {start, end}"
    )


def _parse_iso_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not validate_rfc3339(value):
        raise TimeWindowError(f"time_window.{field} must be RFC3339; got {value!r}")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_relative_days(window: Mapping[str, object]) -> tuple[datetime, datetime]:
    days_raw = window.get("days")
    if not isinstance(days_raw, int) or isinstance(days_raw, bool):
        raise TimeWindowError(f"time_window.days must be int; got {days_raw!r}")
    if days_raw < 1:
        raise TimeWindowError(f"time_window.days must be >= 1; got {days_raw}")
    # We can't compute the end without an as_of, so the caller must inject it.
    # Return a sentinel; the actual start/end are computed per-call in apply().
    raise TimeWindowError(
        "internal: relative windows need as_of injection — use apply_time_filter directly"
    )


def _parse_custom_range(window: Mapping[str, object]) -> tuple[datetime, datetime]:
    start = _parse_iso_utc(str(window["start"]), "start")
    end = _parse_iso_utc(str(window["end"]), "end")
    if start > end:
        raise TimeWindowError(
            f"time_window.start ({start.isoformat()}) > end ({end.isoformat()})"
        )
    return start, end


def _relative_window(window: Mapping[str, object], as_of: str) -> tuple[datetime, datetime]:
    days_raw = window.get("days")
    if not isinstance(days_raw, int) or isinstance(days_raw, bool):
        raise TimeWindowError(f"time_window.days must be int; got {days_raw!r}")
    if days_raw < 1:
        raise TimeWindowError(f"time_window.days must be >= 1; got {days_raw}")
    end_dt = _parse_iso_utc(as_of, "as_of")
    start_dt = end_dt - timedelta(days=days_raw)
    return start_dt, end_dt


def apply_time_filter(
    items: Iterable[Mapping[str, object]],
    window: Mapping[str, object],
    *,
    as_of: str,
) -> TimeFilterResult:
    """Apply the research-plan time_window to a list of Evidence-like dicts.

    Inputs:
      items  : iterable of Evidence dicts (with optional 'published_at')
      window : Phase 1 time_window ({days: N} or {start, end})
      as_of  : injected ISO timestamp; determines 'now' for relative windows.

    Output:
      TimeFilterResult with .kept (in input order) and .dropped (with reasons).
    """
    if not isinstance(window, Mapping):
        raise TimeWindowError(f"time_window must be an object; got {type(window).__name__}")
    if "days" in window:
        start_dt, end_dt = _relative_window(window, as_of)
    elif "start" in window and "end" in window:
        start_dt, end_dt = _parse_custom_range(window)
    else:
        raise TimeWindowError(
            "time_window must have either {days: N} or {start, end}"
        )

    kept: list[dict] = []
    dropped: list[DroppedItem] = []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        eid = str(item.get("evidence_id") or "")
        pa_raw = str(item.get("published_at") or "")
        if not pa_raw:
            dropped.append(
                DroppedItem(evidence_id=eid, reason=DROP_REASON_MISSING, published_at="")
            )
            continue
        if not validate_rfc3339(pa_raw):
            dropped.append(
                DroppedItem(
                    evidence_id=eid, reason=DROP_REASON_INVALID_TS, published_at=pa_raw,
                )
            )
            continue
        try:
            pa_dt = datetime.fromisoformat(pa_raw.replace("Z", "+00:00"))
        except ValueError:
            dropped.append(
                DroppedItem(
                    evidence_id=eid, reason=DROP_REASON_INVALID_TS, published_at=pa_raw,
                )
            )
            continue
        if pa_dt.tzinfo is None:
            pa_dt = pa_dt.replace(tzinfo=timezone.utc)
        pa_dt = pa_dt.astimezone(timezone.utc)

        if pa_dt > end_dt:
            dropped.append(
                DroppedItem(
                    evidence_id=eid,
                    reason=DROP_REASON_FUTURE,
                    published_at=pa_raw,
                )
            )
            continue

        if pa_dt < start_dt:
            dropped.append(
                DroppedItem(
                    evidence_id=eid,
                    reason=f"{DROP_REASON_OUTSIDE_PREFIX}:{pa_dt.date().isoformat()}",
                    published_at=pa_raw,
                )
            )
            continue

        kept.append(dict(item))

    return TimeFilterResult(kept=kept, dropped=dropped)