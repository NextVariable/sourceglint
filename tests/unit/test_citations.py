"""Phase 2 Citation Integrity tests (TDD)."""
import pytest

from gtm_intelligence.citations import check_citations
from gtm_intelligence.errors import CitationIntegrityError
from gtm_intelligence.ledger import EvidenceLedger


def _seed(ledger):
    ledger.add(
        {
            "source": "reddit",
            "source_type": "discussion",
            "url": "https://www.reddit.com/r/AI/comments/1/a",
            "snippet": "first evidence",
            "author": "alice",
            "published_at": "2026-01-01T00:00:00Z",
            "retrieved_at": "2026-09-01T00:00:00Z",
        }
    )
    ledger.add(
        {
            "source": "reddit",
            "source_type": "discussion",
            "url": "https://www.reddit.com/r/AI/comments/2/b",
            "snippet": "second evidence",
            "author": "bob",
            "published_at": "2026-01-02T00:00:00Z",
            "retrieved_at": "2026-09-01T00:00:00Z",
        }
    )


class TestFACTCitations:
    def test_fact_with_evidence_passes(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        result = check_citations(
            ledger,
            [{"insight_id": "ins_f", "type": "FACT", "statement": "X",
              "evidence_ids": [eid], "signal_ids": []}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        assert result.valid is True, result.issues

    def test_fact_without_evidence_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            [{"insight_id": "ins_f", "type": "FACT", "statement": "X",
              "evidence_ids": [], "signal_ids": []}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        assert result.valid is False
        assert any("FACT" in i.reason and "evidence" in i.reason for i in result.issues)

    def test_fact_with_unknown_evidence_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            [{"insight_id": "ins_f", "type": "FACT", "statement": "X",
              "evidence_ids": ["ev_unknown_xxxxxxxxxxxxxxxxxxxxxxxx"], "signal_ids": []}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        assert result.valid is False
        assert any(i.field == "evidence_ids" for i in result.issues)


class TestINFERENCECitations:
    def test_inference_with_signal_passes(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        result = check_citations(
            ledger,
            [{"insight_id": "ins_i", "type": "INFERENCE", "statement": "X",
              "evidence_ids": [eid], "signal_ids": ["sig_a"]}],
            known_signal_ids={"sig_a"},
            known_insight_ids=set(),
        )
        assert result.valid is True, result.issues

    def test_inference_only_via_signal(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            [{"insight_id": "ins_i", "type": "INFERENCE", "statement": "X",
              "evidence_ids": [], "signal_ids": ["sig_a"]}],
            known_signal_ids={"sig_a"},
            known_insight_ids=set(),
        )
        # signal_ids alone is sufficient for INFERENCE traceability.
        assert result.valid is True, result.issues

    def test_inference_with_unknown_signal_reported(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        result = check_citations(
            ledger,
            [{"insight_id": "ins_i", "type": "INFERENCE", "statement": "X",
              "evidence_ids": [eid], "signal_ids": ["sig_ghost"]}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        assert result.valid is False
        assert any(i.field == "signal_ids" for i in result.issues)


class TestRECOMMENDATIONCitations:
    def test_recommendation_must_have_action(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        result = check_citations(
            ledger,
            [{"insight_id": "ins_r", "type": "RECOMMENDATION", "statement": "X",
              "evidence_ids": [eid], "signal_ids": [],
              "action": "Run a pricing experiment."}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        assert result.valid is True, result.issues

    def test_strategy_recommendation_can_be_cited_via_chain(self):
        # Strategy RECOMMENDATION: traceability through signal chain is OK.
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        result = check_citations(
            ledger,
            [{"insight_id": "ins_strat", "type": "RECOMMENDATION",
              "statement": "Move pricing.", "action": "Move pricing down by tier.",
              "evidence_ids": [], "signal_ids": ["sig_a"]}],
            known_signal_ids={"sig_a"},
            known_insight_ids=set(),
        )
        # Recommended action with signal cite is sufficient.
        assert result.valid is True, result.issues


class TestOutputCitations:
    def test_output_recommendation_citations(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        # Per Phase 1 Output schema: recommended_actions = {now, next, watch},
        # each action has `action` + `insight_id`. We pass recommended_actions
        # as the recommended_actions block.
        result = check_citations(
            ledger,
            insights=[],
            output_recommended_actions={
                "now": [
                    {"action": "Apply pricing experiment.",
                     "insight_id": "ins_p"},
                ],
                "next": [],
                "watch": [],
            },
            known_insight_ids={"ins_p"},
        )
        assert result.valid is True, result.issues

    def test_output_recommendation_unknown_insight_id_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            insights=[],
            output_recommended_actions={
                "now": [
                    {"action": "x", "insight_id": "ins_phantom"},
                ],
                "next": [],
                "watch": [],
            },
            known_insight_ids=set(),
        )
        assert result.valid is False

    def test_output_recommendation_missing_insight_id_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            insights=[],
            output_recommended_actions={
                "now": [
                    {"action": "x"},
                ],
                "next": [],
                "watch": [],
            },
            known_insight_ids={"ins_a"},
        )
        assert result.valid is False


class TestCitationErrors:
    def test_citation_error_exposes_issues(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        result = check_citations(
            ledger,
            [{"insight_id": "ins_x", "type": "FACT", "statement": "X",
              "evidence_ids": [], "signal_ids": []}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        with pytest.raises(CitationIntegrityError) as exc_info:
            result.raise_if_invalid()
        assert "ins_x" in str(exc_info.value)


# --------------------------- Negative surface ---------------------------


class TestSemanticsLayer:
    """Citation integrity checks structural chain, NOT semantic truth.

    A FACT with valid evidence_ids still requires the LLM/eval layer
    to confirm the evidence actually supports the claim. Phase 2 only
    locks structural traceability.
    """

    def test_valid_chain_does_not_imply_correctness(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id  # about AI meeting tools
        result = check_citations(
            ledger,
            [{"insight_id": "ins_smoke", "type": "FACT",
              "statement": "Tigers fly.",
              "evidence_ids": [eid], "signal_ids": []}],
            known_signal_ids=set(),
            known_insight_ids=set(),
        )
        # Structural pass: every chain link exists.
        assert result.valid is True
