"""Phase 5 §7–§11, §33–§34 — semantic clustering, validation, IDs."""
from __future__ import annotations

import pytest

from sourceglint.intelligence.dtos import PreparedEvidence, ResearchContext
from sourceglint.intelligence.ids import derive_cluster_id
from sourceglint.intelligence.model import (
    CLUSTERING_RESPONSE_SCHEMA,
    FakeClusterScript,
    FakeIntelligenceModel,
    FailingIntelligenceModel,
    IntelligencePipelineError,
    ModelResponse,
    ModelStatus,
    TASK_CLUSTERING,
)
from sourceglint.intelligence.preparation import model_payloads

# clustering module is under test; import at call time to keep collection
# green while the module does not exist yet.
from sourceglint.intelligence import clustering  # noqa: E402


def _evidence(eid: str, *, source: str = "src-a", text: str = "text") -> PreparedEvidence:
    return PreparedEvidence(
        evidence_id=eid,
        source=source,
        source_type="news",
        window="current",
        title=f"title {eid}",
        snippet=text or f"snippet {eid}",
        published_at="2026-09-01",
        market="global",
        language="en",
        url=f"https://example.com/{eid}",
        has_text=bool(text),
    )


def _default_ctx() -> ResearchContext:
    return ResearchContext(mode="launch", entities=("Acme",), market="US")


# --- happy path -------------------------------------------------------------


def test_cluster_returns_validated_clusters_with_stable_ids():
    ids_in = ("ev-1", "ev-2", "ev-3", "ev-4")
    prepared = [_evidence(i) for i in ids_in]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="L1", claim="C1", evidence_ids=("ev-1", "ev-2")),
            FakeClusterScript(label="L2", claim="C2", evidence_ids=("ev-3", "ev-4")),
        )
    )
    outcome = clustering.cluster(prepared, model, research_context=_default_ctx())
    clusters = outcome.clusters
    assert len(clusters) == 2
    assert clusters[0].cluster_id == derive_cluster_id(("ev-1", "ev-2"))
    assert clusters[1].cluster_id == derive_cluster_id(("ev-3", "ev-4"))
    assert clusters[0].evidence_ids == ("ev-1", "ev-2")
    assert clusters[0].label == "L1"
    assert clusters[0].claim == "C1"
    assert clusters[0].confidence == pytest.approx(0.8)
    assert not outcome.degraded


def test_clusters_sorted_by_cluster_id_regardless_of_model_order():
    prepared = [_evidence(f"ev-{i}") for i in range(1, 5)]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="B", claim="c", evidence_ids=("ev-3", "ev-4")),
            FakeClusterScript(label="A", claim="c", evidence_ids=("ev-1", "ev-2")),
        )
    )
    outcome = clustering.cluster(prepared, model)
    got = [c.cluster_id for c in outcome.clusters]
    assert got == sorted(got)
    assert got[0] == derive_cluster_id(("ev-1", "ev-2"))


def test_same_input_yields_same_cluster_ids_across_runs():
    prepared = [_evidence(f"ev-{i}") for i in range(1, 4)]
    scripts = (
        FakeClusterScript(label="A", claim="c", evidence_ids=("ev-1", "ev-2")),
        FakeClusterScript(label="B", claim="c", evidence_ids=("ev-3",)),
    )

    def run() -> list[str]:
        return [
            c.cluster_id
            for c in clustering.cluster(prepared, FakeIntelligenceModel(scripts=scripts)).clusters
        ]

    assert run() == run()


# --- model payload boundary -------------------------------------------------


def test_cluster_sends_task_payload_and_schema():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1", "ev-2")),)
    )
    clustering.cluster(prepared, model, research_context=_default_ctx())
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["task"] == TASK_CLUSTERING
    assert call["payload"]["evidence_items"] == model_payloads(prepared)
    ctx = call["payload"]["research_context"]
    assert ctx["mode"] == "launch"
    assert ctx["entities"] == ["Acme"]


def test_cluster_defaults_research_context_to_general():
    prepared = [_evidence("ev-1")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1",)),)
    )
    clustering.cluster(prepared, model)
    ctx = model.calls[0]["payload"]["research_context"]
    assert ctx["mode"] == "general"
    assert ctx["market"] == "global"


def test_cluster_payload_never_contains_url():
    prepared = [_evidence("ev-1", text="x")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="L", claim="c", evidence_ids=("ev-1",)),)
    )
    clustering.cluster(prepared, model)
    for item in model.calls[0]["payload"]["evidence_items"]:
        assert "url" not in item


# --- hallucinated ids (PRD §11) ---------------------------------------------


def test_hallucinated_id_removed_with_warning():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(
                label="L", claim="c", evidence_ids=("ev-1", "ghost-id", "ev-2")
            ),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert len(outcome.clusters) == 1
    assert outcome.clusters[0].evidence_ids == ("ev-1", "ev-2")
    assert any("ghost-id" in w for w in outcome.warnings)
    assert outcome.degraded


def test_all_hallucinated_cluster_raises():
    """PRD §27: clustering is required — zero usable clusters must stop."""
    prepared = [_evidence("ev-1")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="L", claim="c", evidence_ids=("ghost-1",)),)
    )
    with pytest.raises(IntelligencePipelineError, match="no usable clusters"):
        clustering.cluster(prepared, model)


def test_no_usable_clusters_raises_pipeline_error():
    prepared = [_evidence("ev-1")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="L", claim="c", evidence_ids=("ghost-1",)),)
    )
    with pytest.raises(IntelligencePipelineError):
        clustering.cluster(prepared, model)


# --- empty / malformed clusters ---------------------------------------------


def test_empty_evidence_cluster_dropped_with_warning():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="Empty", claim="c", evidence_ids=()),
            FakeClusterScript(label="Ok", claim="c", evidence_ids=("ev-2",)),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert [c.label for c in outcome.clusters] == ["Ok"]
    assert outcome.degraded


def test_blank_label_cluster_dropped_while_valid_survives():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="   ", claim="c", evidence_ids=("ev-1",)),
            FakeClusterScript(label="Good", claim="c", evidence_ids=("ev-2",)),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert [c.label for c in outcome.clusters] == ["Good"]
    assert outcome.degraded


def test_non_dict_cluster_item_skipped_while_valid_survives():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]

    class MixedModel:
        model_id = "mixed:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task=TASK_CLUSTERING,
                status=ModelStatus.SUCCESS,
                payload={
                    "clusters": [
                        "not-a-dict",
                        {
                            "label": "Good",
                            "claim": "c",
                            "evidence_ids": ["ev-1"],
                            "confidence": 0.7,
                        },
                    ]
                },
            )

    outcome = clustering.cluster(prepared, MixedModel())
    assert [c.label for c in outcome.clusters] == ["Good"]
    assert outcome.warnings


# --- overlap / double-count (PRD §33–§34) -----------------------------------


def test_duplicate_evidence_across_clusters_keeps_first_occurrence():
    prepared = [_evidence("ev-1"), _evidence("ev-2"), _evidence("ev-3")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="First", claim="c", evidence_ids=("ev-1", "ev-2")),
            FakeClusterScript(label="Second", claim="c", evidence_ids=("ev-2", "ev-3")),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert len(outcome.clusters) == 2
    by_label = {c.label: c for c in outcome.clusters}
    assert by_label["First"].evidence_ids == ("ev-1", "ev-2")
    assert by_label["Second"].evidence_ids == ("ev-3",)
    assert any("ev-2" in w for w in outcome.warnings)
    assert outcome.degraded


def test_secondary_cluster_emptied_by_overlap_is_dropped():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="Big", claim="c", evidence_ids=("ev-1", "ev-2")),
            FakeClusterScript(label="Sub", claim="c", evidence_ids=("ev-2",)),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert [c.label for c in outcome.clusters] == ["Big"]
    assert outcome.warnings


def test_identical_evidence_sets_collide_on_cluster_id():
    """Same membership emitted twice must not yield two clusters with the
    same id — the model may not double-count one evidence set."""
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(
            FakeClusterScript(label="A", claim="c1", evidence_ids=("ev-1", "ev-2")),
            FakeClusterScript(label="B", claim="c2", evidence_ids=("ev-2", "ev-1")),
        )
    )
    outcome = clustering.cluster(prepared, model)
    assert len(outcome.clusters) == 1
    assert outcome.clusters[0].label == "A"
    assert outcome.warnings


# --- no forced coverage (precision > recall) --------------------------------


def test_unassigned_evidence_is_allowed():
    prepared = [_evidence("ev-1"), _evidence("ev-2")]
    model = FakeIntelligenceModel(
        scripts=(FakeClusterScript(label="Only", claim="c", evidence_ids=("ev-1",)),)
    )
    outcome = clustering.cluster(prepared, model)
    assert [c.evidence_ids for c in outcome.clusters] == [("ev-1",)]
    assert not outcome.degraded


# --- model failure semantics (PRD §27) --------------------------------------


def test_model_unavailable_raises_pipeline_error():
    prepared = [_evidence("ev-1")]
    with pytest.raises(IntelligencePipelineError, match="unavailable"):
        clustering.cluster(prepared, FailingIntelligenceModel())


def test_model_invalid_output_raises_pipeline_error():
    prepared = [_evidence("ev-1")]

    class InvalidModel:
        model_id = "invalid:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task=TASK_CLUSTERING,
                status=ModelStatus.INVALID_OUTPUT,
                error="schema violation",
            )

    with pytest.raises(IntelligencePipelineError, match="schema violation"):
        clustering.cluster(prepared, InvalidModel())


def test_success_without_payload_raises():
    prepared = [_evidence("ev-1")]

    class NoPayload:
        model_id = "nopayload:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(task=TASK_CLUSTERING, status=ModelStatus.SUCCESS)

    with pytest.raises(IntelligencePipelineError):
        clustering.cluster(prepared, NoPayload())


def test_missing_clusters_key_raises():
    prepared = [_evidence("ev-1")]

    class NoClusters:
        model_id = "noclusters:v1"

        def complete_structured(self, **kwargs):
            return ModelResponse(
                task=TASK_CLUSTERING,
                status=ModelStatus.SUCCESS,
                payload={"other": 1},
            )

    with pytest.raises(IntelligencePipelineError):
        clustering.cluster(prepared, NoClusters())


# --- empty input ------------------------------------------------------------


def test_empty_prepared_input_is_a_programming_error():
    with pytest.raises(ValueError, match="no evidence"):
        clustering.cluster([], FakeIntelligenceModel())


# --- pure validation helper -------------------------------------------------


def test_validate_clusters_is_pure_and_order_independent():
    from sourceglint.intelligence.dtos import ClusterDraft

    known = {"ev-1", "ev-2", "ev-3"}
    drafts = [
        ClusterDraft(label="B", claim="c", evidence_ids=("ev-3",)),
        ClusterDraft(label="A", claim="c", evidence_ids=("ev-1", "ev-2")),
    ]
    clusters, warnings = clustering.validate_clusters(known, drafts)
    # ids are code-derived, not label-derived
    assert clusters[0].cluster_id == derive_cluster_id(("ev-1", "ev-2"))
    assert clusters[1].cluster_id == derive_cluster_id(("ev-3",))
    assert warnings == []
