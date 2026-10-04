"""Phase 6C — Markdown section builders (§4, §11, §13–§18, §25).

Every builder is a PURE formatter over an already-selected
``SelectedBrief`` plus an evidence lookup. Rules:
  * empty sections return "" — nothing is rendered "for completeness";
  * a section only ever formats fields that exist on the selected
    objects (statements/actions/confidences/citations);
  * the renderer never adds a semantic sentence of its own.

Reuses the Phase 2 rendering helpers (`rendering._heading` et al.) so
there is exactly one formatting layer for headings/bullets/citations
(Phase 6C §41) — no second renderer contract is maintained.
"""
from __future__ import annotations

import html
import re
from typing import Iterable, Mapping

from .. import rendering
from ..provenance import original_platform
from .dtos import (
    BriefContext,
    SelectedBrief,
    SelectedEmergingSignal,
    SelectedFact,
    SelectedInference,
    SelectedRecommendation,
    SelectedWatchout,
)
from .policy import NO_EVIDENCE_STATEMENT, PRIORITY_ORDER, SECTION_HEADINGS

_heading = rendering._heading
_evidence_lookup = rendering._evidence_lookup

H = SECTION_HEADINGS


def _inline(text: object) -> str:
    """Collapse newlines for single-line Markdown bullets (format only)."""
    return " ".join(str(text or "").split())


def _untrusted_inline(text: object) -> str:
    """Render retrieved source text as text, not Markdown or HTML."""
    value = html.escape(_inline(text), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", value)


def _rec_field(rec: object, name: str, default: str = "") -> str:
    if isinstance(rec, Mapping):
        return str(rec.get(name) or default)
    return str(getattr(rec, name, None) or default)


def _ref(lookup: Mapping[str, object], eid: str) -> str:
    """One deterministic citation: [source](url) plus backticked ev id."""
    rec = lookup.get(eid)
    if rec is None:
        return f"`{eid}`"
    url = _rec_field(rec, "url")
    label = original_platform(url) if _rec_field(rec, "source") == "host_web_search" else (_rec_field(rec, "source") or "source")
    date = _rec_field(rec, "published_at")[:10]
    suffix = f" · {date}" if date else ""
    if url:
        return f"[{label}]({url}){suffix} `{eid}`"
    return f"`{eid}`"


def refs(lookup: Mapping[str, object], eids: Iterable[str]) -> str:
    """Join deterministic citations for a list of evidence ids."""
    parts = [_ref(lookup, str(e)) for e in eids if e]
    return ", ".join(parts)


def _meta_line(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


# -------- context header --------


def research_context(ctx: BriefContext) -> str:
    """Title + "what did we research" block (§27). The H1 title is always
    present; each context line appears only when its field has a value."""
    lines = ["# Recent Intelligence Brief" if ctx.discovery_only else "# Sourceglint Brief"]
    subject = (ctx.query or ctx.topic or "").strip()
    if subject:
        lines.append(f"**Research:** {_inline(subject)}")
    scope = _meta_line(
        f"**Mode:** {_inline(ctx.mode)}" if ctx.mode else "",
        f"**Market:** {_inline(ctx.market)}" if ctx.market else "",
        f"**Languages:** {', '.join(ctx.languages)}" if ctx.languages else "",
    )
    if scope:
        lines.append(scope)
    window = _meta_line(
        f"**Window:** {_inline(ctx.time_window)}" if ctx.time_window else "",
        f"**As of:** {_inline(ctx.as_of)}" if ctx.as_of else "",
    )
    if window:
        lines.append(window)
    if ctx.entities:
        lines.append(f"**Entities:** {', '.join(_inline(e) for e in ctx.entities)}")
    if ctx.decision_context:
        lines.append(f"**Decision context:** {_inline(ctx.decision_context)}")
    return "\n".join(lines) + "\n\n"


# -------- executive summary (§26, extractive) --------


def executive(sel: SelectedBrief) -> str:
    if not sel.executive:
        return ""
    bullets = [f"- {_inline(line)}" for line in sel.executive]
    return _heading(2, H["executive"]) + "\n".join(bullets) + "\n\n"


# -------- FACT / INFERENCE sections (§8, §11) --------


def _insight_bullet(statement: str, confidence: float, eids: tuple[str, ...], lookup) -> str:
    meta = f"confidence: {confidence:.2f}"
    cite = refs(lookup, eids)
    if cite:
        meta += f" — {cite}"
    return f"- **{_inline(statement)}**\n  {meta}"


def facts(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    if not sel.facts:
        return ""
    body = "\n".join(_insight_bullet(f.statement, f.confidence, f.evidence_ids, lookup) for f in sel.facts)
    return _heading(2, H["facts"]) + body + "\n\n"


def inferences(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    if not sel.inferences:
        return ""
    body = "\n".join(_insight_bullet(i.statement, i.confidence, i.evidence_ids, lookup) for i in sel.inferences)
    return _heading(2, H["inferences"]) + body + "\n\n"


# -------- Recommended Actions (§11, §15, §29) --------


def actions(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    if not sel.recommendations:
        return ""
    by_bucket: dict[str, list[SelectedRecommendation]] = {b: [] for b in PRIORITY_ORDER}
    for rec in sel.recommendations:
        if rec.priority in by_bucket:
            by_bucket[rec.priority].append(rec)
    blocks: list[str] = []
    for bucket in PRIORITY_ORDER:
        recs = by_bucket[bucket]
        if not recs:
            continue
        body: list[str] = []
        for rec in recs:
            body.append(f"- **{_inline(rec.action)}**")
            meta = f"confidence: {rec.confidence:.2f}"
            if rec.risk:
                meta += f" · risk: {_inline(rec.risk)}"
            body.append(f"  {meta}")
            for why in rec.why_lines:
                body.append(f"  why: {_inline(why)}")
            cite = refs(lookup, rec.evidence_ids)
            if cite:
                body.append(f"  evidence: {cite}")
        blocks.append(_heading(3, bucket.upper()) + "\n".join(body) + "\n\n")
    return _heading(2, H["actions"]) + "".join(blocks)


# -------- Watchouts (§13, §30) --------


def watchouts(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    if not sel.watchouts:
        return ""
    body: list[str] = []
    for w in sel.watchouts:
        if w.kind == "conflict":
            title = f"**{_inline(w.title)}**"
            line = f"- {title}" + (f": {_inline(w.text)}" if w.text else "")
            body.append(line)
            if w.rec_ids:
                body.append(
                    "  related recommendations: "
                    + ", ".join(f"`{_inline(r)}`" for r in w.rec_ids)
                )
        else:  # contradictory signal
            body.append(f"- **{_inline(w.title)}** *(conflicting evidence)*")
            sup = refs(lookup, w.support_evidence_ids)
            if sup:
                body.append(f"  supporting: {sup}")
            counter = refs(lookup, w.counter_evidence_ids)
            if counter:
                body.append(f"  against: {counter}")
    return _heading(2, H["watchouts"]) + "\n".join(body) + "\n\n"


# -------- Emerging Signals (§14) --------


def emerging(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    if not sel.emerging:
        return ""
    body: list[str] = []
    for item in sel.emerging:
        cite = refs(lookup, item.evidence_ids)
        suffix = f" — {cite}" if cite else ""
        body.append(f"- **{_inline(item.label)}** *(weak — monitor)*{suffix}")
    return _heading(2, H["emerging"]) + "\n".join(body) + "\n\n"


def recent_items(sel: SelectedBrief, ledger: object) -> str:
    """Show retrieved items when discovery produced no validated finding.

    These are source observations, not promoted facts or trend claims.
    """
    if not sel.context.discovery_only or sel.facts or sel.inferences or sel.emerging:
        return ""
    if ledger is None:
        return ""
    records = list(ledger)
    if not records:
        return ""
    records.sort(
        key=lambda rec: (str(rec.published_at or ""), str(rec.evidence_id)),
        reverse=True,
    )
    lines = [
        "Retrieved items are listed below; no validated pattern was established."
    ]
    for rec in records[:10]:
        label = _untrusted_inline(rec.title or rec.snippet or rec.url)
        link = f"[{label}]({rec.url.replace(')', '%29')})" if rec.url else label
        meta = " · ".join(part for part in (rec.source, rec.published_at) if part)
        lines.append(f"- {link}" + (f" — {meta}" if meta else ""))
        if rec.snippet:
            lines.append(f"  {_untrusted_inline(rec.snippet[:280])}")
    if len(records) > 10:
        lines.append(f"Showing 10 of {len(records)} retrieved items.")
    return _heading(2, "Recent Evidence") + "\n".join(lines) + "\n\n"


# -------- Coverage (§18, §19) --------


def coverage(sel: SelectedBrief) -> str:
    if not sel.coverage_lines:
        return ""
    bullets = "\n".join(f"- {_inline(line)}" for line in sel.coverage_lines)
    return _heading(2, H["coverage"]) + bullets + "\n\n"


# -------- Sources registry (§17) --------


def _referenced_evidence(sel: SelectedBrief) -> list[str]:
    out: set[str] = set()
    for f in sel.facts:
        out.update(f.evidence_ids)
    for i in sel.inferences:
        out.update(i.evidence_ids)
    for r in sel.recommendations:
        out.update(r.evidence_ids)
    for e in sel.emerging:
        out.update(e.evidence_ids)
    for w in sel.watchouts:
        out.update(w.support_evidence_ids)
        out.update(w.counter_evidence_ids)
    return sorted(out)


def sources(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    eids = _referenced_evidence(sel)
    if not eids:
        return ""
    lines = [f"- {refs(lookup, [e])}" for e in eids]
    return _heading(2, H["sources"]) + "\n".join(lines) + "\n\n"


def evidence_excerpts(sel: SelectedBrief, lookup: Mapping[str, object]) -> str:
    """Keep source observations, including unselected counterexamples, auditable."""
    if not sel.context.discovery_only or not lookup:
        return ""
    cited = set(_referenced_evidence(sel))
    records = sorted(lookup.items(), key=lambda pair: (pair[0] in cited, _rec_field(pair[1], "published_at"), pair[0]), reverse=True)
    limit = max(10, len(cited))
    lines = ["Source excerpts are observations; a launch description is not verified user experience. Cited items appear first; additional items have not been selected as findings. Dates are publication dates where available."]
    for eid, rec in records[:limit]:
        lines.append(f"- {_untrusted_inline(_rec_field(rec, 'title'))} — {_ref(lookup, eid)}")
        excerpt = _rec_field(rec, "snippet")
        if excerpt:
            preview = excerpt[:500]
            lines.append("  " + _untrusted_inline(preview) + (" [excerpt truncated]" if len(excerpt) > 500 else ""))
    if len(records) > limit:
        lines.append(f"Showing {limit} of {len(records)} retained items; use the run ledger for the complete corpus.")
    return _heading(2, "Source Excerpts") + "\n".join(lines) + "\n\n"


# -------- no-evidence guard (§20) --------


def no_evidence_markdown(ctx: BriefContext) -> str:
    """Exact statement when 0 usable evidence was retrieved (§20). The
    brief must NEVER emit a fabricated "no major changes" line."""
    head = research_context(ctx)
    return head + f"{NO_EVIDENCE_STATEMENT}\n"
