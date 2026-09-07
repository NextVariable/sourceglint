"""Phase 5 §28 — semantic cache key + store semantics."""
from __future__ import annotations

import pytest

from gtm_intelligence.intelligence.cache import (
    SemanticCache,
    build_cache_key,
)
from gtm_intelligence.intelligence.model import ModelResponse, ModelStatus

CTX_A = {"mode": "competitive", "entities": ["Acme"], "market": "US"}
CTX_B = {"mode": "competitive", "entities": ["Beta"], "market": "US"}


def _response(**over) -> ModelResponse:
    base = dict(
        task="semantic_factors", status=ModelStatus.SUCCESS,
        payload={"decision_relevance": 0.7},
    )
    base.update(over)
    return ModelResponse(**base)


def _key(**over) -> str:
    base = dict(
        task="semantic_factors",
        prompt_version="semantic_factors:v1",
        model_id="fake:v1",
        evidence_ids=["ev-2", "ev-1"],
        research_context=CTX_A,
    )
    base.update(over)
    return build_cache_key(**base)


# --- key determinism --------------------------------------------------------


def test_key_is_deterministic():
    assert _key() == _key()


def test_key_ignores_evidence_id_order():
    a = _key(evidence_ids=["ev-1", "ev-2", "ev-3"])
    b = _key(evidence_ids=["ev-3", "ev-1", "ev-2"])
    assert a == b


def test_key_changes_with_task():
    assert _key(task="contradiction") != _key()


def test_key_changes_with_prompt_version():
    assert _key(prompt_version="semantic_factors:v2") != _key()


def test_key_changes_with_model_id():
    assert _key(model_id="other:v1") != _key()


def test_key_changes_with_evidence_set():
    assert _key(evidence_ids=["ev-9"]) != _key()


def test_key_changes_with_research_context():
    assert _key(research_context=CTX_B) != _key()


def test_key_is_stable_across_ctx_key_order():
    a = _key(research_context={"mode": "launch", "entities": ["X"], "market": "JP"})
    b = _key(research_context={"market": "JP", "entities": ["X"], "mode": "launch"})
    assert a == b


# --- store semantics --------------------------------------------------------


def test_get_misses_return_none():
    cache = SemanticCache()
    assert cache.get("nope") is None


def test_put_then_get_round_trips():
    cache = SemanticCache()
    cache.put("k", _response())
    got = cache.get("k")
    assert got is not None
    assert got.payload == {"decision_relevance": 0.7}
    assert got.status is ModelStatus.SUCCESS


def test_failure_responses_are_never_cached():
    cache = SemanticCache()
    cache.put("k", ModelResponse(task="t", status=ModelStatus.UNAVAILABLE, error="x"))
    assert cache.get("k") is None
    assert cache.size == 0


def test_invalid_output_never_cached():
    cache = SemanticCache()
    cache.put(
        "k",
        ModelResponse(task="t", status=ModelStatus.INVALID_OUTPUT, error="bad"),
    )
    assert cache.get("k") is None


def test_put_returns_the_response_for_fluent_callers():
    cache = SemanticCache()
    r = _response()
    assert cache.put("k", r) is r


def test_cache_size_tracks_successes():
    cache = SemanticCache()
    cache.put("a", _response())
    cache.put("b", _response())
    cache.put("bad", ModelResponse(task="t", status=ModelStatus.TIMEOUT))
    assert cache.size == 2


def test_clear_empties_store():
    cache = SemanticCache()
    cache.put("k", _response())
    cache.clear()
    assert cache.size == 0
    assert cache.get("k") is None
