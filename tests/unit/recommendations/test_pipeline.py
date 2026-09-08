"""Phase 6B §6, §30, §31 — full pipeline: FACT/INFERENCE → Recommendation Set."""
from __future__ import annotations

from gtm_intelligence.recommendations.model import (
    CONFLICT_SEGMENT,
    FakeConflictScript,
    FakeRecommendationModel,
    FakeRecommendationScript,
)
from gtm_intelligence.recommendations.pipeline import run_recommendation_pipeline

from ._support_recs import evidence, evidence_by_id


def _inputs():
    """One FACT (high-confidence) + one INFERENCE → two distinct candidates."""
    fact = {
        "insight_id": "ins_price_fact",
        "type": "FACT",
        "statement": "Pricing page lists the entry plan at the current price.",
        "signal_ids": ["sig_price"],
        "evidence_ids": ["ev_price"],
        "confidence": 0.9,
    }
    inference = {
        "insight_id": "ins_users_inf",
        "type": "INFERENCE",
        "statement": "Individual users appear more price-sensitive than teams.",
        "signal_ids": ["sig_users"],
        "evidence_ids": ["ev_users"],
        "confidence": 0.6,
    }
    evs = evidence_by_id(
        evidence("ev_price", snippet="Team plan listed on pricing page.", source="page"),
        evidence("ev_users", snippet="User research notes price sensitivity.", source="research"),
    )
    return [fact, inference], evs


def _script0() -> FakeRecommendationScript:
    """High-priority experiment on the entry offer (FACT-backed)."""
    return FakeRecommendationScript(
        statement="Run a short experiment on the entry plan.",
        action="A/B test the current entry offer for two weeks.",
        supporting_insight_ids=("ins_price_fact",),
        action_class="experiment",
        gtm_dimensions=("pricing",),
        confidence=0.6,
        action_anchor="entry_test",
        expected_impact=0.9,
        urgency=0.8,
        feasibility=0.9,
        reversibility="high",
    )


def _script1() -> FakeRecommendationScript:
    """Lower-priority validate move (INFERENCE-backed)."""
    return FakeRecommendationScript(
        statement="Validate team willingness to pay.",
        action="Interview a sample of team buyers about the current price.",
        supporting_insight_ids=("ins_users_inf",),
        action_class="validate",
        gtm_dimensions=("pricing", "positioning"),
        confidence=0.6,
        action_anchor="team_wtp",
    )


def _run(scripts, *, dedup_groups=(), conflict_scripts=()):
    insights, evs = _inputs()
    model = FakeRecommendationModel(
        recommendation_scripts=scripts,
        dedup_groups=dedup_groups,
        conflict_scripts=conflict_scripts,
    )
    result = run_recommendation_pipeline(insights, evs, model)
    return result, model


class TestPipelineEndToEnd:
    def test_happy_path_produces_frozen_schema_recommendations(self):
        s0, s1 = _script0(), _script1()
        result, model = _run([s0, s1])

        assert len(result.recommendations) == 2
        assert len(result.diagnostics) == 2
        assert result.conflicts == ()
        assert not any("recommendation schema" in w for w in result.warnings)

        for rec in result.recommendations:
            assert rec["type"] == "RECOMMENDATION"
            assert rec["insight_id"].startswith("ins_")
            assert rec["action"]["priority"] in {"now", "next", "watch"}
            assert set(rec) <= {"insight_id", "type", "statement", "confidence",
                                "action", "rationale"}  # schema additionalProperties=false

        # Deterministic order: priority desc (§31)
        assert result.recommendations[0]["insight_id"] == s0.rec_id()
        assert result.recommendations[1]["insight_id"] == s1.rec_id()

        # diagnostics carry the explainability payload (out of schema)
        d0 = result.diagnostics[0]
        assert d0.insight_id == s0.rec_id()
        assert d0.action_class == "experiment"
        assert d0.priority_bucket == "now"
        assert d0.overall_risk in {"LOW", "MEDIUM", "HIGH"}
        assert d0.supporting_insight_ids == ("ins_price_fact",)
        assert d0.support.supporting_insight_count == 1
        assert d0.conflict_group_id == ""
        assert d0.collapsed_duplicate_ids == ()

        # model_status contract: one entry per pipeline stage
        assert set(result.model_status) == {
            "generation", "assessment", "dedup", "conflict"
        }

    def test_deterministic_across_runs(self):
        s0, s1 = _script0(), _script1()
        r1, _ = _run([s0, s1])
        r2, _ = _run([s0, s1])
        assert r1.to_dict() == r2.to_dict()

    def test_semantic_dedup_collapse_exposed_in_diagnostics(self):
        s0, s1 = _script0(), _script1()
        # Model judges the two candidates semantic duplicates → s0 wins
        # on higher priority; the loser id must be recorded for audit.
        result, _ = _run([s0, s1], dedup_groups=((0, 1),))
        assert [r["insight_id"] for r in result.recommendations] == [s0.rec_id()]
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].collapsed_duplicate_ids == (s1.rec_id(),)
        assert any("semantic duplicate group" in w for w in result.warnings)

    def test_conflict_group_id_wired_into_diagnostics(self):
        s0, s1 = _script0(), _script1()
        result, _ = _run([s0, s1], conflict_scripts=[
            FakeConflictScript((0, 1), kind=CONFLICT_SEGMENT,
                               rationale="different segments")
        ])
        assert len(result.conflicts) == 1
        group_id = result.conflicts[0].group_id
        by_id = {d.insight_id: d for d in result.diagnostics}
        assert by_id[s0.rec_id()].conflict_group_id == group_id
        assert by_id[s1.rec_id()].conflict_group_id == group_id
        # group_id is the deterministic sorted join
        assert group_id == "+".join(sorted([s0.rec_id(), s1.rec_id()]))


class TestPipelineFilters:
    def test_non_usable_insights_filtered_with_warning(self):
        insights, evs = _inputs()
        insights = insights + [
            {"insight_id": "ins_old_rec", "type": "RECOMMENDATION",
             "statement": "x", "confidence": 0.5},
            {"type": "FACT", "statement": "no id", "confidence": 0.5},
        ]
        s0, s1 = _script0(), _script1()
        result = run_recommendation_pipeline(
            insights, evs, _model_of(s0, s1)
        )
        assert len(result.recommendations) == 2
        assert any("not usable" in w for w in result.warnings)
        assert any("insight without insight_id" in w for w in result.warnings)

    def test_no_usable_insights_short_circuits(self):
        insights = [{"insight_id": "ins_x", "type": "RECOMMENDATION",
                     "statement": "x", "confidence": 0.5}]
        result = run_recommendation_pipeline(insights, {}, _model_of())
        assert result.recommendations == ()
        assert any("no FACT/INFERENCE insights" in w for w in result.warnings)


class TestPipelineFailure:
    def test_all_generated_candidates_invalid(self):
        insights, evs = _inputs()
        bad = FakeRecommendationScript(
            statement="Launch everywhere.",
            action="Launch the product in new markets.",
            supporting_insight_ids=("ins_ghost",),  # hallucinated support
            action_class="change",
            gtm_dimensions=("pricing",),
            action_anchor="bad",
        )
        result = run_recommendation_pipeline(insights, evs, _model_of(bad))
        assert result.recommendations == ()
        assert result.model_status.get("generation") == "invalid_output"
        assert any("no valid candidates" in w for w in result.warnings)


def _model_of(*scripts) -> FakeRecommendationModel:
    return FakeRecommendationModel(recommendation_scripts=scripts)
