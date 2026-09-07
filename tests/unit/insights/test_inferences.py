"""Phase 6A §15–§20, §27, §35 — INFERENCE synthesis + validation.

INFERENCE synthesis: model combines FACTs + Signals into higher-order
inferences. Code validates support, inference distance, evidence scope,
and recommendation leakage.

Key rules:
  - Each inference needs >=1 supporting fact + >=1 supporting signal (§16)
  - Contradictory signals must be preserved, not flattened (§17)
  - Weak signals need calibrated language + lower confidence (§18)
  - Cross-signal synthesis: multiple signals → one inference (§19)
  - No over-synthesis: don't merge unrelated signals (§20)
  - Inference distance: 0/1/2 for MVP (§27)
  - Evidence scope: can reference union of evidence from multiple facts (§35)
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.dtos import (
    FACT,
    INFERENCE,
    FactDraft,
    InferenceDraft,
    PreparedSignal,
)
from gtm_intelligence.insights.inferences import (
    synthesize_inferences,
    validate_inference,
    InferenceSynthesisResult,
)
from gtm_intelligence.insights.model import (
    FakeInferenceScript,
    FakeInsightModel,
    TASK_INFERENCE_SYNTHESIS,
)
from gtm_intelligence.intelligence.dtos import ResearchContext
from gtm_intelligence.intelligence.cache import SemanticCache


def _ps(sid="sig_a", evidence_ids=("ev_1", "ev_2"), **kw):
    base = dict(
        signal_id=sid, signal_type="cross_source", claim="test claim",
        score=0.7, confidence=0.8, evidence_ids=evidence_ids,
        supporting_evidence_summaries=("summary1",), counter_evidence_summaries=(),
        market="jp", language="ja", current_count=2, baseline_count=0, weak_signal=False,
    )
    base.update(kw)
    return PreparedSignal(**base)


def _fact(ins_id="ins_fact_1", signal_ids=("sig_a",), evidence_ids=("ev_1",)):
    return FactDraft(
        statement="Price increased from $10 to $15.",
        signal_ids=signal_ids, evidence_ids=evidence_ids,
        confidence=0.9, rationale="Official pricing page",
    )


class TestValidateInference:
    def _valid_draft(self, fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
                    evidence_ids=("ev_1",)):
        return InferenceDraft(
            statement="Price sensitivity may be rising among SMB users.",
            fact_ids=fact_ids, signal_ids=signal_ids,
            evidence_ids=evidence_ids, confidence=0.6,
            rationale="Multiple communities report churn",
            inference_distance=1,
        )

    def test_valid_inference(self):
        draft = self._valid_draft()
        facts = [_fact()]
        signals = [_ps()]
        ev = {"ev_1": {}, "ev_2": {}}
        valid_fact_ids = {"ins_fact_1"}
        valid_signal_ids = {"sig_a"}
        fact_evidence_map = {"ins_fact_1": {"ev_1"}}
        signal_evidence_map = {"sig_a": {"ev_1", "ev_2"}}
        violations = validate_inference(
            draft, valid_fact_ids=valid_fact_ids,
            valid_signal_ids=valid_signal_ids, evidence_by_id=ev,
            fact_evidence_map=fact_evidence_map, signal_evidence_map=signal_evidence_map,
        )
        assert violations == []

    def test_hallucinated_fact_id_rejected(self):
        draft = self._valid_draft(fact_ids=("ins_fake",))
        facts = [_fact()]
        signals = [_ps()]
        ev = {"ev_1": {}}
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id=ev,
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("ins_fake" in v for v in violations)

    def test_hallucinated_signal_id_rejected(self):
        draft = self._valid_draft(signal_ids=("sig_fake",))
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("sig_fake" in v for v in violations)

    def test_no_supporting_fact_rejected(self):
        """§16: each inference needs >=1 supporting fact."""
        draft = self._valid_draft(fact_ids=())
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("fact" in v.lower() and "support" in v.lower() for v in violations)

    def test_no_supporting_signal_rejected(self):
        """§16: each inference needs >=1 supporting signal."""
        draft = self._valid_draft(signal_ids=())
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("signal" in v.lower() and "support" in v.lower() for v in violations)

    def test_inference_distance_out_of_range(self):
        draft = InferenceDraft(
            statement="test", fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
            evidence_ids=("ev_1",), confidence=0.6, inference_distance=3,
        )
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("distance" in v.lower() for v in violations)

    def test_evidence_scope_union_allowed(self):
        """§35: inference can reference evidence from multiple facts/signals."""
        draft = self._valid_draft(
            fact_ids=("ins_fact_1", "ins_fact_2"),
            signal_ids=("sig_a", "sig_b"),
            evidence_ids=("ev_1", "ev_2", "ev_3"),
        )
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1", "ins_fact_2"},
            valid_signal_ids={"sig_a", "sig_b"},
            evidence_by_id={"ev_1": {}, "ev_2": {}, "ev_3": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}, "ins_fact_2": {"ev_2"}},
            signal_evidence_map={"sig_a": {"ev_1", "ev_2"}, "sig_b": {"ev_3"}},
        )
        assert violations == []

    def test_evidence_outside_scope_rejected(self):
        """Evidence not in any cited fact/signal → rejected."""
        draft = self._valid_draft(evidence_ids=("ev_1", "ev_outside"))
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}, "ev_outside": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("ev_outside" in v for v in violations)

    def test_recommendation_leakage_rejected(self):
        draft = InferenceDraft(
            statement="You should target enterprise buyers first.",
            fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
            evidence_ids=("ev_1",), confidence=0.6,
        )
        violations = validate_inference(
            draft, valid_fact_ids={"ins_fact_1"},
            valid_signal_ids={"sig_a"}, evidence_by_id={"ev_1": {}},
            fact_evidence_map={"ins_fact_1": {"ev_1"}},
            signal_evidence_map={"sig_a": {"ev_1"}},
        )
        assert any("leak" in v.lower() or "should" in v.lower() for v in violations)


class TestSynthesizeInferences:
    def test_basic_synthesis(self):
        facts = [_fact()]
        signals = [_ps()]
        model = FakeInsightModel(inference_scripts=[
            FakeInferenceScript(
                fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
                statement="Price sensitivity may be rising.",
                evidence_ids=("ev_1",), confidence=0.6,
                inference_distance=1,
            )
        ])
        ev = {"ev_1": {}, "ev_2": {}}
        ctx = ResearchContext()
        fact_ids = ["ins_fact_1"]
        result = synthesize_inferences(facts, fact_ids, signals, model, ev, research_context=ctx)
        assert len(result.validated) == 1
        assert result.validated[0].statement == "Price sensitivity may be rising."

    def test_hallucinated_fact_rejected(self):
        facts = [_fact()]
        signals = [_ps()]
        model = FakeInsightModel(inference_scripts=[
            FakeInferenceScript(
                fact_ids=("ins_fake",), signal_ids=("sig_a",),
                statement="Bad inference.", evidence_ids=("ev_1",),
                confidence=0.6,
            )
        ])
        ev = {"ev_1": {}}
        ctx = ResearchContext()
        result = synthesize_inferences(facts, ["ins_fact_1"], signals, model, ev, research_context=ctx)
        assert len(result.validated) == 0
        assert len(result.rejected) == 1

    def test_empty_facts(self):
        signals = [_ps()]
        model = FakeInsightModel()
        ctx = ResearchContext()
        result = synthesize_inferences([], [], signals, model, {}, research_context=ctx)
        assert result.validated == ()
        assert result.rejected == ()

    def test_model_failure(self):
        from gtm_intelligence.intelligence.model import ModelStatus
        facts = [_fact()]
        signals = [_ps()]
        model = FakeInsightModel(status=ModelStatus.UNAVAILABLE)
        ev = {"ev_1": {}}
        ctx = ResearchContext()
        result = synthesize_inferences(facts, ["ins_fact_1"], signals, model, ev, research_context=ctx)
        assert result.validated == ()
        assert any("unavailable" in w.lower() or "fail" in w.lower() for w in result.warnings)

    def test_cache_hit(self):
        facts = [_fact()]
        signals = [_ps()]
        model = FakeInsightModel(inference_scripts=[
            FakeInferenceScript(
                fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
                statement="Cached inference.", evidence_ids=("ev_1",),
                confidence=0.6,
            )
        ])
        ev = {"ev_1": {}}
        ctx = ResearchContext()
        cache = SemanticCache()
        r1 = synthesize_inferences(facts, ["ins_fact_1"], signals, model, ev, research_context=ctx, cache=cache)
        calls1 = len(model.calls)
        r2 = synthesize_inferences(facts, ["ins_fact_1"], signals, model, ev, research_context=ctx, cache=cache)
        assert len(model.calls) == calls1
        assert r2.validated[0].statement == r1.validated[0].statement

    def test_partial_success(self):
        facts = [_fact()]
        signals = [_ps()]
        model = FakeInsightModel(inference_scripts=[
            FakeInferenceScript(
                fact_ids=("ins_fact_1",), signal_ids=("sig_a",),
                statement="Valid inference.", evidence_ids=("ev_1",),
                confidence=0.6,
            ),
            FakeInferenceScript(
                fact_ids=("ins_fake",), signal_ids=("sig_a",),
                statement="Invalid inference.", evidence_ids=("ev_1",),
                confidence=0.6,
            ),
        ])
        ev = {"ev_1": {}}
        ctx = ResearchContext()
        result = synthesize_inferences(facts, ["ins_fact_1"], signals, model, ev, research_context=ctx)
        assert len(result.validated) == 1
        assert len(result.rejected) == 1
