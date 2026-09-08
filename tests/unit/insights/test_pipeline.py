"""Phase 6A §8, §31, §47 — insight pipeline integration tests.

End-to-end: Signal → FACT → INFERENCE → Insight.
STOP at Insight (§47): no RECOMMENDATION, no action, no final brief.
"""
from __future__ import annotations

import json

import pytest

from gtm_intelligence.insights.pipeline import run_insight_pipeline
from gtm_intelligence.insights.ids import derive_insight_id
from gtm_intelligence.insights.model import (
    FakeFactScript,
    FakeGTMImplicationScript,
    FakeInferenceScript,
    FakeInsightModel,
)
from gtm_intelligence.intelligence.dtos import ResearchContext


def _ev(eid, *, snippet="", title="", window="current", market="jp", language="ja"):
    return {
        "evidence_id": eid, "source": "reddit", "source_type": "post",
        "window": window, "snippet": snippet, "title": title,
        "market": market, "language": language,
        "url": "https://example.com/" + eid,
    }


def _sig(sid, *, evidence_ids, supporting=None, counter=None, topic="test",
         stype="cross_source", score=0.7, confidence=0.8):
    return {
        "signal_id": sid, "topic": topic, "evidence_ids": list(evidence_ids),
        "signal_type": stype, "score": score, "confidence": confidence,
        "supporting_evidence_ids": list(supporting or evidence_ids),
        "counter_evidence_ids": list(counter or []),
    }


def _full_setup():
    """Create a complete signal+evidence+model setup for pipeline tests."""
    evidence = {
        "ev_1": _ev("ev_1", snippet="Price increased from $10 to $15"),
        "ev_2": _ev("ev_2", snippet="Users complaining about the price hike"),
        "ev_3": _ev("ev_3", snippet="Free alternatives gaining mentions"),
    }
    signals = [
        _sig("sig_pricing", evidence_ids=["ev_1", "ev_2"], topic="Pricing increase confirmed"),
        _sig("sig_alternatives", evidence_ids=["ev_3"], topic="Free alternatives emerging"),
    ]
    # Compute deterministic fact insight IDs (must match what the pipeline derives)
    fact1_id = derive_insight_id(type="FACT", signal_ids=("sig_pricing",), evidence_ids=("ev_1",))
    fact2_id = derive_insight_id(type="FACT", signal_ids=("sig_alternatives",), evidence_ids=("ev_3",))
    # Compute inference insight ID
    inf_id = derive_insight_id(type="INFERENCE",
                               signal_ids=("sig_pricing", "sig_alternatives"),
                               evidence_ids=("ev_1", "ev_3"))
    model = FakeInsightModel(
        fact_scripts=[
            FakeFactScript(
                signal_ids=("sig_pricing",),
                statement="Product A's listed price increased from $10 to $15.",
                evidence_ids=("ev_1",),
                confidence=0.9,
                rationale="Official pricing page",
            ),
            FakeFactScript(
                signal_ids=("sig_alternatives",),
                statement="Several community posts mention free alternatives.",
                evidence_ids=("ev_3",),
                confidence=0.7,
                rationale="Community discussion",
            ),
        ],
        inference_scripts=[
            FakeInferenceScript(
                fact_ids=(fact1_id,),
                signal_ids=("sig_pricing", "sig_alternatives"),
                statement="Value pressure may be increasing as users compare paid tools with free substitutes.",
                evidence_ids=("ev_1", "ev_3"),
                confidence=0.55,
                rationale="Pricing complaints + free alternative mentions",
                inference_distance=1,
            ),
        ],
        gtm_scripts=[
            FakeGTMImplicationScript(
                insight_id=fact1_id,
                implications={"pricing": "Price sensitivity appears in community discussion"},
            ),
            FakeGTMImplicationScript(
                insight_id=inf_id,
                implications={
                    "pricing": "Value pressure may be increasing",
                    "competitor": "Free alternatives are gaining visibility",
                },
            ),
        ],
    )
    return signals, evidence, model


class TestRunInsightPipeline:
    def test_basic_pipeline(self):
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        assert len(result.insights) >= 2  # at least 2 facts
        types = {i["type"] for i in result.insights}
        assert "FACT" in types

    def test_no_recommendation(self):
        """§47: no RECOMMENDATION in output."""
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        for ins in result.insights:
            assert ins["type"] != "RECOMMENDATION"
            assert "action" not in ins

    def test_insight_ids_valid(self):
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        for ins in result.insights:
            assert ins["insight_id"].startswith("ins_")
            assert len(ins["insight_id"]) > 4

    def test_traceability(self):
        """§3: Insight → Signal → Evidence chain."""
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        signal_ids = {s["signal_id"] for s in signals}
        evidence_ids = set(evidence)
        for ins in result.insights:
            for sid in ins.get("signal_ids", []):
                assert sid in signal_ids, f"signal {sid} not in input signals"
            for eid in ins.get("evidence_ids", []):
                assert eid in evidence_ids, f"evidence {eid} not in ledger"

    def test_deterministic_20_runs(self):
        """§41: 20 consecutive runs produce identical output."""
        signals, evidence, model = _full_setup()
        first = run_insight_pipeline(signals, evidence, model).to_dict()
        for _ in range(19):
            result = run_insight_pipeline(signals, evidence, model).to_dict()
            assert result == first, "pipeline output is not deterministic"

    def test_empty_signals(self):
        model = FakeInsightModel()
        result = run_insight_pipeline([], {}, model)
        assert result.insights == ()
        assert any("no signals" in w for w in result.warnings)

    def test_model_failure(self):
        from gtm_intelligence.intelligence.model import ModelStatus
        signals, evidence, _ = _full_setup()
        model = FakeInsightModel(status=ModelStatus.UNAVAILABLE)
        result = run_insight_pipeline(signals, evidence, model)
        assert result.insights == ()
        assert any("unavailable" in w.lower() or "fail" in w.lower() for w in result.warnings)

    def test_gtm_implications_present(self):
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        has_gtm = any("gtm_implications" in i for i in result.insights)
        assert has_gtm

    def test_diagnostics_present(self):
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        assert len(result.diagnostics) == len(result.insights)
        for diag in result.diagnostics:
            assert diag.insight_id
            assert diag.type in ("FACT", "INFERENCE")

    def test_model_status(self):
        signals, evidence, model = _full_setup()
        result = run_insight_pipeline(signals, evidence, model)
        assert "fact_synthesis" in result.model_status
        assert "inference_synthesis" in result.model_status
        assert "gtm_implications" in result.model_status

    def test_inference_failure_keeps_facts(self):
        """§31: inference failure → facts still returned."""
        signals, evidence, model = _full_setup()
        # Remove inference scripts → inference synthesis returns empty
        model.inference_scripts = ()
        fact1_id = derive_insight_id(type="FACT", signal_ids=("sig_pricing",), evidence_ids=("ev_1",))
        model.gtm_scripts = [
            FakeGTMImplicationScript(
                insight_id=fact1_id,
                implications={"pricing": "Price sensitivity appears"},
            )
        ]
        result = run_insight_pipeline(signals, evidence, model)
        # Facts should still be present
        fact_types = [i for i in result.insights if i["type"] == "FACT"]
        assert len(fact_types) >= 1

    def test_gate_d_fabricated_quantification_rejected(self):
        """Gate D (§12, §32): a fabricated '80%' never reaches output."""
        signals, evidence, model = _full_setup()
        # The scripted model fabricates a percentage the evidence cannot
        # support ("several users" in evidence, "80%" in the statement).
        model.fact_scripts = (
            FakeFactScript(
                signal_ids=("sig_pricing",),
                statement="80% of users complained about the price hike.",
                evidence_ids=("ev_1",),
                confidence=0.9,
            ),
        )
        model.inference_scripts = ()
        model.gtm_scripts = ()
        result = run_insight_pipeline(signals, evidence, model)
        assert result.insights == ()
        assert any("grounding" in w and "quantification" in w for w in result.warnings)
