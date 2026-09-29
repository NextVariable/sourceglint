"""Phase 5 §31–§32, §39–§40 — eval scenarios + deterministic golden.

Four eval fixtures exercise the semantic edges the pipeline must hold:

  A cross_source        — three items (EN + JA) independently describe the
                          same development → ONE cross-source signal.
  B keyword_similar     — shared keyword ("AI launch") but DIFFERENT claims
                          (product launch vs user complaint) → must stay
                          separate (precision over recall, PRD §8).
  C voc_contradiction   — same topic, opposing voice-of-customer views →
                          contradictory signal with counter ids.
  D weak_emerging       — one low-volume novel item + a baseline-only
                          cluster → emerging + weak-candidate signal; the
                          baseline-only cluster is dropped.

Golden assertions (PRD §31–§32): for each scenario the pipeline output
must be byte-identical across 20 consecutive runs, and every emitted
signal must validate against the frozen signal.schema.json. The semantic
step is driven by FakeIntelligenceModel scripts defined in
phase5_eval_golden.json — no network, no live model (PRD §5, §40).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from _support import load_json, load_jsonl, load_schema, validate
from sourceglint.intelligence import pipeline
from sourceglint.intelligence.model import (
    FakeClusterScript,
    FakeIntelligenceModel,
)

GOLDEN = load_json("phase5/phase5_eval_golden.json")
GOLDEN_RUNS = 20


def _as_of(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _model_for(scenario: dict) -> FakeIntelligenceModel:
    scripts = []
    for s in scenario["scripts"]:
        kwargs = dict(s)
        scripts.append(FakeClusterScript(**kwargs))
    return FakeIntelligenceModel(scripts=scripts)


def _run(scenario_meta: dict):
    expect = scenario_meta["expect"]
    records = load_jsonl(scenario_meta["file"])
    result = pipeline.run_intelligence_pipeline(
        records,
        _model_for(scenario_meta),
        as_of=_as_of(scenario_meta["as_of"]),
    )
    return records, result


@pytest.mark.parametrize("name", list(GOLDEN["scenarios"].keys()))
def test_golden_runs_are_byte_identical_20x(name):
    meta = GOLDEN["scenarios"][name]
    records = load_jsonl(meta["file"])
    expect = meta["expect"]

    def one_run() -> dict:
        res = pipeline.run_intelligence_pipeline(
            records,
            _model_for(meta),
            as_of=_as_of(meta["as_of"]),
        )
        return res.to_dict()

    first = one_run()
    for _ in range(GOLDEN_RUNS):
        assert one_run() == first, f"scenario {name} is not deterministic"

    # every signal validates against the frozen schema
    result = pipeline.run_intelligence_pipeline(
        records, _model_for(meta), as_of=_as_of(meta["as_of"])
    )
    schema = load_schema("signal.schema.json")
    for sig in result.signals:
        validate(sig, schema)


@pytest.mark.parametrize("name", list(GOLDEN["scenarios"].keys()))
def test_golden_signal_types_and_membership(name):
    meta = GOLDEN["scenarios"][name]
    expect = meta["expect"]
    _, result = _run(meta)

    # signal_type sequence is score-ordered; compare as a multiset
    assert sorted(s["signal_type"] for s in result.signals) == sorted(
        expect["signal_types"]
    ), f"scenario {name}: unexpected signal_type set"
    if "evidence_ids" in expect:
        assert {frozenset(s["evidence_ids"]) for s in result.signals} == {
            frozenset(e) for e in expect["evidence_ids"]
        }
    if expect.get("min_source_diversity"):
        assert all(
            s["source_diversity"] >= expect["min_source_diversity"]
            for s in result.signals
        )
    if expect.get("counter_ids"):
        assert {frozenset(s["counter_evidence_ids"]) for s in result.signals} == {
            frozenset(c) for c in expect["counter_ids"]
        }
    if expect.get("volume"):
        assert sorted(s["volume"] for s in result.signals) == sorted(expect["volume"])


def test_golden_cross_source_carries_both_languages():
    meta = GOLDEN["scenarios"]["A_cross_source"]
    records, result = _run(meta)
    langs = {r["language"] for r in records}
    assert langs == {"en", "ja"}
    assert result.signals[0]["signal_type"] == "cross_source"


def test_golden_keyword_similar_stays_split():
    """Precision over recall: the shared 'AI launch' keyword must not merge
    a vendor launch with a user complaint (PRD §8)."""
    meta = GOLDEN["scenarios"]["B_keyword_similar"]
    _, result = _run(meta)
    assert len(result.signals) == 2
    topics = {s["topic"] for s in result.signals}
    assert "AI launch broke workspaces" in topics
    assert "AI agent platform launched" in topics


def test_golden_contradictory_requires_counter_evidence():
    meta = GOLDEN["scenarios"]["C_voc_contradiction"]
    _, result = _run(meta)
    sig = result.signals[0]
    assert sig["signal_type"] == "contradictory"
    assert sig["counter_evidence_ids"]  # schema: contradictory => counter non-empty
    # one signal only — the opposing views live in the SAME cluster
    assert len(result.signals) == 1


def test_golden_weak_emerging_and_baseline_drop():
    meta = GOLDEN["scenarios"]["D_weak_emerging"]
    _, result = _run(meta)
    assert len(result.signals) == 1
    sig = result.signals[0]
    assert sig["topic"] == "Prompt-cache billing emerges"
    assert sig["signal_type"] == "emerging"
    assert sig["volume"] == 1
    # baseline-only cluster ev_dbase must be dropped with a warning
    assert any("baseline" in w for w in result.warnings)
    # weak-candidate flag recorded in diagnostics
    assert len(result.diagnostics) == 1
    weak = result.diagnostics[0].weak_signal
    assert weak is not None
    assert weak.is_weak_candidate is True
