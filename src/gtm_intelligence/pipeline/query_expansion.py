"""Deterministic query expansion (Phase 3 §4, §5).

No LLM. No network. No clock.

Input  : Phase 1 Research Plan (mapping)
Output : list[ExpandedQuery]

Each expanded query carries:
  * text           — actual query string (verbatim)
  * intent         — one of {exact, category, problem, alternative,
                          comparison, complaint, commercial,
                          local_language, emerging_terminology, explicit}
  * query_language — ISO 639 code, e.g. "en", "ja"
  * market         — market from the plan (preserved as-is)
  * source         — explicit None (set later by RetrievalPlanner)

Determinism guarantee: same plan → same ordered list. Re-running 100× yields
byte-identical output. No random IDs, no clocks, no env state read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Per Phase 3 PRD §28 — keep <24 hard cap so downstream pipelines don't blow up.
QUERY_EXPANSION_MAX = 24

# Per PRD §4 — finite intent enum. Adding new labels requires a deliberate WHY
# (and likely an ADR), not ad-hoc test additions.
ALL_INTENTS: tuple[str, ...] = (
    "exact",
    "category",
    "problem",
    "alternative",
    "comparison",
    "complaint",
    "commercial",
    "local_language",
    "emerging_terminology",
)

# Per PRD §4 — mode → priority order of intents. The first N are emitted
# (subject to language availability + cap).
MODE_INTENT_PRIORITY: Mapping[str, tuple[str, ...]] = {
    "competitor": (
        "exact", "comparison", "alternative", "complaint", "commercial",
    ),
    "voc": (
        "problem", "complaint", "alternative", "local_language",
    ),
    "trend": (
        "category", "problem", "emerging_terminology", "comparison",
    ),
    "general": (
        "category", "problem", "exact",
    ),
    "market": (
        "category", "exact", "problem", "local_language",
    ),
    "launch": (
        "exact", "comparison", "complaint", "commercial",
    ),
    "channel": (
        "category", "alternative", "commercial", "emerging_terminology",
    ),
}


# Intent templates. Templates are paired with a query_language key — only
# languages declared in `plans.languages` are used. This is the D3 mechanism
# to keep multilingual coverage explicit (no fabricated JP text).
TEMPLATES: Mapping[str, tuple[tuple[str, str], ...]] = {
    "exact": (
        ("{entity}", "en"),
        ("{topic}", "en"),
    ),
    "category": (
        ("{topic} overview", "en"),
        ("{topic} market", "en"),
        ("what is {topic}", "en"),
    ),
    "problem": (
        ("{topic} problems", "en"),
        ("{topic} issues", "en"),
        ("{topic} pain points", "en"),
    ),
    "alternative": (
        ("{topic} alternatives", "en"),
        ("alternatives to {topic}", "en"),
        ("{topic} vs competitors", "en"),
    ),
    "comparison": (
        ("{topic} vs {entity}", "en"),
        ("{topic} comparison", "en"),
        ("{topic} compared to {entity}", "en"),
    ),
    "complaint": (
        ("{topic} complaints", "en"),
        ("{topic} review negative", "en"),
        ("{topic} downsides", "en"),
    ),
    "commercial": (
        ("{topic} pricing", "en"),
        ("{topic} cost", "en"),
        ("{topic} price change", "en"),
    ),
    "local_language": (
        ("{topic}", "local"),
    ),
    "emerging_terminology": (
        ("new {topic}", "en"),
        ("{topic} emerging", "en"),
        ("{topic} 2026", "en"),
    ),
}


@dataclass(frozen=True)
class ExpandedQuery:
    """One expanded query.

    Attributes:
      text           : query body (verbatim — no normalization).
      intent         : query-intent label (see ALL_INTENTS).
      query_language : ISO 639 code (e.g. "en", "ja"); never None.
      market         : market code from the plan (preserved).
    """

    text: str
    intent: str
    query_language: str
    market: str

    def __post_init__(self) -> None:  # pragma: no cover - trivial guard
        if not self.text:
            raise ValueError("ExpandedQuery.text must be non-empty")
        if self.intent not in ALL_INTENTS and self.intent != "explicit":
            raise ValueError(f"unknown intent: {self.intent!r}")
        if not self.query_language:
            raise ValueError("ExpandedQuery.query_language must be non-empty")


class QueryExpander:
    """State-less, deterministic expander."""

    def expand(self, research_plan: Mapping[str, object]) -> list[ExpandedQuery]:
        return expand_queries(research_plan)


def _read_entities(plan: Mapping[str, object]) -> list[str]:
    raw = plan.get("entities") or []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [str(e) for e in raw if e]


def _read_languages(plan: Mapping[str, object]) -> list[str]:
    raw = plan.get("languages") or ["en"]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ["en"]
    out = [str(x) for x in raw if x]
    return out or ["en"]


def _read_market(plan: Mapping[str, object]) -> str:
    return str(plan.get("market") or "global")


def _infer_query_language(
    text: str, declared_languages: Sequence[str]
) -> str:
    """Map a query string to one of the declared languages, without translating.

    The mapping is purely deterministic and never invents a translation:
      1. If text is already in the declared languages list, use it.
      2. Else, fall back to the first declared language.

    We only mark a query as `ja` if (a) the plan declared `ja` and (b) the text
    actually contains Japanese-script characters. We do NOT fabricate.
    """
    if not declared_languages:
        return "en"
    ja_chars = any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF for c in text)
    if ja_chars and "ja" in declared_languages:
        return "ja"
    # Latin / default fallback
    return declared_languages[0]


def _pick_query_for_intent(
    *,
    intent: str,
    topic: str,
    entities: Sequence[str],
    plan_languages: Sequence[str],
    market: str,
) -> ExpandedQuery | None:
    """Pick a single representative ExpandedQuery for the intent.

    Returns None when no template is compatible with the plan's declared
    languages. We emit ONE query per intent (per language priority) so the
    cap of 24 is roomy and the resulting list is human-readable.
    """
    primary_entity = entities[0] if entities else topic
    templates = TEMPLATES.get(intent, ())
    for tmpl_text, tmpl_lang in templates:
        # Resolve language first.
        if tmpl_lang == "local":
            lang = plan_languages[0]
        elif tmpl_lang in plan_languages:
            lang = tmpl_lang
        else:
            # Template language not in plan — skip (no fabrication).
            continue
        rendered = (
            tmpl_text.replace("{entity}", primary_entity).replace("{topic}", topic)
        ).strip()
        if not rendered:
            continue
        # Verify the rendered query's actual script matches the declared lang
        # (or fall back to the first declared language).
        resolved_lang = _infer_query_language(rendered, plan_languages)
        return ExpandedQuery(
            text=rendered,
            intent=intent,
            query_language=resolved_lang,
            market=market,
        )
    return None


def _expand_intent(
    *,
    intent: str,
    topic: str,
    entities: Sequence[str],
    plan_languages: Sequence[str],
    market: str,
) -> list[ExpandedQuery]:
    """Render templates for one intent, scoped to plan-declared languages.

    Phase 3 simplification: emit ONE representative query per intent per
    language (deterministic, roomy under the 24 cap). We avoid emitting
    several near-duplicates that would only differ by minor template phrasing.
    """
    out: list[ExpandedQuery] = []
    primary_entity = entities[0] if entities else topic
    templates = TEMPLATES.get(intent, ())

    seen_langs: set[str] = set()
    for tmpl_text, tmpl_lang in templates:
        if tmpl_lang == "local":
            lang = plan_languages[0]
        else:
            if tmpl_lang not in plan_languages:
                continue
            lang = tmpl_lang
        if lang in seen_langs:
            continue
        rendered = (
            tmpl_text.replace("{entity}", primary_entity).replace("{topic}", topic)
        ).strip()
        if not rendered:
            continue
        resolved_lang = _infer_query_language(rendered, plan_languages)
        if resolved_lang in seen_langs:
            continue
        seen_langs.add(resolved_lang)
        out.append(
            ExpandedQuery(
                text=rendered,
                intent=intent,
                query_language=resolved_lang,
                market=market,
            )
        )
    return out


def expand_queries(research_plan: Mapping[str, object]) -> list[ExpandedQuery]:
    """Deterministic Query Expansion.

    Returns a list of ExpandedQuery ordered as:
      1. explicit queries (verbatim, in plan order, intent="explicit")
      2. expansions grouped by intent, in the mode's priority order
      3. capped at QUERY_EXPANSION_MAX total
    """
    if not isinstance(research_plan, Mapping):
        raise TypeError("research_plan must be a mapping")
    mode = str(research_plan.get("mode") or "")
    if mode not in MODE_INTENT_PRIORITY:
        raise ValueError(f"unknown research mode: {mode!r}")
    topic = str(research_plan.get("topic") or "").strip()
    if not topic:
        raise ValueError("research_plan.topic is required and non-empty")

    plan_languages = _read_languages(research_plan)
    market = _read_market(research_plan)
    entities = _read_entities(research_plan)

    out: list[ExpandedQuery] = []

    # 1) Explicit queries preserved verbatim.
    explicit = research_plan.get("queries") or []
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        for q in explicit:
            text = str(q).strip()
            if not text:
                continue
            lang = _infer_query_language(text, plan_languages)
            out.append(
                ExpandedQuery(
                    text=text,
                    intent="explicit",
                    query_language=lang,
                    market=market,
                )
            )

    # 2) Per-intent expansion in mode priority order.
    priority = MODE_INTENT_PRIORITY[mode]
    for intent in priority:
        # Cap before adding a new intent block.
        if len(out) >= QUERY_EXPANSION_MAX:
            break
        block = _expand_intent(
            intent=intent,
            topic=topic,
            entities=entities,
            plan_languages=plan_languages,
            market=market,
        )
        for q in block:
            if len(out) >= QUERY_EXPANSION_MAX:
                break
            out.append(q)

    # 3) Multilingual coverage: if plan declares languages we haven't yet
    # emitted, add ONE local-language query per missing language so the
    # downstream pipeline knows the user's declared coverage intent.
    emitted_langs = {q.query_language for q in out}
    for lang in plan_languages:
        if len(out) >= QUERY_EXPANSION_MAX:
            break
        if lang in emitted_langs:
            continue
        primary = entities[0] if entities else topic
        rendered = f"{primary} {topic}".strip()
        out.append(
            ExpandedQuery(
                text=rendered,
                intent="local_language",
                query_language=lang,
                market=market,
            )
        )
        emitted_langs.add(lang)

    return out