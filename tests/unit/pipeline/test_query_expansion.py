"""Tests for deterministic Query Expansion (Phase 3 §4).

Contract:
  * Pure deterministic expansion (no LLM, no network, no clock).
  * Explicit `queries` on the Research Plan are preserved verbatim.
  * Each expanded query carries `query_language` (D3).
  * Mode-specific intent priorities:
      competitor → exact, comparison, alternative, complaint, commercial
      voc        → problem, complaint, alternative, local_language
      trend      → category, problem, emerging_terminology, comparison
      general    → category, problem, exact
      market     → category, exact, problem, local_language
      launch     → exact, comparison, complaint, commercial
      channel    → category, alternative, commercial, emerging_terminology
  * Stable ordering: explicit queries first (preserved order), then expansions
    grouped by intent, intent order = the priority list above.
  * Cap total queries at QUERY_EXPANSION_MAX (=24) by intent priority.
  * Never invent translations for languages that the plan didn't list.
"""
from __future__ import annotations

from sourceglint.pipeline.query_expansion import (
    QUERY_EXPANSION_MAX,
    QueryExpander,
    ExpandedQuery,
    expand_queries,
)


def _plan(**overrides):
    base = {
        "topic": "Notion AI",
        "mode": "competitor",
        "market": "global",
        "locale": "en",
        "languages": ["en"],
        "time_window": {"days": 30},
        "entities": ["Notion"],
        "decision_context": "watch pricing changes",
    }
    base.update(overrides)
    return base


def test_expand_preserves_explicit_queries_first():
    plan = _plan(queries=["explicit-query-1", "explicit-query-2"])
    result = expand_queries(plan)
    assert result[0].text == "explicit-query-1"
    assert result[1].text == "explicit-query-2"
    # All explicit queries must keep their declared query_language from plan.
    for q in result[:2]:
        assert q.query_language == "en"
        assert q.intent == "explicit"


def test_expand_deterministic_for_same_plan():
    plan = _plan()
    a = expand_queries(plan)
    b = expand_queries(plan)
    assert [q.text for q in a] == [q.text for q in b]
    assert [q.intent for q in a] == [q.intent for q in b]


def test_competitor_mode_priority_intents():
    plan = _plan(mode="competitor")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    # First non-explicit intents must follow the competitor priority list.
    assert intents[:5] == [
        "exact",
        "comparison",
        "alternative",
        "complaint",
        "commercial",
    ]


def test_voc_mode_priority_intents():
    plan = _plan(mode="voc")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:4] == [
        "problem",
        "complaint",
        "alternative",
        "local_language",
    ]


def test_trend_mode_priority_intents():
    plan = _plan(mode="trend")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:4] == [
        "category",
        "problem",
        "emerging_terminology",
        "comparison",
    ]


def test_general_mode_priority_intents():
    plan = _plan(mode="general")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:3] == ["exact", "category", "problem"]


def test_market_mode_priority_intents():
    plan = _plan(mode="market")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:4] == [
        "category",
        "exact",
        "problem",
        "local_language",
    ]


def test_launch_mode_priority_intents():
    plan = _plan(mode="launch")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:4] == ["exact", "comparison", "complaint", "commercial"]


def test_channel_mode_priority_intents():
    plan = _plan(mode="channel")
    intents = [q.intent for q in expand_queries(plan) if q.intent != "explicit"]
    assert intents[:4] == [
        "category",
        "alternative",
        "commercial",
        "emerging_terminology",
    ]


def test_query_language_per_query_for_multilingual_plan():
    plan = _plan(mode="competitor", languages=["en", "ja"], market="jp", locale="ja-JP")
    seen_langs = {q.query_language for q in expand_queries(plan)}
    # Both languages must appear across the expanded queries.
    assert "en" in seen_langs
    assert "ja" in seen_langs


def test_no_translation_when_localized_query_missing():
    """Without explicit localized queries, do not fabricate translations."""
    plan = _plan(mode="voc", languages=["ja"], entities=["Notion"])
    queries = expand_queries(plan)
    # No Japanese text should appear unless explicit, because expander does
    # not fabricate translations — it relies on plan-level `queries` only.
    # It MAY emit a latin-character expansion that mentions the entity name.
    # Verify no Japanese characters were fabricated:
    ja_chars = any(ord(c) > 0x3000 for q in queries for c in q.text)
    assert not ja_chars


def test_explicit_query_in_japanese_preserved():
    plan = _plan(
        mode="competitor",
        languages=["en", "ja"],
        queries=["Notion 料金"],
    )
    queries = expand_queries(plan)
    # Explicit JP query is preserved with query_language=ja.
    jp_q = next(q for q in queries if q.text == "Notion 料金")
    assert jp_q.query_language == "ja"
    assert jp_q.intent == "explicit"


def test_caps_total_under_or_equal_max():
    plan = _plan(mode="competitor", languages=["en", "ja", "de"])
    queries = expand_queries(plan)
    assert len(queries) <= QUERY_EXPANSION_MAX


def test_explicit_queries_do_not_count_against_cap_priority():
    """Explicit queries come first; cap is applied after them."""
    plan = _plan(
        mode="competitor",
        queries=["explicit-1", "explicit-2"],
        languages=["en"],
    )
    queries = expand_queries(plan)
    # The two explicit queries come first; rest are capped to QUERY_EXPANSION_MAX - 2.
    assert queries[0].text == "explicit-1"
    assert queries[1].text == "explicit-2"
    assert len(queries) <= QUERY_EXPANSION_MAX


def test_entity_appears_in_expansions():
    plan = _plan(entities=["Notion"])
    texts = [q.text for q in expand_queries(plan)]
    assert any("Notion" in t for t in texts)


def test_empty_entities_still_produces_topic_queries():
    plan = _plan(entities=[], topic="AI Meeting Assistant")
    queries = expand_queries(plan)
    assert queries  # non-empty
    assert any("AI Meeting Assistant" in q.text for q in queries)


def test_query_expander_class_api_matches_function():
    plan = _plan()
    expander = QueryExpander()
    fn_out = expand_queries(plan)
    cls_out = expander.expand(plan)
    assert [q.text for q in fn_out] == [q.text for q in cls_out]


def test_each_query_has_query_language_required():
    plan = _plan(languages=["en"])
    for q in expand_queries(plan):
        assert q.query_language in {"en"}


def test_market_field_preserved_on_query():
    plan = _plan(market="jp")
    for q in expand_queries(plan):
        assert q.market == "jp"


def test_invalid_mode_raises():
    plan = _plan(mode="does_not_exist")
    try:
        expand_queries(plan)
    except ValueError:
        return
    raise AssertionError("expected ValueError for invalid mode")


def test_expansion_stable_across_20_runs():
    """Determinism gate: 20 identical runs produce identical result."""
    plan = _plan(mode="competitor", languages=["en", "ja"], entities=["Notion"])
    snapshots = [
        tuple((q.text, q.intent, q.query_language) for q in expand_queries(plan))
        for _ in range(20)
    ]
    first = snapshots[0]
    assert all(s == first for s in snapshots)


def test_unknown_intent_label_filtered_out():
    """Only intents defined in MODE_INTENT_PRIORITY may be emitted."""
    plan = _plan(mode="competitor")
    allowed_intents = {
        "explicit", "exact", "category", "problem", "alternative",
        "comparison", "complaint", "commercial", "local_language",
        "emerging_terminology",
    }
    for q in expand_queries(plan):
        assert q.intent in allowed_intents


def test_expansion_market_field_stable_for_global():
    plan = _plan(market="global")
    for q in expand_queries(plan):
        assert q.market == "global"


def test_competitor_japanese_plan_emits_ja_query_when_localized_in_explicit():
    """If plan queries already include JP, query_language=ja emitted."""
    plan = _plan(
        mode="competitor",
        languages=["en", "ja"],
        market="jp",
        locale="ja-JP",
        queries=[
            "Notion 値上げ",
            "Notion AI vs 代替",
            "Notion pricing complaints",
        ],
    )
    queries = expand_queries(plan)
    ja_queries = [q for q in queries if q.query_language == "ja"]
    # At least the 2 explicit JP queries are emitted as ja-language.
    assert len(ja_queries) >= 2
