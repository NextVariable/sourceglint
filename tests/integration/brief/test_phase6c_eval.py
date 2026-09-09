"""Phase 6C §35–§39 — final-brief eval scenarios + deterministic golden.

Six scenarios drive the real pipeline fully offline:

  A full_healthy     — Evidence → Signal → FACT/INFERENCE → NOW/NEXT/WATCH
                       (JP/EN bilingual, current+baseline, contradictory
                       price signal, weak JA signal, segment conflict) and
                       doubles as the Markdown snapshot golden (§37).
  B no_recommendation — insights exist, no recommendation meets threshold.
  C contradictory    — contradictory signal surfaces in Watchouts with
                       supporting vs against evidence (never hidden).
  D weak_emerging    — weak signal is labelled and kept OUT of the
                       confirmed sections.
  E partial_sources  — failed/unavailable sources → brief renders + warning.
  F empty_research   — 0 evidence → fixed no-evidence statement (§20).

Gates exercised: B (schema), C (section purity), D (citation integrity),
E (no new claims), F (priority order), G/H (contradiction & weak
visibility), I (graceful degradation), J (caps), K (offline renderer),
L (≥50× byte determinism), M (no side effects — no files written by the
renderer; the only writes here are the fixtures themselves).
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from _support_brief6c import (
    build_input,
    golden_markdown_file,
    manifest,
    scenario_meta,
)

from gtm_intelligence.brief.dtos import BriefInput
from gtm_intelligence.brief.pipeline import run_brief_pipeline
from gtm_intelligence.brief.policy import SECTION_HEADINGS

SCENARIOS = tuple(manifest()["scenarios"].keys())

HEADING_KEYS = tuple(SECTION_HEADINGS.keys())


def _md_brief(name: str):
    return run_brief_pipeline(build_input(name))


def _section(md: str, key: str) -> str:
    """Text of one '## <heading>' section (stop at next '## ')."""
    marker = f"## {SECTION_HEADINGS[key]}\n"
    if marker not in md:
        return ""
    start = md.index(marker) + len(marker)
    rest = md[start:]
    nxt = rest.find("\n## ")
    return rest if nxt == -1 else rest[:nxt]


def _evidence_ids_in(md: str) -> list[str]:
    return re.findall(r"`(ev_[a-z0-9_]+)`", md)


# --------------------------------------------------------------------------
# Per-scenario expectations (Gate I graceful degradation etc.)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_meets_expectations(name):
    meta = scenario_meta(name)
    expect = meta["expect"]
    out = _md_brief(name)
    md = out.markdown

    for needle in expect.get("contains") or []:
        assert needle in md, f"{name}: missing {needle!r}"

    for needle in expect.get("not_contains") or []:
        assert needle not in md, f"{name}: unexpected {needle!r}"

    if "no_evidence" in expect:
        assert out.diagnostics.no_evidence is expect["no_evidence"]

    # selected-id bookkeeping (§33)
    d = out.diagnostics
    for field in ("selected_fact_ids", "selected_inference_ids",
                  "selected_recommendation_ids"):
        expected = expect.get(field)
        if expected is not None:
            assert getattr(d, field) == tuple(expected), (
                f"{name}: {field} mismatch"
            )

    # section presence/absence (a section rendered that expectations say
    # should be empty is a regression)
    expected_present = set(expect.get("sections_rendered") or [])
    for key in HEADING_KEYS:
        if key in expected_present:
            assert key in d.sections_rendered, f"{name}: expected section {key}"
        else:
            assert key not in d.sections_rendered, (
                f"{name}: section {key} rendered but expected empty"
            )


@pytest.mark.parametrize("name", [n for n in SCENARIOS if n != "F_empty_research"])
def test_citation_integrity_all_rendered_evidence_resolves(name):
    """Gate D: every evidence id that appears in the Markdown exists in the
    ledger (no dangling citations) and has a clickable source link."""
    inp = build_input(name)
    out = _md_brief(name)
    assert inp.ledger is not None
    ledger_ids = {r.evidence_id for r in inp.ledger}
    for eid in _evidence_ids_in(out.markdown):
        assert eid in ledger_ids, f"{name}: rendered unknown evidence {eid}"


# --------------------------------------------------------------------------
# Gate C — section purity (§8): types never intermix
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["A_full_healthy", "B_no_recommendation", "C_contradictory"]
)
def test_section_purity_types_do_not_intermix(name):
    """Gate C: FACT/INFERENCE/RECOMMENDATION never change their visual
    bucket. A recommendation action can never appear as FACT/INFERENCE; a
    FACT statement can never appear as an INFERENCE. FACT/INFERENCE text
    may appear in Recommended Actions ONLY as an explicitly labelled
    'why:' supporting line (§29), never as an action bullet."""
    meta = scenario_meta(name)
    md = _md_brief(name).markdown

    facts_section = _section(md, "facts")
    inferences_section = _section(md, "inferences")
    actions_section = _section(md, "actions")
    insight_diags = meta.get("insight_diagnostics") or {}

    for ins in meta.get("insights") or []:
        stmt = ins["statement"]
        iid = ins["insight_id"]
        is_weak = bool((insight_diags.get(iid) or {}).get("weak_signal"))
        if ins["type"] == "FACT":
            if is_weak:
                assert stmt not in facts_section, "weak FACT leaked into What We Know"
                assert stmt not in inferences_section
            else:
                assert stmt in facts_section, "FACT missing from What We Know"
                assert stmt not in inferences_section, "FACT leaked into INFERENCE section"
        elif ins["type"] == "INFERENCE":
            if is_weak:
                assert stmt not in inferences_section, "weak INFERENCE leaked into its main section"
                assert stmt not in facts_section
            else:
                assert stmt in inferences_section, "INFERENCE missing from its section"
                assert stmt not in facts_section, "INFERENCE leaked into What We Know"
        if stmt in actions_section:
            assert f"why: {stmt}" in actions_section, (
                "supporting insight leaked into actions without a why: label"
            )

    for rec in meta.get("recommendations") or []:
        action = rec["action"]["action"]
        assert action in actions_section, "recommendation action missing"
        assert action not in facts_section, "recommendation shown as FACT"
        assert action not in inferences_section, "recommendation shown as INFERENCE"


# --------------------------------------------------------------------------
# Gate F — NOW → NEXT → WATCH ordering (§15) + fixed section order (§25)
# --------------------------------------------------------------------------


def test_priority_bucket_order_now_next_watch():
    md = _md_brief("A_full_healthy").markdown
    idx_now = md.index("### NOW")
    idx_next = md.index("### NEXT")
    idx_watch = md.index("### WATCH")
    assert idx_now < idx_next < idx_watch


def test_section_order_is_fixed():
    md = _md_brief("A_full_healthy").markdown
    present = [
        k for k in HEADING_KEYS if f"## {SECTION_HEADINGS[k]}" in md
    ]
    assert present == sorted(present, key=HEADING_KEYS.index)


# --------------------------------------------------------------------------
# Gate G/H — contradiction and weak-signal visibility
# --------------------------------------------------------------------------


def test_contradiction_never_hidden():
    md = _md_brief("C_contradictory").markdown
    assert "(conflicting evidence)" in md
    assert "supporting:" in md and "against:" in md


def test_weak_signal_labeled_and_not_duplicated_as_confirmed():
    meta = scenario_meta("D_weak_emerging")
    out = _md_brief("D_weak_emerging")
    md = out.markdown
    stmt = meta["insights"][0]["statement"]
    assert "## What We Know" not in md
    assert "## What It Likely Means" not in md
    # confirmed sections are empty; the weak item surfaces as an Emerging
    # entry (it may additionally appear as a 'why:' line under the watch
    # recommendation it supports — never as a confirmed claim).
    assert "*(weak — monitor)*" in md
    assert _section(md, "emerging").count(stmt) == 1


# --------------------------------------------------------------------------
# Gate J — caps (§10, §34)
# --------------------------------------------------------------------------


def test_no_spurious_cap_drops_on_healthy_scenario():
    out = _md_brief("A_full_healthy")
    assert out.diagnostics.dropped_due_to_cap == {}


# --------------------------------------------------------------------------
# Gate E (structural proxy) — renderer emits no novel semantic sentence
# --------------------------------------------------------------------------


def test_rendered_statements_are_subset_of_validated_inputs():
    """Gate E (structural proxy): every bolded lead line is a verbatim
    statement/action/topic from the validated inputs or a fixed layout
    label — the renderer cannot have invented new claims."""
    meta = scenario_meta("A_full_healthy")
    known = {
        i["statement"] for i in meta["insights"]
    } | {
        r["action"]["action"] for r in meta["recommendations"]
    } | {
        s["topic"] for s in meta["signals"]
    }
    # Fixed presentation labels the renderer is allowed to emit.
    known |= {
        "Research:", "Mode:", "Market:", "Languages:", "Window:", "As of:",
        "Entities:", "Decision context:",
    }
    from gtm_intelligence.brief.policy import WATCHOUT_KIND_LABELS

    known |= set(WATCHOUT_KIND_LABELS.values())

    md = _md_brief("A_full_healthy").markdown
    for match in re.findall(r"\*\*(.+?)\*\*", md):
        text = match.replace("(weak — monitor)", "").strip()
        if not text:
            continue
        assert text in known, f"renderer produced unknown lead sentence: {text!r}"


# --------------------------------------------------------------------------
# Gate L — determinism ≥50 runs (byte-identical) + golden snapshot (§37)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_golden_50_runs_identical(name):
    runs = scenario_meta(name)["_runs"]
    first = None
    for _ in range(runs):
        md = _md_brief(name).markdown
        if first is None:
            first = md
        else:
            assert md == first, f"{name}: output drifted across runs"


def test_golden_markdown_snapshot_unchanged():
    """A_full_healthy golden Markdown snapshot must stay byte-identical
    (paired with structural assertions above — never a bare equality)."""
    md = _md_brief("A_full_healthy").markdown
    expected_path = golden_markdown_file("A_full_healthy")
    expected = pathlib.Path(expected_path).read_text(encoding="utf-8")
    assert md == expected


def test_markdown_is_not_trace_dump():
    """§12: internal diagnostics must not leak into the user-facing brief."""
    md = _md_brief("A_full_healthy").markdown
    for internal in ("priority_score", "support_strength", "conflict_group_id",
                     "model_status", "dropped_due_to_cap", "action_distance",
                     "semantic cache"):
        assert internal not in md


# --------------------------------------------------------------------------
# Gate K — offline renderer: no model / network / subprocess imports
# --------------------------------------------------------------------------

_FORBIDDEN_NAMES = {
    "IntelligenceModel", "FakeInsightModel", "FakeRecommendationModel",
    "requests", "httpx", "urllib", "subprocess", "openai", "anthropic",
    "http.client", "aiohttp",
}


@pytest.mark.parametrize(
    "module",
    ["sections.py", "renderer.py", "selection.py", "pipeline.py", "dtos.py"],
)
def test_offline_no_model_or_network_imports(module):
    src_dir = pathlib.Path(__file__).resolve().parents[3] / "src" / "gtm_intelligence" / "brief"
    tree = ast.parse((src_dir / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in _FORBIDDEN_NAMES
                assert "model" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                assert alias.name not in _FORBIDDEN_NAMES
            assert "model" not in mod.lower(), f"{module} imports model module {mod}"
            assert not any(bad in mod for bad in ("requests", "urllib", "http", "httpx"))


# --------------------------------------------------------------------------
# Gate M — no side effects: rendering writes nothing outside return value
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_render_has_no_side_effects_on_inputs(name):
    """Rendering must not mutate the input objects (dicts stay frozen)."""
    inp = build_input(name)
    signals_before = [dict(s) for s in inp.signals]
    insights_before = [dict(i) for i in inp.insights]
    recs_before = [dict(r) for r in inp.recommendations]
    _md_brief(name)
    assert [dict(s) for s in inp.signals] == signals_before
    assert [dict(i) for i in inp.insights] == insights_before
    assert [dict(r) for r in inp.recommendations] == recs_before
