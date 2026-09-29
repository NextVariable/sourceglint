"""Phase 6A §24–§25, §28 — GTM implications (descriptive) + leakage guard.

GTM implications are DESCRIPTIVE only (§5, §24):
  "Price sensitivity differs by segment" → OK
  "Lower the price to $9" → REJECT (action, Phase 6B territory)

16 frozen dimensions (§24). Sparsity: only materially relevant (§25).
Recommendation leakage guard (§28) screens implication values for
action language, distinguishing VOC quotes from assistant advice.
"""
from __future__ import annotations

import pytest

from sourceglint.insights.dtos import (
    FACT,
    INFERENCE,
    FactDraft,
    GTMImplicationDraft,
    InferenceDraft,
)
from sourceglint.insights.gtm_implications import (
    derive_gtm_implications,
    validate_gtm_implications,
    GTMImplicationResult,
)
from sourceglint.insights.model import (
    FakeGTMImplicationScript,
    FakeInsightModel,
    TASK_GTM_IMPLICATIONS,
)
from sourceglint.intelligence.dtos import ResearchContext
from sourceglint.intelligence.cache import SemanticCache


def _fact(ins_id="ins_fact_1"):
    return FactDraft(
        statement="Price increased from $10 to $15.",
        signal_ids=("sig_a",), evidence_ids=("ev_1",),
        confidence=0.9, rationale="Official page",
    ), ins_id, FACT


def _inference(ins_id="ins_inf_1"):
    return InferenceDraft(
        statement="Price sensitivity may be rising.",
        fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
        evidence_ids=("ev_1",), confidence=0.6,
        inference_distance=1,
    ), ins_id, INFERENCE


class TestValidateGtmImplications:
    def test_valid_descriptive(self):
        impls = {"pricing": "Price sensitivity differs by segment"}
        violations = validate_gtm_implications(impls)
        assert violations == []

    def test_null_value_ok(self):
        """null = assessed, no implication (§25)."""
        impls = {"pricing": None}
        violations = validate_gtm_implications(impls)
        assert violations == []

    def test_empty_ok(self):
        """Sparsity: no implications is valid (§25)."""
        violations = validate_gtm_implications({})
        assert violations == []

    def test_action_language_rejected(self):
        impls = {"pricing": "Lower the price to $9"}
        violations = validate_gtm_implications(impls)
        assert any("leak" in v.lower() or "lower" in v.lower() for v in violations)

    def test_target_action_rejected(self):
        impls = {"icp": "Target enterprise buyers first"}
        violations = validate_gtm_implications(impls)
        assert any("target" in v.lower() or "leak" in v.lower() for v in violations)

    def test_launch_action_rejected(self):
        impls = {"launch": "Launch a cheaper $9 plan"}
        violations = validate_gtm_implications(impls)
        assert any("launch" in v.lower() or "leak" in v.lower() for v in violations)

    def test_unknown_dimension_rejected(self):
        impls = {"fiscal_policy": "some implication"}
        violations = validate_gtm_implications(impls)
        assert any("fiscal_policy" in v or "dimension" in v.lower() for v in violations)

    def test_non_string_value_rejected(self):
        impls = {"pricing": 123}
        violations = validate_gtm_implications(impls)
        assert any("pricing" in v or "type" in v.lower() for v in violations)

    def test_voc_quote_in_implication_ok(self):
        """§28: quoted user desire in implication is descriptive, not action."""
        impls = {"pain_point": 'Users report the product "should support Japanese"'}
        violations = validate_gtm_implications(impls)
        assert violations == []

    def test_multiple_dimensions(self):
        impls = {
            "pricing": "Price sensitivity differs by segment",
            "icp": "Individual and enterprise users may need separate framing",
            "messaging": None,
        }
        violations = validate_gtm_implications(impls)
        assert violations == []


class TestDeriveGtmImplications:
    def test_basic_derivation(self):
        fact, ins_id, _ = _fact()
        model = FakeInsightModel(gtm_scripts=[
            FakeGTMImplicationScript(
                insight_id=ins_id,
                implications={"pricing": "Price sensitivity differs by segment"},
            )
        ])
        ctx = ResearchContext()
        result = derive_gtm_implications([(fact, ins_id, FACT)], model, research_context=ctx)
        assert len(result.implications) == 1
        gi = result.implications[0]
        assert gi.insight_id == ins_id
        assert gi.implications["pricing"] == "Price sensitivity differs by segment"

    def test_action_language_rejected(self):
        fact, ins_id, _ = _fact()
        model = FakeInsightModel(gtm_scripts=[
            FakeGTMImplicationScript(
                insight_id=ins_id,
                implications={"pricing": "Lower the price to $9"},
            )
        ])
        ctx = ResearchContext()
        result = derive_gtm_implications([(fact, ins_id, FACT)], model, research_context=ctx)
        assert len(result.rejected) == 1
        assert len(result.implications) == 0

    def test_empty_insights(self):
        model = FakeInsightModel()
        ctx = ResearchContext()
        result = derive_gtm_implications([], model, research_context=ctx)
        assert result.implications == ()
        assert result.rejected == ()

    def test_model_failure(self):
        from sourceglint.intelligence.model import ModelStatus
        fact, ins_id, _ = _fact()
        model = FakeInsightModel(status=ModelStatus.UNAVAILABLE)
        ctx = ResearchContext()
        result = derive_gtm_implications([(fact, ins_id, FACT)], model, research_context=ctx)
        assert result.implications == ()
        assert any("unavailable" in w.lower() or "fail" in w.lower() for w in result.warnings)

    def test_cache_hit(self):
        fact, ins_id, _ = _fact()
        model = FakeInsightModel(gtm_scripts=[
            FakeGTMImplicationScript(
                insight_id=ins_id,
                implications={"pricing": "Price sensitivity"},
            )
        ])
        ctx = ResearchContext()
        cache = SemanticCache()
        r1 = derive_gtm_implications([(fact, ins_id, FACT)], model, research_context=ctx, cache=cache)
        calls1 = len(model.calls)
        r2 = derive_gtm_implications([(fact, ins_id, FACT)], model, research_context=ctx, cache=cache)
        assert len(model.calls) == calls1

    def test_partial_success(self):
        fact1, id1, _ = _fact()
        fact2, id2, _ = _fact("ins_fact_2")
        model = FakeInsightModel(gtm_scripts=[
            FakeGTMImplicationScript(insight_id=id1, implications={"pricing": "OK"}),
            FakeGTMImplicationScript(insight_id=id2, implications={"pricing": "Lower price now"}),
        ])
        ctx = ResearchContext()
        result = derive_gtm_implications(
            [(fact1, id1, FACT), (fact2, id2, FACT)], model, research_context=ctx
        )
        assert len(result.implications) == 1
        assert len(result.rejected) == 1

    def test_inference_implications(self):
        inf, ins_id, _ = _inference()
        model = FakeInsightModel(gtm_scripts=[
            FakeGTMImplicationScript(
                insight_id=ins_id,
                implications={"pricing": "Value pressure may be increasing"},
            )
        ])
        ctx = ResearchContext()
        result = derive_gtm_implications([(inf, ins_id, INFERENCE)], model, research_context=ctx)
        assert len(result.implications) == 1
        assert result.implications[0].implications["pricing"] == "Value pressure may be increasing"
