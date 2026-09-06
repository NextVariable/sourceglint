"""Phase 2 Deterministic Markdown Renderer (strict Phase 1 Output contract).

The renderer is a STRICT consumer of `schemas/output.schema.json`. Any
field not declared in the schema is rejected at the contract layer; here
we only read the fields the schema declares.

Phase 1 Output sections (in fixed order):
  1. executive_intelligence       string
  2. changes                      string[]
  3. key_signals                  {signal_id, type[FACT|INFERENCE], what,
                                   why_it_matters, level, gtm_implications}
  4. user_voice                   {quote, evidence_id}
  5. competitive_movement         string[]
  6. weak_signals                 {topic, evidence_ids[], why_watch?}
  7. recommended_actions          {now[], next[], watch[]} each action has
                                   {action, insight_id?}
  8. gaps                         {sources_unavailable[], uncertain[]}
  9. coverage                     {sources_searched[], sources_unavailable[],
                                   coverage_limitation?}
  Confidence & Gaps section renders confidence + gaps + coverage.

Citations: user_voice[].evidence_id and weak_signals[].evidence_ids[]
are rendered as inline markdown links to canonical evidence URLs stored
in the ledger. Citations into key_signals flow through
signal_id -> insight_id linkage (rendered via insight/gat_implications),
not via direct evidence_ids, per Phase 1 contract.

The renderer is byte-stable, optional-section-aware, and uses plain
Python string ops (no Jinja2).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from .ledger import EvidenceLedger


# -------- helpers --------


def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n\n"


def _paragraph(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return f"{text}\n\n"


def _bullets(items: Iterable[str]) -> str:
    items = [i.strip() for i in items if i and i.strip()]
    if not items:
        return ""
    return "\n".join(f"- {i}" for i in items) + "\n\n"


def _evidence_lookup(ledger: EvidenceLedger) -> dict[str, object]:
    return {rec.evidence_id: rec for rec in ledger}


def _source_link(ledger_lookup: Mapping[str, object], evidence_id: str) -> str:
    rec = ledger_lookup.get(evidence_id)
    if not rec:
        return f"`{evidence_id}`"
    url = getattr(rec, "url", "") or ""
    label = getattr(rec, "source", "") or "source"
    return f"[{label}]({url})" if url else f"`{label}`"


# -------- sections --------


def _executive_intelligence(out: Mapping[str, object]) -> str:
    text = out.get("executive_intelligence")
    if not isinstance(text, str) or not text.strip():
        return ""
    return _heading(1, "Executive Intelligence") + _paragraph(text.strip())


def _what_changed(out: Mapping[str, object]) -> str:
    items = out.get("changes") or []
    if not isinstance(items, list) or not items:
        return ""
    bullets = [str(i).strip() for i in items if str(i).strip()]
    return _heading(2, "What Changed") + _bullets(bullets)


def _key_signals(out: Mapping[str, object]) -> str:
    items = out.get("key_signals") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        sig_id = (item.get("signal_id") or "").strip()
        itype = (item.get("type") or "").strip()
        what = (item.get("what") or "").strip()
        level = (item.get("level") or "").strip()
        why = (item.get("why_it_matters") or "").strip()
        if not what:
            continue
        head_bits = []
        if sig_id:
            head_bits.append(f"`{sig_id}`")
        if itype:
            head_bits.append(itype)
        if level:
            head_bits.append(f"level: {level}")
        head = " — ".join(head_bits)
        line = f"**{what}**" + (f" — {head}" if head else "")
        body.append(line)
        if why:
            body.append(f"  why: {why}")
        gtm_implications = item.get("gtm_implications") or {}
        if isinstance(gtm_implications, Mapping):
            for k, v in sorted(gtm_implications.items()):
                if v is None or v == "":
                    continue
                body.append(f"  - {k}: {v}")
    return _heading(2, "Key Signals") + _bullets(body)


def _user_voice(out: Mapping[str, object], lookup: Mapping[str, object]) -> str:
    items = out.get("user_voice") or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        quote = (item.get("quote") or "").strip()
        if not quote:
            continue
        eid = item.get("evidence_id")
        line = f"> {quote}"
        if eid:
            line += f" {_source_link(lookup, str(eid))} `{eid}`"
        body.append(line)
    if not body:
        return ""
    return _heading(2, "User Voice") + "\n".join(body) + "\n\n"


def _competitive_movement(out: Mapping[str, object]) -> str:
    items = out.get("competitive_movement") or []
    if not isinstance(items, list) or not items:
        return ""
    return _heading(2, "Competitive Movement") + _bullets(
        str(i).strip() for i in items
    )


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
        why = (item.get("why_watch") or "").strip()
        eids = [str(e) for e in (item.get("evidence_ids") or []) if e]
        cite_parts = [_source_link(lookup, e) for e in eids]
        if cite_parts:
            topic = topic + " " + " ".join(cite_parts)
        body.append(topic)
        if why:
            body.append(f"  watch because: {why}")
    return _heading(2, "Weak Signals") + _bullets(body)


def _action_list(
    out: Mapping[str, object],
    lookup: Mapping[str, object],
    bucket: str,
) -> str:
    block = out.get("recommended_actions")
    if not isinstance(block, Mapping):
        return ""
    items = block.get(bucket) or []
    if not isinstance(items, list) or not items:
        return ""
    body = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        action = (item.get("action") or "").strip()
        if not action:
            continue
        iid = (item.get("insight_id") or "").strip()
        body.append(action + (f" — `{iid}`" if iid else ""))
    if not body:
        return ""
    title = {"now": "Now", "next": "Next", "watch": "Watch"}.get(bucket, bucket)
    return _heading(3, title) + _bullets(body)


def _recommended_actions(
    out: Mapping[str, object], lookup: Mapping[str, object]
) -> str:
    block = out.get("recommended_actions")
    if not isinstance(block, Mapping):
        block = {}
    has_any = any(block.get(b) for b in ("now", "next", "watch"))
    if not has_any:
        return ""
    text = (
        _action_list(out, lookup, "now")
        + _action_list(out, lookup, "next")
        + _action_list(out, lookup, "watch")
    )
    if not text:
        return ""
    return _heading(2, "Recommended Actions") + text


def _confidence_gaps_coverage(out: Mapping[str, object]) -> str:
    confidence = out.get("confidence")
    gaps = out.get("gaps")
    coverage = out.get("coverage")
    if confidence is None and gaps is None and coverage is None:
        return ""

    body: list[str] = []
    if isinstance(confidence, (int, float)):
        body.append(f"overall: {float(confidence):.2f}")
    if isinstance(gaps, Mapping):
        su = gaps.get("sources_unavailable")
        if isinstance(su, list) and su:
            body.append(
                "sources unavailable: " + ", ".join(sorted(str(s) for s in su if s))
            )
        un = gaps.get("uncertain")
        if isinstance(un, list) and un:
            body.append("uncertain judgments:")
            body.extend(f"- {u}" for u in un if isinstance(u, str) and u.strip())
    if isinstance(coverage, Mapping):
        ss = coverage.get("sources_searched")
        if isinstance(ss, list) and ss:
            body.append(
                "sources searched: " + ", ".join(sorted(str(s) for s in ss if s))
            )
        su_cov = coverage.get("sources_unavailable")
        if isinstance(su_cov, list) and su_cov:
            body.append(
                "coverage gap: " + ", ".join(sorted(str(s) for s in su_cov if s))
            )
        lim = coverage.get("coverage_limitation")
        if isinstance(lim, str) and lim.strip():
            body.append(f"coverage limitation: {lim.strip()}")

    if not body:
        return ""
    return _heading(2, "Confidence & Gaps") + _bullets(body)


# -------- public --------


def render_markdown(ledger: EvidenceLedger, output: Mapping[str, object]) -> str:
    """Render Phase 1 Output -> deterministic Markdown.

    Sections appended in fixed order. Empty/absent sections are silently
    dropped. Plain Python string ops only.
    """
    if not isinstance(output, Mapping):
        output = {}
    lookup = _evidence_lookup(ledger)
    parts = [
        _executive_intelligence(output),
        _what_changed(output),
        _key_signals(output),
        _user_voice(output, lookup),
        _competitive_movement(output),
        _weak_signals(output, lookup),
        _recommended_actions(output, lookup),
        _confidence_gaps_coverage(output),
    ]
    rendered = "".join(parts).rstrip() + "\n"
    return rendered
