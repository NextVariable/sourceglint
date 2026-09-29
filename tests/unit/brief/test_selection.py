"""Phase 6C §9–§10, §14, §26, §34 — deterministic selection & ranking."""
from __future__ import annotations

from sourceglint.brief.dtos import BriefInput, BriefContext
from sourceglint.brief.selection import select_brief

from ._support_brief import (
    context,
    diag,
    evidence,
    fact,
    inference,
    make_ledger,
    recommendation,
    signal,
)


def _eids(ledger) -> tuple:
    return tuple(r.evidence_id for r in ledger)


class TestRankingCaps:
    def test_facts_ranked_by_support_desc(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"), evidence("e2", url="https://b.example/2"))
        e1, e2 = _eids(ledger)
        insights = (
            fact("ins_f_a", "Lower-support fact.", evidence_ids=(e1,), signal_ids=("s1",)),
            fact("ins_f_b", "Higher-support fact.", evidence_ids=(e2,), signal_ids=("s1",)),
        )
        diags = {
            "ins_f_a": diag("ins_f_a", support_strength=0.5),
            "ins_f_b": diag("ins_f_b", support_strength=0.92),
        }
        sel = select_brief(BriefInput(ledger=ledger, insights=insights, insight_diagnostics=diags))
        assert [f.insight_id for f in sel.facts] == ["ins_f_b", "ins_f_a"]
        assert sel.facts[0].support == 0.92

    def test_inferences_ranked_by_confidence_desc(self):
        insights = (
            inference("ins_i_a", "Lower confidence.", confidence=0.5),
            inference("ins_i_b", "Higher confidence.", confidence=0.8),
        )
        sel = select_brief(BriefInput(insights=insights))
        assert [i.insight_id for i in sel.inferences] == ["ins_i_b", "ins_i_a"]

    def test_tie_break_by_stable_id(self):
        insights = (
            fact("ins_f_z", "Z fact.", confidence=0.7),
            fact("ins_f_a", "A fact.", confidence=0.7),
        )
        sel = select_brief(BriefInput(insights=insights))
        assert [f.insight_id for f in sel.facts] == ["ins_f_a", "ins_f_z"]

    def test_recommendation_cap_drops_tail(self):
        recs = tuple(
            recommendation(f"ins_r{i}", f"action {i}", priority="watch", confidence=0.5)
            for i in range(6)
        )
        sel = select_brief(BriefInput(recommendations=recs))
        assert len(sel.recommendations) == 5  # default cap 5 (§10, §34)
        assert sel.diagnostics.dropped_due_to_cap.get("recommendations") == 1
        # deterministic tail-drop: last by stable id
        assert sel.recommendations[-1].insight_id != "ins_r5"

    def test_custom_caps_override_defaults(self):
        recs = tuple(recommendation(f"ins_r{i}", f"action {i}", priority="watch") for i in range(3))
        sel = select_brief(BriefInput(recommendations=recs, caps={"recommendations": 2}))
        assert len(sel.recommendations) == 2
        assert sel.diagnostics.dropped_due_to_cap == {"recommendations": 1}

    def test_recommendation_order_bucket_then_priority_then_id(self):
        recs = (
            recommendation("ins_r_watch1", "watch high", priority="watch", confidence=0.9),
            recommendation("ins_r_now2", "now low", priority="now", confidence=0.4),
            recommendation("ins_r_now1", "now high", priority="now", confidence=0.9),
            recommendation("ins_r_next", "next", priority="next", confidence=0.6),
        )
        sel = select_brief(BriefInput(recommendations=recs))
        assert [r.insight_id for r in sel.recommendations] == [
            "ins_r_now1",
            "ins_r_now2",
            "ins_r_next",
            "ins_r_watch1",
        ]


class TestWeakSeparation:
    def test_weak_fact_not_in_what_we_know_but_in_emerging(self):
        insights = (
            fact("ins_f_strong", "Strong fact."),
            fact("ins_f_weak", "Weak fact.", evidence_ids=()),
        )
        diags = {
            "ins_f_strong": diag("ins_f_strong", weak_signal=False),
            "ins_f_weak": diag("ins_f_weak", weak_signal=True),
        }
        sel = select_brief(BriefInput(insights=insights, insight_diagnostics=diags))
        assert [f.insight_id for f in sel.facts] == ["ins_f_strong"]
        weak = [e for e in sel.emerging if e.origin == "insight"]
        assert [e.emerging_id for e in weak] == ["ins_f_weak"]

    def test_weak_inference_only_in_emerging(self):
        insights = (inference("ins_i_weak", "Weak inference."),)
        diags = {"ins_i_weak": diag("ins_i_weak", weak_signal=True)}
        sel = select_brief(BriefInput(insights=insights, insight_diagnostics=diags))
        assert sel.inferences == ()
        assert sel.emerging[0].emerging_id == "ins_i_weak"

    def test_emerging_signal_overlap_suppressed(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        sigs = (
            signal("sig_em1", signal_type="emerging", evidence_ids=(e1,), score=0.9),
        )
        insights = (inference("ins_i_weak", "Weak claim.", evidence_ids=(e1,), signal_ids=("sig_em1",)),)
        diags = {"ins_i_weak": diag("ins_i_weak", weak_signal=True)}
        sel = select_brief(BriefInput(
            ledger=ledger, signals=sigs, insights=insights, insight_diagnostics=diags,
        ))
        ids = [e.emerging_id for e in sel.emerging]
        assert "ins_i_weak" in ids
        assert "sig_em1" not in ids  # fully covered by the weak insight


class TestEmergingCap:
    def test_emerging_cap_applies(self):
        insights = tuple(
            inference(f"ins_i_weak{i}", f"Weak {i}.")
            for i in range(4)
        )
        diags = {f"ins_i_weak{i}": diag(f"ins_i_weak{i}", weak_signal=True) for i in range(4)}
        sel = select_brief(BriefInput(insights=insights, insight_diagnostics=diags))
        assert len(sel.emerging) == 3
        assert sel.diagnostics.dropped_due_to_cap.get("emerging") == 1


class TestWatchouts:
    def test_conflict_and_contradictory_signal_both_surface(self):
        ledger = make_ledger(
            evidence("e1", url="https://a.example/1"),
            evidence("e2", url="https://b.example/2"),
            evidence("e3", url="https://c.example/3"),
        )
        e1, e2, e3 = _eids(ledger)
        sigs = (
            signal(
                "sig_contra", signal_type="contradictory", topic="price direction",
                supporting_evidence_ids=(e1,), counter_evidence_ids=(e2, e3),
                evidence_ids=(e1, e2, e3),
            ),
        )
        conflicts = (
            {"group_id": "conf_grp_1", "kind": "segment_specific",
             "rationale": "Enterprise and SMB point opposite ways.", "rec_ids": ("ins_r1",)},
        )
        sel = select_brief(BriefInput(ledger=ledger, signals=sigs, conflicts=conflicts))
        kinds = [w.kind for w in sel.watchouts]
        assert kinds == ["conflict", "signal"]
        sig_w = sel.watchouts[1]
        assert sig_w.watchout_id == "sig_contra"
        assert sig_w.support_evidence_ids == (e1,)
        assert sig_w.counter_evidence_ids == (e2, e3)
        assert sel.diagnostics.selected_watchout_ids == ("conf_grp_1", "sig_contra")

    def test_watchout_cap(self):
        sigs = tuple(
            signal(f"sig_c{i}", signal_type="contradictory", topic=f"c{i}",
                   counter_evidence_ids=("ev_x",), evidence_ids=("ev_x",))
            for i in range(4)
        )
        sel = select_brief(BriefInput(signals=sigs))
        assert len(sel.watchouts) == 3


class TestExecutiveSummary:
    def test_summary_is_top_fact_top_inference_top_now(self):
        insights = (
            fact("ins_f1", "Top fact statement.", confidence=0.9),
            inference("ins_i1", "Top inference statement.", confidence=0.8),
            inference("ins_i2", "Lower inference.", confidence=0.5),
        )
        recs = (
            recommendation("ins_r_now", "Top now action.", priority="now", confidence=0.7),
            recommendation("ins_r_watch", "Watch action.", priority="watch", confidence=0.9),
        )
        sel = select_brief(BriefInput(insights=insights, recommendations=recs))
        assert sel.executive == (
            "Top fact statement.",
            "Top inference statement.",
            "Top now action.",
        )

    def test_summary_degrades_when_layers_missing(self):
        insights = (fact("ins_f1", "Only fact."),)
        sel = select_brief(BriefInput(insights=insights))
        assert sel.executive == ("Only fact.",)

    def test_summary_no_now_skips_action_line(self):
        insights = (fact("ins_f1", "Fact."),)
        recs = (recommendation("ins_r1", "Next action.", priority="next"),)
        sel = select_brief(BriefInput(insights=insights, recommendations=recs))
        assert sel.executive == ("Fact.",)


class TestResolution:
    def test_recommendation_evidence_resolves_through_supporting_insight(self):
        ledger = make_ledger(
            evidence("e1", url="https://a.example/1"),
            evidence("e2", url="https://b.example/2"),
        )
        e1, e2 = _eids(ledger)
        insights = (
            fact("ins_f1", "Supports the action.", evidence_ids=(e1, e2)),
            inference("ins_i1", "Also supports.", evidence_ids=(e1,)),
        )
        recs = (
            recommendation("ins_r1", "Act.", priority="now"),
        )
        rec_diags = {
            "ins_r1": {
                "insight_id": "ins_r1", "priority": 0.8, "overall_risk": "MEDIUM",
                "supporting_insight_ids": ("ins_f1", "ins_i1"),
            },
        }
        sel = select_brief(BriefInput(
            ledger=ledger, insights=insights, recommendations=recs,
            recommendation_diagnostics=rec_diags,
        ))
        r = sel.recommendations[0]
        assert set(r.evidence_ids) == {e1, e2}
        assert r.why_lines == ("Supports the action.", "Also supports.")

    def test_insight_evidence_falls_back_to_signal_evidence(self):
        ledger = make_ledger(evidence("e1", url="https://a.example/1"))
        (e1,) = _eids(ledger)
        sigs = (signal("sig_1", evidence_ids=(e1,), signal_type="cross_source"),)
        insights = (
            fact("ins_f1", "Fact via signal.", evidence_ids=(), signal_ids=("sig_1",)),
        )
        sel = select_brief(BriefInput(ledger=ledger, signals=sigs, insights=insights))
        assert sel.facts[0].evidence_ids == (e1,)
