"""Phase 5 §5 / §10 / §29 / §36 — model boundary, ids, prompts, guardrails."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gtm_intelligence.intelligence import ids, model, prompts
from gtm_intelligence.intelligence.guardrails import (
    detect_recommendation_leakage,
    has_recommendation_leakage,
)
from gtm_intelligence.intelligence.ids import (
    derive_cluster_id,
    derive_signal_id,
    is_valid_signal_id,
)
from gtm_intelligence.intelligence.model import (
    CONTRADICTION_RESPONSE_SCHEMA,
    CLUSTERING_RESPONSE_SCHEMA,
    SEMANTIC_FACTORS_RESPONSE_SCHEMA,
    FakeClusterScript,
    FakeIntelligenceModel,
    FailingIntelligenceModel,
    FixtureIntelligenceModel,
    IntelligenceModel,
    ModelResponse,
    ModelStatus,
)
from gtm_intelligence.intelligence.prompts import (
    PROMPT_VERSIONS,
    TASK_CLUSTERING,
    TASK_CONTRADICTION,
    TASK_SEMANTIC_FACTORS,
    get_prompt,
    prompt_version,
)

INTELLIGENCE_DIR = Path(ids.__file__).resolve().parent


# --- protocol ---------------------------------------------------------------


def test_fake_model_satisfies_protocol():
    assert isinstance(FakeIntelligenceModel(), IntelligenceModel)


def test_fixture_model_satisfies_protocol():
    assert isinstance(FixtureIntelligenceModel(fixtures={}), IntelligenceModel)


def test_failing_model_satisfies_protocol():
    assert isinstance(FailingIntelligenceModel(), IntelligenceModel)


def test_no_vendor_binding_in_intelligence_package():
    """PRD §5: core must not name any LLM vendor."""
    forbidden = (
        "openai", "anthropic", "deepseek", "minimax", "kimi",
        "gemini", "claude", "cohere", "mistral", "bedrock",
    )
    violations: list[str] = []
    for path in INTELLIGENCE_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for vendor in forbidden:
            if re.search(rf"\b{vendor}\b", text):
                violations.append(f"{path.name}:{vendor}")
    assert not violations, f"vendor coupling in core: {violations}"


def test_model_status_taxonomy_matches_prd():
    assert {s.value for s in ModelStatus} == {
        "success", "invalid_output", "timeout", "unavailable", "partial",
    }


def test_model_response_ok_requires_payload():
    assert ModelResponse(task="t", status=ModelStatus.SUCCESS).ok is False
    assert (
        ModelResponse(task="t", status=ModelStatus.SUCCESS, payload={}).ok is True
    )


# --- fake model behaviour ---------------------------------------------------


def _script(ids_, **kw):
    return FakeClusterScript(
        label=kw.get("label", "l"),
        claim=kw.get("claim", "c"),
        evidence_ids=tuple(ids_),
        **{k: v for k, v in kw.items() if k not in ("label", "claim")},
    )


def test_fake_clustering_returns_scripted_clusters():
    fake = FakeIntelligenceModel(
        scripts=[_script(["ev_a", "ev_b"], label="pricing", claim="price up")]
    )
    resp = fake.complete_structured(
        task=TASK_CLUSTERING,
        payload={"evidence": []},
        response_schema=CLUSTERING_RESPONSE_SCHEMA,
    )
    assert resp.ok
    assert resp.payload["clusters"][0]["label"] == "pricing"


def test_fake_contradiction_lookup_uses_code_derived_cluster_id():
    script = _script(
        ["ev_a", "ev_b"], counter_evidence_ids=("ev_c",), contradiction_kind="factual"
    )
    fake = FakeIntelligenceModel(scripts=[script])
    cluster_id = derive_cluster_id(["ev_a", "ev_b"])
    resp = fake.complete_structured(
        task=TASK_CONTRADICTION,
        payload={"cluster_id": cluster_id, "evidence_ids": ["ev_a", "ev_b"]},
        response_schema=CONTRADICTION_RESPONSE_SCHEMA,
    )
    assert resp.payload["counter_evidence_ids"] == ["ev_c"]
    assert resp.payload["kind"] == "factual"


def test_fake_contradiction_defaults_support_to_all_minus_counter():
    script = _script(["ev_a", "ev_b", "ev_c"], counter_evidence_ids=("ev_c",))
    fake = FakeIntelligenceModel(scripts=[script])
    resp = fake.complete_structured(
        task=TASK_CONTRADICTION,
        payload={
            "cluster_id": derive_cluster_id(script.evidence_ids),
            "evidence_ids": list(script.evidence_ids),
        },
        response_schema=CONTRADICTION_RESPONSE_SCHEMA,
    )
    assert resp.payload["supporting_evidence_ids"] == ["ev_a", "ev_b"]


def test_fake_factors_never_defaults_to_neutral_half():
    """An UNSCRIPTED cluster gets 0.0 + 'not assessed' — never a 0.5 that
    would silently look like a real judgement (Closeout §3)."""
    fake = FakeIntelligenceModel(scripts=[_script(["ev_zzz"])])
    resp = fake.complete_structured(
        task=TASK_SEMANTIC_FACTORS,
        payload={"cluster_id": derive_cluster_id(["ev_a"])},
        response_schema=SEMANTIC_FACTORS_RESPONSE_SCHEMA,
    )
    assert resp.payload["decision_relevance"] == 0.0
    assert resp.payload["decision_relevance_rationale"] == "not assessed"


def test_fake_factors_returns_scripted_relevance_and_rationale():
    script = _script(["ev_a"], decision_relevance=0.9,
                     decision_relevance_rationale="competitor pricing move")
    fake = FakeIntelligenceModel(scripts=[script])
    resp = fake.complete_structured(
        task=TASK_SEMANTIC_FACTORS,
        payload={"cluster_id": derive_cluster_id(["ev_a"])},
        response_schema=SEMANTIC_FACTORS_RESPONSE_SCHEMA,
    )
    assert resp.payload["decision_relevance"] == 0.9
    assert resp.payload["decision_relevance_rationale"] == "competitor pricing move"


def test_fake_unknown_task_reports_invalid_output():
    fake = FakeIntelligenceModel()
    resp = fake.complete_structured(
        task="nope", payload={}, response_schema={},
    )
    assert resp.status is ModelStatus.INVALID_OUTPUT


def test_failing_model_reports_status_without_raising():
    failing = FailingIntelligenceModel(status=ModelStatus.TIMEOUT)
    resp = failing.complete_structured(
        task=TASK_CLUSTERING, payload={}, response_schema=CLUSTERING_RESPONSE_SCHEMA
    )
    assert resp.status is ModelStatus.TIMEOUT
    assert resp.ok is False


def test_fixture_model_uses_same_code_path_as_fake():
    fixture = FixtureIntelligenceModel(
        fixtures={TASK_CLUSTERING: {"clusters": [{"label": "x", "claim": "y",
                                                  "evidence_ids": ["ev_a"]}]}}
    )
    resp = fixture.complete_structured(
        task=TASK_CLUSTERING, payload={}, response_schema=CLUSTERING_RESPONSE_SCHEMA
    )
    assert resp.payload["clusters"][0]["label"] == "x"


def test_fixture_model_missing_task_is_invalid_output():
    fixture = FixtureIntelligenceModel(fixtures={})
    resp = fixture.complete_structured(
        task=TASK_CLUSTERING, payload={}, response_schema=CLUSTERING_RESPONSE_SCHEMA
    )
    assert resp.status is ModelStatus.INVALID_OUTPUT


def test_model_calls_are_recorded_for_assertions():
    fake = FakeIntelligenceModel(scripts=[_script(["ev_a"])])
    fake.complete_structured(
        task=TASK_CLUSTERING, payload={"evidence": []},
        response_schema=CLUSTERING_RESPONSE_SCHEMA,
    )
    assert fake.calls[0]["task"] == TASK_CLUSTERING


# --- id derivation (PRD §10) ------------------------------------------------


def test_cluster_id_is_prefixed_and_shape_valid():
    cid = derive_cluster_id(["ev_a", "ev_b"])
    assert cid.startswith("cl_")
    assert re.match(r"^cl_[a-z0-9_]{1,64}$", cid)


def test_cluster_id_is_order_independent():
    assert derive_cluster_id(["ev_a", "ev_b"]) == derive_cluster_id(
        ["ev_b", "ev_a"]
    )


def test_cluster_id_ignores_duplicate_ids():
    assert derive_cluster_id(["ev_a", "ev_a"]) == derive_cluster_id(["ev_a"])


def test_cluster_id_differs_for_different_sets():
    assert derive_cluster_id(["ev_a"]) != derive_cluster_id(["ev_b"])


def test_cluster_id_rejects_empty_set():
    with pytest.raises(ValueError):
        derive_cluster_id([])


def test_signal_id_is_prefixed_and_matches_frozen_pattern():
    sid = derive_signal_id(derive_cluster_id(["ev_a"]))
    assert sid.startswith("sig_")
    assert is_valid_signal_id(sid)


def test_signal_id_is_stable_for_same_cluster():
    cid = derive_cluster_id(["ev_a", "ev_b"])
    assert derive_signal_id(cid) == derive_signal_id(cid)


def test_signal_id_differs_across_clusters():
    assert derive_signal_id(derive_cluster_id(["ev_a"])) != derive_signal_id(
        derive_cluster_id(["ev_b"])
    )


def test_signal_id_rejects_empty_cluster_id():
    with pytest.raises(ValueError):
        derive_signal_id("")


# --- prompts (PRD §9 / §29) -------------------------------------------------


def test_every_task_has_a_prompt_file():
    for task in (TASK_CLUSTERING, TASK_CONTRADICTION, TASK_SEMANTIC_FACTORS):
        assert get_prompt(task).render().strip()


def test_prompt_versions_are_explicit_and_stable():
    assert prompt_version(TASK_CLUSTERING) == "clustering:v1"
    assert prompt_version(TASK_CONTRADICTION) == "contradiction:v1"
    assert prompt_version(TASK_SEMANTIC_FACTORS) == "semantic_factors:v1"


def test_prompt_version_changes_when_registry_changes():
    # Guard: someone bumping a version must also update this assertion, so
    # cache invalidation is a conscious act (PRD §29).
    assert set(PROMPT_VERSIONS) == {
        TASK_CLUSTERING, TASK_CONTRADICTION, TASK_SEMANTIC_FACTORS,
    }


def test_unknown_prompt_task_raises():
    with pytest.raises(KeyError):
        prompt_version("does-not-exist")


def test_clustering_prompt_states_merge_and_split_rules():
    text = get_prompt(TASK_CLUSTERING).render()
    assert "Keep separate" in text or "keep separate" in text
    assert "Precision beats recall" in text


def test_clustering_prompt_forbids_inventing_ids():
    text = get_prompt(TASK_CLUSTERING).render()
    assert "Never invent" in text


def test_contradiction_prompt_distinguishes_contextual_disagreement():
    text = get_prompt(TASK_CONTRADICTION).render()
    assert "contextual" in text
    assert "factual" in text


def test_every_prompt_forbids_recommendations():
    for task in (TASK_CLUSTERING, TASK_CONTRADICTION, TASK_SEMANTIC_FACTORS):
        text = get_prompt(task).render()
        assert "recommend" in text.lower(), f"{task} prompt lacks the ban"


def test_prompt_files_contain_no_implementation_code():
    for task in (TASK_CLUSTERING, TASK_CONTRADICTION, TASK_SEMANTIC_FACTORS):
        text = get_prompt(task).render()
        assert "import " not in text
        assert "def " not in text


# --- guardrails (PRD §36) ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You should raise prices",
        "We recommend targeting enterprise",
        "increase budget for paid",
        "you must ship this",
    ],
)
def test_recommendation_phrases_are_detected(text):
    assert has_recommendation_leakage(text)


@pytest.mark.parametrize(
    "text",
    [
        "Price increased for the team plan",
        "翻訳の遅延が報告されている",
        "Competitor launched a translation feature",
    ],
)
def test_descriptive_signal_text_passes(text):
    assert not has_recommendation_leakage(text)


def test_leakage_detection_returns_the_phrases():
    assert "you should" in detect_recommendation_leakage("You should do it")


def test_leakage_detection_handles_empty_text():
    assert detect_recommendation_leakage("") == []
