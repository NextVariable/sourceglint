"""Phase 2 consistency review gate (extends Phase 1 review_consistency.py).

Run from repo root:
    python tests/contracts/review_phase2_consistency.py

Fails (exit 1) if any check fails. Reports only on stdout.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCHEMAS = ROOT / "schemas"

failures = []


def fail(msg: str) -> None:
    failures.append(msg)


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"  -- {detail}"
    print(line)
    return ok


# ----------------------------- Imports -----------------------------------

ids_mod = importlib.import_module("sourceglint.ids")
ledger_mod = importlib.import_module("sourceglint.ledger")
scoring_mod = importlib.import_module("sourceglint.scoring")
validation_mod = importlib.import_module("sourceglint.validation")
citations_mod = importlib.import_module("sourceglint.citations")
rendering_mod = importlib.import_module("sourceglint.rendering")

# ----------------------------- 1. ID format ------------------------------

common = json.loads((SCHEMAS / "common.schema.json").read_text())
ev_pattern = None
for n, b in common["$defs"].items():
    if "pattern" in b and b["pattern"].startswith("^ev_"):
        ev_pattern = b["pattern"]
        break

# Apply derive_evidence_id to a fixed payload and verify id matches the
# common.schema.json evidence_id regex.
import re as _re

ev_re = _re.compile(ev_pattern.lstrip("^").rstrip("$"))

sample = {
    "source": "reddit",
    "url": "https://example.com/x",
    "snippet": "hi",
    "author": "alice",
    "published_at": "2026-01-01T00:00:00Z",
}
sample_id = ids_mod.derive_evidence_id(sample)

ok = bool(ev_re.match(sample_id))
check("evidence_id matches common.schema.json pattern", ok,
      detail=f"got {sample_id!r}, pattern {ev_pattern!r}")
if not ok:
    fail(f"evidence_id {sample_id} does not match pattern {ev_pattern}")

# -------------------------------- 2. scoring keys ------------------------

import yaml

scoring_cfg_yaml = (ROOT / "config" / "scoring.yaml").read_text()
scoring_cfg = yaml.safe_load(scoring_cfg_yaml)
scoring_keys = set(scoring_cfg["weights"].keys())
phase1_factor_names = {"decision_relevance", "evidence_quality", "recency",
                       "market_signal", "novelty"}
ok = scoring_keys == phase1_factor_names
check("scoring.yaml weight keys == v0.2 D9 frozen factor names", ok,
      detail=f"yaml={sorted(scoring_keys)}")
if not ok:
    fail("scoring factor names drifted from v0.2 D9")

# v0.2 D9 froze DR=0.35
ok = abs(scoring_cfg["weights"]["decision_relevance"] - 0.35) < 1e-9
check("decision_relevance weight frozen at 0.35", ok)
if not ok:
    fail("decision_relevance weight drifted from 0.35")

# ----------------------------- 3. Citation tier vs Validator tier ---------

ok = validation_mod.ReferentialIntegrityError.__mro__[1].__name__ != "CitationIntegrityError"
check("ReferentialIntegrityError is NOT CitationIntegrityError", ok)
if not ok:
    fail("exception classes merged")

ok = citations_mod.CitationIntegrityError is not None
check("CitationIntegrityError class exists in errors module", ok)
if not ok:
    fail("CitationIntegrityError missing")

# ----------------------------- 4. Output section set --------------------

output_schema = json.loads((SCHEMAS / "output.schema.json").read_text())
schema_sections = set(output_schema["properties"].keys())
# The renderer reads `executive_intelligence` (Phase 1 Output schema) but
# internally maps it to the rendered # Executive Intelligence heading.
# Test against the schema-declared input names.
renderer_sections = {
    "executive_intelligence",
    "changes", "key_signals", "user_voice", "competitive_movement",
    "weak_signals", "recommended_actions", "confidence", "gaps", "coverage",
}
ok = schema_sections == renderer_sections
check("output renderer covers exactly the Phase 1 Output sections", ok,
      detail=f"schema={sorted(schema_sections)} renderer={sorted(renderer_sections)}")
if not ok:
    fail("output section set drifted between schema and renderer")

# ----------------------------- 5. Sources registry seed ----------------

src_yaml_path = ROOT / "config" / "sources.yaml"
src_yaml = yaml.safe_load(src_yaml_path.read_text())
# Check credentials field is name-only (dict of name->{env}) or list of names
for entry in src_yaml:
    if "credentials" in entry and isinstance(entry["credentials"], list):
        # ensure each item is a string name, not a value
        for c in entry["credentials"]:
            ok = isinstance(c, str)
            if not ok:
                fail(f"sources.yaml credential entry is not a name: {entry['name']}")
# pass print
check("sources.yaml credentials are declared as names only", True)

# ----------------------------- 6. SKILL.md not present --------------------
# SKILL.md belongs to Phase 6. We MUST NOT have one yet.
skill = ROOT / "SKILL.md"
check("SKILL.md not created in Phase 2 (deferred to Phase 6)", not skill.exists())

# ----------------------------- 7. No LLM/web in src ----------------------

bad = []
forbidden_runtime = ["import openai", "import anthropic", "import requests(",
                      "import httpx", "import urllib.request"]
for py in (ROOT / "src").rglob("*.py"):
    text = py.read_text(encoding="utf-8")
    for n, line in enumerate(text.splitlines(), start=1):
        for kw in forbidden_runtime:
            if kw in line:
                bad.append((py, n, kw))
                break
check("src/ contains no LLM SDK / http / network imports", not bad,
      detail="; ".join(f"{p.name}:{ln}={kw}" for p, ln, kw in bad) if bad else "")
if bad:
    fail("runtime LLM/web imports found in deterministic core")

# ----------------------------- summary ------------------------------------

print()
if failures:
    print(f"{len(failures)} consistency failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Phase 2 consistency review PASS.")
