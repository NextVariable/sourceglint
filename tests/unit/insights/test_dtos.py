"""Phase 6A §9 — internal Insight DTOs.

These are INTERNAL to the insight layer. None of them are written to
the frozen insight.schema.json. The only object that ever reaches a
frozen contract is the Insight dict produced by the pipeline, and it
must validate against schemas/insight.schema.json
(additionalProperties: false).
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.dtos import (
    FACT,
    INFERENCE,
    FactDraft,
    GTMImplicationDraft,
    InferenceDraft,
    InsightDiagnostics,
    InsightPipelineResult,
    PreparedSignal,
)


class TestPreparedSignal:
    def _make(self, **kw):
        base = dict(
            signal_id="sig_abc",
            signal_type="cross_source",
            claim="Translation latency dropped below one second",
            score=0.72,
            confidence=0.8,
            evidence_ids=("ev_001", "ev_002"),
            supporting_evidence_summaries=("Source A reports sub-second",),
            counter_evidence_summaries=(),
            market="jp",
            language="ja",
            current_count=2,
            baseline_count=0,
            weak_signal=False,
        )
        base.update(kw)
        return PreparedSignal(**base)

    def test_construction(self):
        ps = self._make()
        assert ps.signal_id == "sig_abc"
        assert ps.signal_type == "cross_source"

    def test_to_model_payload_minimal(self):
        """Model payload must NOT include raw metadata or scores (PRD §10)."""
        ps = self._make()
        payload = ps.to_model_payload()
        assert "signal_id" in payload
        assert "signal_type" in payload
        assert "claim" in payload
        assert "evidence_ids" in payload
        assert "current_count" in payload  # code-computed counts (PRD §37)
        assert "baseline_count" in payload
        # score and confidence are code-owned — NOT sent to model
        assert "score" not in payload
        assert "confidence" not in payload
        assert "weak_signal" in payload

    def test_to_model_payload_excludes_raw_metadata(self):
        ps = self._make()
        payload = ps.to_model_payload()
        assert "raw_metadata" not in payload
        assert "engagement" not in payload
        assert "url" not in payload  # URLs never sent to model

    def test_to_model_payload_includes_evidence_summaries(self):
        ps = self._make(
            supporting_evidence_summaries=("Sub-second latency reported",),
            counter_evidence_summaries=("Still seeing 3s delays",),
        )
        payload = ps.to_model_payload()
        assert payload["supporting_evidence_summaries"] == ["Sub-second latency reported"]
        assert payload["counter_evidence_summaries"] == ["Still seeing 3s delays"]

    def test_to_dict_full(self):
        ps = self._make()
        d = ps.to_dict()
        assert d["signal_id"] == "sig_abc"
        assert d["score"] == 0.72
        assert d["confidence"] == 0.8
        assert d["evidence_ids"] == ["ev_001", "ev_002"]

    def test_to_dict_roundtrip(self):
        ps = self._make()
        d = ps.to_dict()
        assert isinstance(d["evidence_ids"], list)
        assert isinstance(d["supporting_evidence_summaries"], list)


class TestFactDraft:
    def test_construction(self):
        fd = FactDraft(
            statement="Product A raised price from $10 to $15.",
            signal_ids=("sig_pricing",),
            evidence_ids=("ev_001", "ev_002"),
            confidence=0.9,
            rationale="Official pricing page and community confirmation",
        )
        assert fd.statement == "Product A raised price from $10 to $15."
        assert fd.signal_ids == ("sig_pricing",)
        assert fd.confidence == 0.9

    def test_to_dict(self):
        fd = FactDraft(
            statement="Test fact.",
            signal_ids=("sig_a",),
            evidence_ids=("ev_1",),
            confidence=0.8,
            rationale="rationale",
        )
        d = fd.to_dict()
        assert d["statement"] == "Test fact."
        assert d["signal_ids"] == ["sig_a"]
        assert d["evidence_ids"] == ["ev_1"]
        assert d["confidence"] == 0.8


class TestInferenceDraft:
    def test_construction(self):
        id_ = InferenceDraft(
            statement="Price sensitivity may be rising among SMB users.",
            fact_ids=("ins_fact_1", "ins_fact_2"),
            signal_ids=("sig_pricing", "sig_churn"),
            evidence_ids=("ev_1", "ev_2", "ev_3"),
            confidence=0.6,
            rationale="Multiple communities report churn after price hike",
            inference_distance=1,
        )
        assert id_.statement == "Price sensitivity may be rising among SMB users."
        assert id_.fact_ids == ("ins_fact_1", "ins_fact_2")
        assert id_.inference_distance == 1

    def test_to_dict(self):
        id_ = InferenceDraft(
            statement="Test inference.",
            fact_ids=("ins_1",),
            signal_ids=("sig_a",),
            evidence_ids=("ev_1",),
            confidence=0.5,
            rationale="r",
            inference_distance=1,
        )
        d = id_.to_dict()
        assert d["statement"] == "Test inference."
        assert d["fact_ids"] == ["ins_1"]
        assert d["inference_distance"] == 1


class TestGTMImplicationDraft:
    def test_construction(self):
        gi = GTMImplicationDraft(
            insight_id="ins_abc",
            implications={"pricing": "Price sensitivity differs by segment", "icp": None},
        )
        assert gi.insight_id == "ins_abc"
        assert gi.implications["pricing"] == "Price sensitivity differs by segment"
        assert gi.implications["icp"] is None

    def test_to_dict(self):
        gi = GTMImplicationDraft(
            insight_id="ins_abc",
            implications={"market": "JP market shows distinct pricing expectations"},
        )
        d = gi.to_dict()
        assert d["insight_id"] == "ins_abc"
        assert d["implications"]["market"] == "JP market shows distinct pricing expectations"


class TestInsightDiagnostics:
    def test_construction(self):
        diag = InsightDiagnostics(
            insight_id="ins_abc",
            type=FACT,
            support_strength=0.8,
            inference_distance=0,
            supporting_fact_ids=(),
            supporting_signal_ids=("sig_a",),
            supporting_evidence_ids=("ev_1",),
            weak_signal=False,
            contradiction_preserved=False,
            warnings=(),
        )
        assert diag.insight_id == "ins_abc"
        assert diag.type == FACT
        assert diag.support_strength == 0.8
        assert diag.inference_distance == 0

    def test_to_dict(self):
        diag = InsightDiagnostics(
            insight_id="ins_abc",
            type=INFERENCE,
            support_strength=0.6,
            inference_distance=1,
            supporting_fact_ids=("ins_1",),
            supporting_signal_ids=("sig_a",),
            supporting_evidence_ids=("ev_1",),
            weak_signal=True,
            contradiction_preserved=True,
            warnings=("weak signal: low volume",),
        )
        d = diag.to_dict()
        assert d["insight_id"] == "ins_abc"
        assert d["type"] == INFERENCE
        assert d["weak_signal"] is True
        assert d["contradiction_preserved"] is True
        assert d["warnings"] == ["weak signal: low volume"]


class TestInsightPipelineResult:
    def test_empty(self):
        r = InsightPipelineResult()
        assert r.insights == ()
        assert r.diagnostics == ()
        assert r.warnings == ()
        assert r.model_status == {}

    def test_with_data(self):
        r = InsightPipelineResult(
            insights=({"insight_id": "ins_1", "type": "FACT", "statement": "x", "confidence": 0.9},),
            diagnostics=(InsightDiagnostics(
                insight_id="ins_1", type=FACT, support_strength=0.9,
                inference_distance=0, supporting_fact_ids=(),
                supporting_signal_ids=("sig_a",), supporting_evidence_ids=("ev_1",),
                weak_signal=False, contradiction_preserved=False, warnings=(),
            ),),
            warnings=("step ok",),
            model_status={"fact_synthesis": "success"},
        )
        assert len(r.insights) == 1
        assert len(r.diagnostics) == 1
        assert r.warnings == ("step ok",)

    def test_to_dict(self):
        r = InsightPipelineResult(
            insights=({"insight_id": "ins_1", "type": "FACT", "statement": "x", "confidence": 0.9},),
            warnings=("w1",),
            model_status={"fact_synthesis": "success"},
        )
        d = r.to_dict()
        assert len(d["insights"]) == 1
        assert d["warnings"] == ["w1"]
        assert d["model_status"] == {"fact_synthesis": "success"}
