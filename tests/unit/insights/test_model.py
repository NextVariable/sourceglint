"""Phase 6A §7 — reuse IntelligenceModel boundary.

The insights package reuses the Phase 5 IntelligenceModel protocol
without modification. New task constants, response schemas, and a
deterministic FakeInsightModel (backward-compatible extension of
FakeIntelligenceModel) are added so unit tests can drive the insight
pipeline offline (PRD §7, §40).
"""
from __future__ import annotations

import pytest

from gtm_intelligence.intelligence.model import (
    FakeIntelligenceModel,
    ModelStatus,
)
from gtm_intelligence.insights.model import (
    FACT_SYNTHESIS_RESPONSE_SCHEMA,
    INFERENCE_SYNTHESIS_RESPONSE_SCHEMA,
    GTM_IMPLICATIONS_RESPONSE_SCHEMA,
    TASK_FACT_SYNTHESIS,
    TASK_INFERENCE_SYNTHESIS,
    TASK_GTM_IMPLICATIONS,
    FakeFactScript,
    FakeInferenceScript,
    FakeGTMImplicationScript,
    FakeInsightModel,
)


class TestTaskConstants:
    def test_fact_synthesis_constant(self):
        assert TASK_FACT_SYNTHESIS == "fact_synthesis"

    def test_inference_synthesis_constant(self):
        assert TASK_INFERENCE_SYNTHESIS == "inference_synthesis"

    def test_gtm_implications_constant(self):
        assert TASK_GTM_IMPLICATIONS == "gtm_implications"


class TestResponseSchemas:
    def test_fact_response_schema(self):
        assert FACT_SYNTHESIS_RESPONSE_SCHEMA["type"] == "object"
        assert "facts" in FACT_SYNTHESIS_RESPONSE_SCHEMA["required"]
        fact_item = FACT_SYNTHESIS_RESPONSE_SCHEMA["properties"]["facts"]["items"]
        assert "statement" in fact_item["required"]
        assert "signal_ids" in fact_item["required"]
        assert "evidence_ids" in fact_item["required"]
        assert "confidence" in fact_item["required"]

    def test_inference_response_schema(self):
        assert INFERENCE_SYNTHESIS_RESPONSE_SCHEMA["type"] == "object"
        assert "inferences" in INFERENCE_SYNTHESIS_RESPONSE_SCHEMA["required"]
        inf_item = INFERENCE_SYNTHESIS_RESPONSE_SCHEMA["properties"]["inferences"]["items"]
        assert "statement" in inf_item["required"]
        assert "fact_ids" in inf_item["required"]
        assert "signal_ids" in inf_item["required"]

    def test_gtm_implications_response_schema(self):
        assert GTM_IMPLICATIONS_RESPONSE_SCHEMA["type"] == "object"
        assert "implications" in GTM_IMPLICATIONS_RESPONSE_SCHEMA["required"]


class TestFakeInsightModel:
    def test_handles_fact_synthesis(self):
        scripts = [FakeFactScript(
            signal_ids=["sig_a"],
            statement="Price increased from $10 to $15.",
            evidence_ids=["ev_1"],
            confidence=0.9,
        )]
        model = FakeInsightModel(fact_scripts=scripts)
        resp = model.complete_structured(
            task=TASK_FACT_SYNTHESIS,
            payload={"signals": []},
            response_schema=FACT_SYNTHESIS_RESPONSE_SCHEMA,
        )
        assert resp.ok
        facts = resp.payload["facts"]
        assert len(facts) == 1
        assert facts[0]["statement"] == "Price increased from $10 to $15."

    def test_handles_inference_synthesis(self):
        scripts = [FakeInferenceScript(
            fact_ids=["ins_fact_1"],
            signal_ids=["sig_a", "sig_b"],
            statement="Price sensitivity may be rising.",
            evidence_ids=["ev_1", "ev_2"],
            confidence=0.6,
            inference_distance=1,
        )]
        model = FakeInsightModel(inference_scripts=scripts)
        resp = model.complete_structured(
            task=TASK_INFERENCE_SYNTHESIS,
            payload={"facts": [], "signals": []},
            response_schema=INFERENCE_SYNTHESIS_RESPONSE_SCHEMA,
        )
        assert resp.ok
        inferences = resp.payload["inferences"]
        assert len(inferences) == 1
        assert inferences[0]["statement"] == "Price sensitivity may be rising."

    def test_handles_gtm_implications(self):
        scripts = [FakeGTMImplicationScript(
            insight_id="ins_abc",
            implications={"pricing": "Price sensitivity differs by segment"},
        )]
        model = FakeInsightModel(gtm_scripts=scripts)
        resp = model.complete_structured(
            task=TASK_GTM_IMPLICATIONS,
            payload={"insight_id": "ins_abc", "statement": "test", "type": "FACT"},
            response_schema=GTM_IMPLICATIONS_RESPONSE_SCHEMA,
        )
        assert resp.ok
        assert resp.payload["implications"]["pricing"] == "Price sensitivity differs by segment"

    def test_backward_compatible_with_phase5_clustering(self):
        """Phase 5 tasks still work through the parent (PRD §7)."""
        from gtm_intelligence.intelligence.model import FakeClusterScript
        phase5_scripts = [FakeClusterScript(
            label="test",
            claim="test claim",
            evidence_ids=("ev_1",),
        )]
        model = FakeInsightModel(scripts=phase5_scripts)
        resp = model.complete_structured(
            task="clustering",
            payload={},
            response_schema={},
        )
        assert resp.ok
        assert resp.payload["clusters"][0]["label"] == "test"

    def test_failure_status(self):
        model = FakeInsightModel(status=ModelStatus.UNAVAILABLE)
        resp = model.complete_structured(
            task=TASK_FACT_SYNTHESIS,
            payload={},
            response_schema=FACT_SYNTHESIS_RESPONSE_SCHEMA,
        )
        assert resp.status is ModelStatus.UNAVAILABLE
        assert not resp.ok

    def test_empty_fact_scripts_returns_empty(self):
        model = FakeInsightModel()
        resp = model.complete_structured(
            task=TASK_FACT_SYNTHESIS,
            payload={"signals": []},
            response_schema=FACT_SYNTHESIS_RESPONSE_SCHEMA,
        )
        assert resp.ok
        assert resp.payload["facts"] == []

    def test_unknown_task_invalid(self):
        model = FakeInsightModel()
        resp = model.complete_structured(
            task="bogus_task",
            payload={},
            response_schema={},
        )
        assert resp.status is ModelStatus.INVALID_OUTPUT

    def test_model_id(self):
        model = FakeInsightModel()
        assert model.model_id == "fake_insight:v1"
