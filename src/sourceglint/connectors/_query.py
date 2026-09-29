"""Deterministic query shaping for keyword-oriented source APIs."""
from __future__ import annotations

import re


_STOP_WORDS = {
    "a", "about", "an", "and", "are", "been", "did", "do", "does",
    "for", "from", "had", "has", "have", "how", "in", "is", "it",
    "of", "on", "past", "people", "the", "their", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "why", "with",
    "days", "day", "recently", "discussed",
}


def compact_search_query(value: str, *, max_terms: int = 9, max_chars: int = 96) -> str:
    """Turn a long natural-language question into bounded search terms.

    Short queries are preserved exactly. Long questions are tokenized,
    stripped of common English scaffolding, and bounded for APIs such as npm,
    DEV and Reddit that reject or perform poorly on prompt-length strings.
    """
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return ""
    tokens = [token.strip("._-") for token in re.findall(r"[\w+#.\-]+", normalized)]
    tokens = [token for token in tokens if token]
    if len(normalized) <= max_chars and len(tokens) <= max_terms:
        return normalized
    meaningful = [
        token for token in tokens
        if token.casefold() not in _STOP_WORDS
    ]
    selected = meaningful[:max_terms] or tokens[:max_terms]
    compact = " ".join(selected).strip()
    return compact[:max_chars].rstrip() or normalized[:max_chars].rstrip()


__all__ = ["compact_search_query"]
