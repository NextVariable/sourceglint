"""Phase 5 §6 — deterministic evidence preparation (RED-first).

Before anything reaches the semantic model, code must produce a stable,
minimal, size-bounded view of the Evidence Ledger. The model never sees
raw_metadata, never sees URLs, and never sees the full ledger.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.intelligence.dtos import PreparedEvidence
from gtm_intelligence.intelligence.preparation import (
    MAX_SNIPPET_CHARS,
    MAX_TITLE_CHARS,
    prepare_evidence,
)


def _ev(
    evidence_id: str,
    *,
    source: str = "reddit",
    source_type: str = "post",
    url: str | None = None,
    title: str = "",
    snippet: str = "",
    published_at: str = "",
    market: str = "global",
    language: str = "en",
    window: str | None = None,
    source_tier: int | None = None,
    evidence_quality: float | None = None,
    engagement: dict | None = None,
) -> dict:
    payload: dict = {
        "evidence_id": evidence_id,
        "source": source,
        "source_type": source_type,
        "url": url or f"https://example.com/{evidence_id}",
        "retrieved_at": "2026-09-01T00:00:00Z",
    }
    if title:
        payload["title"] = title
    if snippet:
        payload["snippet"] = snippet
    if published_at:
        payload["published_at"] = published_at
    if market:
        payload["market"] = market
    if language:
        payload["language"] = language
    if window is not None:
        payload["window"] = window
    if source_tier is not None:
        payload["source_tier"] = source_tier
    if evidence_quality is not None:
        payload["evidence_quality"] = evidence_quality
    if engagement is not None:
        payload["engagement"] = engagement
    return payload


# --- ordering ---------------------------------------------------------------


def test_prepare_sorts_by_evidence_id_for_stable_ordering():
    out = prepare_evidence([_ev("ev_c"), _ev("ev_a"), _ev("ev_b")])
    assert [p.evidence_id for p in out] == ["ev_a", "ev_b", "ev_c"]


def test_prepare_ordering_is_independent_of_input_order():
    forward = prepare_evidence([_ev("ev_1"), _ev("ev_2"), _ev("ev_3")])
    backward = prepare_evidence([_ev("ev_3"), _ev("ev_2"), _ev("ev_1")])
    assert [p.evidence_id for p in forward] == [p.evidence_id for p in backward]


# --- duplicate / identity ---------------------------------------------------


def test_prepare_drops_duplicate_evidence_ids():
    out = prepare_evidence([_ev("ev_a"), _ev("ev_a")])
    assert [p.evidence_id for p in out] == ["ev_a"]


def test_prepare_duplicate_ids_record_a_warning():
    _out, warnings = prepare_evidence(
        [_ev("ev_a"), _ev("ev_a")], with_warnings=True
    )
    assert any("duplicate" in w for w in warnings)


# --- unknown semantics (Closeout §3: unknown != neutral) --------------------


def test_prepare_absent_window_defaults_to_current():
    out = prepare_evidence([_ev("ev_a")])
    assert out[0].window == "current"


def test_prepare_absent_published_at_is_empty_not_synthesised():
    out = prepare_evidence([_ev("ev_a")])
    assert out[0].published_at == ""


def test_prepare_absent_tier_and_quality_stay_none():
    out = prepare_evidence([_ev("ev_a")])
    assert out[0].source_tier is None
    assert out[0].evidence_quality is None


def test_prepare_keeps_known_tier_and_quality():
    out = prepare_evidence([_ev("ev_a", source_tier=1, evidence_quality=1.0)])
    assert out[0].source_tier == 1
    assert out[0].evidence_quality == 1.0


# --- text handling ----------------------------------------------------------


def test_prepare_flags_evidence_without_any_text():
    out = prepare_evidence([_ev("ev_a")])
    assert out[0].has_text is False


def test_prepare_flags_evidence_with_snippet_only():
    out = prepare_evidence([_ev("ev_a", snippet="quoted text")])
    assert out[0].has_text is True


def test_prepare_preserves_japanese_text_verbatim():
    jp = "翻訳の遅延がひどくて実務で使えない"
    out = prepare_evidence([_ev("ev_a", snippet=jp, language="ja")])
    assert out[0].snippet == jp
    assert out[0].language == "ja"


# --- model payload minimality (PRD §6) --------------------------------------


def test_model_payload_is_minimal_and_excludes_url():
    out = prepare_evidence(
        [_ev("ev_a", url="https://secret.example.com/x", snippet="s")]
    )
    payload = out[0].to_model_payload()
    assert payload["evidence_id"] == "ev_a"
    assert "url" not in payload


def test_model_payload_never_leaks_raw_metadata_bag():
    raw = _ev("ev_a", snippet="s")
    raw["tags"] = ["internal"]
    raw["query"] = "some query"
    out = prepare_evidence([raw])
    payload = out[0].to_model_payload()
    assert "tags" not in payload
    assert "query" not in payload
    assert "engagement" not in payload


def test_model_payload_omits_empty_optional_fields():
    out = prepare_evidence([_ev("ev_a", published_at="", market="")])
    payload = out[0].to_model_payload()
    assert "published_at" not in payload
    assert "market" not in payload


def test_model_payload_includes_window_always():
    out = prepare_evidence([_ev("ev_a")])
    assert out[0].to_model_payload()["window"] == "current"


def test_model_payload_truncates_overlong_snippet():
    long = "x" * (MAX_SNIPPET_CHARS + 500)
    out = prepare_evidence([_ev("ev_a", snippet=long)])
    payload = out[0].to_model_payload()
    assert len(payload["snippet"]) == MAX_SNIPPET_CHARS


def test_model_payload_truncates_overlong_title():
    long = "t" * (MAX_TITLE_CHARS + 500)
    out = prepare_evidence([_ev("ev_a", title=long)])
    payload = out[0].to_model_payload()
    assert len(payload["title"]) == MAX_TITLE_CHARS


def test_model_payload_truncation_is_codepoint_not_byte():
    # 300 full-width chars: already <= 280 code points, must not be cut.
    jp = "あ" * 300
    out = prepare_evidence([_ev("ev_a", snippet=jp, language="ja")])
    payload = out[0].to_model_payload()
    assert payload["snippet"] == jp[:MAX_SNIPPET_CHARS]
    assert len(payload["snippet"]) == MAX_SNIPPET_CHARS


# --- engagement / window ----------------------------------------------------


def test_prepare_reads_engagement_counters():
    out = prepare_evidence([_ev("ev_a", engagement={"upvotes": 12, "comments": 3})])
    assert out[0].engagement["upvotes"] == 12
    assert out[0].engagement["comments"] == 3


def test_prepare_baseline_window_is_preserved():
    out = prepare_evidence([_ev("ev_a", window="baseline")])
    assert out[0].window == "baseline"


# --- DTO shape --------------------------------------------------------------


def test_prepared_evidence_is_frozen():
    out = prepare_evidence([_ev("ev_a")])
    with pytest.raises(Exception):
        out[0].evidence_id = "ev_z"  # type: ignore[misc]


def test_prepare_returns_empty_for_empty_ledger():
    assert prepare_evidence([]) == []


def test_prepared_evidence_keeps_url_for_independence_math():
    """PRD §13 needs canonical URL/domain for source independence, so the
    DTO keeps it even though the model payload omits it."""
    out = prepare_evidence([_ev("ev_a", url="https://news.ycombinator.com/item?id=1")])
    assert out[0].url == "https://news.ycombinator.com/item?id=1"


def test_prepare_exposes_evidence_class_or_dto():
    out = prepare_evidence([_ev("ev_a")])
    assert isinstance(out[0], PreparedEvidence)
