"""Phase 6B §28 — structural + semantic dedup with deterministic winners."""
from __future__ import annotations

from sourceglint.insights.model import ModelStatus
from sourceglint.recommendations.assess import (
    AssessedRecommendation,
    priority_bucket,
)
from sourceglint.recommendations.dedup import deduplicate_recommendations
from sourceglint.recommendations.dtos import (
    RecommendationAssessment,
    RecommendationDraft,
    RecommendationSupport,
)
from sourceglint.recommendations.model import (
    FakeRecommendationModel,
    FakeRecommendationScript,
)

from ._stub_model import StubModel


def _assessed(
    rec_id: str,
    *,
    priority: float = 0.5,
    confidence: float = 0.6,
    support_conf: float = 0.6,
    action: str = "Run the entry offer test.",
    action_class: str = "experiment",
    dims=("pricing",),
    supporting=("ins_fact_a",),
) -> AssessedRecommendation:
    return AssessedRecommendation(
        draft=RecommendationDraft(
            statement="S.",
            action=action,
            supporting_insight_ids=tuple(supporting),
            confidence=confidence,
            action_class=action_class,
            gtm_dimensions=tuple(dims),
            action_anchor="anchor",
        ),
        insight_id=rec_id,
        assessment=RecommendationAssessment(),
        support=RecommendationSupport(min_insight_confidence=support_conf),
        confidence=confidence,
        priority=priority,
        priority_bucket=priority_bucket(priority),
    )


def _script(rec_id_fields, *, action="entry offer", anchor="entry_offer_test",
            **kw) -> FakeRecommendationScript:
    """A script whose derived rec_id equals `rec_id_fields` (must hash the
    same structural inputs)."""
    return FakeRecommendationScript(
        statement="S.",
        action=action,
        supporting_insight_ids=rec_id_fields["supporting"],
        action_class=rec_id_fields["action_class"],
        gtm_dimensions=rec_id_fields["dims"],
        confidence=0.6,
        action_anchor=anchor,
        **kw,
    )


def _rec_id(supporting=("ins_fact_a",), action_class="experiment",
            dims=("pricing",), anchor="entry_offer_test") -> str:
    return FakeRecommendationScript(
        statement="S.",
        action="a",
        supporting_insight_ids=supporting,
        action_class=action_class,
        gtm_dimensions=dims,
        action_anchor=anchor,
    ).rec_id()


class TestStructuralDedup:
    def test_identical_ids_keep_strongest(self):
        rid = _rec_id()
        strong = _assessed(rid, priority=0.9)
        weak = _assessed(rid, priority=0.4)
        result = deduplicate_recommendations(
            [strong, weak], FakeRecommendationModel()
        )
        assert [a.insight_id for a in result.kept] == [rid]
        assert len(result.removed) == 1
        assert result.collapsed == ()  # structural dedup is not a "group"
        assert any("structural duplicate" in w for w in result.warnings)

    def test_empty_candidates(self):
        result = deduplicate_recommendations([], FakeRecommendationModel())
        assert result.kept == ()
        assert result.removed == ()
        assert result.warnings == ()


class TestSemanticDedup:
    def test_semantic_group_keeps_deterministic_winner(self):
        fields = dict(
            supporting=("ins_fact_a",), action_class="experiment",
            dims=("pricing",), anchor="entry_test",
        )
        rid_a = _rec_id(**fields)
        fields_b = dict(fields, anchor="offer_test")
        rid_b = _rec_id(**fields_b)
        a = _assessed(rid_a, priority=0.7)
        b = _assessed(rid_b, priority=0.5)
        model = FakeRecommendationModel(
            recommendation_scripts=[
                _script(fields, anchor="entry_test"),
                _script(fields_b, anchor="offer_test"),
            ],
            dedup_groups=((0, 1),),
        )
        result = deduplicate_recommendations([a, b], model)
        assert [x.insight_id for x in result.kept] == [rid_a]  # higher priority
        assert [x.insight_id for x in result.removed] == [rid_b]
        assert result.collapsed == ((rid_a, rid_b),)
        assert any("semantic duplicate group" in w for w in result.warnings)

    def test_tie_break_shorter_action_wins(self):
        fields = dict(
            supporting=("ins_fact_a",), action_class="experiment",
            dims=("pricing",), anchor="dup_a",
        )
        rid_a = _rec_id(**fields)
        rid_b = _rec_id(anchor="dup_b")
        # identical priority / confidence / support → shorter action wins
        a = _assessed(rid_a, priority=0.5, action="A long rambling action text here.")
        b = _assessed(rid_b, priority=0.5, action="Short action.")
        model = FakeRecommendationModel(
            recommendation_scripts=[
                _script(fields, anchor="dup_a", action="A long rambling action text here."),
                FakeRecommendationScript(
                    statement="S.", action="Short action.",
                    supporting_insight_ids=("ins_fact_a",),
                    action_class="experiment", gtm_dimensions=("pricing",),
                    action_anchor="dup_b",
                ),
            ],
            dedup_groups=((0, 1),),
        )
        result = deduplicate_recommendations([a, b], model)
        assert [x.insight_id for x in result.kept] == [rid_b]
        assert [x.insight_id for x in result.removed] == [rid_a]

    def test_hallucinated_group_ignored(self):
        rid_a = _rec_id(anchor="hall_a")
        rid_b = _rec_id(anchor="hall_b")
        a = _assessed(rid_a, priority=0.6)
        b = _assessed(rid_b, priority=0.5)
        model = StubModel(payload={
            "duplicate_groups": [["ins_ghost", rid_a]],
        })
        result = deduplicate_recommendations([a, b], model)
        # group skipped entirely → both candidates survive
        assert sorted(x.insight_id for x in result.kept) == sorted([rid_a, rid_b])
        assert result.removed == ()
        assert result.collapsed == ()
        assert any("hallucinated rec_id" in w for w in result.warnings)

    def test_model_failure_degrades_to_structural(self):
        rid_a = _rec_id(anchor="keep_a")
        rid_b = _rec_id(anchor="keep_b")
        a = _assessed(rid_a)
        b = _assessed(rid_b)
        model = FakeRecommendationModel()
        model.status = ModelStatus.UNAVAILABLE
        result = deduplicate_recommendations([a, b], model)
        # distinct ids → nothing collapsed; semantic skipped with warning
        assert sorted(x.insight_id for x in result.kept) == sorted([rid_a, rid_b])
        assert result.removed == ()
        assert any("semantic dedup skipped" in w for w in result.warnings)
