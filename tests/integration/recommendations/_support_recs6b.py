"""Phase 6B integration test support — fixture loaders (mirrors 6A)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

from gtm_intelligence.intelligence.dtos import ResearchContext

ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    parts = name.split("/")
    path = FIXTURE_DIR.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(name: str) -> list[dict]:
    parts = name.split("/")
    path = FIXTURE_DIR.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


GOLDEN_META = "phase6b/phase6b_eval_golden.json"


def load_golden() -> dict[str, Any]:
    return load_json(GOLDEN_META)


def load_scenario(name: str) -> dict[str, Any]:
    """Golden meta for one Phase 6B scenario."""
    return load_golden()["scenarios"][name]


def load_evidence(name: str) -> dict[str, dict]:
    """Evidence records for a scenario keyed by evidence_id."""
    meta = load_scenario(name)
    records = load_jsonl(f"phase6b/{meta['file']}")
    return {r["evidence_id"]: r for r in records}


def scenario_insights(name: str) -> list[dict]:
    """The validated FACT/INFERENCE insight set (6A output) for a scenario."""
    return list(load_scenario(name)["insights"])


def scenario_diagnostics(name: str) -> dict[str, dict[str, bool]]:
    """{insight_id: {weak_signal/contradiction_preserved}} from golden meta."""
    meta = load_scenario(name)
    out: dict[str, dict[str, bool]] = {}
    for iid in meta.get("weak_signal_ids") or ():
        out[str(iid)] = {"weak_signal": True}
    for iid in meta.get("contradiction_ids") or ():
        d = out.setdefault(str(iid), {})
        d["contradiction_preserved"] = True
    return out


def research_context() -> ResearchContext:
    """Japan-market bilingual context (the golden domain)."""
    return ResearchContext(
        market="jp",
        languages=("ja", "en"),
        entities=("meeting-tool-vendor",),
        decision_context="entry-price strategy for the next cycle",
    )
