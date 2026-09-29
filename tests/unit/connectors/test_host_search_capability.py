"""Test contract for Host Web Search capability adapter (Phase 4 §4-§5, §29).

Eight required scenarios from PRD §4:
  - normal result              → list[RawSourceResult], all fields mapped
  - empty result               → []  (success with 0 items)
  - malformed host result      → AdapterInvalidResponse
  - timeout                    → AdapterTimeout
  - unavailable capability     → AdapterUnavailable (None or exception)
  - partial result             → AdapterInvalidResponse per Phase 4 §29
  - URL missing                → AdapterInvalidResponse
  - date missing               → published_at field ABSENT (not "unknown")
  - market/language preserved  → request params flow through capability call

Plus negative-edge tests required by PRD §29:
  - capability missing → AdapterUnavailable
  - search(...) returning None → AdapterInvalidResponse
  - limit clamp to DEFAULT_MAX_PER_QUERY
  - source = "host_web_search" / source_type = "page" pinned
  - host adapter does NOT import WorkBuddy/Claude/Codex (architecture guard)
"""
from __future__ import annotations

from pathlib import Path
from typing import List
import re

import pytest

from sourceglint.connectors import host_search as HOST_SEARCH_MODULE
from sourceglint.connectors.host_search import (
    DEFAULT_MAX_PER_QUERY,
    HostWebSearchAdapter,
    SearchCapabilityTimeout,
    SOURCE_NAME,
    SOURCE_TYPE,
    WebSearchHit,
)
from sourceglint.pipeline.adapters import (
    AdapterInvalidResponse,
    AdapterTimeout,
    AdapterUnavailable,
)


# ---- fake capability helpers -------------------------------------------


class _FakeCapability:
    """Test double that records its calls and returns canned hits."""

    def __init__(
        self,
        hits=None,
        *,
        raises=None,
        timeout=False,
        returns_none=False,
        call_log=None,
    ) -> None:
        self._hits = hits or []
        self._raises = raises
        self._timeout = timeout
        self._returns_none = returns_none
        self.calls: list[dict] = call_log if call_log is not None else []

    def search(self, query, *, language="", market="", start="", end="", limit=10):
        self.calls.append(
            {
                "query": query,
                "language": language,
                "market": market,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        if self._raises is not None:
            raise self._raises
        if self._timeout:
            raise SearchCapabilityTimeout(
                source=SOURCE_NAME, reason="simulated timeout"
            )
        if self._returns_none:
            return None
        return list(self._hits)


def _plan_minimal() -> dict:
    return {"topic": "test", "mode": "general", "time_window": {"days": 30}}


def _request(**overrides) -> dict:
    base = {
        "query": "ai meeting assistant",
        "query_language": "en",
        "market": "global",
        "retrieved_at": "2026-09-06T00:00:00Z",
    }
    base.update(overrides)
    return base


# ---- PRD §4 / §29 normal scenarios ------------------------------------


def test_normal_search_returns_raw_source_results():
    cap = _FakeCapability(
        hits=[
            WebSearchHit(
                url="https://example.com/a",
                title="AI meeting assistant launches",
                snippet="A new tool that…",
                published_at="2026-09-01T12:00:00Z",
                language="en",
            ),
            WebSearchHit(
                url="https://example.com/b",
                title="Pricing wars",
                snippet="competitor cuts…",
                published_at="2026-08-30T09:00:00Z",
                language="en",
            ),
        ]
    )
    adapter = HostWebSearchAdapter(capability=cap)
    plan = _plan_minimal()
    req = _request()

    out = adapter.retrieve(plan=plan, request=req)

    assert len(out) == 2
    assert all(r.source == SOURCE_NAME for r in out)
    assert all(r.source_type == SOURCE_TYPE for r in out)
    assert out[0].url == "https://example.com/a"
    assert out[0].title == "AI meeting assistant launches"
    assert out[0].published_at == "2026-09-01T12:00:00Z"
    assert out[0].language == "en"
    # query metadata is carried into the result
    assert out[0].query == "ai meeting assistant"
    assert out[0].query_language == "en"


def test_empty_search_result_returns_empty_list():
    cap = _FakeCapability(hits=[])
    adapter = HostWebSearchAdapter(capability=cap)
    out = adapter.retrieve(plan=_plan_minimal(), request=_request())
    assert out == []


def test_capability_missing_raises_adapter_unavailable():
    adapter = HostWebSearchAdapter(capability=None)
    with pytest.raises(AdapterUnavailable):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_capability_raises_generic_exception_maps_to_unavailable():
    cap = _FakeCapability(raises=RuntimeError("network blip"))
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterUnavailable) as exc_info:
        adapter.retrieve(plan=_plan_minimal(), request=_request())
    assert "network blip" in str(exc_info.value)


def test_capability_timeout_maps_to_adapter_timeout():
    cap = _FakeCapability(timeout=True)
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterTimeout):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_malformed_hit_raises_adapter_invalid_response():
    """A hit that is not a WebSearchHit raises AdapterInvalidResponse."""

    cap = _FakeCapability(
        hits=[{"url": "https://x", "title": "t"}]  # raw dict, not WebSearchHit
    )
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_partial_hit_missing_required_field_raises_invalid_response():
    """Mixed hits where one lacks a required field → AdapterInvalidResponse
    (PRD §29 spec). Silently dropping would hide a contract violation.
    """

    cap = _FakeCapability(
        hits=[
            WebSearchHit(url="https://a", title="t1"),
            WebSearchHit(url="", title="t2"),  # url missing
        ]
    )
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse) as exc_info:
        adapter.retrieve(plan=_plan_minimal(), request=_request())
    assert "url" in str(exc_info.value).lower()


def test_hit_with_missing_url_is_rejected():
    cap = _FakeCapability(
        hits=[WebSearchHit(url="", title="t", snippet="x")]
    )
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_hit_with_missing_title_is_rejected():
    cap = _FakeCapability(
        hits=[WebSearchHit(url="https://x", title="", snippet="y")]
    )
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_date_missing_results_in_empty_published_at():
    """PRD §4 requires that 'date missing' produces an EMPTY published_at,
    not the string 'unknown' (Closeout §3 invariant: unknown ≠ neutral).
    """

    cap = _FakeCapability(
        hits=[WebSearchHit(url="https://a", title="t", published_at="")]
    )
    adapter = HostWebSearchAdapter(capability=cap)
    out = adapter.retrieve(plan=_plan_minimal(), request=_request())
    assert out[0].published_at == ""


def test_market_and_language_are_preserved_through_capability():
    cap = _FakeCapability()
    adapter = HostWebSearchAdapter(capability=cap)
    adapter.retrieve(
        plan=_plan_minimal(),
        request=_request(query_language="ja", market="jp", query="会議 ai"),
    )
    assert cap.calls[0]["query"] == "会議 ai"
    assert cap.calls[0]["language"] == "ja"
    assert cap.calls[0]["market"] == "jp"


def test_limit_is_clamped_to_max_per_query():
    cap = _FakeCapability()
    adapter = HostWebSearchAdapter(capability=cap)
    adapter.retrieve(
        plan=_plan_minimal(),
        request=_request(limit=10000),
    )
    assert cap.calls[0]["limit"] == DEFAULT_MAX_PER_QUERY


def test_capability_returning_none_maps_to_invalid_response():
    cap = _FakeCapability(returns_none=True)
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan_minimal(), request=_request())


def test_retrieve_request_without_query_raises_invalid_response():
    cap = _FakeCapability()
    adapter = HostWebSearchAdapter(capability=cap)
    with pytest.raises(AdapterInvalidResponse):
        adapter.retrieve(plan=_plan_minimal(), request={"query": ""})


# ---- PRD §5 / §30 architecture guard: no host-specific imports ---------


WORKBUDDY_HINT = re.compile(r"\bworkbuddy\b", re.IGNORECASE)
CLAUDE_HINT = re.compile(r"\bclaude\s+code\b|\bclaudecode\b", re.IGNORECASE)
CODEX_HINT = re.compile(r"\bcodex\b", re.IGNORECASE)


def test_module_source_does_not_import_host_specific_packages():
    """PRD §5: neutral capability boundary; host integration MUST live outside.

    We grep the source of `connectors/host_search.py` for forbidden tokens.
    """

    src_path = Path(HOST_SEARCH_MODULE.__file__)
    text = src_path.read_text(encoding="utf-8")
    # The contract `SearchCapability` deliberately references neither; if
    # a future contributor adds an `import workbuddy.search` for example,
    # this test fails loudly.
    forbidden_patterns = {
        "workbuddy": WORKBUDDY_HINT,
        "claude_code": CLAUDE_HINT,
        "codex": CODEX_HINT,
    }
    for label, pattern in forbidden_patterns.items():
        # Allow the FORBIDDEN tokens only in this test file or in comments
        # that explicitly say "do not import". Strip comments and re-check.
        non_comment = "\n".join(
            line.split("#", 1)[0] for line in text.splitlines()
        )
        assert not pattern.search(non_comment), (
            f"host_search.py imports or references {label!r}; "
            f"host-specific deps must stay in the host integration layer"
        )
