"""Phase 6B §33 — No Unsupported Specificity guard.

Prevents the model from inventing specifics the evidence / context do
not support:
  * Budget amounts      ("Spend $50,000 on creators.")
  * Concrete prices     ("Set price to $9.99.")
  * Geographies         ("Launch in Germany." when the research market
                         is jp and no insight supports a cross-market move)
  * Personas / ICP      ("Target CFOs." without ICP support)
  * KPI targets         ("Aim for 30% conversion." without a benchmark)

Grounding principle (mirrors 6A grounding): a specificity token is
ALLOWED when it already appears in the supporting evidence text pool
(evidence owned by the cited insights + the cited insight statements)
or when the research context itself provides it (market / target
entity). Otherwise the token is rejected — the model is inventing
specificity the sources do not support (§33, §34).

Quoted / reported user speech is not exempt here: a recommendation is
assistant-generated advice, so advisory specificity is always checked.

This module returns violation strings only — callers reject the draft
(§32 — no silent repair).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

#: Currency amounts: $50,000 / $20k / ¥9,999 / 1.2m USD etc.
_MONEY_RE = re.compile(
    r"(?:\$|€|£|¥)\s?\d[\d,]*(?:\.\d+)?(?:k|m|b)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|jpy|cny|dollars?|euros?|yen|rmb)\b",
    re.IGNORECASE,
)

#: Percentage KPI targets: "30%", "23.5%".
_PERCENT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s?%")

#: Persona / ICP labels that must be grounded (§33 persona).
_PERSONA_TERMS: tuple[str, ...] = (
    "cfo", "cmo", "cto", "ceo", "head of sales", "head of marketing",
    "it admin", "procurement", "hr team", "recruiter", "sales rep",
    "founder", "startup founders", "enterprise buyer", "individual user",
    "small business owner", "creator",
)

#: Geography names -> market code (small map; cross-market moves need
#: evidence support, §34). Market codes use common.schema market_code.
_GEO_TERMS: dict[str, str] = {
    "germany": "de", "france": "fr", "japan": "jp", "brazil": "br",
    "united states": "us", "usa": "us", "uk": "gb", "united kingdom": "gb",
    "india": "in", "china": "cn", "australia": "au", "canada": "ca",
    "korea": "kr", "south korea": "kr", "singapore": "sg",
    "netherlands": "nl", "spain": "es", "italy": "it", "mexico": "mx",
}

#: Market codes treated as "no fixed geography" (global scope).
_GLOBAL_MARKETS = frozenset({"global", "intl", "ww"})


def _evidence_text(ev: Mapping[str, Any] | None) -> str:
    if not ev:
        return ""
    parts = []
    for key in ("snippet", "title", "text", "content", "summary"):
        value = ev.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return " ".join(parts)


def build_specificity_pool(
    supporting_insight_ids: Iterable[str],
    insight_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    """Text pool that grounds specificity tokens: evidence owned by the
    cited insights plus the cited insight statements themselves."""
    texts: list[str] = []
    seen: set[str] = set()
    for iid in supporting_insight_ids:
        ins = insight_by_id.get(iid)
        if ins is None:
            continue
        stmt = str(ins.get("statement") or "")
        if stmt:
            texts.append(stmt)
        for eid in ins.get("evidence_ids") or ():
            if eid in seen or eid not in evidence_by_id:
                continue
            seen.add(eid)
            text = _evidence_text(evidence_by_id.get(eid))
            if text:
                texts.append(text)
    return " ".join(texts)


def _strip_number(token: str) -> str:
    """'$20k' / '20k usd' -> '20k' (lowercased, currency removed)."""
    t = token.strip().lower().replace(",", "")
    for cur in ("$", "€", "£", "¥"):
        t = t.replace(cur, "")
    for suffix in ("usd", "eur", "jpy", "cny", "dollars", "euros", "yen", "rmb"):
        t = t.replace(suffix, "").strip()
    return t


def _grounded_in(token: str, pool_lower: str) -> bool:
    """A specificity token is grounded when it appears in the pool text."""
    if not token:
        return False
    # Try full token, then its numeric core (handles $15 vs "15").
    candidates = {token.lower()}
    core = _strip_number(token)
    if core:
        candidates.add(core)
    for cand in candidates:
        if cand and cand in pool_lower:
            return True
    return False


def _money_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _MONEY_RE.finditer(text)]


def _percent_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _PERCENT_RE.finditer(text)]


def _geo_hits(text: str) -> list[tuple[str, str]]:
    """Return (country_word, market_code) pairs mentioned in text."""
    lower = text.lower()
    hits: list[tuple[str, str]] = []
    for word, code in _GEO_TERMS.items():
        if re.search(rf"\b{re.escape(word)}\b", lower):
            hits.append((word, code))
    return hits


def _persona_hits(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in _PERSONA_TERMS if term in lower]


def check_specificity(
    text: str,
    *,
    supporting_insight_ids: Iterable[str],
    insight_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    research_market: str = "global",
    target_entity: str = "",
) -> list[str]:
    """Return specificity violations for a recommendation text (empty =
    grounded). `text` is the concatenation of statement + action +
    expected_outcome (the fields that may carry specifics)."""
    if not text or not text.strip():
        return []

    pool = build_specificity_pool(
        supporting_insight_ids, insight_by_id, evidence_by_id
    )
    pool_lower = pool.lower()
    market = (research_market or "global").lower()
    target_lower = (target_entity or "").lower()
    violations: list[str] = []

    # 1. Money / budget / price (§33)
    for token in _money_tokens(text):
        core = _strip_number(token)
        if core and core in target_lower:
            continue  # target entity itself may carry an amount
        if not _grounded_in(token, pool_lower):
            violations.append(
                f"unsupported money specificity: '{token}' not grounded in cited evidence"
            )

    # 2. KPI percentages (§33)
    for token in _percent_tokens(text):
        if not _grounded_in(token, pool_lower):
            violations.append(
                f"unsupported KPI specificity: '{token}' not grounded in cited evidence"
            )

    # 3. Geography (§33, §34) — a cross-market move needs grounding or
    #    an explicit global market.
    if market not in _GLOBAL_MARKETS:
        for word, code in _geo_hits(text):
            if code == market:
                continue  # same market — allowed
            if word in target_lower:
                continue  # target entity itself is named by the word
            if not _grounded_in(word, pool_lower):
                violations.append(
                    f"unsupported geography: '{word}' (market={code}) outside "
                    f"research market '{market}' and not grounded in cited evidence"
                )

    # 4. Persona / ICP (§33)
    for term in _persona_hits(text):
        if term in target_lower:
            continue
        if not _grounded_in(term, pool_lower):
            violations.append(
                f"unsupported persona: '{term}' not grounded in cited evidence"
            )

    return violations
