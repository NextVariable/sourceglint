"""Phase 7 §12–§14 — deterministic intent / market / language / window parsing.

No LLM is used to recognise modes (§12). The chain is:

    explicit mode (when the host set one)
    -> lexical cues (ordered, deterministic regexes)
    -> fallback ``general``

Mode-selection failure degrades to ``general`` and NEVER blocks
execution. Market parsing is a small ISO-ish table plus raw-string
fallback; multi-market queries are noted but the engine runs single-
market (a limitation, recorded — no silent merge, §13).
"""
from __future__ import annotations

import re

from .request import (
    DEFAULT_DAYS,
    MARKET_LANGUAGES,
    MODES,
    ParsedRequest,
    SkillRequest,
)

# ---------------------------------------------------------------- language --

_KANA = re.compile(r"[\u3040-\u30ff]")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def detect_query_language(text: str) -> str:
    """Surface language of the query: 'ja' if kana present, 'zh' if Han
    characters present, otherwise 'en'. Deterministic, order matters."""
    if not text:
        return "en"
    if _KANA.search(text):
        return "ja"
    if _HAN.search(text):
        return "zh"
    return "en"


# ------------------------------------------------------------------ market --

# ISO-ish alias table + the canonical market code. Keys are lowercased.
_MARKET_ALIASES: dict[str, str] = {
    "jp": "jp",
    "japan": "jp",
    "japanese": "jp",
    "日本": "jp",
    "de": "de",
    "deutschland": "de",
    "germany": "de",
    "german": "de",
    "德国": "de",
    "ドイツ": "de",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "america": "us",
    "american": "us",
    "美国": "us",
    "米国": "us",
    "uk": "gb",
    "gb": "gb",
    "britain": "gb",
    "united kingdom": "gb",
    "英国": "gb",
    "イギリス": "gb",
    "fr": "fr",
    "france": "fr",
    "french": "fr",
    "法国": "fr",
    "フランス": "fr",
    "kr": "kr",
    "korea": "kr",
    "korean": "kr",
    "韩国": "kr",
    "cn": "cn",
    "china": "cn",
    "中国": "cn",
    "global": "global",
}
_MARKET_TOKEN = re.compile(
    r"\b(japan|japanese|jp|deutschland|germany|german|de|usa|united states|america|"
    r"us|uk|britain|united kingdom|france|french|korea|korean|china|global)\b",
    re.IGNORECASE,
)
_CJK_MARKET_TOKEN = re.compile(r"日本|美国|英国|德国|法国|韩国|中国|米国")


def resolve_market(text: str, explicit: str = "") -> str:
    """ISO-ish market code; 'global' when nothing is recognisable."""
    if explicit:
        key = explicit.strip().lower()
        if key in _MARKET_ALIASES:
            return _MARKET_ALIASES[key]
        # Allow a bare ISO code not in the alias table (e.g. 'br').
        if re.fullmatch(r"[a-z]{2}", key):
            return key
    m = _MARKET_TOKEN.search(text)
    if m:
        return _MARKET_ALIASES[m.group(1).lower()]
    m = _CJK_MARKET_TOKEN.search(text)
    if m:
        return _MARKET_ALIASES[m.group(0)]
    return "global"


# -------------------------------------------------------------------- mode --

# Ordered lexical cues. First match wins; explicit mode wins over all.
_MODE_CUES: tuple[tuple[tuple[str, ...], str], ...] = (
    # launch — go-to-market / entry events.
    (
        (
            r"\b(launch(ing|ed|es)?|rollout|roll ?out|release)\b",
            r"\benter(ing)?\s+the\b",
            "上市",
            "発売",
            "ローンチ",
            "进入.*市场",
            "進出",
        ),
        "launch",
    ),
    # channel — creators / channels / influencers / KOL.
    (
        (
            r"\b(creator|creators|channel|channels|influencer|influencers|kol|"
            r"partnerships?)\b",
            "频道",
            "创作者",
            "クリエイター",
            "チャンネル",
            "インフルエンサー",
        ),
        "channel",
    ),
    # trend — emerging workflows / adoption / direction of travel.
    (
        (
            r"\btrend(s|ing)?\b",
            r"\bemerging\b",
            r"\bnew workflows?\b",
            r"\bnew patterns?\b",
            r"\badoption\b",
            r"\bwhat'?s new\b",
            "趋势",
            "トレンド",
            "新しい",
            "変わりつつある",
        ),
        "trend",
    ),
    # competitor — competitor / rivalry / pricing-positioning of an entity.
    (
        (
            r"\bcompetitors?\b",
            r"\bcompetitive\b",
            r"\brivals?\b",
            r"\bpricing and positioning\b",
            "竞品",
            "竞争对手",
            "竞争",
            "定价",
            "定位",
            "競合",
            "ライバル",
        ),
        "competitor",
    ),
    # voc — user complaints / feedback / voice-of-customer.
    (
        (
            r"\b(complaints?|complaining|complain)\b",
            r"\bfeedback\b",
            r"\bvocs?\b",
            r"\busers?\s+(say|think|report|complain)\b",
            r"\breddit[^.]*\b(complain|hate|annoy|angry)\b",
            "用户反馈",
            "抱怨",
            "吐槽",
            "骂",
            "レビュー",
            "苦情",
            "クレーム",
            "不満",
            "悪評",
        ),
        "voc",
    ),
    # market — broad market / industry scans.
    (
        (
            r"\bmarket(s|place)?\b",
            r"\bindustry\b",
            "市场",
            "行业",
            "市場",
            "業界",
        ),
        "market",
    ),
)


def resolve_mode(text: str, explicit: str = "") -> str:
    if explicit:
        return explicit if explicit in MODES else MODE_FALLBACK
    lowered = text.lower()
    for cues, mode in _MODE_CUES:
        for cue in cues:
            try:
                if re.search(cue, lowered):
                    return mode
            except re.error:  # pragma: no cover - cue table is static
                if cue in lowered:
                    return mode
    return MODE_FALLBACK


MODE_FALLBACK = "general"


# ------------------------------------------------------------------ window --

_WINDOW_DAYS = re.compile(r"(?:last\s+)?(\d+)\s*(?:days?|日|天)\b", re.IGNORECASE)
_WINDOW_MONTHS = re.compile(r"(\d+)\s*(?:months?|ヶ月|个月|か月)\b", re.IGNORECASE)
_WINDOW_QUARTER = re.compile(r"\b(quarter|quarterly)\b", re.IGNORECASE)


def resolve_window(text: str, window_days: int | None = None) -> tuple[dict, str]:
    """(time_window mapping, human text). Explicit day override wins."""
    if window_days is not None:
        return {"days": window_days}, f"Last {window_days} days"
    m = _WINDOW_DAYS.search(text)
    if m:
        days = int(m.group(1))
        return {"days": days}, f"Last {days} days"
    m = _WINDOW_MONTHS.search(text)
    if m:
        days = int(m.group(1)) * 30
        return {"days": days}, f"Last {days} days"
    if _WINDOW_QUARTER.search(text):
        return {"days": 90}, "Last 90 days"
    return {"days": DEFAULT_DAYS}, f"Last {DEFAULT_DAYS} days"


# ---------------------------------------------------------------- entities --

# "Research Notion.", "about Otter.ai", "around Product X" — capture a
# trailing capitalized product-ish token. The anchor words are
# case-insensitive but the captured token must START uppercase (no
# case-insensitive class), so lowercase continuations never match.
_ENTITY_CUE = re.compile(
    r"(?i:(?:research|about|around|on|watch|track|monitor))\s+"
    r"([A-Z][A-Za-z0-9][A-Za-z0-9._ -]{0,40}?)(?:[?。.!.,]|$)"
)
# "What has Otter changed in pricing ..." / "What did Otter do ..."
_COMPETITOR_ENTITY_CUE = re.compile(
    r"(?i:what\s+(?:has|did|is|are))\s+([A-Z][A-Za-z0-9][A-Za-z0-9._-]{0,30}?)(?:\s+|\?)"
)
_GENERIC_TAIL = {
    "market",
    "markets",
    "tool",
    "tools",
    "software",
    "app",
    "apps",
    "industry",
    "space",
    "product",
    "products",
}
_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9._-]{1,40}")
_LATIN_STOP = {
    "the",
    "and",
    "for",
    "with",
    "what",
    "recent",
    "recently",
    "about",
    "research",
    "now",
    "how",
    "why",
    "when",
    "you",
    "your",
    "users",
    "user",
    "should",
    "know",
    "before",
    "this",
    "launching",
    "launch",
    "market",
    "markets",
    "ai",
    "gpt",
    "llm",
    "llms",
    "saas",
    "api",
    "app",
    "apps",
    "vs",
}


def _entity_from_match(match: re.Match) -> str:
    token = match.group(1).strip().rstrip(".,!?。")
    words = token.split()
    if not words:
        return ""
    if words[-1].lower() in _GENERIC_TAIL:
        return ""
    return token


def _latin_entities_in_cjk(text: str) -> tuple[str, ...]:
    """Capitalized Latin tokens inside a CJK sentence (e.g. Otter in
    Chinese text). Skip the noise stop list."""
    out: list[str] = []
    for m in _LATIN_TOKEN.finditer(text):
        tok = m.group(0)
        if tok[0].isupper() and tok.lower() not in _LATIN_STOP:
            out.append(tok)
    return tuple(dict.fromkeys(out))


def resolve_entities(
    text: str,
    explicit: tuple[str, ...],
    *,
    mode: str = MODE_FALLBACK,
) -> tuple[str, ...]:
    if explicit:
        return explicit
    out: list[str] = []
    if mode in ("voc", "channel"):
        return ()
    for m in _ENTITY_CUE.finditer(text):
        token = _entity_from_match(m)
        if token:
            out.append(token)
    if mode == "competitor":
        for m in _COMPETITOR_ENTITY_CUE.finditer(text):
            token = _entity_from_match(m)
            if token:
                out.append(token)
    seen: set[str] = set()
    uniq: list[str] = []
    for e in out:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return tuple(uniq)


# ------------------------------------------------------------ clarification --

_CLARIFY_COMPETITOR_NO_TARGET = re.compile(
    r"\b(competitors?|rivals?)\b", re.IGNORECASE
)


def _clarification_reason(
    text: str, mode: str, market: str, entities: tuple[str, ...]
) -> str:
    """Only ask when no meaningful plan can be built (§11, §40).

    Current rule: a bare competitor/rival request with no named product
    and no market would produce an unbounded competitor scan — that is
    the single case where clarification genuinely changes the object of
    research. Everything else runs.
    """
    if mode == "competitor" and not entities and market == "global":
        if _CLARIFY_COMPETITOR_NO_TARGET.search(text):
            return (
                "competitor request without a target product and without a "
                "market — specify which competitor or which market to scan."
            )
    return ""


# ------------------------------------------------------------------ entry ---

def parse_request(request: SkillRequest) -> ParsedRequest:
    """Normalize one SkillRequest into a ParsedRequest (§12–§14)."""
    text = request.query.strip()
    qlang = detect_query_language(text)

    mode = resolve_mode(text, explicit=request.mode)
    market = resolve_market(text, explicit=request.market)
    window, window_text = resolve_window(text, window_days=request.window_days)

    entities = resolve_entities(text, request.entities, mode=mode)
    if not entities and qlang in ("zh", "ja"):
        entities = _latin_entities_in_cjk(text)
    target = request.target or (entities[0] if entities else "")

    if request.languages:
        languages: tuple[str, ...] = tuple(dict.fromkeys(request.languages))
    else:
        base = list(MARKET_LANGUAGES.get(market, ("en",)))
        # If the query is local-language, surface that too.
        if qlang != "en" and qlang not in base and market == "global":
            base.append(qlang)
        languages = tuple(dict.fromkeys(base))

    reason = _clarification_reason(text, mode, market, entities)
    parsed = ParsedRequest(
        query=text,
        mode=mode,
        market=market,
        languages=languages,
        time_window=window,
        time_window_text=window_text,
        entities=entities,
        target=target,
        baseline=request.baseline,
        source_preferences=request.source_preferences,
        decision_context=request.decision_context,
        query_language=qlang,
        needs_clarification=bool(reason),
        clarification_reason=reason,
    )
    return parsed


def parse_query(query: str, **overrides: object) -> ParsedRequest:
    """Convenience: parse a bare query string into a ParsedRequest."""
    kwargs = {k: v for k, v in overrides.items() if v is not None}
    return parse_request(SkillRequest(query=query, **kwargs))
