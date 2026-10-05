"""Phase 5 review gates (PRD §46 A–K).

Every gate must pass for the Phase 5 closeout to be READY. Unlike the
Phase 3/4 gate files, these gates avoid nested pytest subprocesses (the
outer pytest invocation already runs the whole suite); each gate does a
direct, local, auditable check instead.

  A. Regression baseline — the intelligence unit + eval suites exist and
     the eval determinism constant is locked.
  B. Frozen-schema output — every pipeline signal validates against
     signal.schema.json (jsonschema + referencing, local registry).
  C. Classification invariants — single enum; cross_source requires >=2
     independent origins; emerging/repeated never claimed without a
     baseline window.
  D. Contradiction invariants — counter ids are cluster members; the
     schema requires the counter key; contradictory => counter non-empty;
     support/counter partition the cluster.
  E. Determinism — the eval golden asserts 20 byte-identical runs
     (constant locked here so it cannot silently shrink).
  F. Offline core — no network import/socket usage anywhere in the
     intelligence package; no LLM vendor name (PRD §5).
  G. No recommendation leakage — frozen eval labels/claims screen clean
     through the guardrail (recommendations never reach signal topics).
  H. Cache semantics — success-only caching and deterministic keys hold.
  I. Stop boundary — the pipeline result structure carries signals,
     clusters, diagnostics, warnings, model_status — and nothing else
     (no insight / recommendation / brief).
  J. Capability honesty — config never out-claims code: github lists
     exactly what the adapter implements (PRD §44).
  K. Traceability — every emitted signal id is deterministically
     derivable from its cluster and every evidence id traces to the run's
     input ledger.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from _support import load_jsonl, load_schema, validate
from sourceglint.intelligence import cache as cache_mod
from sourceglint.intelligence import pipeline as pipeline_mod
from sourceglint.intelligence import signals as signals_mod
from sourceglint.intelligence.contradiction import ContradictionAssessment
from sourceglint.intelligence.dtos import (
    CONTRADICTION_FACTUAL,
    WINDOW_BASELINE,
    WINDOW_CURRENT,
    PreparedEvidence,
    SignalFeatures,
    ValidatedCluster,
)
from sourceglint.intelligence.factors import FactorSet
from sourceglint.intelligence.features import derive_features
from sourceglint.intelligence.guardrails import screen_texts
from sourceglint.intelligence.ids import derive_cluster_id, derive_signal_id
from sourceglint.intelligence.model import (
    CONTRADICTION_RESPONSE_SCHEMA,
    FakeClusterScript,
    FakeIntelligenceModel,
    ModelResponse,
    ModelStatus,
)

ROOT = Path(__file__).resolve().parents[3]
INTELLIGENCE_PKG = Path(pipeline_mod.__file__).resolve().parent
GOLDEN = json.loads(
    (ROOT / "tests/fixtures/phase5/phase5_eval_golden.json").read_text(encoding="utf-8")
)
EVAL_MODULE = Path(__file__).resolve().parent / "test_phase5_eval.py"


def _run_scenario(name: str):
    meta = GOLDEN["scenarios"][name]
    records = load_jsonl(meta["file"])
    result = pipeline_mod.run_intelligence_pipeline(
        records,
        FakeIntelligenceModel(scripts=[FakeClusterScript(**s) for s in meta["scripts"]]),
        as_of=datetime.fromisoformat(meta["as_of"].replace("Z", "+00:00")),
    )
    return records, result


def _ev(eid: str, window: str, url: str) -> PreparedEvidence:
    return PreparedEvidence(
        evidence_id=eid, source="s", source_type="comment", window=window,
        title="t", snippet="x", published_at="2026-09-01T00:00:00Z",
        market="global", language="en", source_tier=2,
        evidence_quality=0.7, url=url, has_text=True,
    )


def _cluster(*ids: str) -> ValidatedCluster:
    return ValidatedCluster(
        cluster_id=derive_cluster_id(ids), label="L", claim="c",
        evidence_ids=ids, confidence=0.8,
    )


# --- Gate A — regression baseline --------------------------------------


def test_gate_a_regression_baseline():
    text = EVAL_MODULE.read_text(encoding="utf-8")
    assert re.search(r"GOLDEN_RUNS\s*=\s*20", text)
    assert (ROOT / "tests/unit/intelligence/test_clustering.py").is_file()
    assert (ROOT / "tests/unit/intelligence/test_pipeline.py").is_file()


# --- Gate B — frozen-schema output -------------------------------------


def test_gate_b_eval_signals_validate_against_frozen_schema():
    schema = load_schema("signal.schema.json")
    for name in GOLDEN["scenarios"]:
        _, result = _run_scenario(name)
        for sig in result.signals:
            validate(sig, schema)  # raises on violation


# --- Gate C — classification invariants --------------------------------


def test_gate_c_classification_invariants():
    base = _ev("b", WINDOW_BASELINE, "https://a.example.com/b")
    cur_same = _ev("c1", WINDOW_CURRENT, "https://a.example.com/c1")
    cur_other = _ev("c2", WINDOW_CURRENT, "https://b.example.com/c2")
    idx = {e.evidence_id: e for e in (base, cur_same, cur_other)}
    none = ContradictionAssessment(cluster_id="cl_x")

    # single origin + current-only with a global baseline => emerging (1), not cross
    feats = derive_features(_cluster("c1"), idx)
    assert feats.appeared_only_current is True
    assert signals_mod.classify_signal_type(feats, none) == "emerging"

    # two independent origins => cross_source outranks emerging
    feats2 = derive_features(_cluster("c1", "c2"), idx)
    assert signals_mod.classify_signal_type(feats2, none) == "cross_source"

    # no baseline window at all => no emerging/repeated claim possible
    cur_only_idx = {
        "c1": _ev("c1", WINDOW_CURRENT, "https://a.example.com/c1"),
        "c2": _ev("c2", WINDOW_CURRENT, "https://b.example.com/c2"),
    }
    feats3 = derive_features(_cluster("c1"), cur_only_idx)
    assert feats3.has_baseline_data is False
    assert signals_mod.classify_signal_type(feats3, none) == "single_source"


# --- Gate D — contradiction invariants ---------------------------------


def test_gate_d_contradiction_invariants():
    assert set(CONTRADICTION_RESPONSE_SCHEMA["required"]) == {
        "supporting_evidence_ids", "counter_evidence_ids"
    }
    cluster_obj = _cluster("ev-1", "ev-2")
    feats = SignalFeatures(cluster_id=cluster_obj.cluster_id, evidence_count=2)
    assessment = ContradictionAssessment(
        cluster_id=cluster_obj.cluster_id,
        supporting_evidence_ids=("ev-1",),
        counter_evidence_ids=("ev-2",),
        kind=CONTRADICTION_FACTUAL,
    )
    fset = FactorSet(cluster_id=cluster_obj.cluster_id)
    index = {
        "ev-1": _ev("ev-1", WINDOW_CURRENT, "https://a.example.com/1"),
        "ev-2": _ev("ev-2", WINDOW_CURRENT, "https://a.example.com/2"),
    }
    sig, _ = signals_mod.build_signal(cluster_obj, feats, assessment, fset,
                                      evidence_by_id=index)
    assert sig["signal_type"] == "contradictory"
    assert sig["counter_evidence_ids"] == ["ev-2"]
    assert set(sig["supporting_evidence_ids"]) | set(sig["counter_evidence_ids"]) == {
        "ev-1", "ev-2"
    }
    assert signals_mod.validate_signal_contract(sig) == []


# --- Gate E — determinism ----------------------------------------------


def test_gate_e_golden_runs_never_shrink():
    text = EVAL_MODULE.read_text(encoding="utf-8")
    assert "for _ in range(GOLDEN_RUNS)" in text


# --- Gate F — offline core ---------------------------------------------


def test_gate_f_offline_core():
    # urllib.parse (urlsplit) is stdlib and never opens a socket; the
    # network-facing imports are requests/socket/httpx/aiohttp/urllib.request.
    forbidden_imports = re.compile(
        r"^\s*(import|from)\s+(requests|socket|httpx|aiohttp)\b|"
        r"^\s*import urllib\b|^\s*from urllib\.request\b",
        re.MULTILINE,
    )
    vendors = re.compile(
        r"\b(openai|anthropic|deepseek|minimax|kimi|gemini|claude)\b", re.I
    )
    for py in INTELLIGENCE_PKG.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert not forbidden_imports.search(text), f"network import in {py.name}"
        assert not vendors.search(text), f"vendor name in {py.name}"
    assert not (INTELLIGENCE_PKG / "_http.py").exists()


# --- Gate G — no recommendation leakage --------------------------------


def test_gate_g_eval_labels_claims_are_clean():
    for meta in GOLDEN["scenarios"].values():
        for script in meta["scripts"]:
            hits = screen_texts(script["label"], script.get("claim", ""))
            assert hits == [], f"recommendation leakage in {meta['file']}: {hits}"


# --- Gate H — cache semantics ------------------------------------------


def test_gate_h_cache_only_stores_success():
    sc = cache_mod.SemanticCache()
    sc.put("k1", ModelResponse(task="t", status=ModelStatus.SUCCESS, payload={"a": 1}))
    sc.put("k2", ModelResponse(task="t", status=ModelStatus.UNAVAILABLE, error="x"))
    assert sc.get("k1") is not None
    assert sc.get("k2") is None
    key = cache_mod.build_cache_key(
        task="t", prompt_version="v1", model_id="m",
        evidence_ids=["b", "a"], research_context={"z": 1, "a": 2},
    )
    assert key == cache_mod.build_cache_key(
        task="t", prompt_version="v1", model_id="m",
        evidence_ids=["a", "b"], research_context={"a": 2, "z": 1},
    )


# --- Gate I — stop boundary --------------------------------------------


def test_gate_i_result_carries_no_insight_or_recommendation():
    import dataclasses

    from sourceglint.intelligence.dtos import IntelligencePipelineResult

    allowed = {"signals", "clusters", "diagnostics", "warnings", "model_status"}
    assert set(dataclasses.asdict(IntelligencePipelineResult())) == allowed
    assert set(signals_mod.SIGNAL_SCHEMA_KEYS) == {
        "signal_id", "topic", "evidence_ids", "representative_evidence_ids",
        "source_diversity", "volume", "recency", "signal_type", "novelty",
        "score", "confidence", "supporting_evidence_ids", "counter_evidence_ids", "contradiction_assessed",
    }


# --- Gate J — capability honesty (PRD §44) -----------------------------


def test_gate_j_config_never_out_claims_code():
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    github = next(s for s in registry if s["name"] == "github")
    assert github["capabilities"] == ["search", "comments"]
    from sourceglint.connectors._deep import issue_results
    assert callable(issue_results)  # Discussion capability has an implementation.


# --- Gate K — traceability ---------------------------------------------


def test_gate_k_every_signal_traces_to_input():
    for name in GOLDEN["scenarios"]:
        records, result = _run_scenario(name)
        ledger_ids = {r["evidence_id"] for r in records}
        for sig in result.signals:
            assert set(sig["evidence_ids"]) <= ledger_ids
            assert set(sig["representative_evidence_ids"]) <= set(sig["evidence_ids"])
            cluster_id = derive_cluster_id(sig["evidence_ids"])
            assert sig["signal_id"] == derive_signal_id(cluster_id)
