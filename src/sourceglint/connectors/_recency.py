"""Upstream time bounds; downstream publication filtering remains authoritative."""
from datetime import datetime, timedelta, timezone
from typing import Mapping


def search_bounds(plan: Mapping, request: Mapping) -> tuple[datetime, datetime] | None:
    window = plan.get("time_window") or {}
    if not isinstance(window, Mapping):
        return None
    try:
        if "start" in window and "end" in window:
            start = datetime.fromisoformat(str(window["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(window["end"]).replace("Z", "+00:00"))
        else:
            end = datetime.fromisoformat(str(request["retrieved_at"]).replace("Z", "+00:00"))
            start = end - timedelta(days=int(window["days"]))
        if start.tzinfo is None or end.tzinfo is None or start > end:
            return None
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
