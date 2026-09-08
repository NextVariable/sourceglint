"""Phase 6B §10–§11, §18–§19, §32 — candidate generation + code validation."""
from __future__ import annotations

from gtm_intelligence.insights.ids import derive_insight_id
from gtm_intelligence.recommendations.generate import (
    CandidateGenerationResult,
    detect_action_bundling,
    generate_candidate_recommendations,
)
from gtm_intelligence.recommendations.model import (
    FakeRecommendationModel,
    FakeRecommendationScript,
)

from ._support_recs import (
    diagnostics_map,
    evidence,
    evidence_by_id,
    insight_fact,
    insight_inference,
)


def _fact(sig="sig_a", ev=("ev_1",), conf=0.8, statement="Pricing page lists $15."):
    return insight_fact(
        insight_id=derive_insight_id(type="FACT", signal_ids=(sig,), evidence_ids=ev),
        signal_ids=(sig,),
        evidence_ids=ev,
        confidence=conf,
        statement=statement,
    )


def _base():
    fact = _fact()
    inf = insight_inference(
        insight_id=derive_insight_id(
            type="INFERENCE", signal_ids=("sig_b",), evidence_ids=("ev_2",)
        ),
        signal_ids=("sig_b",),
        evidence_ids=("ev_2",),
    )
    evs = evidence_by_id(
        evidence("ev_1", snippet="Team plan: $15 per user per month.", market="jp"),
        evidence("ev_2", snippet="Individual users report price sensitivity.", market="jp"),
    )
    return [fact, inf], evs


def _model(*scripts):
    return FakeRecommendationModel(recommendation_scripts=scripts)


def _run(scripts, *, diags=None, market="jp"):
    insights, evs = _base()
    model = _model(*scripts)
    result = generate_candidate_recommendations(
        insights, model, evs,
        insight_diagnostics=diags or {},
        research_context=None,
        target_entity="",
    )
    return result


def _valid_script(**kw):
    # Default statement deliberately carries NO persona/geo/money/KPI
    # specifics: default support is FACT-only (§12 fact-only is allowed),
    # and the Team-plan FACT evidence does not mention individual users —
    # an unsupported persona there would correctly trip §33. Persona
    # grounding (pass + reject) is exercised by dedicated tests below.
    base = dict(
        statement="Test a lower-friction entry offer.",
        action="Run a two-week A/B test of an entry-level plan at the current entry price.",
        supporting_insight_ids=(_fact()["insight_id"],),
        action_class="experiment",
        gtm_dimensions=("pricing",),
        confidence=0.6,
        action_anchor="entry_offer_test",
    )
    base.update(kw)
    return FakeRecommendationScript(**base)


def _inference(*, sig="sig_b", ev=("ev_2",), conf=0.6, statement=None):
    """The base INFERENCE from _base() (individual-user price sensitivity)."""
    return insight_inference(
        insight_id=derive_insight_id(
            type="INFERENCE", signal_ids=(sig,), evidence_ids=ev
        ),
        signal_ids=(sig,),
        evidence_ids=ev,
        confidence=conf,
        statement=statement
        or "Individual users appear more price-sensitive than enterprise buyers.",
    )


class TestGenerationHappyPath:
    def test_valid_candidate(self):
        fact = _fact()
        result = _run([_valid_script(supporting_insight_ids=(fact["insight_id"],))])
        assert result.model_status == "success"
        assert len(result.validated) == 1
        assert result.rejected == ()
        assert result.validated[0].action_anchor == "entry_offer_test"

    def test_persona_grounded_via_inference_passes(self):
        # §33 persona: "individual users" appears in the cited INFERENCE
        # statement + its evidence (ev_2) — guard must NOT block it.
        inf = _inference()
        result = _run([_valid_script(
            supporting_insight_ids=(inf["insight_id"],),
            statement="Test a lower-friction entry offer for individual users.",
        )])
        assert len(result.validated) == 1
        assert result.rejected == ()

    def test_no_insights(self):
        from gtm_intelligence.recommendations.generate import (
            generate_candidate_recommendations,
        )

        r = generate_candidate_recommendations([], _model(), {})
        assert r.validated == ()
        assert any("no insights" in w for w in r.warnings)


class TestGenerationRejections:
    def test_hallucinated_insight_rejected(self):
        result = _run([
            _valid_script(supporting_insight_ids=("ins_fake",))
        ])
        assert result.validated == ()
        assert len(result.rejected) == 1
        assert any("hallucinated insight_id" in w for w in result.warnings)

    def test_unknown_class_rejected(self):
        result = _run([_valid_script(action_class="launch")])
        assert result.validated == ()
        assert any("unknown action_class" in w for w in result.warnings)

    def test_unknown_dimension_rejected(self):
        result = _run([_valid_script(gtm_dimensions=("investors",))])
        assert result.validated == ()
        assert any("unknown GTM dimension" in w for w in result.warnings)

    def test_empty_dimensions_rejected(self):
        result = _run([_valid_script(gtm_dimensions=())])
        assert result.validated == ()
        assert any("empty" in w and "§25" in w for w in result.warnings)

    def test_unsupported_budget_rejected(self):
        result = _run([_valid_script(action="Spend $50,000 on creator partnerships.")])
        assert result.validated == ()
        assert any("money" in w and "50,000" in w for w in result.warnings)

    def test_confidence_out_of_range_rejected(self):
        result = _run([_valid_script(confidence=1.4)])
        assert result.validated == ()

    def test_fact_only_support_ok(self):
        # §12: FACT-only support is allowed (no "must include an
        # INFERENCE" rule). Statement stays grounded in the FACT's own
        # evidence, so the only thing under test is fact-only acceptance.
        fact = _fact()
        result = _run([_valid_script(supporting_insight_ids=(fact["insight_id"],))])
        assert len(result.validated) == 1

    def test_ungrounded_persona_rejected(self):
        # §33: "CFOs" appears nowhere in the cited FACT's evidence pool —
        # the model is inventing ICP specificity → reject.
        fact = _fact()
        result = _run([_valid_script(
            supporting_insight_ids=(fact["insight_id"],),
            statement="Test a lower-friction entry offer for CFOs.",
        )])
        assert result.validated == ()
        assert any("unsupported persona" in w for w in result.warnings)


class TestWeakContradictionCaps:
    def _ids(self):
        fact = _fact()
        inf = _fact(sig="sig_w", ev=("ev_w",), statement="weak")
        return fact, inf

    def test_weak_signal_blocks_change(self):
        fact = _fact()
        weak_inf = insight_inference(
            insight_id=derive_insight_id(
                type="INFERENCE", signal_ids=("sig_w",), evidence_ids=("ev_2",)
            ),
            signal_ids=("sig_w",),
            evidence_ids=("ev_2",),
        )
        insights, evs = [fact, weak_inf], None
        # fix evidence map: ev_2 already present in base? use a custom run
        evs = evidence_by_id(
            evidence("ev_1", snippet="$15 plan.", market="jp"),
            evidence("ev_2", snippet="weak signal", market="jp"),
        )
        model = _model(_valid_script(
            supporting_insight_ids=(weak_inf["insight_id"],),
            action_class="change",
            action="Reposition the whole product around the entry offer.",
        ))
        diags = diagnostics_map(weak=(weak_inf["insight_id"],))
        result = generate_candidate_recommendations(
            [fact, weak_inf], model, evs, insight_diagnostics=diags
        )
        assert result.validated == ()
        assert any("weak-signal policy" in w for w in result.warnings)

    def test_weak_signal_allows_experiment(self):
        fact = _fact()
        weak_inf = insight_inference(
            insight_id=derive_insight_id(
                type="INFERENCE", signal_ids=("sig_w",), evidence_ids=("ev_2",)
            ),
            signal_ids=("sig_w",),
            evidence_ids=("ev_2",),
        )
        evs = evidence_by_id(
            evidence("ev_1", snippet="$15 plan.", market="jp"),
            evidence("ev_2", snippet="weak signal", market="jp"),
        )
        diags = diagnostics_map(weak=(weak_inf["insight_id"],))
        result = generate_candidate_recommendations(
            [fact, weak_inf],
            _model(_valid_script(
                supporting_insight_ids=(weak_inf["insight_id"],),
                action_class="experiment",
                action="Monitor and test whether entry-offer messaging resonates.",
            )),
            evs,
            insight_diagnostics=diags,
        )
        assert len(result.validated) == 1

    def test_contradiction_blocks_update(self):
        fact = _fact()
        contra_inf = insight_inference(
            insight_id=derive_insight_id(
                type="INFERENCE", signal_ids=("sig_c",), evidence_ids=("ev_2",)
            ),
            signal_ids=("sig_c",),
            evidence_ids=("ev_2",),
        )
        evs = evidence_by_id(
            evidence("ev_1", snippet="$15 plan.", market="jp"),
            evidence("ev_2", snippet="mixed reports", market="jp"),
        )
        diags = diagnostics_map(contradiction=(contra_inf["insight_id"],))
        result = generate_candidate_recommendations(
            [fact, contra_inf],
            _model(_valid_script(
                supporting_insight_ids=(contra_inf["insight_id"],),
                action_class="change",
                action="Market translation quality as the product's strongest feature.",
            )),
            evs,
            insight_diagnostics=diags,
        )
        assert result.validated == ()
        assert any("contradiction policy" in w for w in result.warnings)


class TestAtomicBundling:
    def test_bundled_action_warns(self):
        fact = _fact()
        script = _valid_script(
            supporting_insight_ids=(fact["insight_id"],),
            action="Run an A/B test and update the pricing page.",
        )
        result = _run([script])
        assert len(result.validated) == 1  # not rejected (§11 MVP warning)
        assert any("bundles multiple actions" in w for w in result.warnings)

    def test_detector_finds_connectors(self):
        assert detect_action_bundling("Do X and Y.") != []
        assert detect_action_bundling("Do X.") == []
