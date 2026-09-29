"""Phase 6B §46 — policy constants sanity (no scattered magic numbers)."""
from __future__ import annotations

from sourceglint.recommendations import policy


class TestWeightsSumToOne:
    def test_priority_weights_sum_to_one(self):
        total = (
            policy.PRIORITY_W_SUPPORT
            + policy.PRIORITY_W_IMPACT
            + policy.PRIORITY_W_URGENCY
            + policy.PRIORITY_W_REVERSIBILITY
            + policy.PRIORITY_W_FEASIBILITY
        )
        assert abs(total - 1.0) < 1e-9


class TestClassIntensity:
    def test_all_classes_mapped(self):
        assert set(policy.ACTION_CLASSES) == set(policy.CLASS_INTENSITY)

    def test_weak_cap_is_experiment_or_less(self):
        # §18: weak signals may be observed/validated/experimented, not
        # committed via update/change.
        assert policy.WEAK_SIGNAL_MAX_INTENSITY <= policy.CLASS_INTENSITY["experiment"]
        assert policy.WEAK_SIGNAL_MAX_INTENSITY >= policy.CLASS_INTENSITY["observe"]

    def test_contradiction_cap_is_experiment_or_less(self):
        # §19: contradictory support → validate/segment/experiment.
        assert policy.CONTRADICTION_MAX_INTENSITY <= policy.CLASS_INTENSITY["experiment"]


class TestActionDistance:
    def test_update_is_direct(self):
        assert policy.CLASS_ACTION_DISTANCE["update"] == 0

    def test_change_is_strategic(self):
        assert policy.CLASS_ACTION_DISTANCE["change"] == 2


class TestThresholds:
    def test_bucket_thresholds_ordered(self):
        assert policy.PRIORITY_NOW_THRESHOLD > policy.PRIORITY_NEXT_THRESHOLD

    def test_max_candidates_reasonable(self):
        assert 1 <= policy.MAX_CANDIDATES <= 10
