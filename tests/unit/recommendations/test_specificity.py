"""Phase 6B §33 — No Unsupported Specificity guard."""
from __future__ import annotations

from gtm_intelligence.recommendations.specificity import check_specificity

from ._support_recs import evidence, evidence_by_id, insight_by_id


def _base():
    """Insight + evidence supporting "$15 Team plan for Japanese SMB". """
    ins = {
        "insight_id": "ins_fact_1",
        "type": "FACT",
        "statement": "The vendor pricing page lists the Team plan at $15 per user per month.",
        "signal_ids": ["sig_a"],
        "evidence_ids": ["ev_1"],
        "confidence": 0.8,
    }
    evs = evidence_by_id(
        evidence(
            "ev_1",
            url="https://vendor.example/pricing",
            snippet="Team plan: $15 per user per month (up from $18).",
            market="jp",
        )
    )
    return ins, evs


def _check(text, *, market="jp", ins=None, evs=None, target=""):
    i, e = _base()
    return check_specificity(
        text,
        supporting_insight_ids=(ins["insight_id"] if ins else i["insight_id"],),
        insight_by_id=insight_by_id(ins or i),
        evidence_by_id=evs or e,
        research_market=market,
        target_entity=target,
    )


class TestMoneySpecificity:
    def test_grounded_money_allowed(self):
        # The $15 price is in the supporting evidence — battlecard update
        # referencing it is grounded.
        assert _check("Update battlecards to reflect the new $15 price.") == []

    def test_invented_budget_rejected(self):
        out = _check("Spend $50,000 on creator partnerships.")
        assert any("money" in v and "50,000" in v for v in out)

    def test_invented_price_rejected(self):
        out = _check("Set the entry price to $9.99.")
        assert any("money" in v and "9.99" in v for v in out)


class TestKpiSpecificity:
    def test_invented_kpi_rejected(self):
        out = _check("Aim for 30% conversion on the landing page.")
        assert any("KPI" in v and "30%" in v for v in out)

    def test_grounded_qualitative_outcome_allowed(self):
        assert _check("Learn whether entry pricing lifts signup interest.") == []


class TestGeographySpecificity:
    def test_same_market_allowed(self):
        assert _check("Run the test for Japanese SMB traffic.") == []

    def test_other_market_rejected(self):
        out = _check("Launch the test in Germany.")
        assert any("geography" in v and "germany" in v for v in out)

    def test_global_market_not_restricted(self):
        assert _check("Launch the test in Germany.", market="global") == []

    def test_cross_market_grounded_allowed(self):
        # Evidence mentions Germany → grounded, not invented.
        ins = {
            "insight_id": "ins_fact_1",
            "type": "FACT",
            "statement": "German SMB community posts report price sensitivity.",
            "signal_ids": ["sig_a"],
            "evidence_ids": ["ev_1"],
            "confidence": 0.8,
        }
        evs = evidence_by_id(
            evidence("ev_1", snippet="German SMB founders discuss pricing.", market="de")
        )
        assert _check("Run the test for German SMB traffic.", ins=ins, evs=evs) == []


class TestPersonaSpecificity:
    def test_unsupported_persona_rejected(self):
        out = _check("Target CFOs with the enterprise pitch.")
        assert any("persona" in v and "cfo" in v for v in out)

    def test_grounded_persona_allowed(self):
        ins = {
            "insight_id": "ins_fact_1",
            "type": "FACT",
            "statement": "Individual users report price sensitivity.",
            "signal_ids": ["sig_a"],
            "evidence_ids": ["ev_1"],
            "confidence": 0.8,
        }
        evs = evidence_by_id(
            evidence("ev_1", snippet="Individual users say the plan is too expensive.")
        )
        assert _check("Test an entry offer for individual users.", ins=ins, evs=evs) == []


class TestTargetEntity:
    def test_entity_named_amount_allowed(self):
        # target_entity carries the amount/geo → not an invented specificity.
        assert _check(
            "Target Acme Japan with the $15 plan.",
            target="Acme Japan $15",
        ) == []
