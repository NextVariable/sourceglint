"""Phase 6C integration test support — fixture loaders (mirrors 6A/6B)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

from sourceglint.brief.dtos import BriefContext, BriefInput
from sourceglint.ledger import EvidenceLedger

ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "phase6c"
MANIFEST = "phase6c_eval_manifest.json"

#: BriefContext accepted field names (ctx fixture may carry extras).
_CTX_FIELDS = {
    "query", "topic", "mode", "market", "languages", "time_window",
    "as_of", "entities", "decision_context",
}


def load_json(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(name: str) -> list[dict]:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def manifest() -> dict[str, Any]:
    return load_json(MANIFEST)


def scenario_meta(name: str) -> dict[str, Any]:
    m = manifest()["scenarios"][name]
    meta = load_json(m["file"])
    meta["_runs"] = int(m.get("runs", 50))
    return meta


def build_input(name: str) -> BriefInput:
    """Assemble a BriefInput for one scenario from its fixtures."""
    m = manifest()["scenarios"][name]
    meta = load_json(m["file"])

    ctx_raw = meta.get("ctx") or {}
    ctx = BriefContext(
        **{k: v for k, v in ctx_raw.items() if k in _CTX_FIELDS}
    )

    ledger: EvidenceLedger | None = None
    if m.get("evidence"):
        ledger = EvidenceLedger(":memory:")
        for rec in load_jsonl(m["evidence"]):
            ledger.add(dict(rec))

    return BriefInput(
        context=ctx,
        ledger=ledger,
        signals=tuple(meta.get("signals") or []),
        insights=tuple(meta.get("insights") or []),
        recommendations=tuple(meta.get("recommendations") or []),
        insight_diagnostics=meta.get("insight_diagnostics") or {},
        recommendation_diagnostics=meta.get("recommendation_diagnostics") or {},
        conflicts=tuple(meta.get("conflicts") or []),
        coverage=meta.get("coverage"),
    )


def golden_markdown_file(name: str) -> str:
    m = manifest()["scenarios"][name]
    fname = m["golden_markdown"]
    return str(FIXTURE_DIR / fname)
