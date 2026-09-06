"""Phase 2 Deterministic Markdown Renderer (Phase 1 Output contract).

Driven by Phase 1 Output schema. The renderer:

  * Receives the Phase 1 Output JSON (validated upstream by the validation
    layer + citation tier).
  * Produces a deterministic Markdown document.
  * Skips absent/empty sections silently (no "No data" filler).
  * Renders evidence citations as markdown links to the canonicalized URL.
  * Uses plain string concatenation; no template engine, no LLM.

Section order (fixed by Phase 1 output contract):
  1. Executive Intelligence
  2. What Changed
  3. Key Signals
  4. User Voice
  5. Competitive Movement
  6. Weak Signals
  7. Recommended Actions
  8. Confidence & Gaps
"""
from __future__ import annotations

from typing import Mapping

from .ledger import EvidenceLedger


# Ordered Markdown builders. Each returns either a populated string or ""
# (empty => caller skips).
def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n\n"


def _paragraph(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return f"{text}\n\n"


def _bullets(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    return "\n".join(f"- {i}" for i in items) + "\n\n"


def _evidence_lookup(ledger: EvidenceLedger) -> dict[str, object]:
    return {rec.evidence_id: rec for rec in ledger}


def _link_for(lookup: Mapping[str, object], evidence_id: str) -> str:
    rec = lookup.get(evidence_id)
    if not rec:
        return f"`[{evidence_id}]`"
    url = getattr(rec, "url", "") or ""
    label = getattr(rec, "source", "") or "source"
    # Compact inline citation: [label](url)
    if url:
        return f"[{label}]({url})"
    return f"`{label}`"


def _cite_one(lookup: Mapping[str, object], evidence_id: str) -> str:
    return f"({_link_for(lookup, evidence_id)}) `{evidence_id}`"


def _cite_many(lookup: Mapping[str, object], evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return ""
    return " " + " ".join(_cite_one(lookup, e) for e in evidence_ids)


def _executive_intelligence(out: Mapping[str, object]) -> str:
    summary = out.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return ""
    return _heading(1, "Executive Intelligence") + _paragraph(summary.strip())


def _what_changed(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("changes") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = (item.get("change") or "").strip()
        if not text:
            continue
        cites = _cite_many(lookup, list(item.get("evidence_ids") or []))
        body.append(text + cites)
    return _heading(2, "What Changed") + _bullets(body)


def _key_signals(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("key_signals") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    nested = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        topic = (item.get("topic") or "").strip()
        if not topic:
            continue
        score = item.get("score")
        score_str = f" — score {score:.2f}" if isinstance(score, (int, float)) else ""
        cites = _cite_many(lookup, list(item.get("evidence_ids") or []))
        body.append(f"**{topic}**{score_str}{cites}")
        gtm_implications = item.get("gtm_implications") or {}
        if isinstance(gtm_implications, Mapping):
            for k, v in sorted(gtm_implications.items()):
                if v is None or v == "":
                    continue
                nested.append(f"{k}: {v}")
    if not body:
        return ""
    text = _bullets(body)
    if nested:
        text += "\n" + _bullets(nested)
    return _heading(2, "Key Signals") + text


def _user_voice(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("user_voice") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        sentiment = item.get("sentiment")
        quote = f"> {text}"
        if sentiment:
            quote += f" _[{sentiment}]_"
        eid = item.get("evidence_id")
        if eid:
            cite = _link_for(lookup, str(eid))
            quote += f" {cite}"
        body.append(quote)
    if not body:
        return ""
    return _heading(2, "User Voice") + "\n".join(body) + "\n\n"


def _competitive_movement(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    block = out.get("competitive_movement")
    if not isinstance(block, Mapping):
        return ""
    summary = (block.get("summary") or "").strip()
    if not summary:
        return ""
    cites = _cite_many(lookup, list(block.get("evidence_ids") or []))
    return _heading(2, "Competitive Movement") + _paragraph(summary + (cites or ""))


def _weak_signals(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("weak_signals") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        topic = (item.get("topic") or "").strip()
        if not topic:
            continue
        cites = _cite_many(lookup, list(item.get("evidence_ids") or []))
        body.append(topic + cites)
    return _heading(2, "Weak Signals") + _bullets(body)


def _recommended_actions(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("recommended_actions") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        action = (item.get("action") or "").strip()
        if not action:
            continue
        horizon = item.get("horizon")
        priority = item.get("priority")
        meta = []
        if priority:
            meta.append(f"priority `{priority}`")
        if horizon:
            meta.append(f"horizon: {horizon}")
        meta_str = f" ({'; '.join(meta)})" if meta else ""
        cites = _cite_many(lookup, list(item.get("evidence_ids") or []))
        body.append(f"{action}{meta_str}{cites}")
    return _heading(2, "Recommended Actions") + _bullets(body)


def _confidence_and_gaps(out: Mapping[str, object]) -> str:
    confidence = out.get("confidence")
    gaps = out.get("gaps") or []
    coverage = out.get("coverage")

    parts = []
    if isinstance(confidence, Mapping):
        overall = confidence.get("overall")
        rationale = (confidence.get("rationale") or "").strip()
        if isinstance(overall, (int, float)):
            parts.append(f"- overall: {overall:.2f}")
        if rationale:
            parts.append(f"- rationale: {rationale}")
    if isinstance(gaps, list):
        for g in gaps:
            if isinstance(g, str) and g.strip():
                parts.append(f"- gap: {g.strip()}")
    if isinstance(coverage, Mapping):
        ss = coverage.get("sources_searched") or []
        su = coverage.get("sources_unavailable") or []
        if isinstance(ss, list) and ss:
            parts.append(f"- sources searched: {', '.join(sorted(str(s) for s in ss if s))}")
        if isinstance(su, list) and su:
            parts.append(f"- sources unavailable: {', '.join(sorted(str(s) for s in su if s))}")
    if not parts:
        return ""
    return _heading(2, "Confidence & Gaps") + _bullets(parts)


def render_markdown(ledger: EvidenceLedger, output: Mapping[str, object]) -> str:
    """Render Output contract -> deterministic Markdown.

    Sections are appended in fixed order. Empty/absent sections are skipped.
    Plain Python string ops only.
    """
    if not isinstance(output, Mapping):
        output = {}
    lookup = _evidence_lookup(ledger)
    parts = [
        _executive_intelligence(output),
        _what_changed(output, lookup),
        _key_signals(output, lookup),
        _user_voice(output, lookup),
        _competitive_movement(output, lookup),
        _weak_signals(output, lookup),
        _recommended_actions(output, lookup),
        _confidence_and_gaps(output),
    ]
    rendered = "".join(parts).rstrip() + "\n"
    return rendered
