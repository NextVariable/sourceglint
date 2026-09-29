"""Phase 6B §43–§45 — recommendation eval scenarios + deterministic golden.

Six scenarios exercise the edges the Recommendation layer must hold:

  A_now_watch_ordering     — strong FACT → `now` action; weak INFERENCE →
                            `watch`. Deterministic priority ordering.
  B_weak_cap               — weak single-source signal; model proposes a
                            strategic `change` → weak-signal cap (§18)
                            rejects it; only a bounded `experiment`
                            survives.
  C_contradiction_segments — opposed actions for different segments are
                            classified segment_specific (§29) — BOTH kept,
                            never auto-resolved (§30); conflict_group_id
                            wired to each side's diagnostics.
  D_semantic_dedup         — near-identical experiments collapse to one
                            deterministic winner (§28); the loser id is
                            recorded on the winner's diagnostics.
  E_specificity_guard      — model invents an ungrounded budget and an
                            ungrounded persona → both rejected (§33); only
                            the grounded candidate survives.
  F_jp_bilingual           — EN + JA evidence feed one cross-source chain;
                            Japanese wording in the recommendation grounds
                            in the cited JA evidence (bilingual golden).

Golden (§41-style): ≥20 consecutive runs produce identical ids, ordering,
diagnostics and byte-identical serialization for every scenario.

Gates exercised: B (schema, both validators), C (referential integrity),
D (confidence bounds), J (determinism), K (offline fakes only), plus the
6B behavior gates (weak cap, contradiction classification, dedup winner,
specificity guard, priority ordering, bilingual grounding).
"""
from __future__ import annotations

import json

import pytest

from _support_recs6b import (
    load_evidence,
    load_scenario,
    research_context,
    scenario_diagnostics,
    scenario_insights,
)

from sourceglint.insights.validation import (
    validate_insight_against_frozen_schema,
    validate_insight_schema,
)
from sourceglint.recommendations.model import (
    CONFLICT_SEGMENT,
    FakeConflictScript,
    FakeRecommendationModel,
    FakeRecommendationScript,
)
from sourceglint.recommendations.pipeline import run_recommendation_pipeline

#: All scenarios — order mirrors the golden file.
SCENARIOS: tuple[str, ...] = (
    "A_now_watch_ordering",
    "B_weak_cap",
    "C_contradiction_segments",
    "D_semantic_dedup",
    "E_specificity_guard",
    "F_jp_bilingual",
)

#: §41-style minimum consecutive identical runs.
GOLDEN_RUNS = 20

assert SCENARIOS, "scenario list must not be empty"


# --- scripted model per scenario (deterministic, offline) ------------------


def _scripts_for(name: str) -> tuple[list[FakeRecommendationScript], dict]:
    """(recommendation_scripts, extra model kwargs) for one scenario."""
    if name == "A_now_watch_ordering":
        s0 = FakeRecommendationScript(
            statement="Run a short experiment on the entry plan.",
            action="A/B the current entry offer for two weeks.",
            supporting_insight_ids=("ins_price_a_fact",),
            action_class="experiment",
            gtm_dimensions=("pricing",),
            confidence=0.6,
            action_anchor="entry_ab",
            expected_impact=0.9,
            urgency=0.8,
            feasibility=0.9,
            reversibility="high",
        )
        s1 = FakeRecommendationScript(
            statement="Monitor buyer attention around the entry price.",
            action="Track community mentions of the entry price over the coming cycle.",
            supporting_insight_ids=("ins_price_a_inf",),
            action_class="investigate",
            gtm_dimensions=("positioning",),
            confidence=0.6,
            action_anchor="attention_monitor",
            expected_impact=0.1,
            urgency=0.1,
            feasibility=0.5,
            reversibility="medium",
        )
        return [s0, s1], {}

    if name == "B_weak_cap":
        s_change = FakeRecommendationScript(
            statement="Reposition the product around the entry offer.",
            action="Change the product and go-to-market positioning to lead with the entry offer.",
            supporting_insight_ids=("ins_price_b_fact",),
            action_class="change",
            gtm_dimensions=("positioning", "market"),
            confidence=0.5,
            action_anchor="reposition_entry",
        )
        s_exp = FakeRecommendationScript(
            statement="Test whether the entry offer resonates with buyers.",
            action="Run a two-week entry-offer experiment on the current plan.",
            supporting_insight_ids=("ins_price_b_fact",),
            action_class="experiment",
            gtm_dimensions=("pricing",),
            confidence=0.6,
            action_anchor="entry_test",
        )
        return [s_change, s_exp], {}

    if name == "C_contradiction_segments":
        s_std = FakeRecommendationScript(
            statement="Validate standard-tier price tolerance.",
            action="Probe standard-tier willingness to pay with a short survey.",
            supporting_insight_ids=("ins_price_c_std",),
            action_class="validate",
            gtm_dimensions=("pricing", "icp"),
            confidence=0.55,
            action_anchor="std_wtp",
        )
        s_pre = FakeRecommendationScript(
            statement="Validate premium-tier price tolerance.",
            action="Probe premium-tier willingness to pay with a short survey.",
            supporting_insight_ids=("ins_price_c_pre",),
            action_class="validate",
            gtm_dimensions=("pricing", "icp"),
            confidence=0.55,
            action_anchor="pre_wtp",
        )
        return [s_std, s_pre], {
            "conflict_scripts": [FakeConflictScript(
                (0, 1), kind=CONFLICT_SEGMENT,
                rationale="opposed price signals apply to different segments",
            )],
        }

    if name == "D_semantic_dedup":
        s_long = FakeRecommendationScript(
            statement="Run an entry-offer experiment.",
            action="Run a two-week A/B test of an entry-level plan at the current entry price.",
            supporting_insight_ids=("ins_price_d_fact",),
            action_class="experiment",
            gtm_dimensions=("pricing",),
            confidence=0.6,
            action_anchor="entry_a",
        )
        s_short = FakeRecommendationScript(
            statement="A/B the entry offer.",
            action="A/B the current entry offer.",
            supporting_insight_ids=("ins_price_d_fact",),
            action_class="experiment",
            gtm_dimensions=("pricing",),
            confidence=0.6,
            action_anchor="entry_b",
        )
        return [s_long, s_short], {"dedup_groups": ((0, 1),)}

    if name == "E_specificity_guard":
        s_valid = FakeRecommendationScript(
            statement="Test a lower-friction entry offer.",
            action="Run a two-week A/B test of the current entry plan.",
            supporting_insight_ids=("ins_price_e_fact",),
            action_class="experiment",
            gtm_dimensions=("pricing",),
            confidence=0.6,
            action_anchor="entry_test",
        )
        s_budget = FakeRecommendationScript(
            statement="Fund an influencer push.",
            action="Spend $50,000 on creator outreach this quarter.",
            supporting_insight_ids=("ins_price_e_fact",),
            action_class="experiment",
            gtm_dimensions=("channel", "creator"),
            confidence=0.6,
            action_anchor="creator_push",
        )
        s_persona = FakeRecommendationScript(
            statement="Target CFOs with a new enterprise tier.",
            action="Launch an enterprise tier aimed at CFO buyers.",
            supporting_insight_ids=("ins_price_e_fact",),
            action_class="change",
            gtm_dimensions=("icp",),
            confidence=0.6,
            action_anchor="cfo_tier",
        )
        return [s_valid, s_budget, s_persona], {}

    if name == "F_jp_bilingual":
        s_tr = FakeRecommendationScript(
            statement="会議ツールの日本語翻訳品質を検証する小規模な実験を実施する。",
            action="Run a two-week experiment measuring Japanese translation quality in the meeting tool.",
            supporting_insight_ids=("ins_trans_f_inf",),
            action_class="experiment",
            gtm_dimensions=("product", "localization"),
            confidence=0.6,
            action_anchor="ja_translation_quality",
        )
        return [s_tr], {}

    raise AssertionError(f"unknown scenario: {name}")


def _run(name: str):
    """Run the Phase 6B pipeline for one scenario."""
    meta = load_scenario(name)
    insights = scenario_insights(name)
    evidence = load_evidence(name)
    diags = scenario_diagnostics(name)
    scripts, extra = _scripts_for(name)
    model = FakeRecommendationModel(recommendation_scripts=scripts, **extra)
    result = run_recommendation_pipeline(
        insights,
        evidence,
        model,
        research_context=research_context(),
        insight_diagnostics=diags,
    )
    return meta, evidence, insights, diags, result, scripts


# --- Gate J: golden determinism (§41-style) --------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_20_runs_identical(name):
    meta = load_scenario(name)
    insights = scenario_insights(name)
    evidence = load_evidence(name)
    diags = scenario_diagnostics(name)
    scripts, extra = _scripts_for(name)

    def one_run() -> dict:
        model = FakeRecommendationModel(recommendation_scripts=scripts, **extra)
        return run_recommendation_pipeline(
            insights, evidence, model,
            research_context=research_context(),
            insight_diagnostics=diags,
        ).to_dict()

    first = one_run()
    for i in range(GOLDEN_RUNS):
        assert one_run() == first, f"{name}: run {i + 2} diverged from run 1"


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_serialization_is_byte_identical(name):
    meta = load_scenario(name)
    insights = scenario_insights(name)
    evidence = load_evidence(name)
    diags = scenario_diagnostics(name)
    scripts, extra = _scripts_for(name)

    def one_dump() -> str:
        model = FakeRecommendationModel(recommendation_scripts=scripts, **extra)
        payload = run_recommendation_pipeline(
            insights, evidence, model,
            research_context=research_context(),
            insight_diagnostics=diags,
        ).to_dict()
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)

    first = one_dump()
    for i in range(GOLDEN_RUNS):
        assert one_dump() == first, f"{name}: serialization diverged on run {i + 2}"


# --- Gate B: frozen schema on every Recommendation -------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_recommendations_pass_frozen_schema(name):
    """Every recommendation validates against insight.schema.json."""
    *_, result, _ = _run(name)
    for rec in result.recommendations:
        violations = validate_insight_schema(rec)
        assert violations == [], f"{name}: schema violations {violations}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_recommendations_pass_real_frozen_json_schema(name):
    """Authoritative jsonschema Draft 2020-12 validation."""
    *_, result, _ = _run(name)
    assert result.recommendations, f"{name}: no recommendations produced"
    for rec in result.recommendations:
        violations = validate_insight_against_frozen_schema(rec)
        assert violations == [], f"{name}: frozen schema violations {violations}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_recommendation_structure_contract(name):
    """Schema SoT: RECOMMENDATION carries action; priority enum frozen."""
    *_, result, _ = _run(name)
    for rec in result.recommendations:
        assert rec["type"] == "RECOMMENDATION"
        assert rec["insight_id"].startswith("ins_")
        assert set(rec) <= {
            "insight_id", "type", "statement", "confidence", "action", "rationale"
        }
        assert rec["action"]["action"]
        assert rec["action"]["priority"] in {"now", "next", "watch"}


# --- Gate C: referential integrity -----------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_traceability_chain_resolves(name):
    """Recommendation → Insight → Evidence → URL all resolve."""
    _, evidence, _, _, result, _ = _run(name)
    assert result.recommendations, f"{name}: no recommendations"
    assert len(result.recommendations) == len(result.diagnostics)
    for d in result.diagnostics:
        assert d.supporting_insight_ids, "rec must cite ≥1 insight"
        assert d.supporting_evidence_ids, "support chain must reach evidence"
        for eid in d.supporting_evidence_ids:
            assert eid in evidence, f"unknown evidence ref {eid}"
            assert evidence[eid].get("url"), f"evidence {eid} has no URL"


@pytest.mark.parametrize("name", SCENARIOS)
def test_confidence_within_bounds(name):
    """§26-style: confidence always in [0, 1] after the ceiling clamp."""
    *_, result, _ = _run(name)
    for rec in result.recommendations:
        assert 0.0 <= float(rec["confidence"]) <= 1.0


@pytest.mark.parametrize("name", SCENARIOS)
def test_offline_fake_models_only(name):
    """Gate K: the default eval never touches a real provider."""
    scripts, _ = _scripts_for(name)
    model = FakeRecommendationModel(recommendation_scripts=scripts)
    assert model.model_id.startswith("fake_")


# --- Gate D: statement quality ---------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_statements_are_non_empty_and_readable(name):
    *_, result, _ = _run(name)
    for rec in result.recommendations:
        stmt = rec["statement"]
        assert len(stmt.strip()) >= 10
        assert "ins_" not in stmt
        assert "sig_" not in stmt


# --- per-scenario behavior gates -------------------------------------------


def test_a_priority_ordering_now_then_watch():
    meta, _, _, _, result, scripts = _run("A_now_watch_ordering")
    s0, s1 = scripts
    assert [r["insight_id"] for r in result.recommendations] == [s0.rec_id(), s1.rec_id()]
    assert [d.priority_bucket for d in result.diagnostics] == ["now", "watch"]
    assert result.diagnostics[0].action_class == "experiment"
    assert result.diagnostics[1].action_class == "investigate"
    # lower-priority rec must not outrank the now action
    assert result.diagnostics[0].priority > result.diagnostics[1].priority


def test_b_weak_signal_cap_rejects_change():
    meta, _, _, _, result, scripts = _run("B_weak_cap")
    s_change, s_exp = scripts
    assert [r["insight_id"] for r in result.recommendations] == [s_exp.rec_id()]
    assert result.diagnostics[0].action_class == "experiment"
    assert result.diagnostics[0].weak_signal_present is True
    assert any("weak-signal policy" in w for w in result.warnings)
    # no stronger-than-experiment commitment survived
    assert all(d.action_class in {"observe", "investigate", "validate", "experiment"}
               for d in result.diagnostics)


def test_c_contradiction_kept_as_segment_specific():
    meta, _, _, _, result, scripts = _run("C_contradiction_segments")
    s_std, s_pre = scripts
    assert len(result.recommendations) == 2  # never auto-resolved
    assert len(result.conflicts) == 1
    conf = result.conflicts[0]
    assert conf.kind == CONFLICT_SEGMENT
    assert set(conf.rec_ids) == {s_std.rec_id(), s_pre.rec_id()}
    by_id = {d.insight_id: d for d in result.diagnostics}
    assert by_id[s_std.rec_id()].conflict_group_id == conf.group_id
    assert by_id[s_pre.rec_id()].conflict_group_id == conf.group_id
    assert by_id[s_std.rec_id()].contradiction_present is True


def test_d_semantic_dedup_keeps_deterministic_winner():
    meta, _, _, _, result, scripts = _run("D_semantic_dedup")
    s_long, s_short = scripts
    # §28 tie-break: equal priority/confidence → shorter action wins
    winner = min(scripts, key=lambda s: (len(s.action), s.rec_id()))
    loser = s_short if winner is s_long else s_long
    assert [r["insight_id"] for r in result.recommendations] == [winner.rec_id()]
    assert result.diagnostics[0].collapsed_duplicate_ids == (loser.rec_id(),)
    assert any("semantic duplicate group" in w for w in result.warnings)


def test_e_specificity_guard_rejects_ungrounded_specifics():
    meta, _, _, _, result, scripts = _run("E_specificity_guard")
    s_valid = scripts[0]
    assert [r["insight_id"] for r in result.recommendations] == [s_valid.rec_id()]
    warnings = " ".join(result.warnings)
    assert "unsupported money specificity" in warnings, warnings
    assert "unsupported persona" in warnings, warnings


def test_f_jp_bilingual_evidence_and_wording():
    meta, evidence, _, _, result, scripts = _run("F_jp_bilingual")
    s_tr = scripts[0]
    assert [r["insight_id"] for r in result.recommendations] == [s_tr.rec_id()]
    # the JA evidence reaches the support chain and is actually cited
    d = result.diagnostics[0]
    assert "ev_f2" in d.supporting_evidence_ids
    langs = {evidence[eid]["language"] for eid in d.supporting_evidence_ids}
    assert {"en", "ja"} <= langs
    # Japanese wording in the statement grounds in the cited JA snippet
    stmt = result.recommendations[0]["statement"]
    ja_snippet = evidence["ev_f2"]["snippet"]
    assert "翻訳品質" in stmt
    assert "会議ツール" in stmt
    assert "翻訳品質" in ja_snippet  # grounded, not invented
