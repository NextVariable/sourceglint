"""PRD §36 — no recommendation leakage.

Phase 5 stops at the Signal layer: it states what happened or may be
forming. It never tells anyone what to do. Model output is screened for
recommendation phrasing; a hit is rejected (or stripped + warned) so a
recommendation cannot sneak into a signal claim.
"""
from __future__ import annotations

import re

#: Lower-cased phrases that indicate advisory / recommendation content.
RECOMMENDATION_PATTERNS: tuple[str, ...] = (
    "you should",
    "we should",
    "you must",
    "we recommend",
    "i recommend",
    "recommend ",
    "recommendation:",
    "should target",
    "should invest",
    "increase budget",
    "you need to",
    "consider launching",
    "our recommendation",
)

_PATTERN_RE = re.compile(
    "|".join(re.escape(p) for p in RECOMMENDATION_PATTERNS),
    re.IGNORECASE,
)


def detect_recommendation_leakage(text: str) -> list[str]:
    """Return the recommendation phrases found in `text` (may be empty)."""
    if not text:
        return []
    found = {match.group(0).lower() for match in _PATTERN_RE.finditer(text)}
    return sorted(found)


def has_recommendation_leakage(text: str) -> bool:
    return bool(detect_recommendation_leakage(text))


def screen_texts(*texts: str) -> list[str]:
    """Screen several strings at once (label, claim, rationale, ...)."""
    hits: list[str] = []
    for text in texts:
        for phrase in detect_recommendation_leakage(text):
            if phrase not in hits:
                hits.append(phrase)
    return hits
