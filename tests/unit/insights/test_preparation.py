"""Phase 6A §10 — PreparedSignal layer.

prepare_signals() converts Phase 5 signal dicts + evidence ledger into
minimal PreparedSignal DTOs for the insight model. It is pure CODE:
stable ordering, evidence summary extraction, code-computed counts
(PRD §37: model never counts), weak-signal flag injection.

The model never sees: score, confidence, engagement, URL, raw_metadata.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.preparation import prepare_signals
from gtm_intelligence.insights.dtos import PreparedSignal


def _ev(eid, *, snippet="", title="", window="current", market="jp", language="ja"):
    return {
        "evidence_id": eid,
        "source": "reddit",
        "source_type": "post",
        "window": window,
        "snippet": snippet,
        "title": title,
        "market": market,
        "language": language,
        "url": "https://example.com/" + eid,
    }


def _sig(sid, *, evidence_ids, supporting=None, counter=None, topic="test", stype="cross_source", score=0.7, confidence=0.8):
    return {
        "signal_id": sid,
        "topic": topic,
        "evidence_ids": list(evidence_ids),
        "signal_type": stype,
        "score": score,
        "confidence": confidence,
        "supporting_evidence_ids": list(supporting or evidence_ids),
        "counter_evidence_ids": list(counter or []),
    }


class TestPrepareSignals:
    def test_empty_signals(self):
        prepared, warnings = prepare_signals([], {})
        assert prepared == []
        assert warnings == []

    def test_basic_preparation(self):
        ev = {"ev_1": _ev("ev_1", snippet="Sub-second latency")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"], topic="latency drop")]
        prepared, _ = prepare_signals(sigs, ev)
        assert len(prepared) == 1
        ps = prepared[0]
        assert ps.signal_id == "sig_a"
        assert ps.signal_type == "cross_source"
        assert ps.claim == "latency drop"
        assert ps.evidence_ids == ("ev_1",)

    def test_score_and_confidence_excluded_from_payload(self):
        ev = {"ev_1": _ev("ev_1")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"], score=0.9, confidence=0.95)]
        prepared, _ = prepare_signals(sigs, ev)
        payload = prepared[0].to_model_payload()
        assert "score" not in payload
        assert "confidence" not in payload

    def test_evidence_summaries_extracted_from_snippet(self):
        ev = {
            "ev_1": _ev("ev_1", snippet="Latency dropped to 500ms"),
            "ev_2": _ev("ev_2", snippet="Still seeing 3s delays"),
        }
        sigs = [_sig("sig_a", evidence_ids=["ev_1", "ev_2"],
                      supporting=["ev_1"], counter=["ev_2"])]
        prepared, _ = prepare_signals(sigs, ev)
        ps = prepared[0]
        assert "Latency dropped to 500ms" in ps.supporting_evidence_summaries
        assert "Still seeing 3s delays" in ps.counter_evidence_summaries

    def test_evidence_summaries_fallback_to_title(self):
        ev = {"ev_1": _ev("ev_1", title="Pricing page shows $15", snippet="")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"])]
        prepared, _ = prepare_signals(sigs, ev)
        assert "Pricing page shows $15" in prepared[0].supporting_evidence_summaries

    def test_code_computed_counts(self):
        ev = {
            "ev_1": _ev("ev_1", window="current"),
            "ev_2": _ev("ev_2", window="baseline"),
            "ev_3": _ev("ev_3", window="current"),
        }
        sigs = [_sig("sig_a", evidence_ids=["ev_1", "ev_2", "ev_3"])]
        prepared, _ = prepare_signals(sigs, ev)
        ps = prepared[0]
        assert ps.current_count == 2
        assert ps.baseline_count == 1

    def test_weak_signal_flag(self):
        ev = {"ev_1": _ev("ev_1")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"], stype="emerging")]
        prepared, _ = prepare_signals(sigs, ev, weak_signal_ids={"sig_a"})
        assert prepared[0].weak_signal is True

    def test_weak_signal_default_false(self):
        ev = {"ev_1": _ev("ev_1")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"])]
        prepared, _ = prepare_signals(sigs, ev)
        assert prepared[0].weak_signal is False

    def test_missing_evidence_warning(self):
        sigs = [_sig("sig_a", evidence_ids=["ev_missing"])]
        prepared, warnings = prepare_signals(sigs, {})
        assert len(prepared) == 1
        assert any("ev_missing" in w for w in warnings)
        assert prepared[0].supporting_evidence_summaries == ()

    def test_market_language_from_evidence(self):
        ev = {"ev_1": _ev("ev_1", market="jp", language="ja")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"])]
        prepared, _ = prepare_signals(sigs, ev)
        assert prepared[0].market == "jp"
        assert prepared[0].language == "ja"

    def test_stable_ordering(self):
        """Signals are sorted by signal_id for determinism."""
        ev = {"ev_1": _ev("ev_1")}
        sigs = [
            _sig("sig_b", evidence_ids=["ev_1"]),
            _sig("sig_a", evidence_ids=["ev_1"]),
        ]
        prepared, _ = prepare_signals(sigs, ev)
        assert prepared[0].signal_id == "sig_a"
        assert prepared[1].signal_id == "sig_b"

    def test_url_not_in_payload(self):
        ev = {"ev_1": _ev("ev_1")}
        sigs = [_sig("sig_a", evidence_ids=["ev_1"])]
        prepared, _ = prepare_signals(sigs, ev)
        payload = prepared[0].to_model_payload()
        assert "url" not in payload
