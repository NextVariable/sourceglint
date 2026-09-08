"""Phase 6B §29–§30 — conflict detection + classification (never resolved)."""
from __future__ import annotations

from gtm_intelligence.insights.model import ModelStatus
from gtm_intelligence.recommendations.assess import (
    AssessedRecommendation,
    priority_bucket,
)
from gtm_intelligence.recommendations.conflicts import detect_conflicts
from gtm_intelligence.recommendations.dtos import (
    RecommendationAssessment,
    RecommendationDraft,
    RecommendationSupport,
)
from gtm_intelligence.recommendations.model import (
    CONFLICT_HORIZON,
    CONFLICT_KINDS,
    CONFLICT_SEGMENT,
    CONFLICT_TRUE,
    FakeRecommendationModel,
    FakeConflictScript,
    FakeRecommendationScript,
)

from ._stub_model import StubModel


def _script(
    *,
    supporting=("ins_fact_a",),
    action_class="experiment",
    dims=("pricing",),
    anchor,
    action="Some action.",
) -> FakeRecommendationScript:
    return FakeRecommendationScript(
        statement="S.",
        action=action,
        supporting_insight_ids=supporting,
        action_class=action_class,
        gtm_dimensions=dims,
        action_anchor=anchor,
    )


def _assessed(rec_id: str, *, priority: float = 0.5) -> AssessedRecommendation:
    return AssessedRecommendation(
        draft=RecommendationDraft(
            statement="S.",
            action="Some action.",
            supporting_insight_ids=("ins_fact_a",),
            confidence=0.6,
            action_class="experiment",
            gtm_dimensions=("pricing",),
            action_anchor="anchor",
        ),
        insight_id=rec_id,
        assessment=RecommendationAssessment(),
        support=RecommendationSupport(min_insight_confidence=0.6),
        priority=priority,
        priority_bucket=priority_bucket(priority),
    )


def _group_id(*ids: str) -> str:
    return "+".join(sorted(set(ids)))


class TestConflictDetection:
    def test_fewer_than_two_no_conflicts(self):
        result = detect_conflicts([_assessed("ins_a")], FakeRecommendationModel())
        assert result.conflicts == ()

    def test_detects_and_classifies_true_conflict(self):
        s0 = _script(anchor="raise_price", action="Raise the entry price.")
        s1 = _script(anchor="lower_price", action="Lower the entry price.")
        recs = [_assessed(s0.rec_id()), _assessed(s1.rec_id())]
        model = FakeRecommendationModel(
            recommendation_scripts=[s0, s1],
            conflict_scripts=[FakeConflictScript(
                (0, 1), kind=CONFLICT_TRUE,
                rationale="opposed price directions", gtm_dimensions=("pricing",),
            )],
        )
        result = detect_conflicts(recs, model)
        assert result.model_status == "success"
        assert len(result.conflicts) == 1
        c = result.conflicts[0]
        assert c.kind == CONFLICT_TRUE
        assert set(c.rec_ids) == {s0.rec_id(), s1.rec_id()}
        assert c.rec_ids == tuple(sorted({s0.rec_id(), s1.rec_id()}))
        assert c.group_id == _group_id(s0.rec_id(), s1.rec_id())
        assert c.rationale == "opposed price directions"
        assert c.gtm_dimensions == ("pricing",)

    def test_classifications_preserved_and_deterministic_order(self):
        s0 = _script(anchor="a0", action="A0.")
        s1 = _script(anchor="a1", action="A1.")
        s2 = _script(anchor="a2", action="A2.")
        recs = [_assessed(s0.rec_id()), _assessed(s1.rec_id()),
                _assessed(s2.rec_id())]
        model = FakeRecommendationModel(
            recommendation_scripts=[s0, s1, s2],
            conflict_scripts=[
                FakeConflictScript((0, 1), kind=CONFLICT_SEGMENT),
                FakeConflictScript((1, 2), kind=CONFLICT_HORIZON),
            ],
        )
        result = detect_conflicts(recs, model)
        assert len(result.conflicts) == 2
        # deterministic order by group_id
        assert [c.group_id for c in result.conflicts] == sorted(
            c.group_id for c in result.conflicts
        )
        kinds = {c.kind for c in result.conflicts}
        assert kinds == {CONFLICT_SEGMENT, CONFLICT_HORIZON}

    def test_hallucinated_rec_id_skipped(self):
        rid = _script(anchor="real").rec_id()
        recs = [_assessed(rid), _assessed(_script(anchor="real2").rec_id())]
        model = StubModel(payload={
            "conflict_groups": [{
                "rec_ids": ["ins_ghost", rid],
                "kind": CONFLICT_TRUE,
                "rationale": "r",
            }]
        })
        result = detect_conflicts(recs, model)
        assert result.conflicts == ()
        assert any("hallucinated rec_id" in w for w in result.warnings)

    def test_unknown_kind_skipped(self):
        s0 = _script(anchor="k0")
        s1 = _script(anchor="k1")
        recs = [_assessed(s0.rec_id()), _assessed(s1.rec_id())]
        model = StubModel(payload={
            "conflict_groups": [{
                "rec_ids": [s0.rec_id(), s1.rec_id()],
                "kind": "not_a_kind",
            }]
        })
        result = detect_conflicts(recs, model)
        assert result.conflicts == ()
        assert any("unknown conflict kind" in w for w in result.warnings)

    def test_single_member_group_skipped(self):
        rid = _script(anchor="solo").rec_id()
        recs = [_assessed(rid), _assessed(_script(anchor="solo2").rec_id())]
        model = StubModel(payload={
            "conflict_groups": [{"rec_ids": [rid], "kind": CONFLICT_TRUE}]
        })
        result = detect_conflicts(recs, model)
        assert result.conflicts == ()
        assert any("smaller than 2" in w for w in result.warnings)

    def test_model_failure_degrades_gracefully(self):
        s0 = _script(anchor="f0")
        s1 = _script(anchor="f1")
        recs = [_assessed(s0.rec_id()), _assessed(s1.rec_id())]
        model = FakeRecommendationModel(recommendation_scripts=[s0, s1])
        model.status = ModelStatus.UNAVAILABLE
        result = detect_conflicts(recs, model)
        assert result.conflicts == ()
        assert result.model_status == "unavailable"
        assert any("conflict detection skipped" in w for w in result.warnings)

    def test_kind_enum_contract(self):
        # Frozen kinds — regression guard for the classifier vocabulary.
        assert CONFLICT_KINDS == (CONFLICT_TRUE, CONFLICT_SEGMENT, CONFLICT_HORIZON)
