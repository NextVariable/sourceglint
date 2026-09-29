"""Phase 2 Referential Integrity Validator tests (TDD)."""
import pytest

from sourceglint.errors import ReferentialIntegrityError
from sourceglint.ledger import EvidenceLedger
from sourceglint.validation import (
    IntegrityIssue,
    ValidationResult,
    validate_insight,
    validate_output,
    validate_signal,
)


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


class TestSignalIntegrity:
    def test_valid_signal_passes(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        sig = {
            "signal_id": "sig_a",
            "topic": "AI meeting tools pricing",
            "evidence_ids": [ledger.all()[0].evidence_id, ledger.all()[1].evidence_id],
            "representative_evidence_ids": [ledger.all()[0].evidence_id],
            "source_diversity": ["reddit", "reddit"],
            "volume": 2,
            "recency": 0.9,
            "signal_type": "repeated",
            "novelty": 0.5,
            "score": 0.7,
            "confidence": 0.6,
            "supporting_evidence_ids": [ledger.all()[1].evidence_id],
            "counter_evidence_ids": [],
        }
        result = validate_signal(ledger, sig)
        assert result.valid is True
        assert result.issues == []

    def test_missing_evidence_id_reported(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        sig = {
            "signal_id": "sig_b",
            "topic": "x",
            "evidence_ids": [ledger.all()[0].evidence_id, "ev_does_not_exist"],
            "representative_evidence_ids": [ledger.all()[0].evidence_id],
            "source_diversity": ["reddit"],
            "volume": 1,
            "recency": 0.5,
            "signal_type": "single_source",
            "novelty": 0.5,
            "score": 0.5,
            "confidence": 0.5,
            "supporting_evidence_ids": [],
            "counter_evidence_ids": [],
        }
        result = validate_signal(ledger, sig)
        assert result.valid is False
        assert any(
            i.missing_ids == ["ev_does_not_exist"]
            and i.field == "evidence_ids"
            and i.object_id == "sig_b"
            for i in result.issues
        )

    def test_counter_evidence_id_also_validated(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        sig = {
            "signal_id": "sig_c",
            "topic": "x",
            "evidence_ids": [ledger.all()[0].evidence_id],
            "representative_evidence_ids": [ledger.all()[0].evidence_id],
            "source_diversity": ["reddit"],
            "volume": 1,
            "recency": 0.5,
            "signal_type": "contradictory",
            "novelty": 0.7,
            "score": 0.6,
            "confidence": 0.6,
            "supporting_evidence_ids": [],
            "counter_evidence_ids": ["ev_phantom"],
        }
        result = validate_signal(ledger, sig)
        assert result.valid is False
        assert any(i.field == "counter_evidence_ids" for i in result.issues)

    def test_representative_evidence_id_validated(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        sig = {
            "signal_id": "sig_d",
            "topic": "x",
            "evidence_ids": [ledger.all()[0].evidence_id],
            "representative_evidence_ids": ["ev_phantom_rep"],
            "source_diversity": ["reddit"],
            "volume": 1,
            "recency": 0.5,
            "signal_type": "single_source",
            "novelty": 0.5,
            "score": 0.5,
            "confidence": 0.5,
            "supporting_evidence_ids": [],
            "counter_evidence_ids": [],
        }
        result = validate_signal(ledger, sig)
        assert result.valid is False
        assert any(i.field == "representative_evidence_ids" for i in result.issues)

    def test_contradictory_with_empty_counter_evidence_reported(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        sig = {
            "signal_id": "sig_e",
            "topic": "x",
            "evidence_ids": [ledger.all()[0].evidence_id],
            "representative_evidence_ids": [ledger.all()[0].evidence_id],
            "source_diversity": ["reddit"],
            "volume": 1,
            "recency": 0.5,
            "signal_type": "contradictory",
            "novelty": 0.5,
            "score": 0.5,
            "confidence": 0.5,
            "supporting_evidence_ids": [],
            "counter_evidence_ids": [],
        }
        result = validate_signal(ledger, sig)
        assert result.valid is False
        assert any(i.field == "counter_evidence_ids"
                   and "contradictory" in i.reason for i in result.issues)


class TestInsightIntegrity:
    def _seed_insight_ledger(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        signals = {
            "sig_a": {
                "topic": "pricing",
                "evidence_ids": [ledger.all()[0].evidence_id],
                "signal_type": "repeated",
            }
        }
        return ledger, signals

    def test_valid_insight_passes(self):
        ledger, signals = self._seed_insight_ledger()
        ins = {
            "insight_id": "ins_a",
            "type": "INFERENCE",
            "statement": "Pricing complaints are rising.",
            "evidence_ids": [ledger.all()[0].evidence_id],
            "signal_ids": ["sig_a"],
            "confidence": 0.6,
            "gtm_implications": {"pricing": "Review pricing model."},
            "rationale": "Cross-source repeat over 7 days.",
        }
        result = validate_insight(ledger, ins, known_signal_ids=set(signals))
        assert result.valid is True, result.issues

    def test_missing_evidence_in_insight(self):
        ledger, signals = self._seed_insight_ledger()
        ins = {
            "insight_id": "ins_b",
            "type": "FACT",
            "statement": "X",
            "evidence_ids": ["ev_phantom"],
            "signal_ids": [],
            "confidence": 0.6,
            "gtm_implications": {},
            "rationale": "",
        }
        result = validate_insight(ledger, ins, known_signal_ids=set(signals))
        assert result.valid is False
        assert any(i.field == "evidence_ids" for i in result.issues)

    def test_missing_signal_in_insight(self):
        ledger, signals = self._seed_insight_ledger()
        ins = {
            "insight_id": "ins_c",
            "type": "INFERENCE",
            "statement": "X",
            "evidence_ids": [ledger.all()[0].evidence_id],
            "signal_ids": ["sig_unknown"],
            "confidence": 0.6,
            "gtm_implications": {},
            "rationale": "",
        }
        result = validate_insight(ledger, ins, known_signal_ids=set(signals))
        assert result.valid is False
        assert any(i.field == "signal_ids" for i in result.issues)


class TestOutputIntegrity:
    def test_output_with_full_chain_passes(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        eid = ledger.all()[0].evidence_id
        output = {
            "executive_intelligence": "Summary",
            "user_voice": [{"quote": "too expensive", "evidence_id": eid}],
            "weak_signals": [
                {"topic": "k", "evidence_ids": [eid]},
            ],
            "key_signals": [
                {
                    "signal_id": "sig_k",
                    "type": "INFERENCE",
                    "what": "k",
                    "level": "high",
                }
            ],
        }
        known_signal_ids = {"sig_k"}
        result = validate_output(ledger, output, known_signal_ids=known_signal_ids)
        assert result.valid is True, result.issues

    def test_output_user_voice_with_unknown_evidence_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        output = {
            "executive_intelligence": "x",
            "user_voice": [{"quote": "complaint", "evidence_id": "ev_ghost"}],
        }
        result = validate_output(ledger, output, known_signal_ids=set())
        assert result.valid is False
        assert any(i.field == "user_voice[].evidence_id" for i in result.issues)

    def test_output_weak_signals_with_unknown_evidence_fails(self):
        ledger = EvidenceLedger(":memory:")
        _seed(ledger)
        output = {
            "weak_signals": [
                {"topic": "k", "evidence_ids": ["ev_ghost"]},
            ],
        }
        result = validate_output(ledger, output, known_signal_ids=set())
        assert result.valid is False
        assert any(i.field == "weak_signals[].evidence_ids" for i in result.issues)

    def test_optional_sections_all_absent_is_valid(self):
        ledger = EvidenceLedger(":memory:")
        result = validate_output(ledger, {}, known_signal_ids=set())
        assert result.valid is True
        assert result.issues == []


class TestIntegrityError:
    def test_issues_carry_required_fields(self):
        issue = IntegrityIssue(
            object_type="signal",
            object_id="sig_x",
            field="evidence_ids",
            missing_ids=["ev_y"],
            reason="not in ledger",
        )
        assert issue.object_type == "signal"
        assert issue.missing_ids == ["ev_y"]

    def test_issue_string_round_trip(self):
        issue = IntegrityIssue(
            object_type="insight",
            object_id="ins_a",
            field="signal_ids",
            missing_ids=["sig_b"],
            reason="not in signals",
        )
        s = str(issue)
        assert "ins_a" in s and "signal_ids" in s and "sig_b" in s

    def test_result_raises_when_invalid(self):
        result = ValidationResult(valid=False, issues=[
            IntegrityIssue("signal", "s", "f", ["x"], "r")
        ])
        with pytest.raises(ReferentialIntegrityError) as exc_info:
            result.raise_if_invalid()
        assert "signal" in str(exc_info.value)
