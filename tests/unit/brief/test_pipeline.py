"""Phase 6C §19–§20, §24, §33 — pipeline triage / degradation / diagnostics."""
from __future__ import annotations

from sourceglint.brief.dtos import BriefContext, BriefInput
from sourceglint.brief.pipeline import run_brief_pipeline

from ._support_brief import (
    context,
    evidence,
    fact,
    inference,
    make_ledger,
    recommendation,
)


def _eids(ledger) -> tuple:
    return tuple(r.evidence_id for r in ledger)


class TestInputTriage:
    def test_schema_invalid_insight_dropped_with_warning(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        bad = {"insight_id": "ins_bad", "type": "FACT", "confidence": 0.9,
               "evidence_ids": [e1]}
        good = fact("ins_f1", "Valid fact.", evidence_ids=(e1,))
        out = run_brief_pipeline(BriefInput(
            ledger=ledger, insights=(bad, good),
        ))
        assert len(out.diagnostics.selected_fact_ids) == 1
        assert out.diagnostics.warning_count == 1

    def test_hallucinated_evidence_reference_dropped(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        ghost = fact("ins_f2", "Ghost fact.", evidence_ids=("ev_nope",))
        out = run_brief_pipeline(BriefInput(
            ledger=ledger, insights=(ghost,),
        ))
        assert out.diagnostics.selected_fact_ids == ()
        assert out.diagnostics.warning_count == 1

    def test_non_insight_entries_skipped(self):
        out = run_brief_pipeline(BriefInput(
            insights=({"type": "FACT", "statement": "no id", "confidence": 0.5},),
        ))
        assert out.diagnostics.warning_count == 1

    def test_rec_without_action_dict_skipped(self):
        rec = {"insight_id": "ins_r1", "type": "RECOMMENDATION",
               "statement": "x", "confidence": 0.5}
        out = run_brief_pipeline(BriefInput(recommendations=(rec,)))
        assert out.diagnostics.warning_count == 1


class TestNoEvidence:
    def test_empty_research_emits_no_evidence_statement(self):
        out = run_brief_pipeline(BriefInput())
        assert out.diagnostics.no_evidence is True
        assert "No usable evidence was retrieved for this research request." in out.markdown
        assert "No major changes" not in out.markdown

    def test_evidence_but_no_layers_renders_degradation_notes(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        out = run_brief_pipeline(BriefInput(ledger=ledger))
        assert out.diagnostics.no_evidence is False
        assert "No usable evidence" not in out.markdown
        assert "No validated signals found." in out.markdown
        assert "No recommendation met the support threshold." in out.markdown


class TestDiagnostics:
    def test_sections_rendered_recorded(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        insights = (fact("ins_f1", "Fact.", evidence_ids=(e1,)),)
        out = run_brief_pipeline(BriefInput(ledger=ledger, insights=insights))
        assert "facts" in out.diagnostics.sections_rendered
        assert "coverage" in out.diagnostics.sections_rendered
        assert "actions" not in out.diagnostics.sections_rendered

    def test_evidence_count_recorded(self):
        ledger = make_ledger(
            evidence("e1", url="https://a.example/1"),
            evidence("e2", url="https://b.example/2"),
        )
        (e1, e2) = _eids(ledger)
        insights = (fact("ins_f1", "Fact.", evidence_ids=(e1, e2)),)
        out = run_brief_pipeline(BriefInput(ledger=ledger, insights=insights))
        assert out.diagnostics.evidence_count == 2

    def test_full_pipeline_end_to_end(self):
        ledger = make_ledger(
            evidence("e1", url="https://a.example/1", source="official"),
            evidence("e2", url="https://b.example/2", source="community"),
        )
        e1, e2 = _eids(ledger)
        ctx = context()
        insights = (
            fact("ins_f1", "A verified fact.", evidence_ids=(e1, e2), confidence=0.9),
            inference("ins_i1", "An inference.", evidence_ids=(e1,), confidence=0.6),
        )
        recs = (recommendation("ins_r1", "Do the thing.", priority="now"),)
        rec_diags = {"ins_r1": {
            "priority": 0.7, "overall_risk": "LOW", "supporting_insight_ids": ("ins_f1",),
        }}
        out = run_brief_pipeline(BriefInput(
            context=ctx, ledger=ledger, insights=insights, recommendations=recs,
            recommendation_diagnostics=rec_diags,
        ))
        assert out.markdown.startswith("# Sourceglint Brief")
        assert "## Executive Summary" in out.markdown
        assert "## What We Know" in out.markdown
        assert "## Recommended Actions" in out.markdown
        assert out.diagnostics.selected_fact_ids == ("ins_f1",)
        assert out.diagnostics.selected_recommendation_ids == ("ins_r1",)
        assert out.diagnostics.no_evidence is False


class TestContextRendering:
    def test_context_rendered_at_top(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        out = run_brief_pipeline(BriefInput(
            context=context(), ledger=ledger,
            insights=(fact("ins_f1", "Fact.", evidence_ids=(e1,)),),
        ))
        assert "**Research:** AI meeting assistants in Japan" in out.markdown
        assert "**As of:** 2026-09-09" in out.markdown
