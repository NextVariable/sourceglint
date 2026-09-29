"""Phase 6B §14, §20–§22 — assessment, priority formula, risk categories."""
from __future__ import annotations

import pytest

from sourceglint.insights.model import ModelStatus
from sourceglint.recommendations.assess import (
    assess_priority,
    assess_recommendations,
    assess_risk,
    compute_reversibility,
    priority_bucket,
)
from sourceglint.recommendations.dtos import (
    RecommendationAssessment,
    RecommendationDraft,
    RecommendationSupport,
)
from sourceglint.recommendations.model import (
    FakeRecommendationModel,
    FakeRecommendationScript,
)
from sourceglint.recommendations.policy import (
    PRIORITY_W_FEASIBILITY,
    PRIORITY_W_IMPACT,
    PRIORITY_W_REVERSIBILITY,
    PRIORITY_W_SUPPORT,
    PRIORITY_W_URGENCY,
    REVERSIBILITY_SCORE,
)

from ._support_recs import (
    diagnostics_map,
    evidence,
    evidence_by_id,
    insight_by_id,
    insight_fact,
)


def _fact(
    *,
    insight_id="ins_fact_a",
    confidence=0.8,
    ev=("ev_1", "ev_2"),
    sig=("sig_a",),
):
    return insight_fact(
        insight_id=insight_id,
        signal_ids=sig,
        evidence_ids=ev,
        confidence=confidence,
    )


def _draft(
    *,
    supporting=("ins_fact_a",),
    confidence=0.6,
    action_class="experiment",
    anchor="entry_offer_test",
) -> RecommendationDraft:
    return RecommendationDraft(
        statement="Test a lower-friction entry offer.",
        action="Run a two-week A/B test of an entry-level plan.",
        supporting_insight_ids=tuple(supporting),
        confidence=confidence,
        action_class=action_class,
        gtm_dimensions=("pricing",),
        action_anchor=anchor,
    )


def _script_for(draft: RecommendationDraft, **assessment_kw) -> FakeRecommendationScript:
    """A script mirroring the draft so the fake model matches by rec_id."""
    return FakeRecommendationScript(
        statement=draft.statement,
        action=draft.action,
        supporting_insight_ids=draft.supporting_insight_ids,
        action_class=draft.action_class,
        gtm_dimensions=draft.gtm_dimensions,
        confidence=draft.confidence,
        action_anchor=draft.action_anchor,
        **assessment_kw,
    )


def _insight_map(*facts) -> dict:
    return insight_by_id(*facts)


class TestPriorityBucket:
    def test_thresholds(self):
        assert priority_bucket(0.66) == "now"
        assert priority_bucket(0.65) == "next"
        assert priority_bucket(0.45) == "next"
        assert priority_bucket(0.44) == "watch"
        assert priority_bucket(0.0) == "watch"


class TestAssessPriority:
    def test_formula_matches_weights(self):
        a = RecommendationAssessment(
            expected_impact=0.8, urgency=0.6, feasibility=0.5
        )
        score = assess_priority(
            support_confidence=0.7, assessment=a, reversibility="high"
        )
        expected = round(
            PRIORITY_W_SUPPORT * 0.7
            + PRIORITY_W_IMPACT * 0.8
            + PRIORITY_W_URGENCY * 0.6
            + PRIORITY_W_REVERSIBILITY * REVERSIBILITY_SCORE["high"]
            + PRIORITY_W_FEASIBILITY * 0.5,
            4,
        )
        assert score == expected

    def test_high_support_high_actionability_is_now(self):
        a = RecommendationAssessment(
            expected_impact=1.0, urgency=1.0, feasibility=1.0
        )
        score = assess_priority(
            support_confidence=0.9, assessment=a, reversibility="high"
        )
        assert priority_bucket(score) == "now"


class TestReversibility:
    def test_valid_values(self):
        assert compute_reversibility(
            RecommendationAssessment(reversibility="high")
        ) == "high"

    def test_unknown_falls_back_medium(self):
        assert compute_reversibility(
            RecommendationAssessment(reversibility="irreversible-ish")
        ) == "medium"


class TestAssessRisk:
    def test_low_when_strong_support_and_easy(self):
        support = RecommendationSupport(
            supporting_insight_count=2,
            supporting_signal_count=2,
            supporting_evidence_count=3,
            independent_source_count=3,
            min_insight_confidence=0.8,
        )
        assessment = RecommendationAssessment(
            feasibility=0.9, effort=0.2
        )
        factors, overall = assess_risk(
            support=support,
            action_distance=0,
            assessment=assessment,
            reversibility="high",
        )
        assert set(factors) == {
            "evidence_risk", "execution_risk",
            "reversibility_risk", "contradiction_risk",
        }
        assert all(v == "LOW" for v in factors.values())
        assert overall == "LOW"

    def test_thin_evidence_is_high(self):
        support = RecommendationSupport(min_insight_confidence=0.3)
        factors, overall = assess_risk(
            support=support,
            action_distance=1,
            assessment=RecommendationAssessment(feasibility=0.9, effort=0.1),
            reversibility="high",
        )
        assert factors["evidence_risk"] == "HIGH"
        assert overall == "HIGH"

    def test_weak_with_few_sources_is_high(self):
        support = RecommendationSupport(
            min_insight_confidence=0.7,
            independent_source_count=1,
            weak_signal_present=True,
        )
        factors, _ = assess_risk(
            support=support,
            action_distance=1,
            assessment=RecommendationAssessment(feasibility=0.9, effort=0.1),
            reversibility="high",
        )
        assert factors["evidence_risk"] == "HIGH"

    def test_contradiction_on_strategic_move_is_high(self):
        support = RecommendationSupport(
            min_insight_confidence=0.7,
            independent_source_count=2,
            contradiction_present=True,
        )
        factors, overall = assess_risk(
            support=support,
            action_distance=2,  # change
            assessment=RecommendationAssessment(feasibility=0.9, effort=0.1),
            reversibility="high",
        )
        assert factors["contradiction_risk"] == "HIGH"
        assert overall == "HIGH"

    def test_irreversible_action_risk(self):
        factors, _ = assess_risk(
            support=RecommendationSupport(min_insight_confidence=0.9),
            action_distance=0,
            assessment=RecommendationAssessment(feasibility=0.9, effort=0.1),
            reversibility="low",
        )
        assert factors["reversibility_risk"] == "HIGH"


class TestAssessRecommendations:
    def _run(self, drafts, model, *, diags=None):
        return assess_recommendations(
            drafts,
            model,
            insight_by_id=_insight_map(_fact()),
            evidence_by_id=evidence_by_id(
                # distinct URLs → 2 independent sources (counted by URL)
                evidence("ev_1", url="https://src-a.example/"),
                evidence("ev_2", url="https://src-b.example/"),
            ),
            insight_diagnostics=diags or {},
        )

    def test_single_candidate_scored(self):
        draft = _draft()
        model = FakeRecommendationModel(recommendation_scripts=[
            _script_for(draft, expected_impact=0.8, urgency=0.7,
                        feasibility=0.9, reversibility="high")
        ])
        result = self._run([draft], model)
        assert result.model_status == "success"
        assert result.failed_insight_ids == ()
        assert len(result.assessed) == 1
        a = result.assessed[0]
        assert a.insight_id.startswith("ins_")
        assert a.insight_id == model.recommendation_scripts[0].rec_id()
        # code-computed support chain
        assert a.support_confidence == pytest.approx(0.8)
        assert a.support.supporting_insight_count == 1
        assert a.support.supporting_evidence_count == 2
        assert a.support.independent_source_count == 2
        assert a.supporting_signal_ids == ("sig_a",)
        assert a.supporting_evidence_ids == ("ev_1", "ev_2")
        # class -> distance (§15): experiment = 1
        assert a.action_distance == 1
        # confidence below ceiling (0.8 * 0.85 = 0.68) → untouched
        assert a.confidence == pytest.approx(0.6)
        assert a.reversibility == "high"
        # priority formula deterministic
        expected = round(
            PRIORITY_W_SUPPORT * 0.8
            + PRIORITY_W_IMPACT * 0.8
            + PRIORITY_W_URGENCY * 0.7
            + PRIORITY_W_REVERSIBILITY * REVERSIBILITY_SCORE["high"]
            + PRIORITY_W_FEASIBILITY * 0.9,
            4,
        )
        assert a.priority == pytest.approx(expected)
        assert a.priority_bucket == priority_bucket(a.priority)
        assert a.overall_risk == "LOW"

    def test_empty_drafts(self):
        result = assess_recommendations(
            [], FakeRecommendationModel(), insight_by_id={}, evidence_by_id={}
        )
        assert result.assessed == ()
        assert result.model_status == "success"

    def test_confidence_capped_to_support_ceiling(self):
        draft = _draft(confidence=0.9)
        fact = _fact(confidence=0.6)
        result = assess_recommendations(
            [draft],
            FakeRecommendationModel(recommendation_scripts=[
                _script_for(draft)
            ]),
            insight_by_id=insight_by_id(fact),
            evidence_by_id=evidence_by_id(
                evidence("ev_1", source="src_a"),
                evidence("ev_2", source="src_b"),
            ),
        )
        a = result.assessed[0]
        # ceiling = 0.6 * (1 - 0.15*1) = 0.51 → clamp with warning
        assert a.confidence == pytest.approx(0.51)
        assert any("capped" in w for w in result.warnings)

    def test_weak_flag_propagates_to_risk(self):
        fact = _fact(insight_id="ins_weak", ev=("ev_w",), confidence=0.7)
        draft = _draft(supporting=("ins_weak",))
        result = assess_recommendations(
            [draft],
            FakeRecommendationModel(),
            insight_by_id=insight_by_id(fact),
            evidence_by_id=evidence_by_id(evidence("ev_w", source="src_a")),
            insight_diagnostics=diagnostics_map(weak=("ins_weak",)),
        )
        a = result.assessed[0]
        assert a.weak_signal_present is True
        # weak + single source → evidence risk HIGH
        assert a.risk_factors["evidence_risk"] == "HIGH"

    def test_model_failure_drops_candidate(self):
        model = FakeRecommendationModel()
        model.status = ModelStatus.UNAVAILABLE
        draft = _draft()
        result = self._run([draft], model)
        assert result.assessed == ()
        assert len(result.failed_insight_ids) == 1
        assert result.failed_insight_ids[0].startswith("ins_")
        assert result.model_status == "invalid_output"
        assert any("dropped" in w for w in result.warnings)
