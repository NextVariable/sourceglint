"""Phase 5 §17 — weak-signal detection, free of engagement bias."""
from __future__ import annotations

import pytest

from sourceglint.intelligence import weak_signal
from sourceglint.intelligence.dtos import WINDOW_BASELINE, WeakSignalAssessment
from sourceglint.intelligence.ids import derive_cluster_id
from sourceglint.intelligence.dtos import SignalFeatures


def _feats(
    *,
    volume: int,
    engagement: int = 0,
    independent: int = 1,
    appeared_only_current: bool = False,
) -> SignalFeatures:
    return SignalFeatures(
        cluster_id=derive_cluster_id((f"ev-{i}",) for i in range(volume)) or "cl_x",
        evidence_count=volume,
        independent_source_count=independent,
        engagement_total=engagement,
        current_count=volume,
        baseline_count=0,
        appeared_only_current=appeared_only_current,
        has_baseline_data=bool(appeared_only_current),
    )


# --- candidacy rules --------------------------------------------------------


def test_low_volume_high_novelty_is_weak_candidate():
    """Low volume + high semantic novelty → candidate, even at ZERO
    engagement (PRD §17: engagement must not gate weak signals out)."""
    out = weak_signal.assess(
        features=_feats(volume=2, engagement=0),
        decision_relevance=0.4,
        semantic_novelty=0.9,
        code_novelty=0.0,
    )
    assert isinstance(out, WeakSignalAssessment)
    assert out.is_weak_candidate is True
    assert out.volume == 2
    assert out.engagement_total == 0
    assert out.decision_relevance == pytest.approx(0.4)
    assert out.novelty == pytest.approx(0.9)


def test_low_volume_high_decision_relevance_is_weak_candidate():
    out = weak_signal.assess(
        features=_feats(volume=1, engagement=3),
        decision_relevance=0.85,
        semantic_novelty=0.0,
        code_novelty=0.0,
    )
    assert out.is_weak_candidate is True


def test_low_volume_fresh_from_baseline_is_weak_candidate():
    out = weak_signal.assess(
        features=_feats(volume=1, appeared_only_current=True),
        decision_relevance=0.5,
        semantic_novelty=None,
        code_novelty=1.0,
    )
    assert out.is_weak_candidate is True
    assert any("baseline" in r for r in out.reasons)


def test_high_volume_is_not_weak():
    out = weak_signal.assess(
        features=_feats(volume=25, engagement=1000),
        decision_relevance=0.9,
        semantic_novelty=0.9,
        code_novelty=1.0,
    )
    assert out.is_weak_candidate is False


def test_low_volume_low_quality_noise_is_not_weak():
    """Few mentions with nothing semantically interesting is noise, not a
    weak signal — high relevance OR novelty must back the candidacy."""
    out = weak_signal.assess(
        features=_feats(volume=2, engagement=5),
        decision_relevance=0.1,
        semantic_novelty=0.0,
        code_novelty=0.0,
    )
    assert out.is_weak_candidate is False
    assert out.reasons == ()


def test_engagement_never_directly_blocks_or_forces_candidacy():
    low_eng = weak_signal.assess(
        features=_feats(volume=1, engagement=0),
        decision_relevance=0.9, semantic_novelty=0.0, code_novelty=0.0,
    )
    high_eng = weak_signal.assess(
        features=_feats(volume=1, engagement=500),
        decision_relevance=0.9, semantic_novelty=0.0, code_novelty=0.0,
    )
    assert low_eng.is_weak_candidate is high_eng.is_weak_candidate is True


def test_semantic_novelty_none_treated_as_unknown_not_zero_trigger():
    """None → no novelty-based reason, but DR can still nominate."""
    out = weak_signal.assess(
        features=_feats(volume=1, engagement=0),
        decision_relevance=0.9,
        semantic_novelty=None,
        code_novelty=0.0,
    )
    assert out.is_weak_candidate is True
    assert out.novelty == 0.0  # unknown is not neutral, not a trigger


# --- reasons ----------------------------------------------------------------


def test_reasons_describe_what_nominated_the_candidate():
    out = weak_signal.assess(
        features=_feats(volume=1, engagement=0),
        decision_relevance=0.8,
        semantic_novelty=0.7,
        code_novelty=0.0,
    )
    joined = " ".join(out.reasons)
    assert "relevance" in joined
    assert "novelty" in joined


def test_decision_boundary_volume_three_is_still_weak():
    out = weak_signal.assess(
        features=_feats(volume=3, engagement=0),
        decision_relevance=0.0, semantic_novelty=0.8, code_novelty=0.0,
    )
    assert out.is_weak_candidate is True


def test_decision_boundary_volume_four_is_not_weak():
    out = weak_signal.assess(
        features=_feats(volume=4, engagement=0),
        decision_relevance=0.0, semantic_novelty=0.8, code_novelty=0.0,
    )
    assert out.is_weak_candidate is False
