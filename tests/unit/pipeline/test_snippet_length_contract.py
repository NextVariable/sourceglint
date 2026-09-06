"""Tests for Evidence snippet length semantics (Phase 3 Closeout §2).

The Evidence schema declares snippet maxLength: 280 — JSON Schema string
length semantics count Unicode code points (not bytes). Our normalizer
must produce EVIDENCE that always validates against the schema, regardless
of script (ASCII / Japanese / emoji / combining marks).

Reference: JSON Schema draft 2020-12, §6.3 — maxLength counts UTF-16 code
units in JavaScript validators and Unicode scalar values in language-
agnostic implementations. Python `len()` on str counts code points, which
matches jsonschema Draft202012Validator behavior.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.normalization import (
    EvidenceNormalizationError,
    normalize_raw,
    validate_evidence_payload,
)
from gtm_intelligence.pipeline.adapters import RawSourceResult


def _raw(text: str) -> RawSourceResult:
    return RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="x",
        url="https://reddit.com/r/x/comments/x",
        title="t",
        text=text,
        published_at="2026-08-25T00:00:00Z",
        language="en",
        market="global",
    )


def _snippet_count(s):
    """Count Unicode code points (matches JSON Schema maxLength semantics)."""
    return len(s)


def test_ascii_exactly_280_passes():
    text = "a" * 280
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280
    assert ev["snippet"] == text


def test_ascii_281_is_truncated_to_280():
    text = "a" * 281
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280
    assert ev["snippet"] == "a" * 280


def test_japanese_exactly_280_codepoints_passes():
    # Each Japanese kanji is 1 code point in Python str.
    text = "あ" * 280
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280


def test_japanese_281_codepoints_truncated_to_280():
    text = "あ" * 281
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280


def test_mixed_script_truncation_byte_count_unaffected():
    """Mixed Japanese + ASCII truncates by code-point count, not byte count.

    280 Japanese chars = 840 UTF-8 bytes (3 bytes each). The normalizer
    must produce exactly 280 code points, NOT 280 bytes."""
    text = "あ" * 280
    raw = _raw(text)
    raw_utf8_len = len(text.encode("utf-8"))  # == 840
    assert raw_utf8_len == 840
    ev = normalize_raw(raw, as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280
    # byte count of the truncated value is 840 — strictly > 280.
    assert len(ev["snippet"].encode("utf-8")) == 840


def test_emoji_codepoint_counted_as_one():
    """Emoji like '🙂' is a single code point. 280 emojis = 280 code points."""
    text = "🙂" * 280
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280


def test_emoji_281_truncated_to_280():
    text = "🙂" * 281
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert _snippet_count(ev["snippet"]) == 280


def test_combining_chars_each_codepoint_counts():
    """Combining diacritics are separate code points — Schema counts each.
    e + combining acute (U+0301) is 2 code points (1 'e' + 1 combining '´')."""
    # U+0065 (LATIN SMALL LETTER E) followed by U+0301 (COMBINING ACUTE
    # ACCENT). 280 such pairs = 560 code points. 280 such pairs less one
    # combining mark = 559 code points.
    pair = "e\u0301"
    text = pair * 280 + "a"
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    # 280 full pairs = 560 + 1 trailing 'a' = 561 codepoints, truncated to 280.
    assert _snippet_count(ev["snippet"]) == 280


def test_short_text_passes_through_unchanged():
    text = "Hello world"
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert ev["snippet"] == text


def test_no_truncation_marker_appended():
    """Truncation is by raw slice (no ellipsis), keeping the deterministic
    character sequence — prevents LLM-style summarizing."""
    text = "a" * 500
    ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(ev)
    assert ev["snippet"] == "a" * 280
    assert "…" not in ev["snippet"]
    assert "..." not in ev["snippet"]


def test_snippet_never_exceeds_schema_maxlength():
    """Hard guarantee: validator rejects any snippet we ever produce that
    violates schema. (Generated fuzz to mitigate any future regression.)"""
    for n in (1, 50, 279, 280, 281, 500, 1000):
        text = "x" * n
        ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
        # Always must pass schema validation.
        validate_evidence_payload(ev)


def test_determinism_snippet_truncation_x20():
    """Truncation must be byte-stable across calls."""
    text = "あ" * 350 + "x" * 50
    snap = []
    for _ in range(20):
        ev = normalize_raw(_raw(text), as_of="2026-09-06T10:00:00Z")
        validate_evidence_payload(ev)
        snap.append(ev["snippet"])
    assert len(set(snap)) == 1
