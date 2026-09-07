"""Phase 5 §14–§15, §24–§26 — signal construction + contract invariants."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gtm_intelligence.intelligence import signals
from gtm_intelligence.intelligence.contradiction import ContradictionAssessment
from gtm_intelligence.intelligence.dtos import (
    WINDOW_BASELINE,
    WINDOW_CURRENT,
    CONTRADICTION_FACTUAL,
    PreparedEvidence,
    ResearchContext,
    SignalFeatures,
)
from gtm_intelligence.intelligence.factors import derive_factors
from gtm_intelligence.intelligence.features import derive_features
from gtm_intelligence.intelligence.ids import derive_cluster_id, derive_signal_id
from gtm_intelligence.intelligence.model import (
    FakeClusterScript,
    FakeIntelligenceModel,
)
from gtm_intelligence.intelligence.dtos import ValidatedCluster

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _ev(
    eid: str,
    *,
    text: str = "x",
    window: str = WINDOW_CURRENT,
    quality: float = 0.8,
    tier: int = 2,
    url: str = "",
    source: str = "reddit",
) -> PreparedEvidence:
    return PreparedEvidence(
        evidence_id=eid,
        source=source,
        source_type="comment",
        window=window,
        title=f"title {eid}",
        snippet=f"snippet {eid}" if text else "",
        published_at="2026-09-06T00:00:00+00:00",
        market="global",
        language="en",
        source_tier=tier,
        evidence_quality=quality,
        engagement={"upvotes": 10},
        url=url or f"https://reddit.com/r/x/{eid}",
        has_text=bool(text),
    )


def _cluster(evidence_ids: tuple[str, ...], label: str = "Topic L") -> ValidatedCluster:
    return ValidatedCluster(
        cluster_id=derive_cluster_id(evidence_ids),
        label=label,
        claim="claim",
        evidence_ids=evidence_ids,
        confidence=0.8,
    )


def _all(*items: PreparedEvidence) -> dict[str, PreparedEvidence]:
    return {e.evidence_id: e for e in items}


def _assessment(
    cluster: ValidatedCluster,
    *,
    counter: tuple[str, ...] = (),
    kind: str = "none",
) -> ContradictionAssessment:
    return ContradictionAssessment(
        cluster_id=cluster.cluster_id,
        supporting_evidence_ids=tuple(
            e for e in cluster.evidence_ids if e not in counter
        ),
        counter_evidence_ids=counter,
        kind=kind,
    )


def _build(
    *items: PreparedEvidence,
    counter: tuple[str, ...] = (),
    kind: str = "none",
    cluster: ValidatedCluster | None = None,
    extra_baseline_global: bool = False,
    label: str = "Topic L",
):
    prepared = list(items)
    if extra_baseline_global:
        prepared.append(_ev("__gbase__", window=WINDOW_BASELINE))
    cluster = cluster or _cluster(tuple(e.evidence_id for e in items), label=label)
    features = derive_features(cluster, _all(*prepared))
    assessment = _assessment(cluster, counter=counter, kind=kind)
    script = FakeClusterScript(
        label=label, claim="claim",
        evidence_ids=tuple(e.evidence_id for e in items),
        decision_relevance=0.7,
        semantic_novelty=0.4,
        supporting_evidence_ids=tuple(e.evidence_id for e in items if e.evidence_id not in counter),
        counter_evidence_ids=counter,
    )
    model = FakeIntelligenceModel(scripts=(script,))
    fset = derive_factors(
        cluster, features, _all(*items), NOW, model=model,
        research_context=ResearchContext(),
    )
    return signals.build_signal(
        cluster, features, assessment, fset, evidence_by_id=_all(*items)
    )


# --- classification ---------------------------------------------------------


def test_counter_evidence_wins_classification():
    a = _ev("ev-1")
    b = _ev("ev-2", url="https://other.example.com/2")
    cluster = _cluster(("ev-1", "ev-2"))
    features = derive_features(cluster, _all(a, b))  # independent=2
    kind = signals.classify_signal_type(features, _assessment(cluster, counter=("ev-2",), kind=CONTRADICTION_FACTUAL))
    assert kind == "contradictory"


def test_two_independent_origins_are_cross_source():
    a = _ev("ev-1", url="https://a.example.com/1")
    b = _ev("ev-2", url="https://b.example.com/2")
    cluster = _cluster(("ev-1", "ev-2"))
    features = derive_features(cluster, _all(a, b))
    assert signals.classify_signal_type(features, _assessment(cluster)) == "cross_source"


def test_single_origin_both_windows_is_repeated():
    a = _ev("ev-1", window=WINDOW_CURRENT)
    b = _ev("ev-2", window=WINDOW_BASELINE)
    cluster = _cluster(("ev-1", "ev-2"))
    features = derive_features(cluster, _all(a, b))
    assert signals.classify_signal_type(features, _assessment(cluster)) == "repeated"


def test_single_origin_current_only_with_baseline_is_emerging():
    cur = _ev("ev-1", window=WINDOW_CURRENT)
    base = _ev("__gbase__", window=WINDOW_BASELINE)
    cluster = _cluster(("ev-1",))
    features = derive_features(cluster, _all(cur, base))
    assert signals.classify_signal_type(features, _assessment(cluster)) == "emerging"


def test_no_baseline_window_means_no_emerging_claim():
    """Closeout §3: without a baseline there is nothing to be 'new' against."""
    a = _ev("ev-1")
    cluster = _cluster(("ev-1",))
    features = derive_features(cluster, _all(a))
    assert features.has_baseline_data is False
    assert signals.classify_signal_type(features, _assessment(cluster)) == "single_source"


def test_single_origin_single_window_falls_back_to_single_source():
    a = _ev("ev-1")
    b = _ev("ev-2", url="https://reddit.com/r/x/ev-2")  # same host
    cluster = _cluster(("ev-1", "ev-2"))
    features = derive_features(cluster, _all(a, b))  # independent=1, no baseline
    assert signals.classify_signal_type(features, _assessment(cluster)) == "single_source"


# --- builder: schema-shaped output ------------------------------------------


def test_built_signal_is_schema_shaped():
    a = _ev("ev-1", url="https://a.example.com/1")
    b = _ev("ev-2", url="https://b.example.com/2")
    signal, diag = _build(a, b)
    assert set(signal) <= set(signals.SIGNAL_SCHEMA_KEYS)
    assert signal["signal_type"] == "cross_source"
    assert signal["evidence_ids"] == ["ev-1", "ev-2"]
    assert signal["signal_id"] == derive_signal_id(derive_cluster_id(("ev-1", "ev-2")))
    assert 0.0 <= signal["score"] <= 1.0
    assert signal["confidence"] == pytest.approx(0.8)


def test_signal_deterministic_across_runs():
    a = _ev("ev-1", url="https://a.example.com/1")
    b = _ev("ev-2", url="https://b.example.com/2")
    s1, d1 = _build(a, b)
    s2, d2 = _build(a, b)
    assert s1 == s2
    assert d1.to_dict() == d2.to_dict()


def test_representative_ids_prefer_text_bearing_members():
    a = _ev("ev-1", text="")
    b = _ev("ev-2", text="x")
    c = _ev("ev-3", text="y")
    d = _ev("ev-4", text="z")
    cluster = _cluster(("ev-1", "ev-2", "ev-3", "ev-4"))
    signal, _ = _build(a, b, c, d, cluster=cluster)
    assert set(signal["representative_evidence_ids"]) == {"ev-2", "ev-3", "ev-4"}


def test_representatives_fallback_without_text():
    a = _ev("ev-1", text="")
    b = _ev("ev-2", text="")
    cluster = _cluster(("ev-1", "ev-2"))
    signal, _ = _build(a, b, cluster=cluster)
    assert set(signal["representative_evidence_ids"]) <= {"ev-1", "ev-2"}


def test_contradictory_signal_carries_counter_ids():
    a = _ev("ev-1")
    b = _ev("ev-2")
    cluster = _cluster(("ev-1", "ev-2"))
    signal, _ = _build(a, b, counter=("ev-2",), kind=CONTRADICTION_FACTUAL, cluster=cluster)
    assert signal["signal_type"] == "contradictory"
    assert signal["counter_evidence_ids"] == ["ev-2"]
    assert signal["supporting_evidence_ids"] == ["ev-1"]


def test_score_equals_frozen_geometric_mean():
    from gtm_intelligence import scoring as sc

    a = _ev("ev-1")
    cluster = _cluster(("ev-1",))
    features = derive_features(cluster, _all(a))
    fset = derive_factors(
        cluster, features, _all(a), NOW,
        model=FakeIntelligenceModel(scripts=(
            FakeClusterScript(label="Topic L", claim="claim", evidence_ids=("ev-1",), decision_relevance=0.7),
        )),
    )
    signal, diag = signals.build_signal(
        cluster, features, _assessment(cluster), fset, evidence_by_id=_all(a)
    )
    expected = sc.compute_score(fset.factors).score
    assert signal["score"] == pytest.approx(expected)
    assert diag.score == pytest.approx(expected)


def test_diagnostics_carry_full_factor_trail():
    a = _ev("ev-1")
    cluster = _cluster(("ev-1",))
    signal, diag = _build(a, cluster=cluster)
    assert diag.signal_id == signal["signal_id"]
    assert diag.raw_factors["decision_relevance"] == pytest.approx(0.7)
    assert diag.clamped_factors == {
        k: diag.raw_factors[k] < diag.effective_factors[k]
        for k in diag.raw_factors
    }
    assert diag.weak_signal is not None


def test_source_diversity_floor_is_one():
    a = _ev("ev-1")
    cluster = _cluster(("ev-1",))
    signal, _ = _build(a, cluster=cluster)
    assert signal["source_diversity"] >= 1


# --- contract validation ----------------------------------------------------


def test_valid_signal_has_no_violations():
    a = _ev("ev-1", url="https://a.example.com/1")
    b = _ev("ev-2", url="https://b.example.com/2")
    signal, _ = _build(a, b)
    assert signals.validate_signal_contract(signal) == []


def test_contradictory_without_counter_is_a_violation():
    signal = {
        "signal_id": "sig_x",
        "topic": "t",
        "evidence_ids": ["ev-1"],
        "signal_type": "contradictory",
    }
    violations = signals.validate_signal_contract(signal)
    assert any("counter_evidence_ids" in v for v in violations)


def test_unknown_signal_type_is_a_violation():
    signal = {
        "signal_id": "sig_x",
        "topic": "t",
        "evidence_ids": ["ev-1"],
        "signal_type": "mega_trend",
    }
    assert signals.validate_signal_contract(signal)


def test_extra_keys_are_a_violation():
    a = _ev("ev-1")
    cluster = _cluster(("ev-1",))
    signal, _ = _build(a, cluster=cluster)
    signal["recommendation"] = "spend more"
    assert signals.validate_signal_contract(signal)


def test_missing_required_key_reports_it():
    violations = signals.validate_signal_contract({"topic": "t"})
    assert any("signal_id" in v for v in violations)


def test_bad_signal_id_pattern_is_a_violation():
    signal = {
        "signal_id": "signal_1",
        "topic": "t",
        "evidence_ids": ["ev-1"],
        "signal_type": "single_source",
    }
    assert signals.validate_signal_contract(signal)
