"""Contract tests for evidence.schema.json.

Derived from v0.2 Architecture Baseline §9 + D3 (market/locale/language/query_language
fields first-class) + PRD Evidence Ledger requirements.

Covers: valid / invalid / boundary / schema-vs-referential-integrity separation.
"""

from __future__ import annotations

import pytest

from conftest import validate


def _minimal_evidence(**overrides):
    ev = {
        "evidence_id": "ev_reddit_a1b2c3",
        "source": "reddit",
        "source_tier": 2,
        "source_type": "comment",
        "author": "u/francis",
        "title": "Thread title",
        "snippet": "verbatim user quote, ≤280 chars",
        "url": "https://www.reddit.com/r/x/comments/abc/",
        "published_at": "2026-08-30T12:00:00Z",
        "retrieved_at": "2026-09-06T09:30:00Z",
        "market": "jp",
        "locale": "ja-JP",
        "language": "ja",
        "query_language": "en",
        "engagement": {"upvotes": 342, "comments": 87},
        "evidence_quality": 0.62,
        "query": "notion 高い 替代",
        "window": "current",
        "tags": ["pricing", "complaint"],
    }
    ev.update(overrides)
    return ev


# ---------------------------------------------------------------- valid cases

class TestEvidenceValid:
    def test_full_evidence(self, evidence_schema):
        validate(_minimal_evidence(), evidence_schema)

    def test_minimal_required_only(self, evidence_schema):
        ev = {
            "evidence_id": "ev_web_a1b2c3d4e5f6",
            "source": "official_web",
            "source_tier": 1,
            "source_type": "page",
            "snippet": "Pricing page copy",
            "url": "https://example.com/pricing",
            "retrieved_at": "2026-09-06T09:30:00Z",
        }
        validate(ev, evidence_schema)

    def test_global_market_default(self, evidence_schema):
        ev = _minimal_evidence(market="global", language="en")
        validate(ev, evidence_schema)

    def test_multilingual_fields(self, evidence_schema):
        """D3: market/locale/language/query_language independently expressible."""
        ev = _minimal_evidence(
            market="de", locale="de-DE", language="de", query_language="en"
        )
        validate(ev, evidence_schema)

    def test_engagement_empty_object(self, evidence_schema):
        ev = _minimal_evidence(engagement={})
        validate(ev, evidence_schema)

    def test_unknown_author_via_absent(self, evidence_schema):
        """Unknown author expressed by omitting field (not null)."""
        ev = _minimal_evidence()
        del ev["author"]
        validate(ev, evidence_schema)

    def test_tags_empty_list(self, evidence_schema):
        ev = _minimal_evidence(tags=[])
        validate(ev, evidence_schema)

    def test_baseline_window(self, evidence_schema):
        ev = _minimal_evidence(window="baseline")
        validate(ev, evidence_schema)

    def test_null_semantics_snippet_absent(self, evidence_schema):
        """Null snippet not allowed by schema (absent instead)."""
        ev = _minimal_evidence()
        del ev["snippet"]
        validate(ev, evidence_schema)


# --------------------------------------------------------------- invalid cases

class TestEvidenceInvalid:
    def test_missing_required_evidence_id(self, evidence_schema):
        ev = _minimal_evidence()
        del ev["evidence_id"]
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_missing_required_source(self, evidence_schema):
        ev = _minimal_evidence()
        del ev["source"]
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_source_type_enum(self, evidence_schema):
        ev = _minimal_evidence(source_type="tweet")  # not in enum
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_timestamp_format(self, evidence_schema):
        ev = _minimal_evidence(published_at="2026/08/30")
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_url_format(self, evidence_schema):
        ev = _minimal_evidence(url="not-a-url")
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_evidence_quality_out_of_range(self, evidence_schema):
        ev = _minimal_evidence(evidence_quality=1.5)
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_market_code(self, evidence_schema):
        ev = _minimal_evidence(market="日本")  # not global / not 2-letter
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_language_code(self, evidence_schema):
        ev = _minimal_evidence(language="en-US")  # language must be bare code
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_locale_code(self, evidence_schema):
        ev = _minimal_evidence(locale="日本")
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_invalid_window_value(self, evidence_schema):
        ev = _minimal_evidence(window="future")
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_unknown_property_rejected(self, evidence_schema):
        ev = _minimal_evidence()
        ev["fabricated"] = True
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_engagement_non_numeric(self, evidence_schema):
        ev = _minimal_evidence(engagement={"upvotes": "many"})
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_wrong_evidence_id_prefix(self, evidence_schema):
        ev = _minimal_evidence(evidence_id="sig_reddit_a1b2c3")
        with pytest.raises(Exception):
            validate(ev, evidence_schema)


# -------------------------------------------------------------- boundary cases

class TestEvidenceBoundary:
    def test_snippet_280_chars_boundary(self, evidence_schema):
        """Snippet is verbatim quote with hard 280 cap (v0.2 §9)."""
        ev = _minimal_evidence(snippet="x" * 280)
        validate(ev, evidence_schema)

    def test_snippet_over_280_rejected(self, evidence_schema):
        ev = _minimal_evidence(snippet="x" * 281)
        with pytest.raises(Exception):
            validate(ev, evidence_schema)

    def test_zero_engagement(self, evidence_schema):
        ev = _minimal_evidence(engagement={"upvotes": 0, "comments": 0})
        validate(ev, evidence_schema)

    def test_quality_zero_and_one(self, evidence_schema):
        validate(_minimal_evidence(evidence_quality=0.0), evidence_schema)
        validate(_minimal_evidence(evidence_quality=1.0), evidence_schema)

    def test_timestamp_timezone_offset_allowed(self, evidence_schema):
        """RFC3339 allows offsets; contract stores UTC-preferred but accepts offset."""
        ev = _minimal_evidence(published_at="2026-08-30T12:00:00+09:00")
        validate(ev, evidence_schema)

    def test_no_evidence_id_collision_semantics_in_schema(self, evidence_schema):
        """Schema cannot know whether an id collides — that is validator's job.
        This documents the schema/validator boundary (Phase 1 scope)."""
        ev = _minimal_evidence()
        validate(ev, evidence_schema)  # no assertion, documents boundary
