"""Phase 6B §7, §9, §10 — internal Recommendation DTOs."""
from __future__ import annotations

import pytest

from sourceglint.recommendations.dtos import (
    PreparedInsight,
    RecommendationAssessment,
    RecommendationConflict,
    RecommendationDiagnostics,
    RecommendationDraft,
    RecommendationPipelineResult,
    RecommendationSupport,
)


class TestPreparedInsight:
    def _make(self, **kw):
        base = dict(
            insight_id="ins_abc",
            type="INFERENCE",
            statement="Price sensitivity appears stronger among individual users.",
            confidence=0.7,
            gtm_implications={"pricing": "differs by segment"},
            weak_signal=False,
            contradiction_preserved=False,
        )
        base.update(kw)
        return PreparedInsight(**base)

    def test_model_payload_minimal(self):
        payload = self._make().to_model_payload()
        assert payload["insight_id"] == "ins_abc"
        assert payload["type"] == "INFERENCE"
        assert payload["statement"]
        assert payload["confidence"] == 0.7
        assert payload["gtm_implications"] == {"pricing": "differs by segment"}
        assert payload["weak_signal"] is False

    def test_model_payload_omits_empty_optional(self):
        payload = self._make(gtm_implications={}).to_model_payload()
        assert "gtm_implications" not in payload


class TestRecommendationDraft:
    def test_roundtrip(self):
        d = RecommendationDraft(
            statement="Test a lower-friction entry offer for individual users.",
            action="Run a 2-week A/B test of an entry-level plan.",
            supporting_insight_ids=("ins_a",),
            confidence=0.6,
            action_class="experiment",
            gtm_dimensions=("pricing",),
            action_anchor="entry_offer_test",
        )
        out = d.to_dict()
        assert out["statement"].startswith("Test")
        assert out["supporting_insight_ids"] == ["ins_a"]
        assert out["action_class"] == "experiment"
        assert out["gtm_dimensions"] == ["pricing"]


class TestRecommendationAssessment:
    def test_defaults(self):
        a = RecommendationAssessment()
        assert a.expected_impact == 0.0
        assert a.reversibility == "medium"


class TestRecommendationSupport:
    def test_defaults(self):
        s = RecommendationSupport()
        assert s.supporting_insight_count == 0
        assert s.independent_source_count == 0


class TestDiagnosticsRoundtrip:
    def test_to_dict(self):
        diag = RecommendationDiagnostics(
            insight_id="ins_rec_1",
            gtm_dimensions=("pricing",),
            priority_bucket="next",
        )
        out = diag.to_dict()
        assert out["insight_id"] == "ins_rec_1"
        assert out["gtm_dimensions"] == ["pricing"]
        assert out["priority_bucket"] == "next"
        assert out["conflict_group_id"] == ""


class TestConflictRoundtrip:
    def test_to_dict(self):
        c = RecommendationConflict(
            group_id="ins_a+ins_b", rec_ids=("ins_a", "ins_b"),
            kind="segment_specific",
        )
        out = c.to_dict()
        assert out["kind"] == "segment_specific"
        assert out["rec_ids"] == ["ins_a", "ins_b"]


class TestPipelineResult:
    def test_to_dict(self):
        r = RecommendationPipelineResult(
            recommendations=({"insight_id": "ins_rec_1", "type": "RECOMMENDATION"},),
            warnings=("w1",),
        )
        out = r.to_dict()
        assert out["recommendations"][0]["type"] == "RECOMMENDATION"
        assert out["warnings"] == ["w1"]
        assert out["conflicts"] == []
