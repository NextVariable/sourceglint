from gtm_intelligence.connectors._query import compact_search_query


def test_short_keyword_query_is_preserved():
    assert compact_search_query("AI agents") == "AI agents"


def test_long_natural_language_question_becomes_bounded_keywords():
    query = (
        "What new AI agent tools, workflows, and user needs have people "
        "discussed in the past 30 days? overview"
    )
    compact = compact_search_query(query)
    assert compact == "new AI agent tools workflows user needs 30 overview"
    assert len(compact) <= 96


def test_unicode_topic_survives_query_shaping():
    query = "最近 30 天里日本用户如何讨论 AI エージェント 工作流程以及有哪些问题和需求"
    compact = compact_search_query(query)
    assert "AI" in compact
    assert "日本用户如何讨论" in compact
