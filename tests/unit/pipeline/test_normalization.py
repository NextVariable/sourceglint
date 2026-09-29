"""Tests for Normalization: RawSourceResult -> Evidence (Phase 3 §12).

Contract:
  * Strictly consumes Phase 1 evidence.schema.json (additionalProperties:false).
  * URL canonicalized via ids.canonicalize_url.
  * Snippet hard-capped at 280 chars (deterministic truncation, not LLM summary).
  * Title truncated only if it exceeds 280 chars (title has minLength:1, no max
    in schema; we still cap for sanity to keep ledger readable).
  * Optional fields: ABSENT (not "unknown" / "N/A") when the raw lacks them.
  * Timestamp: rfc3339-validator-friendly. Evidence.published_at absent when
    raw lacks it; Evidence.retrieved_at filled by as_of.
  * engagement normalized: only known keys (upvotes/comments/likes/views/points);
    negatives rejected.
  * window = current/baseline passed through from the request.
  * Generated Evidence must be schema-valid (validate against evidence.schema.json
    in addition to functional assertions).
  * source_tier is derived from source registry, OR falls back to schema-defined
    map (T1=1.0/T2=2/T3=3/T4=4). For MVP, derive by source_type heuristic or
    explicit registry hint.

    Phase 3 simplification: source_tier is derived from a small lookup table:
      official_web  -> 1
      github        -> 1
      host_web_search -> 4
      reddit        -> 2
      hacker_news   -> 2
    Plus: evidence_quality initial value follows the v0.2 §9 tier map.
"""
from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from sourceglint.normalization import (
    EvidenceNormalizationError,
    Normalizer,
    normalize_raw,
    validate_evidence_payload,
)
from sourceglint.pipeline.adapters import RawSourceResult


SOURCE_TIER_MAP = {
    "official_web": 1,
    "github": 1,
    "host_web_search": 4,
    "reddit": 2,
    "hacker_news": 2,
}


def _evidence_schema():
    import json
    from pathlib import Path
    return json.loads(
        (Path(__file__).resolve().parents[3] / "schemas" / "evidence.schema.json")
        .read_text(encoding="utf-8")
    )


def _common_schema():
    import json
    from pathlib import Path
    return json.loads(
        (Path(__file__).resolve().parents[3] / "schemas" / "common.schema.json")
        .read_text(encoding="utf-8")
    )


def _evidence_validator():
    from referencing import Registry, Resource
    reg = (
        Registry()
        .with_resources([("common.schema.json", Resource.from_contents(_common_schema()))])
    )
    return jsonschema.Draft202012Validator(_evidence_schema(), registry=reg)


def _raw(
    *,
    source: str = "reddit",
    source_type: str = "post",
    source_native_id: str = "abc123",
    url: str = "https://reddit.com/r/x/comments/abc",
    title: str = "Title",
    text: str = "Snippet text",
    **overrides,
) -> RawSourceResult:
    base = dict(
        source=source,
        source_type=source_type,
        source_native_id=source_native_id,
        url=url,
        title=title,
        text=text,
    )
    base.update(overrides)
    return RawSourceResult(**base)


def test_normalize_produces_evidence_dict():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z", window="current")
    assert isinstance(e, dict)
    assert e["source"] == "reddit"
    assert e["url"] == "https://reddit.com/r/x/comments/abc"
    assert e["snippet"] == "Snippet text"


def test_normalize_url_canonicalized():
    r = _raw(url="HTTPS://Reddit.com/r/x/comments/abc?utm_source=x")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["url"] == "https://reddit.com/r/x/comments/abc"


def test_normalize_url_lowercases_scheme_and_host():
    r = _raw(url="HTTPS://Reddit.COM/r/x/comments/abc")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["url"].startswith("https://reddit.com/")


def test_normalize_drops_tracking_params():
    r = _raw(url="https://reddit.com/r/x?utm_source=fb&page=2")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert "utm_source" not in e["url"]
    assert "page=2" in e["url"]


def test_normalize_snippet_truncates_at_280():
    long_text = "x" * 500
    r = _raw(text=long_text)
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert len(e["snippet"]) <= 280


def test_normalize_snippet_unicode_preserved():
    r = _raw(text="Notion 値上げが高すぎる — ¥3,980 / 月")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert "値上げ" in e["snippet"]
    assert "¥3,980" in e["snippet"]


def test_normalize_japanese_text_byte_stable():
    text = "日本語のテスト — 文字化けなし"
    r = _raw(text=text)
    a = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    b = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert a["snippet"] == b["snippet"]
    assert a["snippet"] == text


def test_normalize_title_preserved():
    r = _raw(title="Important: pricing changes 2026")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["title"] == "Important: pricing changes 2026"


def test_normalize_published_at_passed_through_when_iso():
    r = _raw(published_at="2026-08-30T12:00:00Z")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["published_at"] == "2026-08-30T12:00:00Z"


def test_normalize_published_at_absent_when_raw_missing():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert "published_at" not in e


def test_normalize_published_at_rejected_when_not_iso():
    r = _raw(published_at="yesterday")
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_retrieved_at_set_from_as_of():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["retrieved_at"] == "2026-09-06T10:00:00Z"


def test_normalize_query_passed_through():
    r = _raw(query="Notion AI pricing", query_language="en")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["query"] == "Notion AI pricing"
    assert e["query_language"] == "en"


def test_normalize_engagement_only_known_keys():
    r = _raw(engagement={"upvotes": 100, "comments": 12, "secret": 5})
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["engagement"] == {"upvotes": 100, "comments": 12}


def test_normalize_engagement_drops_negative():
    r = _raw(engagement={"upvotes": -5})
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_engagement_drops_non_int():
    r = _raw(engagement={"upvotes": "abc"})
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_window_current_default():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["window"] == "current"


def test_normalize_window_baseline():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z", window="baseline")
    assert e["window"] == "baseline"


def test_normalize_window_invalid_rejected():
    r = _raw()
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z", window="weird")


def test_normalize_source_tier_official_web():
    r = _raw(source="official_web", source_type="page")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["source_tier"] == 1


def test_normalize_source_tier_reddit():
    r = _raw(source="reddit")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["source_tier"] == 2


def test_normalize_source_tier_host_web_search():
    r = _raw(source="host_web_search")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["source_tier"] == 4


def test_normalize_evidence_quality_initial_official():
    r = _raw(source="official_web", source_type="page")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["evidence_quality"] == 1.0


def test_normalize_evidence_quality_initial_t2():
    r = _raw(source="reddit")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert abs(e["evidence_quality"] - 0.6) < 1e-9


def test_normalize_evidence_quality_initial_t4():
    r = _raw(source="host_web_search")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert abs(e["evidence_quality"] - 0.3) < 1e-9


def test_normalize_market_passed_through():
    r = _raw(market="jp")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["market"] == "jp"


def test_normalize_locale_passed_through():
    r = _raw(locale="ja-JP")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["locale"] == "ja-JP"


def test_normalize_language_passed_through():
    r = _raw(language="ja")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["language"] == "ja"


def test_normalize_language_default_en_when_absent():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["language"] == "en"


def test_normalize_unknown_source_type_rejected():
    r = _raw(source_type="press_release")
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_url_required():
    """url is required by the evidence contract."""
    r = _raw(url="")
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_invalid_url_scheme_rejected():
    r = _raw(url="ftp://example.com/post")
    with pytest.raises(EvidenceNormalizationError):
        normalize_raw(r, as_of="2026-09-06T10:00:00Z")


def test_normalize_evidence_id_derived():
    """Normalizer generates evidence_id when absent (canonical derivation)."""
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["evidence_id"].startswith("ev_")
    assert len(e["evidence_id"]) == 35


def test_normalize_evidence_id_stable():
    r1 = _raw(url="https://reddit.com/r/x/comments/abc", title="t", text="b")
    r2 = _raw(url="https://reddit.com/r/x/comments/abc", title="t", text="b")
    e1 = normalize_raw(r1, as_of="2026-09-06T10:00:00Z")
    e2 = normalize_raw(r2, as_of="2026-09-06T10:00:00Z")
    assert e1["evidence_id"] == e2["evidence_id"]


def test_normalize_url_canonicalization_yields_same_id_for_variants():
    r1 = _raw(url="HTTPS://Reddit.com/r/x/comments/abc")
    r2 = _raw(url="https://reddit.com/r/x/comments/abc/")
    e1 = normalize_raw(r1, as_of="2026-09-06T10:00:00Z")
    e2 = normalize_raw(r2, as_of="2026-09-06T10:00:00Z")
    assert e1["evidence_id"] == e2["evidence_id"]


def test_normalize_output_passes_schema_validation():
    """The normalized Evidence must be valid against evidence.schema.json."""
    validator = _evidence_validator()
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    validator.validate(e)


def test_normalize_japanese_output_passes_schema_validation():
    """Japanese text doesn't break schema validation."""
    validator = _evidence_validator()
    r = _raw(
        title="Notion 値上げ",
        text="Notionの値上げが高すぎる",
        language="ja",
        market="jp",
        locale="ja-JP",
    )
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    validator.validate(e)


def test_normalize_rejects_extra_field():
    """Schema additionalProperties:false — extras rejected."""
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    # If we tried to attach a new field post-hoc, the schema would reject it.
    e["unknown_field"] = "should_fail"
    validator = _evidence_validator()
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(e)


def test_normalize_tags_passed_through_when_present():
    """Tags field is allowed (optional, array of strings)."""
    # Tags aren't in raw, but Normalizer must NOT add them by default.
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    # tags are downstream-only; raw lacks them; do not fabricate.
    assert "tags" not in e


def test_normalize_class_api_matches_function():
    n = Normalizer(as_of="2026-09-06T10:00:00Z")
    r = _raw()
    a = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    b = n.normalize(r)
    assert a["evidence_id"] == b["evidence_id"]


def test_normalize_determinism_x20():
    r = _raw(url="HTTPS://Reddit.com/r/x/comments/abc?utm_source=x")
    snapshots = [
        json.dumps(normalize_raw(r, as_of="2026-09-06T10:00:00Z"), sort_keys=True)
        for _ in range(20)
    ]
    assert len(set(snapshots)) == 1


def test_normalize_evidence_quality_within_range():
    """evidence_quality is always in [0, 1] when present (None = unknown)."""
    sources = ["official_web", "reddit", "host_web_search"]
    for src in sources:
        r = _raw(source=src)
        e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
        assert 0.0 <= e["evidence_quality"] <= 1.0
    # Unknown source MUST omit the synthetic default (Closeout §3).
    unknown_r = _raw(source="unknown_xyz")
    unknown_e = normalize_raw(unknown_r, as_of="2026-09-06T10:00:00Z")
    assert "evidence_quality" not in unknown_e


def test_normalize_published_at_accepts_plus_offset():
    """Schema is iso_timestamp format date-time — '+09:00' offset is OK."""
    r = _raw(published_at="2026-08-30T12:00:00+09:00")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["published_at"] == "2026-08-30T12:00:00+09:00"


def test_normalize_source_unknown_omits_tier_and_quality():
    """Unknown source MUST NOT be assigned a synthetic T3 / 0.5 default.

    Per Closeout §3: source_tier and evidence_quality are OPTIONAL in the
    Evidence schema. Unknown sources must omit both. Replaces the prior
    'fallback to T3 / 0.5' assertion."""
    r = _raw(source="unknown_source")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert "source_tier" not in e
    assert "evidence_quality" not in e


def test_validate_evidence_payload_helper():
    e = normalize_raw(_raw(), as_of="2026-09-06T10:00:00Z")
    validate_evidence_payload(e)  # no exception


def test_validate_evidence_payload_rejects_unknown_field():
    e = normalize_raw(_raw(), as_of="2026-09-06T10:00:00Z")
    e["unknown"] = "x"
    with pytest.raises(jsonschema.ValidationError):
        validate_evidence_payload(e)


def test_normalize_author_optional_absent():
    r = _raw()
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert "author" not in e


def test_normalize_author_present_passed_through():
    r = _raw(author="u/alice")
    e = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
    assert e["author"] == "u/alice"


# ----- imports at module level for json use -----
import json