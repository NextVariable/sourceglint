"""Phase 2 deterministic Evidence ID contract tests (TDD)."""
import re

import pytest

from sourceglint.ids import canonicalize_url, derive_evidence_id, normalize_text


PATTERN = re.compile(r"^ev_[0-9a-z]{32}$")


def _ev(**kwargs):
    base = {
        "source": "reddit",
        "source_type": "discussion",
        "url": "https://www.reddit.com/r/AI/comments/123/example/",
        "snippet": "Original snippet text.",
        "author": "alice",
        "published_at": "2026-01-15T10:00:00Z",
    }
    base.update(kwargs)
    return base


class TestCanonicalizeUrl:
    def test_lowercase_scheme_and_host(self):
        assert canonicalize_url("HTTPS://Example.COM/x") == "https://example.com/x"

    def test_strip_fragment(self):
        assert canonicalize_url("https://example.com/x?a=1#section") == "https://example.com/x?a=1"

    def test_sort_query_params(self):
        a = canonicalize_url("https://example.com/x?b=2&a=1")
        b = canonicalize_url("https://example.com/x?a=1&b=2")
        assert a == b == "https://example.com/x?a=1&b=2"

    def test_drop_tracking_params(self):
        url = "https://example.com/x?utm_source=tw&id=1&fbclid=abc"
        assert canonicalize_url(url) == "https://example.com/x?id=1"

    def test_drop_tracking_params_in_any_order(self):
        a = canonicalize_url("https://example.com/x?utm_source=tw&id=1")
        b = canonicalize_url("https://example.com/x?id=1&utm_source=tw")
        assert a == b == "https://example.com/x?id=1"

    def test_collapse_trailing_slash(self):
        assert canonicalize_url("https://example.com/about/") == "https://example.com/about"
        assert canonicalize_url("https://example.com/") == "https://example.com/"

    def test_collapse_repeated_slashes(self):
        assert canonicalize_url("https://example.com//a//b/") == "https://example.com/a/b"

    def test_unicode_url_lowercases_host_only(self):
        # Path may carry unicode; host stays lowercase ASCII.
        out = canonicalize_url("https://EXAMPLE.COM/wiki/%E4%B8%AD%E6%96%87")
        assert out.startswith("https://example.com/wiki/")

    def test_rejects_non_string(self):
        with pytest.raises(TypeError):
            canonicalize_url(None)  # type: ignore[arg-type]


class TestNormalizeText:
    def test_nfkc_full_width_to_ascii(self):
        assert normalize_text("ＡＢＣ １２３") == "ABC 123"

    def test_collapse_whitespace(self):
        assert normalize_text("a  b\tc\n d") == "a b c d"

    def test_collapse_multiple_newlines(self):
        assert normalize_text("a\n\n\nb") == "a b"


class TestDeriveEvidenceId:
    def test_returns_deterministic_format(self):
        out = derive_evidence_id(_ev())
        assert PATTERN.match(out), f"unexpected id format: {out}"

    def test_same_input_same_id(self):
        a = derive_evidence_id(_ev())
        b = derive_evidence_id(_ev())
        assert a == b

    def test_different_input_different_id(self):
        a = derive_evidence_id(_ev(snippet="A"))
        b = derive_evidence_id(_ev(snippet="B"))
        assert a != b

    def test_url_trailing_slash_collision(self):
        a = derive_evidence_id(_ev(url="https://www.reddit.com/r/x/comments/1/a"))
        b = derive_evidence_id(_ev(url="https://www.reddit.com/r/x/comments/1/a/"))
        assert a == b

    def test_url_query_param_order_collision(self):
        a = derive_evidence_id(_ev(url="https://x.com/p?a=1&b=2"))
        b = derive_evidence_id(_ev(url="https://x.com/p?b=2&a=1"))
        assert a == b

    def test_url_tracking_param_dropped(self):
        a = derive_evidence_id(_ev(url="https://x.com/p?id=1"))
        b = derive_evidence_id(_ev(url="https://x.com/p?id=1&utm_source=tw"))
        assert a == b

    def test_url_fragment_dropped(self):
        a = derive_evidence_id(_ev(url="https://x.com/p"))
        b = derive_evidence_id(_ev(url="https://x.com/p#section"))
        assert a == b

    def test_url_case_irrelevant_for_host(self):
        a = derive_evidence_id(_ev(url="https://X.com/p"))
        b = derive_evidence_id(_ev(url="https://x.com/p"))
        assert a == b

    def test_enrichment_metadata_does_not_change_id(self):
        # retrieved_at, engagement, tags, query, evidence_quality MUST NOT
        # alter id (otherwise re-retrieval produces new ids and dedup breaks).
        e1 = _ev()
        e2 = _ev()
        e2.update(
            {
                "retrieved_at": "2026-12-31T23:59:59Z",
                "engagement": {"upvotes": 99999, "comments": 500},
                "tags": ["hot", "viral"],
                "query": "different query string",
                "evidence_quality": 0.99,
            }
        )
        assert derive_evidence_id(e1) == derive_evidence_id(e2)

    def test_unicode_content_stability(self):
        a = derive_evidence_id(_ev(snippet="テスト AI 要約"))
        b = derive_evidence_id(_ev(snippet="　テスト\nAI\n　 要約"))
        assert a == b

    def test_url_only_no_snippet_uses_empty_content(self):
        # Missing snippet is allowed; identity reduces to URL + author + date.
        # Both versions must agree as long as those fields agree.
        a = derive_evidence_id(_ev(snippet=""))
        b = derive_evidence_id(_ev(snippet=""))
        assert a == b
        # And differs when URL differs:
        c = derive_evidence_id(_ev(snippet="", url="https://www.reddit.com/r/AI/comments/999/different/"))
        assert a != c

    def test_rejects_missing_url(self):
        e = _ev()
        e["url"] = ""
        with pytest.raises(ValueError, match="url missing"):
            derive_evidence_id(e)

    def test_rejects_missing_source(self):
        e = _ev()
        e["source"] = ""
        with pytest.raises(ValueError, match="source missing"):
            derive_evidence_id(e)

    def test_rejects_non_mapping(self):
        with pytest.raises(TypeError):
            derive_evidence_id(None)  # type: ignore[arg-type]


class TestEvidenceIdMonotonicity:
    """Two similar but not identical inputs MUST differ."""

    def test_author_changes_id(self):
        a = derive_evidence_id(_ev(author="alice"))
        b = derive_evidence_id(_ev(author="bob"))
        assert a != b

    def test_published_at_changes_id(self):
        a = derive_evidence_id(_ev(published_at="2026-01-15T10:00:00Z"))
        b = derive_evidence_id(_ev(published_at="2026-01-15T10:00:01Z"))
        assert a != b

    def test_source_changes_id(self):
        a = derive_evidence_id(_ev(source="reddit"))
        b = derive_evidence_id(_ev(source="hacker_news"))
        assert a != b
