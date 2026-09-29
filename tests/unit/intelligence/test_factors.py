"""Phase 5 §19–§24 — deterministic + semantic factor derivation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sourceglint.intelligence import factors
from sourceglint.intelligence.dtos import (
    WINDOW_BASELINE,
    WINDOW_CURRENT,
    PreparedEvidence,
    ResearchContext,
    SignalFeatures,
)
from sourceglint.intelligence.features import derive_features
from sourceglint.intelligence.ids import derive_cluster_id
from sourceglint.intelligence.model import (
    FakeClusterScript,
    FakeIntelligenceModel,
    FailingIntelligenceModel,
    ModelResponse,
    ModelStatus,
)
from sourceglint.intelligence.dtos import ValidatedCluster

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _dt(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _ev(
    eid: str,
    *,
    published_days_ago: int | None = 1,
    quality: float | None = 0.8,
    window: str = WINDOW_CURRENT,
    engagement: dict | None = None,
    source: str = "reddit",
    tier: int = 2,
    url: str = "",
) -> PreparedEvidence:
    return PreparedEvidence(
        evidence_id=eid,
        source=source,
        source_type="comment",
        window=window,
        title=f"title {eid}",
        snippet=f"snippet {eid}",
        published_at=_dt(published_days_ago) if published_days_ago is not None else "",
        market="global",
        language="en",
        source_tier=tier,
        evidence_quality=quality,
        engagement=dict(engagement or {}),
        url=url or f"https://reddit.com/r/x/{eid}",
        has_text=True,
    )


def _cluster(evidence_ids: tuple[str, ...]) -> ValidatedCluster:
    return ValidatedCluster(
        cluster_id=derive_cluster_id(evidence_ids),
        label="L",
        claim="c",
        evidence_ids=evidence_ids,
        confidence=0.8,
    )


def _index(*items: PreparedEvidence) -> dict[str, PreparedEvidence]:
    return {e.evidence_id: e for e in items}


def _feats(*items: PreparedEvidence, extra_baseline: bool = False) -> SignalFeatures:
    prepared = list(items)
    if extra_baseline:
        prepared.append(_ev("__base__", published_days_ago=40, window=WINDOW_BASELINE))
    return derive_features(_cluster(tuple(e.evidence_id for e in items)), _index(*prepared))


# --- evidence quality (PRD §21) ---------------------------------------------


def test_evidence_quality_is_mean_of_known_values():
    a = _ev("ev-1", quality=0.8)
    b = _ev("ev-2", quality=0.6)
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")), _feats(a, b), _index(a, b), NOW
    )
    assert out.evidence_quality == pytest.approx(0.7)


def test_evidence_quality_skips_unknown_members():
    import dataclasses

    a = _ev("ev-1", quality=0.8)
    b = dataclasses.replace(_ev("ev-2"), evidence_quality=None)
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")), _feats(a, b), _index(a, b), NOW
    )
    assert out.evidence_quality == pytest.approx(0.8)


def test_evidence_quality_never_defaults_to_neutral():
    """All unknown → 0.0 with a warning, never 0.5 (Closeout §3)."""
    import dataclasses

    a = dataclasses.replace(_ev("ev-1"), evidence_quality=None)
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(a), _index(a), NOW)
    assert out.evidence_quality == 0.0
    assert any("evidence quality" in w for w in out.warnings)


# --- recency (PRD §22) ------------------------------------------------------


def test_recency_today_is_one():
    ev = _ev("ev-1", published_days_ago=0)
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    assert out.recency == pytest.approx(1.0)


def test_recency_halves_at_half_life():
    ev = _ev("ev-1", published_days_ago=30)
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    assert out.recency == pytest.approx(0.5, rel=1e-6)


def test_recency_decays_exponentially():
    ev = _ev("ev-1", published_days_ago=90)
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    assert out.recency == pytest.approx(0.5 ** (90 / 30), rel=1e-6)


def test_recency_uses_youngest_member():
    old = _ev("ev-1", published_days_ago=80)
    fresh = _ev("ev-2", published_days_ago=2)
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")), _feats(old, fresh), _index(old, fresh), NOW
    )
    assert out.recency == pytest.approx(0.5 ** (2 / 30), rel=1e-6)


def test_recency_unknown_when_no_dates():
    import dataclasses

    ev = dataclasses.replace(_ev("ev-1"), published_at="")
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    assert out.recency == 0.0
    assert any("recency" in w for w in out.warnings)


def test_future_dates_clamp_to_one():
    ev = _ev("ev-1", published_days_ago=-5)
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    assert out.recency == pytest.approx(1.0)


def test_recency_deterministic_given_as_of():
    """The same input at a different as_of yields a different, deterministic value."""
    ev = _ev("ev-1", published_days_ago=10)
    later = NOW + timedelta(days=10)
    out_early = factors.derive_factors(_cluster(("ev-1",)), _feats(ev), _index(ev), NOW)
    out_later = factors.derive_factors(
        _cluster(("ev-1",)), _feats(ev), _index(ev), later
    )
    assert out_early.recency > out_later.recency


# --- novelty factor: code-computed (prompt: semantic_novelty is metadata) ---


def test_novelty_not_assessed_without_baseline_window():
    a = _ev("ev-1")
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(a), _index(a), NOW)
    assert out.novelty == 0.0
    assert any("novelty" in w for w in out.warnings)


def test_novelty_one_when_absent_from_baseline():
    a = _ev("ev-1")
    b = _ev("__b__", window=WINDOW_BASELINE)
    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a, extra_baseline=True), _index(a, b), NOW
    )
    assert out.novelty == pytest.approx(1.0)


def test_novelty_zero_when_only_in_baseline():
    a = _ev("ev-1", window=WINDOW_BASELINE)
    b = _ev("ev-2", window=WINDOW_CURRENT)
    out = factors.derive_factors(
        _cluster(("ev-1",)),
        derive_features(_cluster(("ev-1",)), _index(a, b)),
        _index(a, b),
        NOW,
    )
    assert out.novelty == 0.0


def test_novelty_half_for_continuing_topic():
    """Present in BOTH windows = a continuing topic: deterministically 0.5."""
    a = _ev("ev-1", window=WINDOW_CURRENT)
    b = _ev("ev-2", window=WINDOW_BASELINE)
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")),
        derive_features(_cluster(("ev-1", "ev-2")), _index(a, b)),
        _index(a, b),
        NOW,
    )
    assert out.novelty == pytest.approx(0.5)


# --- market signal (PRD §23) -------------------------------------------------


def test_market_signal_zero_for_single_origin_no_engagement():
    a = _ev("ev-1", engagement={})
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(a), _index(a), NOW)
    assert out.market_signal == pytest.approx(0.0)


def test_market_signal_breadth_saturates_at_two_origins():
    a = _ev("ev-1", engagement={}, source="official_web",
            url="https://a.example.com/1")
    b = _ev("ev-2", engagement={}, source="reddit",
            url="https://b.example.com/2")
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")), _feats(a, b), _index(a, b), NOW
    )
    # breadth=1.0 (2+ origins), depth=0 → 0.6*breadth + 0.4*depth = 0.6
    assert out.market_signal == pytest.approx(0.6)


def test_market_signal_engagement_is_weak_contributor():
    """§23: engagement alone (single origin, high volume of reactions) is a
    weak market signal — breadth dominates."""
    a = _ev("ev-1", engagement={"upvotes": 500, "comments": 500})
    out = factors.derive_factors(_cluster(("ev-1",)), _feats(a), _index(a), NOW)
    # depth saturates at 1.0 but breadth is 0 → 0.4
    assert out.market_signal == pytest.approx(0.4)


def test_market_signal_full_for_breadth_and_depth():
    a = _ev("ev-1", engagement={"upvotes": 500}, source="official_web",
            url="https://a.example.com/1")
    b = _ev("ev-2", engagement={"upvotes": 100}, source="reddit",
            url="https://b.example.com/2")
    out = factors.derive_factors(
        _cluster(("ev-1", "ev-2")), _feats(a, b), _index(a, b), NOW
    )
    assert out.market_signal == pytest.approx(1.0)


# --- semantic assessment (DR) ------------------------------------------------


def test_decision_relevance_comes_from_model():
    a = _ev("ev-1")
    script = FakeClusterScript(
        label="L", claim="c", evidence_ids=("ev-1",),
        decision_relevance=0.85, decision_relevance_rationale="core pricing",
    )
    model = FakeIntelligenceModel(scripts=(script,))
    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW,
        model=model, research_context=ResearchContext(mode="competitive", entities=("X",)),
    )
    assert out.decision_relevance == pytest.approx(0.85)
    assert out.semantic_flags["decision_relevance_rationale"] == "core pricing"


def test_semantic_novelty_is_metadata_not_novelty_factor():
    a = _ev("ev-1")
    script = FakeClusterScript(
        label="L", claim="c", evidence_ids=("ev-1",),
        decision_relevance=0.5, semantic_novelty=0.9, early_signal=True,
    )
    model = FakeIntelligenceModel(scripts=(script,))
    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW, model=model
    )
    # code novelty has no baseline data → 0.0, untouched by semantic 0.9
    assert out.novelty == 0.0
    assert out.semantic_flags["semantic_novelty"] == pytest.approx(0.9)
    assert out.semantic_flags["early_signal"] is True


def test_model_failure_degrades_dr_without_raising():
    a = _ev("ev-1")
    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW,
        model=FailingIntelligenceModel(),
    )
    assert out.decision_relevance == 0.0
    assert out.degraded
    assert out.model_status != "success"


def test_missing_dr_in_response_degrades():
    a = _ev("ev-1")

    class NoDr:
        model_id = "nodr:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task="semantic_factors", status=ModelStatus.SUCCESS,
                payload={"commercial_intent": 0.3},
            )

    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW, model=NoDr()
    )
    assert out.decision_relevance == 0.0
    assert out.degraded
    assert any("decision_relevance" in w for w in out.warnings)


def test_semantic_payload_carries_cluster_and_research_context():
    a = _ev("ev-1")
    script = FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1",))
    model = FakeIntelligenceModel(scripts=(script,))
    factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW, model=model,
        research_context=ResearchContext(mode="launch", entities=("Acme",)),
    )
    call = model.calls[0]
    assert call["task"] == "semantic_factors"
    assert call["payload"]["cluster_id"].startswith("cl_")
    assert call["payload"]["evidence_ids"] == ["ev-1"]
    assert call["payload"]["research_context"]["mode"] == "launch"
    assert "snippet" in call["payload"]["evidence_items"][0]


# --- factor set completeness (PRD §24) --------------------------------------


def test_factor_set_exposes_all_five_factors():
    a = _ev("ev-1")
    script = FakeClusterScript(
        label="L", claim="c", evidence_ids=("ev-1",), decision_relevance=0.7,
    )
    model = FakeIntelligenceModel(scripts=(script,))
    out = factors.derive_factors(
        _cluster(("ev-1",)), _feats(a), _index(a), NOW, model=model
    )
    for name in (
        "decision_relevance", "evidence_quality", "recency",
        "market_signal", "novelty",
    ):
        assert 0.0 <= getattr(out, name) <= 1.0, name
    assert out.cluster_id.startswith("cl_")
