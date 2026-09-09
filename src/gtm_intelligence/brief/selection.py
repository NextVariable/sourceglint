"""Phase 6C §9, §10, §26, §33, §34 — deterministic selection & ranking.

Everything in this module is CODE. The renderer does not think, and the
selection layer does not reason either: it only ranks already-validated
objects by code-owned numeric fields, applies per-section caps with
stable-id tie-breaking, resolves citation chains through the ledger, and
composes the extractive executive summary from already-validated
statements (§26). No semantic claim is produced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .dtos import (
    BriefContext,
    BriefDiagnostics,
    BriefInput,
    SelectedBrief,
    SelectedEmergingSignal,
    SelectedFact,
    SelectedInference,
    SelectedRecommendation,
    SelectedWatchout,
)
from .policy import (
    EXECUTIVE_MAX_LINES,
    PRIORITY_ORDER,
    RISK_RANK,
    WATCHOUT_KIND_LABELS,
)

__all__ = ["select_brief"]


# -------- normalization helpers --------


def _as_dict(obj: Any) -> Mapping[str, Any]:
    """Normalize a dataclass (with to_dict) or mapping to a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        out = to_dict()
        return out if isinstance(out, Mapping) else {}
    return {}


def _diag(diags: Mapping[str, Any], obj_id: str) -> Mapping[str, Any]:
    raw = diags.get(obj_id)
    return _as_dict(raw)


def _support_strength(insight: Mapping[str, Any], diag: Mapping[str, Any]) -> float:
    conf = _float(insight.get("confidence"))
    ss = _float(diag.get("support_strength"))
    return ss if ss > 0.0 else conf


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bucket_rank(priority: Any) -> int:
    try:
        return PRIORITY_ORDER.index(str(priority))
    except ValueError:
        return len(PRIORITY_ORDER)  # unknown buckets sort last


def _risk_rank(risk: Any) -> int:
    return RISK_RANK.get(str(risk).upper(), len(RISK_RANK))


# -------- citation chain resolution (code-only, §16) --------


def _evidence_from_signals(
    signal_ids: Iterable[str], signals: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Union of evidence ids cited by the given signals (sorted)."""
    out: set[str] = set()
    for sid in signal_ids:
        sig = signals.get(str(sid))
        if not sig:
            continue
        for eid in sig.get("evidence_ids") or ():
            if eid:
                out.add(str(eid))
    return sorted(out)


def _resolve_evidence(
    obj: Mapping[str, Any], signals: Mapping[str, Mapping[str, Any]]
) -> tuple[str, ...]:
    """Direct evidence_ids first; otherwise resolve via cited signals."""
    direct = [str(e) for e in (obj.get("evidence_ids") or []) if e]
    if direct:
        return tuple(direct)
    return tuple(_evidence_from_signals(obj.get("signal_ids") or [], signals))


def _rec_evidence(
    rec: Mapping[str, Any],
    insight_by_id: Mapping[str, Mapping[str, Any]],
    diag: Mapping[str, Any],
    signals: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Recommendation → supporting insight → evidence chain (§16).

    Union of the recommendation's own evidence_ids and the resolved
    evidence of each supporting FACT/INFERENCE insight (the insight's
    own evidence_ids first, else its cited signals' evidence). Never
    reaches past validated objects; sorted for byte stability.
    """
    own = [str(e) for e in (rec.get("evidence_ids") or []) if e]
    out: set[str] = set(own)
    for iid in diag.get("supporting_insight_ids") or ():
        sup = insight_by_id.get(str(iid))
        if sup:
            out.update(_resolve_evidence(sup, signals))
    return tuple(sorted(out))


# -------- per-layer selectors --------


@dataclass
class _LayerSelection:
    """Scratch result of one layer before cap bookkeeping."""

    items: list[Any]
    ids: list[str]
    dropped: int


def _select_insight_layer(
    insights: Iterable[Mapping[str, Any]],
    insight_type: str,
    diags: Mapping[str, Any],
    signals: Mapping[str, Mapping[str, Any]],
    cap: int,
    sort_facts_by_support: bool,
) -> _LayerSelection:
    """Rank + cap one insight layer (FACT or INFERENCE).

    Weak-signal insights are EXCLUDED here (§14): they surface only in
    the Emerging Signals section so users can always tell weak from
    confirmed cross-source evidence. Ranking (Phase 6C §9):
      * FACT:      support strength DESC → confidence DESC → stable id
      * INFERENCE: confidence DESC → support strength DESC → stable id
    (Decision relevance is not exposed as a numeric field by 6A/6B;
    confidence + support strength are the code-owned proxies — recorded
    in the closeout log.)
    """
    items: list[Any] = []
    for ins in insights:
        if ins.get("type") != insight_type:
            continue
        iid = str(ins.get("insight_id", ""))
        if not iid:
            continue
        diag = _diag(diags, iid)
        if diag.get("weak_signal"):
            continue  # → Emerging Signals, never the main sections (§14)
        support = _support_strength(ins, diag)
        conf = _float(ins.get("confidence"))
        if sort_facts_by_support:
            key = (-support, -conf, iid)
        else:
            key = (-conf, -support, iid)
        items.append((key, ins, diag))
    items.sort(key=lambda t: t[0])
    ranked: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = [
        (ins, diag) for _, ins, diag in items
    ]
    dropped = max(0, len(ranked) - cap)
    kept = ranked[:cap]

    if insight_type == "FACT":
        selected = [
            SelectedFact(
                insight_id=str(ins.get("insight_id", "")),
                statement=str(ins.get("statement", "")),
                confidence=_float(ins.get("confidence")),
                support=_support_strength(ins, diag),
                evidence_ids=_resolve_evidence(ins, signals),
            )
            for ins, diag in kept
        ]
    else:
        selected = [
            SelectedInference(
                insight_id=str(ins.get("insight_id", "")),
                statement=str(ins.get("statement", "")),
                confidence=_float(ins.get("confidence")),
                support=_support_strength(ins, diag),
                evidence_ids=_resolve_evidence(ins, signals),
            )
            for ins, diag in kept
        ]
    ids = [s.insight_id for s in selected]
    return _LayerSelection(selected, ids, dropped)


def _collect_weak_insights(
    insights: Iterable[Mapping[str, Any]],
    diags: Mapping[str, Any],
    signals: Mapping[str, Mapping[str, Any]],
    insight_type: str,
) -> list[SelectedEmergingSignal]:
    """Weak FACT/INFERENCE → Emerging Signals candidates (§14)."""
    out: list[SelectedEmergingSignal] = []
    for ins in insights:
        if ins.get("type") != insight_type:
            continue
        iid = str(ins.get("insight_id", ""))
        if not iid:
            continue
        diag = _diag(diags, iid)
        if not diag.get("weak_signal"):
            continue
        out.append(
            SelectedEmergingSignal(
                emerging_id=iid,
                label=str(ins.get("statement", "")).strip(),
                evidence_ids=_resolve_evidence(ins, signals),
                origin="insight",
            )
        )
    return out


def _select_recommendations(
    recommendations: Iterable[Mapping[str, Any]],
    rec_diags: Mapping[str, Any],
    insight_by_id: Mapping[str, Mapping[str, Any]],
    signals: Mapping[str, Mapping[str, Any]],
    cap: int,
) -> _LayerSelection:
    """Rank + cap recommendations (§9, §34).

    Global order: priority bucket (now → next → watch) → raw priority
    score DESC → confidence DESC → risk (LOW first) → stable insight_id.
    The cap applies to the GLOBAL list (deterministic drop of the tail),
    per Phase 6C §34; rendering then regroups the survivors into buckets.
    """
    items: list[Any] = []
    for rec in recommendations:
        action = rec.get("action")
        if not isinstance(action, Mapping):
            continue
        priority = action.get("priority")
        iid = str(rec.get("insight_id", ""))
        if not iid:
            continue
        diag = _diag(rec_diags, iid)
        conf = _float(rec.get("confidence"))
        prio_score = _float(diag.get("priority"))
        risk = str(diag.get("overall_risk") or "LOW")
        key = (
            _bucket_rank(priority),
            -prio_score,
            -conf,
            _risk_rank(risk),
            iid,
        )
        items.append((key, rec, diag))
    items.sort(key=lambda t: t[0])
    dropped = max(0, len(items) - cap)
    kept = items[:cap]

    selected = [
        SelectedRecommendation(
            insight_id=str(rec.get("insight_id", "")),
            action=str(((rec.get("action") or {}).get("action")) or ""),
            priority=str((rec.get("action") or {}).get("priority") or ""),
            confidence=_float(rec.get("confidence")),
            risk=str(diag.get("overall_risk") or "LOW"),
            priority_score=_float(diag.get("priority")),
            why_lines=tuple(
                str(insight_by_id[iid2].get("statement", "")).strip()
                for iid2 in (diag.get("supporting_insight_ids") or [])
                if insight_by_id.get(str(iid2)) is not None
                and str(insight_by_id[str(iid2)].get("statement", "")).strip()
            ),
            evidence_ids=_rec_evidence(rec, insight_by_id, diag, signals),
        )
        for _, rec, diag in kept
    ]
    ids = [s.insight_id for s in selected]
    return _LayerSelection(selected, ids, dropped)


def _select_emerging(
    weak_facts: list[SelectedEmergingSignal],
    weak_inferences: list[SelectedEmergingSignal],
    signals: Mapping[str, Mapping[str, Any]],
    all_signals: Iterable[Mapping[str, Any]],
    cap: int,
) -> _LayerSelection:
    """Weak/emerging items (§14): weak FACT/INFERENCE first, then
    Phase 5 `emerging` signals not already fully covered by a weak
    insight (evidence-overlap suppression — code rule, not semantics)."""
    items: list[SelectedEmergingSignal] = list(weak_facts) + list(weak_inferences)
    used_evidence: set[str] = set()
    for item in items:
        used_evidence.update(item.evidence_ids)

    # Phase 5 `emerging` signals not fully covered by a weak insight.
    sig_candidates: list[tuple[tuple, Mapping[str, Any]]] = []
    for sig in all_signals:
        if sig.get("signal_type") != "emerging":
            continue
        sid = str(sig.get("signal_id", ""))
        if not sid:
            continue
        ev = tuple(str(e) for e in (sig.get("evidence_ids") or []) if e)
        if not ev:
            continue
        if set(ev) <= used_evidence:
            continue  # already surfaced through a weak insight
        key = (-_float(sig.get("score")), -_float(sig.get("confidence")), sid)
        sig_candidates.append((key, sig))
    sig_candidates.sort(key=lambda t: t[0])

    for _, sig in sig_candidates:
        items.append(
            SelectedEmergingSignal(
                emerging_id=str(sig.get("signal_id", "")),
                label=str(sig.get("topic", "")).strip()
                or str(sig.get("signal_id", "")),
                evidence_ids=tuple(
                    str(e) for e in (sig.get("evidence_ids") or []) if e
                ),
                origin="signal",
            )
        )

    dropped = max(0, len(items) - cap)
    kept = items[:cap]
    ids = [i.emerging_id for i in kept]
    return _LayerSelection(kept, ids, dropped)


def _select_watchouts(
    conflicts: Iterable[Any],
    all_signals: Iterable[Mapping[str, Any]],
    cap: int,
) -> _LayerSelection:
    """Watchouts (§13, §30): Phase 6B conflicts first (deterministic by
    group_id), then Phase 5 `contradictory` signals (score DESC)."""
    items: list[SelectedWatchout] = []

    conflict_items: list[tuple[tuple, SelectedWatchout]] = []
    for conf in conflicts:
        c = _as_dict(conf)
        kind_raw = str(c.get("kind") or "true_conflict")
        group_id = str(c.get("group_id") or "")
        title = WATCHOUT_KIND_LABELS.get(kind_raw, kind_raw)
        rationale = str(c.get("rationale") or "").strip()
        rec_ids = tuple(str(r) for r in (c.get("rec_ids") or []) if r)
        if not group_id and not rec_ids:
            continue
        conflict_items.append(
            (
                (group_id,),
                SelectedWatchout(
                    watchout_id=group_id or (rec_ids[0] if rec_ids else "conflict"),
                    kind="conflict",
                    title=title,
                    text=rationale,
                    rec_ids=rec_ids,
                ),
            )
        )
    conflict_items.sort(key=lambda t: t[0])
    for _, w in conflict_items:
        items.append(w)

    sig_items: list[tuple[tuple, SelectedWatchout]] = []
    for sig in all_signals:
        if sig.get("signal_type") != "contradictory":
            continue
        sid = str(sig.get("signal_id", ""))
        if not sid:
            continue
        all_ev = set(str(e) for e in (sig.get("evidence_ids") or []) if e)
        counter = tuple(
            str(e) for e in (sig.get("counter_evidence_ids") or []) if e
        )
        supporting = tuple(
            str(e)
            for e in (
                sig.get("supporting_evidence_ids")
                or sorted(all_ev - set(counter))
            )
            if e
        )
        if not counter:
            continue  # schema requires counter ids for contradictory signals
        sig_items.append(
            (
                (-_float(sig.get("score")), -_float(sig.get("confidence")), sid),
                SelectedWatchout(
                    watchout_id=sid,
                    kind="signal",
                    title=str(sig.get("topic", "")).strip() or sid,
                    support_evidence_ids=supporting,
                    counter_evidence_ids=counter,
                ),
            )
        )
    sig_items.sort(key=lambda t: t[0])
    for _, w in sig_items:
        items.append(w)

    dropped = max(0, len(items) - cap)
    kept = items[:cap]
    ids = [w.watchout_id for w in kept]
    return _LayerSelection(kept, ids, dropped)


# -------- executive summary (§26, extractive only) --------


def _compose_executive(
    facts: tuple[SelectedFact, ...],
    inferences: tuple[SelectedInference, ...],
    recommendations: tuple[SelectedRecommendation, ...],
) -> tuple[str, ...]:
    """summary = top FACT + top INFERENCE + top NOW recommendation.

    Missing layers degrade naturally — the template never forces a
    "Therefore…" bridge that would manufacture inference (§26).
    """
    lines: list[str] = []
    if facts:
        lines.append(facts[0].statement)
    if inferences:
        lines.append(inferences[0].statement)
    for rec in recommendations:
        if rec.priority == "now":
            lines.append(rec.action)
            break
    return tuple(lines[:EXECUTIVE_MAX_LINES])


# -------- coverage lines (§18) --------


def _coverage_lines(coverage: Any) -> list[str]:
    c = _as_dict(coverage)
    if not c:
        return []
    lines: list[str] = []

    markets = [str(m) for m in (c.get("markets_covered") or []) if m]
    if markets:
        lines.append(f"Markets: {', '.join(sorted(markets))}")
    languages = [str(l) for l in (c.get("languages_covered") or []) if l]
    if languages:
        lines.append(f"Languages: {', '.join(sorted(languages))}")

    final_n = _int_or_none(c.get("final_evidence_count"))
    cur_n = _int_or_none(c.get("current_window_count"))
    base_n = _int_or_none(c.get("baseline_window_count"))
    if final_n is not None:
        bits = [f"{final_n} evidence items"]
        if cur_n is not None:
            bits.append(f"current window {cur_n}")
        if base_n is not None:
            bits.append(f"baseline {base_n}")
        lines.append("Evidence: " + "; ".join(bits))

    reached = [str(s) for s in (c.get("successful_sources") or []) if s]
    if reached:
        lines.append("Sources reached: " + ", ".join(sorted(reached)))
    failed = [
        str(s)
        for s in (
            (c.get("failed_sources") or [])
            + (c.get("sources_unavailable") or [])
        )
        if s
    ]
    seen: set[str] = set()
    uniq_failed: list[str] = []
    for s in sorted(failed):
        if s not in seen:
            seen.add(s)
            uniq_failed.append(s)
    if uniq_failed:
        lines.append("Sources unavailable: " + ", ".join(uniq_failed))

    lim = (c.get("coverage_limitation") or "").strip()
    if lim:
        lines.append(f"Coverage limitation: {lim}")
    return lines


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# -------- public entry (§9–§10, §26, §33) --------


def select_brief(brief_input: BriefInput) -> SelectedBrief:
    """Deterministically select/rank/cap a full brief from valid inputs.

    Pure code: no model, no network, no clock, no randomness. The output
    is fully resolved (citations chains materialized) so the renderer can
    stay a pure formatter.
    """
    ctx = brief_input.context or BriefContext()
    signals_map: dict[str, Mapping[str, Any]] = {
        str(s.get("signal_id", "")): s
        for s in brief_input.signals
        if s.get("signal_id")
    }
    insight_by_id: dict[str, Mapping[str, Any]] = {
        str(i.get("insight_id", "")): i
        for i in brief_input.insights
        if i.get("insight_id")
    }

    caps = brief_input.effective_caps()

    fact_sel = _select_insight_layer(
        brief_input.insights,
        "FACT",
        brief_input.insight_diagnostics,
        signals_map,
        cap=caps["facts"],
        sort_facts_by_support=True,
    )
    inf_sel = _select_insight_layer(
        brief_input.insights,
        "INFERENCE",
        brief_input.insight_diagnostics,
        signals_map,
        cap=caps["inferences"],
        sort_facts_by_support=False,
    )
    rec_sel = _select_recommendations(
        brief_input.recommendations,
        brief_input.recommendation_diagnostics,
        insight_by_id,
        signals_map,
        cap=caps["recommendations"],
    )
    emerging_sel = _select_emerging(
        _collect_weak_insights(
            brief_input.insights,
            brief_input.insight_diagnostics,
            signals_map,
            "FACT",
        ),
        _collect_weak_insights(
            brief_input.insights,
            brief_input.insight_diagnostics,
            signals_map,
            "INFERENCE",
        ),
        signals_map,
        brief_input.signals,
        cap=caps["emerging"],
    )
    watchout_sel = _select_watchouts(
        brief_input.conflicts,
        brief_input.signals,
        cap=caps["watchouts"],
    )

    facts = tuple(fact_sel.items)
    inferences = tuple(inf_sel.items)
    recommendations = tuple(rec_sel.items)
    executive = _compose_executive(facts, inferences, recommendations)

    # Degradation notes (§19) ride in the Coverage section.
    coverage_lines = _coverage_lines(brief_input.coverage)
    missing: list[str] = []
    if not brief_input.signals:
        from .policy import NO_SIGNALS_NOTE

        missing.append("signals")
        coverage_lines.append(NO_SIGNALS_NOTE)
    if not brief_input.insights:
        from .policy import NO_INSIGHTS_NOTE

        missing.append("insights")
        coverage_lines.append(NO_INSIGHTS_NOTE)
    if not brief_input.recommendations:
        from .policy import NO_RECOMMENDATIONS_NOTE

        missing.append("recommendations")
        coverage_lines.append(NO_RECOMMENDATIONS_NOTE)

    dropped = {
        "facts": fact_sel.dropped,
        "inferences": inf_sel.dropped,
        "recommendations": rec_sel.dropped,
        "emerging": emerging_sel.dropped,
        "watchouts": watchout_sel.dropped,
    }

    diagnostics = BriefDiagnostics(
        selected_fact_ids=tuple(fact_sel.ids),
        selected_inference_ids=tuple(inf_sel.ids),
        selected_recommendation_ids=tuple(rec_sel.ids),
        selected_emerging_ids=tuple(emerging_sel.ids),
        selected_watchout_ids=tuple(watchout_sel.ids),
        dropped_due_to_cap={k: v for k, v in dropped.items() if v > 0},
        missing_layers=tuple(missing),
    )

    return SelectedBrief(
        context=ctx,
        facts=facts,
        inferences=inferences,
        recommendations=recommendations,
        emerging=tuple(emerging_sel.items),
        watchouts=tuple(watchout_sel.items),
        executive=executive,
        coverage_lines=tuple(coverage_lines),
        diagnostics=diagnostics,
    )
