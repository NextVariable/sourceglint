"""Phase 7 §12–§14, §39–§42 — deterministic parser eval tests.

The parsing layer is pure deterministic lexical normalization. This
file pins: the 7-mode eval set (§39 A–G), the ambiguity policy (§40),
Chinese input stability (§41) and Japanese input tolerance (§42).
"""
from __future__ import annotations

import pytest

from gtm_intelligence.interface.parser import (
    detect_query_language,
    parse_query,
    parse_request,
    resolve_market,
    resolve_mode,
    resolve_window,
)
from gtm_intelligence.interface.request import SkillRequest


class TestQueryLanguageDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("What changed in Japan?", "en"),
            ("最近日本 AI 会议助手市场有什么变化？", "zh"),
            ("最近のAI会議アシスタント市場の変化を調べてください。", "ja"),
            ("", "en"),
        ],
    )
    def test_detection(self, text, expected):
        assert detect_query_language(text) == expected


class TestModeParsing:
    @pytest.mark.parametrize(
        "query,expected",
        [
            # §39 eval set A–G
            ("What changed in AI meeting assistants recently?", "general"),
            ("What has Otter changed in pricing and positioning recently?", "competitor"),
            ("What are users complaining about in AI translation tools?", "voc"),
            ("What should I know before launching this in Japan?", "launch"),
            ("Which recent creator/channel patterns are emerging?", "channel"),
            ("What new workflows are emerging?", "trend"),
            ("What is changing in the Japanese market?", "market"),
            # zh / ja cues (§41–§42)
            ("最近日本 AI 会议助手市场有什么变化？", "market"),
            ("帮我看最近 Otter 的定价、定位和用户反馈有什么变化。", "competitor"),
            ("最近 Reddit 上大家对 AI 翻译硬件最常抱怨什么？", "voc"),
            ("最近のAI会議アシスタント市場の変化を調べてください。", "market"),
            ("竞争对手在怎么改定价？", "competitor"),
        ],
    )
    def test_lexical_modes(self, query, expected):
        assert resolve_mode(query) == expected

    def test_explicit_mode_wins(self):
        assert resolve_mode("whatever wording", explicit="voc") == "voc"

    def test_unknown_explicit_degrades_to_general(self):
        assert resolve_mode("x", explicit="nope") == "general"

    def test_lexical_failure_degrades_to_general(self):
        assert resolve_mode("Write me a LinkedIn post.") == "general"
        assert resolve_mode("Explain what GTM means.") == "general"


class TestMarketParsing:
    @pytest.mark.parametrize(
        "text,explicit,expected",
        [
            ("What changed in Japan?", "", "jp"),
            ("Japan market", "", "jp"),
            ("日本市場", "", "jp"),
            ("Germany pricing", "", "de"),
            ("US competitors", "", "us"),
            ("英国の動向", "", "gb"),
            ("法国市场", "", "fr"),
            ("China launch", "", "cn"),
            ("no market cue", "", "global"),
            ("anything", "de", "de"),
            ("anything", "JP", "jp"),
            ("anything", "br", "br"),
        ],
    )
    def test_market_resolution(self, text, explicit, expected):
        assert resolve_market(text, explicit=explicit) == expected


class TestWindowParsing:
    def test_explicit_override_wins(self):
        win, text = resolve_window("whatever", window_days=7)
        assert win == {"days": 7}
        assert text == "Last 7 days"

    @pytest.mark.parametrize(
        "phrase,days",
        [
            ("last 7 days", 7),
            ("in the last 90 days", 90),
            ("过去30天", 30),
            ("直近14日", 14),
            ("3 months", 90),
            ("3ヶ月", 90),
            ("quarter", 90),
        ],
    )
    def test_relative_windows(self, phrase, days):
        win, text = resolve_window(phrase)
        assert win == {"days": days}
        assert text == f"Last {days} days"

    def test_default_30(self):
        win, text = resolve_window("What changed in Japan?")
        assert win == {"days": 30}


class TestEntityExtraction:
    def test_research_notion(self):
        p = parse_query("Research Notion.")
        assert p.mode == "general"
        assert p.entities == ("Notion",)
        assert p.target == "Notion"

    def test_competitor_otter_entity(self):
        p = parse_query("What has Otter changed in pricing and positioning recently?")
        assert p.mode == "competitor"
        assert p.entities == ("Otter",)
        assert p.target == "Otter"

    def test_latin_entity_inside_cjk(self):
        p = parse_query("帮我看最近 Otter 的定价、定位和用户反馈有什么变化。")
        assert p.target == "Otter"

    def test_no_entity_for_bare_voc(self):
        p = parse_query("What are users complaining about in AI translation tools?")
        assert p.entities == ()


class TestClarificationPolicy:
    def test_bare_competitors_needs_clarification(self):
        p = parse_query("Research competitors.")
        assert p.needs_clarification
        assert "without a target product" in p.clarification_reason

    def test_named_target_runs(self):
        p = parse_query("What has Otter changed in pricing and positioning recently?")
        assert not p.needs_clarification

    def test_market_competitor_scan_runs(self):
        p = parse_query("What are German competitors doing in pricing?")
        assert not p.needs_clarification

    def test_ordinary_request_never_asks(self):
        p = parse_query("最近日本 AI 会议助手市场有什么变化？")
        assert not p.needs_clarification


class TestLanguageNormalization:
    def test_default_en(self):
        p = parse_query("What changed?")
        assert p.languages == ("en",)

    def test_jp_market_en_first_ja_second(self):
        p = parse_query("What changed in the Japanese market?")
        assert p.languages == ("en", "ja")

    def test_explicit_languages_kept_and_deduped(self):
        p = parse_query(
            "whatever", **{"languages": ("en", "en", "ja")}
        )
        assert p.languages == ("en", "ja")

    def test_chinese_global_query_keeps_zh(self):
        p = parse_query("AI 翻译硬件有哪些变化？")
        assert p.query_language == "zh"
        assert "zh" in p.languages

    def test_japanese_query_never_crashes(self):
        p = parse_query("最近のAI会議アシスタント市場の変化を調べてください。")
        assert p.query_language == "ja"
        assert p.mode in {
            "general", "trend", "competitor", "market", "voc", "launch", "channel"
        }


class TestParseRequestEndToEnd:
    def test_full_normalization_to_plan(self):
        req = SkillRequest(
            query="What has Otter changed in pricing and positioning in Japan recently?"
        )
        parsed = parse_request(req)
        assert parsed.mode == "competitor"
        assert parsed.market == "jp"
        assert parsed.languages == ("en", "ja")
        plan = parsed.to_plan()
        assert plan["mode"] == "competitor"
        assert plan["market"] == "jp"
        assert plan["languages"] == ["en", "ja"]
        assert plan["time_window"] == {"days": 30}
        assert plan["topic"] == req.query
