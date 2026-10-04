"""Phase 6C — brief orchestration (§19, §20, §24, §33).

run_brief_pipeline():
  1. input triage   — schema-validate every insight/recommendation dict;
                      invalid objects are DROPPED with an explicit warning
                      (§24 — never best-effort render an invalid object);
                      referential-integrity check against the ledger when
                      one is supplied.
  2. selection      — deterministic rank/cap/resolve (see selection.py).
  3. render         — pure Markdown composition (see renderer.py).
  4. diagnostics    — selected ids, caps-dropped counts, evidence count,
                      warning count, missing layers, rendered sections.

Graceful degradation (§19): the brief renders whatever validated layers
exist and states plainly (in Coverage) which layers are absent. No
evidence at all (§20) emits the fixed no-evidence statement — never a
fabricated "no major changes".
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .. import validation
from . import renderer, selection
from .dtos import (
    BriefContext,
    BriefDiagnostics,
    BriefInput,
    RenderedBrief,
    SelectedBrief,
)
from .policy import SECTION_HEADINGS

__all__ = ["run_brief_pipeline"]

_FACT = "FACT"
_INFERENCE = "INFERENCE"
_RECOMMENDATION = "RECOMMENDATION"


def _warn(warnings: list[str], message: str) -> None:
    warnings.append(message)


def _schema_violations(obj: Mapping[str, Any]) -> list[str]:
    """Frozen insight.schema violations for one insight/recommendation dict."""
    from ..insights.validation import validate_insight_schema

    return validate_insight_schema(obj)


def _usable_insights(
    insights: Sequence[Mapping[str, Any]],
    known_signals: set[str],
    known_insights: set[str],
    ledger: Any,
    warnings: list[str],
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    """Keep only schema-valid FACT/INFERENCE dicts (§24)."""
    kept: dict[str, Mapping[str, Any]] = {}
    for ins in insights:
        if not isinstance(ins, Mapping) or not ins.get("insight_id"):
            _warn(warnings, "brief: skipping insight without insight_id")
            continue
        itype = ins.get("type")
        if itype not in (_FACT, _INFERENCE):
            _warn(
                warnings,
                f"brief: insight {ins.get('insight_id')} has unusable type {itype!r}",
            )
            continue
        violations = _schema_violations(ins)
        if violations:
            _warn(
                warnings,
                f"brief: dropping schema-invalid {itype} "
                f"{ins.get('insight_id')}: {'; '.join(violations)}",
            )
            continue
        if ledger is not None:
            if not _reference_ok(ins, ledger, known_signals):
                _warn(
                    warnings,
                    f"brief: dropping {itype} {ins.get('insight_id')} — "
                    f"references are not resolvable (evidence not in ledger "
                    f"or unknown signal)",
                )
                continue
        known_insights.add(str(ins.get("insight_id")))
        kept[str(ins.get("insight_id"))] = ins
    return kept, known_insights


def _reference_ok(
    ins: Mapping[str, Any], ledger: Any, known_signals: set[str]
) -> bool:
    """Cheap referential check without requiring the full signal set.

    When signals are supplied (known_signals non-empty) the strict
    validator runs (signal refs must resolve). Otherwise only evidence
    presence is checked — FACT/INFERENCE evidence ids must exist in the
    ledger, and a FACT must cite at least one evidence (§24).
    """
    ev = [str(e) for e in (ins.get("evidence_ids") or []) if e]
    if ins.get("type") == _FACT and not ev:
        return False
    if any(not ledger.exists(e) for e in ev):
        return False
    if known_signals:
        result = validation.validate_insight(
            ledger, ins, known_signal_ids=known_signals
        )
        return result.valid
    return True


def _usable_recommendations(
    recommendations: Sequence[Mapping[str, Any]],
    known_insights: set[str],
    ledger: Any,
    warnings: list[str],
) -> dict[str, Mapping[str, Any]]:
    """Keep only schema-valid RECOMMENDATION dicts (§24)."""
    kept: dict[str, Mapping[str, Any]] = {}
    for rec in recommendations:
        if not isinstance(rec, Mapping) or not rec.get("insight_id"):
            _warn(warnings, "brief: skipping recommendation without insight_id")
            continue
        if rec.get("type") != _RECOMMENDATION:
            _warn(
                warnings,
                f"brief: recommendation {rec.get('insight_id')} has "
                f"unusable type {rec.get('type')!r}",
            )
            continue
        violations = _schema_violations(rec)
        if violations:
            _warn(
                warnings,
                f"brief: dropping schema-invalid RECOMMENDATION "
                f"{rec.get('insight_id')}: {'; '.join(violations)}",
            )
            continue
        kept[str(rec.get("insight_id"))] = rec
    return kept


def run_brief_pipeline(brief_input: BriefInput) -> RenderedBrief:
    """Compose the final Intelligence Brief from validated objects.

    Pure code path — no model, no network, no clock (Gate K). The brief
    never reasons; it selects, orders, formats, resolves, and degrades.
    """
    warnings: list[str] = []
    ctx = brief_input.context or BriefContext()

    signals: list[Mapping[str, Any]] = [
        s for s in brief_input.signals if isinstance(s, Mapping) and s.get("signal_id")
    ]
    known_signals: set[str] = {str(s.get("signal_id")) for s in signals}

    ledger = brief_input.ledger
    evidence_count = len(list(ledger)) if ledger is not None else 0

    # ---- input triage (§24) -------------------------------------------------
    known_insights: set[str] = set()
    usable_insights, known_insights = _usable_insights(
        brief_input.insights,
        known_signals,
        known_insights,
        ledger,
        warnings,
    )
    usable_recs = _usable_recommendations(
        brief_input.recommendations, known_insights, ledger, warnings
    )
    usable_insight_list = list(usable_insights.values())
    usable_rec_list = list(usable_recs.values())

    # ---- no-evidence guard (§20) -------------------------------------------
    has_layer = bool(signals or usable_insight_list or usable_rec_list)
    if evidence_count == 0 and not has_layer:
        md = renderer.render_no_evidence_markdown(ctx)
        if brief_input.coverage is not None:
            from . import sections
            md += "\n" + sections.coverage(selection.select_brief(brief_input))
        diag = BriefDiagnostics(
            evidence_count=0,
            warning_count=len(warnings),
            missing_layers=("signals", "insights", "recommendations"),
            no_evidence=True,
            sections_rendered=(),
        )
        return RenderedBrief(markdown=md, diagnostics=diag)

    if evidence_count == 0 and has_layer:
        _warn(
            warnings,
            "brief: no ledger evidence to resolve citations; references "
            "will render as bare ids",
        )

    # ---- selection (§9–§10) -------------------------------------------------
    prepared = BriefInput(
        context=ctx,
        ledger=ledger,
        signals=tuple(signals),
        insights=tuple(usable_insight_list),
        recommendations=tuple(usable_rec_list),
        insight_diagnostics=brief_input.insight_diagnostics,
        recommendation_diagnostics=brief_input.recommendation_diagnostics,
        conflicts=brief_input.conflicts,
        coverage=brief_input.coverage,
        caps=brief_input.caps,
    )
    selected: SelectedBrief = selection.select_brief(prepared)
    md = renderer.render_brief_markdown(selected, ledger)

    # ---- diagnostics (§33) -------------------------------------------------
    rendered = tuple(
        key
        for key, label in SECTION_HEADINGS.items()
        if f"## {label}" in md
    )

    diag = BriefDiagnostics(
        selected_fact_ids=selected.diagnostics.selected_fact_ids,
        selected_inference_ids=selected.diagnostics.selected_inference_ids,
        selected_recommendation_ids=selected.diagnostics.selected_recommendation_ids,
        selected_emerging_ids=selected.diagnostics.selected_emerging_ids,
        selected_watchout_ids=selected.diagnostics.selected_watchout_ids,
        dropped_due_to_cap=selected.diagnostics.dropped_due_to_cap,
        evidence_count=evidence_count,
        warning_count=len(warnings),
        missing_layers=selected.diagnostics.missing_layers,
        no_evidence=False,
        sections_rendered=rendered,
    )
    return RenderedBrief(markdown=md, diagnostics=diag)
