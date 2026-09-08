"""Phase 6A §11–§14, §32, §34 — FACT synthesis + grounding validation.

FACT synthesis: model compresses one or more Signals into grounded
FACT statements. Code validates referential integrity, grounding rules,
and recommendation leakage. No silent repair (§32): hallucinated refs
are rejected, not stripped.

Grounding rules (§12):
  - Unsupported quantification → reject
  - Unsupported causality → reject
  - Unsupported universality → reject
  - Unsupported future → reject

Evidence scope (§34): FACT evidence_ids must be a subset of the
evidence belonging to the cited signal_ids.
"""
from __future__ import annotations

import pytest

from gtm_intelligence.insights.dtos import (
    FACT,
    FactDraft,
    InferenceDraft,
    PreparedSignal,
)
from gtm_intelligence.insights.facts import (
    synthesize_facts,
    validate_fact,
    FactSynthesisResult,
)
from gtm_intelligence.insights.model import (
    FakeFactScript,
    FakeInsightModel,
    TASK_FACT_SYNTHESIS,
)
from gtm_intelligence.intelligence.dtos import ResearchContext
from gtm_intelligence.intelligence.cache import SemanticCache


def _ps(sid="sig_a", evidence_ids=("ev_1", "ev_2"), **kw):
    base = dict(
        signal_id=sid,
        signal_type="cross_source",
        claim="test claim",
        score=0.7,
        confidence=0.8,
        evidence_ids=evidence_ids,
        supporting_evidence_summaries=("summary1",),
        counter_evidence_summaries=(),
        market="jp",
        language="ja",
        current_count=2,
        baseline_count=0,
        weak_signal=False,
    )
    base.update(kw)
    return PreparedSignal(**base)


def _signal_evidence_map(*signals):
    return {s.signal_id: set(s.evidence_ids) for s in signals}


class TestValidateFact:
    def _valid_draft(self, signal_ids=("sig_a",), evidence_ids=("ev_1",)):
        return FactDraft(
            statement="Product A raised price from $10 to $15.",
            signal_ids=signal_ids,
            evidence_ids=evidence_ids,
            confidence=0.9,
            rationale="Official pricing page",
        )

    def test_valid_fact(self):
        draft = self._valid_draft()
        signals = [_ps()]
        ev = {
            "ev_1": {"evidence_id": "ev_1", "snippet": "Price increased from $10 to $15"},
            "ev_2": {"evidence_id": "ev_2", "snippet": "Users complaining about the price hike"},
        }
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert violations == []

    def test_hallucinated_signal_id_rejected(self):
        """No silent repair (§32): fake signal_id → reject, not strip."""
        draft = self._valid_draft(signal_ids=("sig_fake",))
        signals = [_ps()]
        ev = {"ev_1": {"evidence_id": "ev_1"}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("sig_fake" in v for v in violations)

    def test_hallucinated_evidence_id_rejected(self):
        """No silent repair (§32): fake evidence_id → reject, not strip."""
        draft = self._valid_draft(evidence_ids=("ev_fake",))
        signals = [_ps()]
        ev = {"ev_1": {"evidence_id": "ev_1"}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("ev_fake" in v for v in violations)

    def test_evidence_outside_signal_scope_rejected(self):
        """§34: evidence must belong to at least one cited signal."""
        # sig_a has ev_1, ev_2. ev_3 belongs to sig_b (not cited).
        draft = self._valid_draft(signal_ids=("sig_a",), evidence_ids=("ev_1", "ev_3"))
        signals = [_ps("sig_a", evidence_ids=("ev_1", "ev_2"))]
        ev = {"ev_1": {}, "ev_2": {}, "ev_3": {}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a", "sig_b"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("ev_3" in v for v in violations)

    def test_confidence_out_of_range(self):
        draft = self._valid_draft()
        draft = FactDraft(**{**draft.__dict__, "confidence": 1.5})
        signals = [_ps()]
        ev = {"ev_1": {}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("confidence" in v.lower() for v in violations)

    def test_empty_statement_rejected(self):
        draft = FactDraft(statement="", signal_ids=("sig_a",),
                         evidence_ids=("ev_1",), confidence=0.8)
        signals = [_ps()]
        ev = {"ev_1": {}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("statement" in v.lower() for v in violations)

    def test_recommendation_leakage_rejected(self):
        draft = FactDraft(
            statement="You should lower the price to compete.",
            signal_ids=("sig_a",), evidence_ids=("ev_1",), confidence=0.8,
        )
        signals = [_ps()]
        ev = {"ev_1": {}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        assert any("recommend" in v.lower() or "should" in v.lower() for v in violations)

    def test_voc_quote_not_flagged_as_recommendation(self):
        """§28: quoted user desire ≠ assistant action advice."""
        draft = FactDraft(
            statement='Users say the product "should support Japanese."',
            signal_ids=("sig_a",), evidence_ids=("ev_1",), confidence=0.8,
        )
        signals = [_ps()]
        ev = {"ev_1": {}}
        sem = _signal_evidence_map(*signals)
        violations = validate_fact(draft, valid_signal_ids={"sig_a"},
                                    evidence_by_id=ev, signal_evidence_map=sem)
        # This is a VOC fact quoting user desire — NOT a recommendation
        assert not any("recommend" in v.lower() or "should" in v.lower()
                        for v in violations if "leak" in v.lower())


    def test_grounded_fact_with_counts_passes(self):
        """§37: a number that mirrors a code-computed count is grounded."""
        signals = [_ps("sig_a", evidence_ids=("ev_1",), current_count=7, baseline_count=0)]
        sem = _signal_evidence_map(*signals)
        draft = FactDraft(
            statement=(
                "The issue appears in 7 current-window evidence items "
                "and 0 baseline items."
            ),
            signal_ids=("sig_a",), evidence_ids=("ev_1",), confidence=0.8,
        )
        ev = {"ev_1": {"evidence_id": "ev_1", "snippet": "Translation latency complaints"}}
        violations = validate_fact(
            draft, valid_signal_ids={"sig_a"},
            evidence_by_id=ev, signal_evidence_map=sem,
            code_counts={"sig_a": (7, 0)},
        )
        assert violations == []

    def test_unsupported_quantification_rejected(self):
        """§12: 'several' in evidence ≠ '80%' in the FACT statement."""
        signals = [_ps("sig_a", evidence_ids=("ev_1",))]
        sem = _signal_evidence_map(*signals)
        draft = FactDraft(
            statement="80% of users complained about translation latency.",
            signal_ids=("sig_a",), evidence_ids=("ev_1",), confidence=0.8,
        )
        ev = {"ev_1": {"evidence_id": "ev_1", "snippet": "Several users complained"}}
        violations = validate_fact(
            draft, valid_signal_ids={"sig_a"},
            evidence_by_id=ev, signal_evidence_map=sem,
        )
        assert any("grounding" in v and "quantification" in v for v in violations)

    def test_unsupported_causality_rejected_not_stripped(self):
        """§12 + §32: an unsupported causal claim is rejected, not repaired."""
        signals = [_ps("sig_a", evidence_ids=("ev_1", "ev_2"))]
        sem = _signal_evidence_map(*signals)
        draft = FactDraft(
            statement="The price increase caused the sales decline.",
            signal_ids=("sig_a",), evidence_ids=("ev_1", "ev_2"), confidence=0.8,
        )
        ev = {
            "ev_1": {"evidence_id": "ev_1", "snippet": "Price increased this quarter"},
            "ev_2": {"evidence_id": "ev_2", "snippet": "Sales declined this quarter"},
        }
        violations = validate_fact(
            draft, valid_signal_ids={"sig_a"},
            evidence_by_id=ev, signal_evidence_map=sem,
        )
        assert any("grounding" in v and "causality" in v for v in violations)


class TestSynthesizeFacts:
    def test_basic_synthesis(self):
        signals = [_ps()]
        model = FakeInsightModel(fact_scripts=[
            FakeFactScript(
                signal_ids=("sig_a",),
                statement="Price increased from $10 to $15.",
                evidence_ids=("ev_1",),
                confidence=0.9,
                rationale="Official pricing page",
            )
        ])
        ev = {
            "ev_1": {"evidence_id": "ev_1", "snippet": "Price increased from $10 to $15"},
            "ev_2": {"evidence_id": "ev_2", "snippet": "Users complaining about the price hike"},
        }
        ctx = ResearchContext()
        result = synthesize_facts(signals, model, ev, research_context=ctx)
        assert len(result.validated) == 1
        assert result.validated[0].statement == "Price increased from $10 to $15."
        assert result.rejected == ()

    def test_hallucinated_ref_rejected_not_stripped(self):
        """§32: hallucinated refs rejected, not silently repaired."""
        signals = [_ps()]
        model = FakeInsightModel(fact_scripts=[
            FakeFactScript(
                signal_ids=("sig_fake",),
                statement="Fake fact.",
                evidence_ids=("ev_fake",),
                confidence=0.9,
            )
        ])
        ev = {"ev_1": {}, "ev_2": {}}
        ctx = ResearchContext()
        result = synthesize_facts(signals, model, ev, research_context=ctx)
        assert len(result.validated) == 0
        assert len(result.rejected) == 1
        assert any("sig_fake" in w or "ev_fake" in w for w in result.warnings)

    def test_empty_signals(self):
        model = FakeInsightModel()
        ctx = ResearchContext()
        result = synthesize_facts([], model, {}, research_context=ctx)
        assert result.validated == ()
        assert result.rejected == ()

    def test_model_failure_returns_empty_with_warning(self):
        from gtm_intelligence.intelligence.model import ModelStatus
        signals = [_ps()]
        model = FakeInsightModel(status=ModelStatus.UNAVAILABLE)
        ev = {"ev_1": {}}
        ctx = ResearchContext()
        result = synthesize_facts(signals, model, ev, research_context=ctx)
        assert result.validated == ()
        assert result.rejected == ()
        assert any("unavailable" in w.lower() or "fail" in w.lower() for w in result.warnings)

    def test_cache_hit_skips_model_call(self):
        signals = [_ps()]
        model = FakeInsightModel(fact_scripts=[
            FakeFactScript(signal_ids=("sig_a",), statement="Cached fact.",
                          evidence_ids=("ev_1",), confidence=0.9)
        ])
        ev = {"ev_1": {}, "ev_2": {}}
        ctx = ResearchContext()
        cache = SemanticCache()
        # First call populates cache
        r1 = synthesize_facts(signals, model, ev, research_context=ctx, cache=cache)
        assert len(r1.validated) == 1
        calls_after_first = len(model.calls)
        # Second call should hit cache (no new model calls)
        r2 = synthesize_facts(signals, model, ev, research_context=ctx, cache=cache)
        assert len(model.calls) == calls_after_first  # no new calls
        assert r2.validated[0].statement == r1.validated[0].statement

    def test_partial_success(self):
        """One valid fact + one invalid fact → partial."""
        signals = [_ps()]
        model = FakeInsightModel(fact_scripts=[
            FakeFactScript(signal_ids=("sig_a",), statement="Valid fact.",
                          evidence_ids=("ev_1",), confidence=0.9),
            FakeFactScript(signal_ids=("sig_fake",), statement="Invalid fact.",
                          evidence_ids=("ev_fake",), confidence=0.9),
        ])
        ev = {"ev_1": {}, "ev_2": {}}
        ctx = ResearchContext()
        result = synthesize_facts(signals, model, ev, research_context=ctx)
        assert len(result.validated) == 1
        assert len(result.rejected) == 1
