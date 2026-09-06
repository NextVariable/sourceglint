"""Deterministic Retrieval Planning (Phase 3 §6).

Inputs:
  * Phase 1 Research Plan (mapping)
  * source registry (list of source entries)
  * expanded queries (from query_expansion.expand_queries)

Output:
  * ordered list[RetrievalPlan]

A RetrievalPlan separates WHAT to search from HOW the source is called.
Same Plan + same registry -> same ordered list. Priority desc, name asc.

Disabled sources are filtered out. Sources whose `markets` do not include
the plan's market are filtered out. Sources whose `languages` do not include
the query's query_language are filtered out for THAT query (not source-wide).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RetrievalPlan:
    """A single (source, query) retrieval intent.

    Attributes:
      source          : source name from registry (e.g. "reddit")
      query           : query text (verbatim from ExpandedQuery.text)
      query_language  : ISO 639 code (e.g. "en", "ja")
      market          : market code (e.g. "global", "jp")
      mode            : research mode (passed through from plan)
      time_window     : passed through from plan (relative days or custom range)
      priority        : numeric priority from source registry (default 50)
    """

    source: str
    query: str
    query_language: str
    market: str
    mode: str
    time_window: dict
    priority: int = 50

    def __post_init__(self) -> None:  # pragma: no cover - trivial guard
        if not self.source:
            raise ValueError("RetrievalPlan.source must be non-empty")
        if not self.query:
            raise ValueError("RetrievalPlan.query must be non-empty")
        if not self.query_language:
            raise ValueError("RetrievalPlan.query_language must be non-empty")


class RetrievalPlanner:
    """State-less deterministic planner."""

    def plan(
        self,
        research_plan: dict,
        sources: Sequence[dict],
        expanded_queries: Iterable[dict],
    ) -> list[RetrievalPlan]:
        return build_retrieval_plans(research_plan, sources, expanded_queries)


def _market_compatible(source_markets: Sequence[str], plan_market: str) -> bool:
    """A source serves a plan market if:
      * plan_market == "global" and source markets include "global"
        (a "global" source is for global plans only — it isn't an
        automatic fallback for every specific country), OR
      * plan_market is explicitly listed in source markets.
    Absent/empty source_markets means the source declares no market —
    it's only eligible for global plans (most conservative).
    """
    if not source_markets:
        return plan_market == "global"
    if plan_market == "global":
        return "global" in source_markets
    return plan_market in source_markets


def _language_compatible(source_languages: Sequence[str], query_lang: str) -> bool:
    """A source supports a query language if it's explicitly listed.
    Absent/empty source_languages means 'no languages declared' → treat as
    compatible with English only (most permissive, but explicit)."""
    if not source_languages:
        return query_lang == "en"
    return query_lang in source_languages


def _eligible_sources(
    sources: Sequence[dict], plan_market: str
) -> list[dict]:
    """Filter to enabled sources whose markets include plan_market."""
    out: list[dict] = []
    for s in sources:
        if not s.get("enabled", False):
            continue
        if not _market_compatible(s.get("markets") or [], plan_market):
            continue
        out.append(s)
    return out


def _ordered(
    eligible: Sequence[dict],
    plan_source_priorities: Sequence[str] | None,
) -> list[dict]:
    """Deterministic ordering:
      1. If plan supplied source_priorities (named order), honor that first.
      2. Else use registry priority desc, name asc.
    """
    if plan_source_priorities:
        idx = {name: i for i, name in enumerate(plan_source_priorities)}
        return sorted(
            eligible,
            key=lambda s: (
                idx.get(s["name"], len(idx) + 1),
                -int(s.get("priority", 50)),
                s["name"],
            ),
        )
    return sorted(
        eligible,
        key=lambda s: (-int(s.get("priority", 50)), s["name"]),
    )


def build_retrieval_plans(
    research_plan: dict,
    sources: Sequence[dict],
    expanded_queries: Iterable[dict],
) -> list[RetrievalPlan]:
    """Build a deterministic list of RetrievalPlan entries.

    The function does NOT call out to any source. It only computes the
    (source, query) tuples that downstream adapters will act on.
    """
    if not isinstance(research_plan, dict):
        raise TypeError("research_plan must be a dict")
    plan_market = str(research_plan.get("market") or "global")
    mode = str(research_plan.get("mode") or "")
    time_window = dict(research_plan.get("time_window") or {})
    source_priorities = research_plan.get("source_priorities") or []
    if isinstance(source_priorities, str) or not isinstance(source_priorities, Sequence):
        source_priorities = []

    eligible = _eligible_sources(sources, plan_market)
    ordered = _ordered(eligible, list(source_priorities) if source_priorities else None)

    plans: list[RetrievalPlan] = []
    for q in expanded_queries:
        # Accept both dict and ExpandedQuery dataclass.
        if hasattr(q, "text") and not isinstance(q, dict):
            text = str(getattr(q, "text", "") or "").strip()
            qlang = str(getattr(q, "query_language", "") or "en")
        elif isinstance(q, dict):
            text = str(q.get("text") or "").strip()
            qlang = str(q.get("query_language") or "en")
        else:
            continue
        if not text:
            continue
        for src in ordered:
            if not _language_compatible(src.get("languages") or [], qlang):
                continue
            plans.append(
                RetrievalPlan(
                    source=src["name"],
                    query=text,
                    query_language=qlang,
                    market=plan_market,
                    mode=mode,
                    time_window=time_window,
                    priority=int(src.get("priority", 50)),
                )
            )
    return plans