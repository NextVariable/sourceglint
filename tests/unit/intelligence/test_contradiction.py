"""Phase 5 §16 — support-vs-contradiction classification per cluster."""
from __future__ import annotations

import pytest

from sourceglint.intelligence import contradiction
from sourceglint.intelligence.dtos import (
    CONTRADICTION_CONTEXTUAL,
    CONTRADICTION_EXPERIENCE,
    CONTRADICTION_FACTUAL,
    CONTRADICTION_NONE,
    PreparedEvidence,
)
from sourceglint.intelligence.ids import derive_cluster_id
from sourceglint.intelligence.model import (
    FakeClusterScript,
    FakeIntelligenceModel,
    FailingIntelligenceModel,
    ModelResponse,
    ModelStatus,
)
from sourceglint.intelligence.dtos import ValidatedCluster


def _ev(eid: str) -> PreparedEvidence:
    return PreparedEvidence(
        evidence_id=eid,
        source="reddit",
        source_type="comment",
        window="current",
        title=f"title {eid}",
        snippet=f"snippet {eid}",
        published_at="2026-09-01",
        market="global",
        language="en",
        source_tier=2,
        url=f"https://reddit.com/r/x/{eid}",
        has_text=True,
    )


def _cluster(evidence_ids: tuple[str, ...], label: str = "L") -> ValidatedCluster:
    return ValidatedCluster(
        cluster_id=derive_cluster_id(evidence_ids),
        label=label,
        claim="c",
        evidence_ids=evidence_ids,
        confidence=0.8,
    )


def _index(*items: PreparedEvidence) -> dict[str, PreparedEvidence]:
    return {e.evidence_id: e for e in items}


def _model(*scripts: FakeClusterScript) -> FakeIntelligenceModel:
    return FakeIntelligenceModel(scripts=scripts)


# --- happy paths ------------------------------------------------------------


def test_no_contradiction_defaults_to_all_support():
    cluster = _cluster(("ev-1", "ev-2"))
    model = _model(FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1", "ev-2")))
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"))
    )
    assert len(outcome.assessments) == 1
    a = outcome.assessments[0]
    assert a.cluster_id == cluster.cluster_id
    assert a.counter_evidence_ids == ()
    assert a.kind == CONTRADICTION_NONE
    assert not a.degraded
    assert not outcome.warnings


def test_factual_contradiction_partitions_support_and_counter():
    cluster = _cluster(("ev-1", "ev-2", "ev-3"))
    model = _model(
        FakeClusterScript(
            label="L",
            claim="c",
            evidence_ids=("ev-1", "ev-2", "ev-3"),
            counter_evidence_ids=("ev-3",),
            contradiction_kind=CONTRADICTION_FACTUAL,
            contradiction_confidence=0.9,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model,
        evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"), _ev("ev-3")),
    )
    a = outcome.assessments[0]
    assert a.counter_evidence_ids == ("ev-3",)
    # support is the code-computed complement — never overlaps counter
    assert a.supporting_evidence_ids == ("ev-1", "ev-2")
    assert a.kind == CONTRADICTION_FACTUAL
    assert a.confidence == pytest.approx(0.9)


def test_contextual_and_experience_kinds_preserved():
    for kind in (CONTRADICTION_CONTEXTUAL, CONTRADICTION_EXPERIENCE):
        cluster = _cluster(("ev-1", "ev-2"))
        model = _model(
            FakeClusterScript(
                label="L", claim="c", evidence_ids=("ev-1", "ev-2"),
                counter_evidence_ids=("ev-2",), contradiction_kind=kind,
            )
        )
        outcome = contradiction.analyze_contradictions(
            [cluster], model, evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"))
        )
        assert outcome.assessments[0].kind == kind


def test_assessments_sorted_by_cluster_id():
    c1 = _cluster(("ev-1",))
    c2 = _cluster(("ev-2",))
    # FakeIntelligenceModel returns scripts in script order; whichever order
    # we pass, assessments must come back sorted by cluster_id.
    outcome = contradiction.analyze_contradictions(
        [c2, c1], _model(
            FakeClusterScript(label="A", claim="c", evidence_ids=("ev-1",)),
            FakeClusterScript(label="B", claim="c", evidence_ids=("ev-2",)),
        ),
        evidence_by_id=_index(_ev("ev-1"), _ev("ev-2")),
    )
    got = [a.cluster_id for a in outcome.assessments]
    assert got == sorted(got)
    assert got == sorted([c1.cluster_id, c2.cluster_id])


def test_multiple_clusters_each_get_own_assessment():
    clusters = [_cluster(("ev-1",)), _cluster(("ev-2",))]
    outcome = contradiction.analyze_contradictions(
        clusters,
        _model(
            FakeClusterScript(label="A", claim="c", evidence_ids=("ev-1",)),
            FakeClusterScript(label="B", claim="c", evidence_ids=("ev-2",)),
        ),
        evidence_by_id=_index(_ev("ev-1"), _ev("ev-2")),
    )
    assert {a.cluster_id for a in outcome.assessments} == {
        c.cluster_id for c in clusters
    }


# --- id hygiene -------------------------------------------------------------


def test_counter_id_outside_cluster_is_cut():
    """A counter id must belong to THIS cluster — evidence from another
    cluster cannot contradict a claim it was never grouped under."""
    cluster = _cluster(("ev-1", "ev-2"))
    other = _ev("other-9")
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1", "ev-2"),
            counter_evidence_ids=("ev-2", "other-9"),
            contradiction_kind=CONTRADICTION_FACTUAL,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model,
        evidence_by_id={**_index(_ev("ev-1"), _ev("ev-2")), **{"other-9": other}},
    )
    a = outcome.assessments[0]
    assert a.counter_evidence_ids == ("ev-2",)
    assert any("other-9" in w for w in outcome.warnings)
    assert a.degraded


def test_hallucinated_counter_id_is_cut():
    cluster = _cluster(("ev-1",))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1",),
            counter_evidence_ids=("ghost-id",),
            contradiction_kind=CONTRADICTION_FACTUAL,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"))
    )
    a = outcome.assessments[0]
    assert a.counter_evidence_ids == ()
    # after the cut there is no counter evidence → kind must collapse to none
    assert a.kind == CONTRADICTION_NONE
    assert a.degraded


def test_support_counter_always_disjoint_by_construction():
    cluster = _cluster(("ev-1", "ev-2", "ev-3"))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1", "ev-2", "ev-3"),
            counter_evidence_ids=("ev-3",),
            contradiction_kind=CONTRADICTION_EXPERIENCE,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model,
        evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"), _ev("ev-3")),
    )
    a = outcome.assessments[0]
    overlap = set(a.supporting_evidence_ids) & set(a.counter_evidence_ids)
    assert overlap == set()


# --- kind consistency -------------------------------------------------------


def test_kind_without_counter_evidence_collapses_to_none():
    cluster = _cluster(("ev-1", "ev-2"))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1", "ev-2"),
            counter_evidence_ids=(), contradiction_kind=CONTRADICTION_FACTUAL,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"))
    )
    a = outcome.assessments[0]
    assert a.kind == CONTRADICTION_NONE
    assert a.degraded


def test_invalid_kind_value_collapses_to_none():
    cluster = _cluster(("ev-1",))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1",),
            counter_evidence_ids=(), contradiction_kind="suspicious",
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"))
    )
    assert outcome.assessments[0].kind == CONTRADICTION_NONE


def test_kind_none_but_counter_present_is_flagged_degraded():
    """Model contradiction: kind=none with non-empty counter. Code keeps the
    counter ids (evidence of a real contradiction) but flags under-reporting
    instead of silently inventing a kind."""
    cluster = _cluster(("ev-1", "ev-2"))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1", "ev-2"),
            counter_evidence_ids=("ev-2",), contradiction_kind=CONTRADICTION_NONE,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"), _ev("ev-2"))
    )
    a = outcome.assessments[0]
    assert a.counter_evidence_ids == ("ev-2",)
    assert a.degraded
    assert outcome.warnings


def test_confidence_clamped_to_unit_interval():
    cluster = _cluster(("ev-1",))
    model = _model(
        FakeClusterScript(
            label="L", claim="c", evidence_ids=("ev-1",),
            counter_evidence_ids=("ev-1",),
            contradiction_kind=CONTRADICTION_FACTUAL,
            contradiction_confidence=5.0,
        )
    )
    outcome = contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"))
    )
    assert outcome.assessments[0].confidence == pytest.approx(1.0)


# --- model failure semantics (PRD §27) --------------------------------------


def test_model_failure_degrades_instead_of_raising():
    """Contradiction is NOT a required step: a failure must degrade to
    'no contradiction found' per cluster, never raise."""
    cluster = _cluster(("ev-1", "ev-2"))
    outcome = contradiction.analyze_contradictions(
        [cluster], FailingIntelligenceModel(),
        evidence_by_id=_index(_ev("ev-1"), _ev("ev-2")),
    )
    a = outcome.assessments[0]
    assert a.counter_evidence_ids == ()
    assert a.kind == CONTRADICTION_NONE
    assert a.degraded
    assert outcome.warnings


def test_model_invalid_output_degrades():
    cluster = _cluster(("ev-1",))

    class InvalidModel:
        model_id = "invalid:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task="contradiction", status=ModelStatus.INVALID_OUTPUT,
                error="bad schema",
            )

    outcome = contradiction.analyze_contradictions(
        [cluster], InvalidModel(), evidence_by_id=_index(_ev("ev-1"))
    )
    assert outcome.assessments[0].degraded
    assert outcome.assessments[0].kind == CONTRADICTION_NONE


def test_success_without_payload_degrades():
    cluster = _cluster(("ev-1",))

    class NoPayload:
        model_id = "np:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(task="contradiction", status=ModelStatus.SUCCESS)

    outcome = contradiction.analyze_contradictions(
        [cluster], NoPayload(), evidence_by_id=_index(_ev("ev-1"))
    )
    assert outcome.assessments[0].degraded


def test_malformed_payload_degrades():
    cluster = _cluster(("ev-1",))

    class JunkModel:
        model_id = "junk:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task="contradiction", status=ModelStatus.SUCCESS,
                payload={"supporting_evidence_ids": "oops"},
            )

    outcome = contradiction.analyze_contradictions(
        [cluster], JunkModel(), evidence_by_id=_index(_ev("ev-1"))
    )
    assert outcome.assessments[0].degraded


# --- payload boundary -------------------------------------------------------


def test_payload_carries_cluster_context_and_member_text():
    cluster = _cluster(("ev-1",))
    model = _model(FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1",)))
    contradiction.analyze_contradictions(
        [cluster], model, evidence_by_id=_index(_ev("ev-1"))
    )
    call = model.calls[0]
    assert call["task"] == "contradiction"
    assert call["payload"]["cluster_id"] == cluster.cluster_id
    assert call["payload"]["evidence_ids"] == ["ev-1"]
    items = call["payload"]["evidence_items"]
    assert [i["evidence_id"] for i in items] == ["ev-1"]
    assert "snippet" in items[0]


# --- empty input ------------------------------------------------------------


def test_no_clusters_returns_empty_outcome_without_model_call():
    model = _model()
    outcome = contradiction.analyze_contradictions([], model, evidence_by_id={})
    assert outcome.assessments == ()
    assert model.calls == []
