"""Phase 7 §9–§10, §56 — host-neutral request contract.

``SkillRequest`` is the thin input a host sends. ``query`` is the only
required field; everything else is parsed from the query or falls back
to engine defaults (§10 — never interrogate the user about internal
schema fields).

``ParsedRequest`` is the normalized, engine-ready form produced by
``interface.parser``. ``to_plan()`` emits a research_plan-shaped dict
(schema: schemas/research_plan.schema.json) so the core engine never
sees two parallel schemas (§9). No parallel SkillRequest/CLIRequest/
HostRequest vocabulary is created — one contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

MODE_GENERAL = "general"
MODES: tuple[str, ...] = (
    "general",
    "trend",
    "competitor",
    "market",
    "voc",
    "launch",
    "channel",
)

DEFAULT_DAYS = 30

# Market -> default research languages (English-first, market-local fallback).
MARKET_LANGUAGES: Mapping[str, tuple[str, ...]] = {
    "global": ("en",),
    "jp": ("en", "ja"),
    "de": ("en", "de"),
    "fr": ("en", "fr"),
    "us": ("en",),
    "gb": ("en",),
    "cn": ("en", "zh"),
    "kr": ("en", "ko"),
}


@dataclass(frozen=True)
class SkillRequest:
    """Host → engine request. Only ``query`` is required (§10).

    All other fields are optional overrides: when empty the parser
    derives them from the query, when present they win.
    """

    query: str
    mode: str = ""  # one of MODES when set; "" -> parse from query
    market: str = ""  # ISO 3166-1 alpha-2 or 'global'; "" -> parse / global
    languages: tuple[str, ...] = ()  # bare ISO 639 codes; () -> parse / default
    window_days: int | None = None  # relative window override (1..365)
    entities: tuple[str, ...] = ()  # named products/companies
    target: str = ""  # primary entity of interest (e.g. a competitor)
    baseline: bool = False  # include prior-window baseline evidence
    source_preferences: tuple[str, ...] = ()
    decision_context: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("SkillRequest.query is required and non-empty")
        if self.mode and self.mode not in MODES:
            raise ValueError(
                f"SkillRequest.mode must be one of {MODES!r}; got {self.mode!r}"
            )
        if self.window_days is not None and not 1 <= self.window_days <= 365:
            raise ValueError(
                f"window_days must be within 1..365; got {self.window_days}"
            )


def window_text_for(window: Mapping[str, Any]) -> str:
    """Human-readable window for the brief header (§27). Deterministic."""
    if "days" in window:
        days = int(window["days"])
        return f"Last {days} days"
    if "start" in window and "end" in window:
        return f"{window['start'][:10]} to {window['end'][:10]}"
    return "current"


@dataclass(frozen=True)
class ParsedRequest:
    """Normalized engine request (output of interface.parser).

    Every mode/market/language/window is resolved to a concrete value,
    so downstream code never branches on "unknown".
    """

    query: str
    mode: str
    market: str
    languages: tuple[str, ...]
    time_window: Mapping[str, Any]
    time_window_text: str
    entities: tuple[str, ...]
    target: str = ""
    baseline: bool = False
    source_preferences: tuple[str, ...] = ()
    decision_context: str = ""
    query_language: str = "en"  # 'en' | 'zh' | 'ja' (query surface language)
    needs_clarification: bool = False
    clarification_reason: str = ""

    def to_plan(self) -> dict[str, Any]:
        """Emit a research_plan-shaped dict (schema SoT, §9).

        Only keys declared by schemas/research_plan.schema.json are
        emitted (additionalProperties is false). ``baseline`` is not a
        plan field — the orchestrator passes it to the signal layer as
        ``drop_baseline_only`` (Phase 5 semantics).
        """
        plan: dict[str, Any] = {
            "topic": self.query.strip(),
            "mode": self.mode,
            "time_window": dict(self.time_window),
        }
        if self.market and self.market != "global":
            plan["market"] = self.market
        if self.languages:
            plan["languages"] = list(self.languages)
        if self.entities:
            plan["entities"] = list(self.entities)
        if self.decision_context:
            plan["decision_context"] = self.decision_context
        if self.source_preferences:
            plan["source_priorities"] = list(self.source_preferences)
        return plan

    @property
    def clarification_required(self) -> bool:
        return self.needs_clarification

    def as_clarification(self, reason: str) -> "ParsedRequest":
        """Flag that no meaningful plan can be built yet (§11, §40)."""
        return _replace(self, needs_clarification=True, clarification_reason=reason)


def _replace(req: ParsedRequest, **kw: Any) -> ParsedRequest:
    return ParsedRequest(
        query=req.query,
        mode=req.mode,
        market=req.market,
        languages=req.languages,
        time_window=req.time_window,
        time_window_text=req.time_window_text,
        entities=req.entities,
        target=req.target,
        baseline=req.baseline,
        source_preferences=req.source_preferences,
        decision_context=req.decision_context,
        query_language=req.query_language,
        needs_clarification=kw.get("needs_clarification", req.needs_clarification),
        clarification_reason=kw.get("clarification_reason", req.clarification_reason),
    )
