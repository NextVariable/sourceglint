"""Phase 6A §39–§42 — reasoning-quality eval scenarios + deterministic golden.

Five eval scenarios exercise the reasoning edges the pipeline must hold:

  A direct_fact         — first-party pricing change → FACT, no excessive
                          inference (§39-A).
  B cross_source        — multiple independent sources (EN + JA) →
                          cross-source FACT + INFERENCE (§39-B, §40).
  C contradictory_voc   — opposing voice-of-customer views → inference
                          preserves uncertainty, never flattens (§17, §39-C).
  D weak_emerging       — low volume + high novelty → preserved with
                          calibrated language + lower confidence (§18, §39-D).
  E recommendation_trap — evidence easily induces "should lower price" →
                          Phase 6A must NOT produce action advice (§28, §39-E).

Golden (§41): 20 consecutive runs produce identical output — insight IDs,
ordering, signal refs, evidence refs, schema output, diagnostics, and
byte-identical serialization.

Gates exercised here: B (schema), C (referential integrity), D (grounding),
E (inference boundary), F (contradiction), G (weak-signal calibration),
H (recommendation leakage), I (GTM implication boundary), J (determinism),
K (offline — FakeInsightModel only).
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from gtm_intelligence.insights.facts import _detect_phase6a_leakage
from gtm_intelligence.insights.gtm_implications import GTM_DIMENSIONS
from gtm_intelligence.insights.ids import derive_insight_id
from gtm_intelligence.insights.model import (
    FakeFactScript,
    FakeGTMImplicationScript,
    FakeInferenceScript,
    FakeInsightModel,
)
from gtm_intelligence.insights.pipeline import run_insight_pipeline
from gtm_intelligence.insights.validation import (
    validate_insight_against_frozen_schema,
    validate_insight_schema,
)

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _ROOT / "tests" / "fixtures"

SCENARIOS: tuple[str, ...] = (
    "A_direct_fact",
    "B_cross_source",
    "C_contradictory_voc",
    "D_weak_emerging",
    "E_recommendation_trap",
)

#: §41 — minimum consecutive identical runs for golden determinism.
GOLDEN_RUNS = 20

assert SCENARIOS, "scenario list must not be empty"


# --- fixture loaders --------------------------------------------------------


def _load_json(name: str) -> dict[str, Any]:
    path = _FIXTURE_DIR.joinpath(*name.split("/"))
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_jsonl(name: str) -> list[dict[str, Any]]:
    path = _FIXTURE_DIR.joinpath(*name.split("/"))
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _load_scenario(name: str) -> tuple[dict, list[dict], dict]:
    """Return (meta, evidence_records, evidence_by_id) for a scenario."""
    meta = _load_json("phase6a/phase6a_eval_golden.json")["scenarios"][name]
    records = _load_jsonl(f"phase6a/{meta['file']}")
    return meta, records, {r["evidence_id"]: r for r in records}


# --- scripted model per scenario (§40: deterministic, offline) --------------


def _model_for(name: str, signals: list[dict]) -> FakeInsightModel:
    """Build a FakeInsightModel whose scripts are scenario-appropriate.

    These scripts stand in for what a real model would return. They are
    deliberately written to satisfy the Phase 6A boundary: grounded,
    hedged where evidence is weak, and never prescriptive.
    """
    sig = signals[0]
    sig_id = sig["signal_id"]
    all_ev = tuple(sig["evidence_ids"])

    if name == "A_direct_fact":
        ev_ids = ("ev_a1",)  # first-party pricing page only
        fact_id = derive_insight_id(
            type="FACT", signal_ids=(sig_id,), evidence_ids=ev_ids
        )
        return FakeInsightModel(
            fact_scripts=[
                FakeFactScript(
                    signal_ids=(sig_id,),
                    statement=(
                        "The vendor's pricing page lists the Team plan at "
                        "$20 per user per month, up from $18 the previous month."
                    ),
                    evidence_ids=ev_ids,
                    confidence=0.9,
                    rationale="First-party pricing page plus two community confirmations",
                ),
            ],
            gtm_scripts=[
                FakeGTMImplicationScript(
                    insight_id=fact_id,
                    implications={
                        "pricing": "The official Team-plan price anchor moved upward in the current window"
                    },
                ),
            ],
        )

    if name == "B_cross_source":
        fact_id = derive_insight_id(
            type="FACT", signal_ids=(sig_id,), evidence_ids=all_ev
        )
        inf_id = derive_insight_id(
            type="INFERENCE", signal_ids=(sig_id,), evidence_ids=all_ev
        )
        return FakeInsightModel(
            fact_scripts=[
                FakeFactScript(
                    signal_ids=(sig_id,),
                    statement=(
                        "Three independent sources, including the vendor's own "
                        "Japanese blog post, report real-time translation latency "
                        "falling below one second."
                    ),
                    evidence_ids=all_ev,
                    confidence=0.85,
                    rationale="Official JA blog + EN Reddit + EN Hacker News",
                ),
            ],
            inference_scripts=[
                FakeInferenceScript(
                    fact_ids=(fact_id,),
                    signal_ids=(sig_id,),
                    statement=(
                        "Real-time multilingual quality may be becoming a more "
                        "visible competitive dimension in AI meeting tools."
                    ),
                    evidence_ids=all_ev,
                    confidence=0.6,
                    rationale="Multi-source, multi-language confirmation of the same improvement",
                    inference_distance=1,
                ),
            ],
            gtm_scripts=[
                FakeGTMImplicationScript(
                    insight_id=fact_id,
                    implications={
                        "product": "Translation latency improved across independent sources"
                    },
                ),
                FakeGTMImplicationScript(
                    insight_id=inf_id,
                    implications={
                        "competitor": "Translation speed is appearing as a differentiation axis"
                    },
                ),
            ],
        )

    if name == "C_contradictory_voc":
        fact_id = derive_insight_id(
            type="FACT", signal_ids=(sig_id,), evidence_ids=all_ev
        )
        inf_id = derive_insight_id(
            type="INFERENCE", signal_ids=(sig_id,), evidence_ids=all_ev
        )
        return FakeInsightModel(
            fact_scripts=[
                FakeFactScript(
                    signal_ids=(sig_id,),
                    statement=(
                        "One sampled user reports the new translation works well, "
                        "while another continues to report roughly three-second "
                        "delays on Japanese."
                    ),
                    evidence_ids=all_ev,
                    confidence=0.7,
                    rationale="Opposing reports inside the same signal cluster",
                ),
            ],
            inference_scripts=[
                FakeInferenceScript(
                    fact_ids=(fact_id,),
                    signal_ids=(sig_id,),
                    statement=(
                        "Translation experience appears uneven across users or "
                        "language contexts rather than uniformly improved."
                    ),
                    evidence_ids=all_ev,
                    confidence=0.5,
                    rationale="Contradictory evidence preserved, not flattened",
                    inference_distance=1,
                ),
            ],
            gtm_scripts=[
                FakeGTMImplicationScript(
                    insight_id=inf_id,
                    implications={
                        "pain_point": "Translation experience varies across sampled users"
                    },
                ),
            ],
        )

    if name == "D_weak_emerging":
        ev_ids = ("ev_d1",)  # single low-volume source
        fact_id = derive_insight_id(
            type="FACT", signal_ids=(sig_id,), evidence_ids=ev_ids
        )
        return FakeInsightModel(
            fact_scripts=[
                FakeFactScript(
                    signal_ids=(sig_id,),
                    statement=(
                        "A single sampled source reports a prompt-cache billing "
                        "model appearing on the API documentation."
                    ),
                    evidence_ids=ev_ids,
                    confidence=0.45,
                    rationale="One low-volume source, high novelty — emerging status",
                ),
            ],
            gtm_scripts=[
                FakeGTMImplicationScript(
                    insight_id=fact_id,
                    implications={
                        "pricing": "A cached-token billing form is beginning to appear"
                    },
                ),
            ],
        )

    if name == "E_recommendation_trap":
        fact_id = derive_insight_id(
            type="FACT", signal_ids=(sig_id,), evidence_ids=all_ev
        )
        return FakeInsightModel(
            fact_scripts=[
                FakeFactScript(
                    signal_ids=(sig_id,),
                    statement=(
                        "Two sampled community posts report the product is too "
                        "expensive and say they are considering free alternatives."
                    ),
                    evidence_ids=all_ev,
                    confidence=0.7,
                    rationale="Two community posts describing price sensitivity",
                ),
            ],
            gtm_scripts=[
                FakeGTMImplicationScript(
                    insight_id=fact_id,
                    implications={
                        "pricing": "Price complaints are appearing in sampled community discussion"
                    },
                ),
            ],
        )

    raise AssertionError(f"unknown scenario: {name}")


def _run(name: str):
    """Run the insight pipeline for one scenario."""
    meta, records, evidence = _load_scenario(name)
    signals = list(meta["signals"])
    model = _model_for(name, signals)
    result = run_insight_pipeline(
        signals,
        evidence,
        model,
        weak_signal_ids=set(meta.get("weak_signal_ids") or ()),
    )
    return meta, records, evidence, signals, result


# --- Gate J: golden determinism (§41) --------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_20_runs_identical(name):
    """§41: 20 runs → identical ids, ordering, refs, diagnostics."""
    meta, records, evidence = _load_scenario(name)
    signals = list(meta["signals"])
    model = _model_for(name, signals)

    def one_run() -> dict:
        return run_insight_pipeline(
            signals,
            evidence,
            model,
            weak_signal_ids=set(meta.get("weak_signal_ids") or ()),
        ).to_dict()

    first = one_run()
    for i in range(GOLDEN_RUNS):
        assert one_run() == first, f"{name}: run {i + 2} diverged from run 1"


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_serialization_is_byte_identical(name):
    """§41: JSON serialization is byte-identical across 20 runs."""
    meta, records, evidence = _load_scenario(name)
    signals = list(meta["signals"])
    model = _model_for(name, signals)

    def one_dump() -> str:
        payload = run_insight_pipeline(
            signals,
            evidence,
            model,
            weak_signal_ids=set(meta.get("weak_signal_ids") or ()),
        ).to_dict()
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)

    first = one_dump()
    for i in range(GOLDEN_RUNS):
        assert one_dump() == first, f"{name}: serialization diverged on run {i + 2}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_insight_ids_are_code_derived(name):
    """§21: every insight_id is reproducible from structural inputs."""
    _, _, _, _, result = _run(name)
    assert result.insights, f"{name}: expected at least one insight"
    for ins in result.insights:
        expected = derive_insight_id(
            type=ins["type"],
            signal_ids=tuple(ins["signal_ids"]),
            evidence_ids=tuple(ins["evidence_ids"]),
        )
        assert ins["insight_id"] == expected
        assert ins["insight_id"].startswith("ins_")


# --- Gate B: frozen insight schema (§4) ------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_insights_pass_frozen_schema(name):
    """Gate B: every insight validates against schemas/insight.schema.json."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        violations = validate_insight_schema(ins)
        assert violations == [], f"{name}: schema violations {violations}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_insights_pass_real_frozen_json_schema(name):
    """Gate B (authoritative): real jsonschema Draft 2020-12 validation."""
    _, _, _, _, result = _run(name)
    assert result.insights, f"{name}: no insights produced"
    for ins in result.insights:
        violations = validate_insight_against_frozen_schema(ins)
        assert violations == [], (
            f"{name}: frozen insight.schema.json violations {violations}"
        )


# --- Gate C: referential integrity (§3, §33) -------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_traceability_chain_resolves(name):
    """Gate C: Insight → Signal → Evidence → URL all resolve."""
    meta, records, evidence, signals, result = _run(name)
    signal_ids = {s["signal_id"] for s in signals}
    evidence_ids = set(evidence)

    for ins in result.insights:
        assert ins["signal_ids"], "insight must cite at least one signal"
        assert ins["evidence_ids"], "insight must cite at least one evidence"
        for sid in ins["signal_ids"]:
            assert sid in signal_ids, f"unknown signal ref {sid}"
        for eid in ins["evidence_ids"]:
            assert eid in evidence_ids, f"unknown evidence ref {eid}"
            # Evidence → URL must resolve (§33 citation integrity)
            assert evidence[eid].get("url"), f"evidence {eid} has no URL"


@pytest.mark.parametrize("name", SCENARIOS)
def test_evidence_ids_are_subset_of_cited_signals(name):
    """§34: an insight's evidence must belong to its cited signals."""
    _, _, _, signals, result = _run(name)
    signal_evidence = {
        s["signal_id"]: set(s["evidence_ids"]) for s in signals
    }
    for ins in result.insights:
        allowed: set[str] = set()
        for sid in ins["signal_ids"]:
            allowed |= signal_evidence.get(sid, set())
        for eid in ins["evidence_ids"]:
            assert eid in allowed, (
                f"{name}: evidence {eid} not owned by cited signals "
                f"{ins['signal_ids']}"
            )


# --- Gate D + E: grounding and inference boundary (§12, §23) ---------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_confidence_within_bounds(name):
    """§26: confidence is always in [0, 1]."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        assert 0.0 <= float(ins["confidence"]) <= 1.0


@pytest.mark.parametrize("name", SCENARIOS)
def test_statements_are_non_empty_and_readable(name):
    """§38: concise, specific, grounded — never 'Signal 1 indicates X'."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        stmt = ins["statement"]
        assert len(stmt.strip()) > 20
        assert "Signal " not in stmt
        assert "sig_" not in stmt


# --- Gate F: contradiction preservation (§17) ------------------------------


def test_contradictory_voc_preserves_uncertainty():
    """C: opposing VOC must NOT be flattened into a one-sided claim."""
    _, _, _, _, result = _run("C_contradictory_voc")
    inferences = [i for i in result.insights if i["type"] == "INFERENCE"]
    assert inferences, "expected at least one INFERENCE"

    stmt = inferences[0]["statement"].lower()
    assert any(w in stmt for w in ("appears", "may", "uneven", "varies", "suggests"))
    # A one-sided "improved" claim would be a contradiction violation
    assert "has improved" not in stmt

    # Diagnostics must flag the contradiction as preserved
    contradiction_diags = [d for d in result.diagnostics if d.contradiction_preserved]
    assert contradiction_diags, "contradiction not recorded in diagnostics"


def test_contradictory_scenario_has_counter_evidence_in_signal():
    """C: the signal fixture itself carries counter-evidence."""
    meta, _, _, _, _ = _run("C_contradictory_voc")
    sig = meta["signals"][0]
    assert sig["counter_evidence_ids"], "fixture must carry counter-evidence"
    assert sig["signal_type"] == "contradictory"


# --- Gate G: weak-signal calibration (§18) ---------------------------------


def test_weak_signal_preserved_with_calibration():
    """D: weak signal is preserved (not dropped) and stays low-confidence."""
    _, _, _, _, result = _run("D_weak_emerging")
    assert result.insights, "weak signal must not be dropped"

    weak_diags = [d for d in result.diagnostics if d.weak_signal]
    assert weak_diags, "weak_signal not recorded in diagnostics"

    for ins in result.insights:
        # Emerging signals must not be stated as settled market truth
        stmt = ins["statement"].lower()
        assert "the market is shifting" not in stmt
        assert "will dominate" not in stmt


# --- Gate H: recommendation leakage (§28) ----------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_zero_recommendation_leakage(name):
    """Gate H: 0 assistant-generated recommendations anywhere in output."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        assert ins["type"] != "RECOMMENDATION"
        assert "action" not in ins, "FACT/INFERENCE must not carry action"
        assert "recommended_actions" not in ins

        leaks = _detect_phase6a_leakage(ins["statement"])
        assert leaks == [], f"{name}: recommendation leakage {leaks}"


def test_recommendation_trap_produces_no_action_advice():
    """E: evidence induces 'should lower price' — output stays descriptive."""
    _, _, _, _, result = _run("E_recommendation_trap")
    assert result.insights

    for ins in result.insights:
        stmt = ins["statement"]
        assert _detect_phase6a_leakage(stmt) == []
        lowered = stmt.lower()
        for forbidden in (
            "we should",
            "you should lower",
            "recommend lowering",
            "lower the price",
            "cut the price",
            "we must",
        ):
            assert forbidden not in lowered, f"action advice leaked: {forbidden}"


# --- Gate I: GTM implication boundary (§5, §24, §25) -----------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_gtm_implications_descriptive_only(name):
    """Gate I: descriptive, sparsely populated, never prescriptive."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        gtm = ins.get("gtm_implications") or {}
        for dim, value in gtm.items():
            assert dim in GTM_DIMENSIONS, f"unknown GTM dimension {dim}"
            if value is None:
                continue
            assert _detect_phase6a_leakage(value) == [], (
                f"{name}: action language in gtm_implications[{dim}]: {value}"
            )


@pytest.mark.parametrize("name", SCENARIOS)
def test_gtm_implications_are_sparse(name):
    """§25: never fill all 16 dimensions to look structurally complete."""
    _, _, _, _, result = _run(name)
    for ins in result.insights:
        gtm = ins.get("gtm_implications") or {}
        assert len(gtm) < len(GTM_DIMENSIONS), (
            f"{name}: GTM implications filled all 16 dimensions"
        )


# --- §39-A: direct fact produces no excessive inference --------------------


def test_direct_fact_produces_fact_only():
    """A: first-party pricing change → FACT, not over-synthesized."""
    _, _, _, _, result = _run("A_direct_fact")
    types = sorted({i["type"] for i in result.insights})
    assert types == ["FACT"]
    assert all(float(i["confidence"]) >= 0.7 for i in result.insights)


# --- §39-B / §40: bilingual cross-source -----------------------------------


def test_cross_source_is_bilingual():
    """B: EN + JA evidence feed one cross-source signal → INFERENCE."""
    _, records, _, _, result = _run("B_cross_source")
    langs = {r["language"] for r in records}
    assert {"en", "ja"} <= langs

    inferences = [i for i in result.insights if i["type"] == "INFERENCE"]
    assert inferences, "cross-source scenario must yield an INFERENCE"
    # Inference confidence must not exceed its supporting fact (§26)
    facts = [i for i in result.insights if i["type"] == "FACT"]
    assert max(float(i["confidence"]) for i in inferences) <= max(
        float(f["confidence"]) for f in facts
    )


def test_japanese_evidence_is_cited():
    """§40: the JA evidence item is actually cited by an insight."""
    _, records, _, _, result = _run("B_cross_source")
    ja_ids = {r["evidence_id"] for r in records if r["language"] == "ja"}
    cited = {eid for ins in result.insights for eid in ins["evidence_ids"]}
    assert ja_ids & cited, "Japanese evidence was dropped from the citation chain"


# --- expected-type gate from golden metadata --------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_insight_types_match_golden_expectation(name):
    meta, _, _, _, result = _run(name)
    expected = sorted(meta["expect"]["insight_types"])
    actual = sorted({i["type"] for i in result.insights})
    assert actual == expected, f"{name}: expected {expected}, got {actual}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_diagnostics_cover_every_insight(name):
    """Every validated insight has a diagnostics record (§16, §35)."""
    _, _, _, _, result = _run(name)
    insight_ids = {i["insight_id"] for i in result.insights}
    diag_ids = {d.insight_id for d in result.diagnostics}
    assert insight_ids == diag_ids


@pytest.mark.parametrize("name", SCENARIOS)
def test_offline_no_real_model_calls(name):
    """Gate K: the default suite never touches a real provider."""
    meta, _, _, signals, _ = _run(name)
    model = _model_for(name, signals)
    assert model.model_id.startswith("fake_")
