"""Phase 6B §27 — deterministic Recommendation ids + anchor normalization."""
from __future__ import annotations

import pytest

from gtm_intelligence.recommendations.ids import (
    RECOMMENDATION,
    derive_recommendation_id,
    is_valid_action_anchor,
    normalize_action_anchor,
)


class TestNormalizeAnchor:
    def test_lowercases_and_underscores(self):
        assert normalize_action_anchor("Entry Offer TEST") == "entry_offer_test"

    def test_collapses_runs_and_trims(self):
        assert normalize_action_anchor("  entry---offer..test  ") == "entry_offer_test"

    def test_empty_falls_back_to_action(self):
        assert normalize_action_anchor("") == "action"
        assert normalize_action_anchor("!!!") == "action"

    def test_caps_at_48_chars(self):
        long = "x" * 100
        assert len(normalize_action_anchor(long)) == 48


class TestValidAnchor:
    def test_valid(self):
        assert is_valid_action_anchor("entry_offer_test")

    def test_invalid(self):
        assert not is_valid_action_anchor("Entry Offer")
        assert not is_valid_action_anchor("")
        assert not is_valid_action_anchor("x" * 49)


class TestDeriveRecommendationId:
    def test_starts_with_ins_prefix(self):
        rid = derive_recommendation_id(
            supporting_insight_ids=("ins_abc",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
            action_anchor="entry_offer_test",
        )
        assert rid.startswith("ins_")

    def test_deterministic_and_order_independent(self):
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_b", "ins_a"),
            gtm_dimensions=("pricing", "messaging"),
            action_class="experiment",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_a", "ins_b"),
            gtm_dimensions=("messaging", "pricing"),
            action_class="experiment",
        )
        assert a == b

    def test_changes_with_supporting_insights(self):
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_b",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
        )
        assert a != b

    def test_changes_with_gtm_dimension(self):
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("positioning",),
            action_class="experiment",
        )
        assert a != b

    def test_changes_with_action_class(self):
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="change",
        )
        assert a != b

    def test_wording_does_not_change_id(self):
        """§27: natural-language action text must NOT enter the hash."""
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
            action_anchor="entry_offer_test",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
            action_anchor="entry_offer_test",
        )
        assert a == b

    def test_anchor_variation_changes_id(self):
        a = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
            action_anchor="entry_offer_test",
        )
        b = derive_recommendation_id(
            supporting_insight_ids=("ins_a",),
            gtm_dimensions=("pricing",),
            action_class="experiment",
            action_anchor="price_survey",
        )
        assert a != b

    def test_empty_support_raises(self):
        with pytest.raises(ValueError):
            derive_recommendation_id(
                supporting_insight_ids=(), gtm_dimensions=("pricing",),
                action_class="experiment",
            )
