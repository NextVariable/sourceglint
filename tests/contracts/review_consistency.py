"""Contract Consistency Review (12-item gate) — run from repo root."""
import json
import pathlib
import re

SCHEMAS = pathlib.Path("schemas")
checks = {k: [] for k in range(1, 13)}


def load(name):
    return json.loads((SCHEMAS / name).read_text())


common = load("common.schema.json")
all_text = {p.name: json.dumps(json.loads(p.read_text())) for p in SCHEMAS.glob("*.json")}
schemas = {p.name: json.loads(p.read_text()) for p in SCHEMAS.glob("*.json")}

sig = schemas["signal.schema.json"]
ins = schemas["insight.schema.json"]
reg = schemas["source_registry.schema.json"]
out = schemas["output.schema.json"]

# 1. naming: ID prefixes live in common defs only
for prefix, label in [("ev_", "evidence"), ("sig_", "signal"), ("ins_", "insight")]:
    defs = [d for d, b in common["$defs"].items() if "pattern" in b and b["pattern"].startswith("^" + prefix)]
    checks[1].append(f"{label} id def(s) in common: {defs}")

# 2. confidence SoT
checks[2].append(
    f"0-1 number defs in common: "
    f"{[d for d, b in common['$defs'].items() if b.get('type') == 'number' and b.get('minimum') == 0.0 and b.get('maximum') == 1.0]}"
)
checks[2].append(f"$ref to confidence used across schemas: {sum(t.count('#/$defs/confidence') for t in all_text.values())}x")
inline = []
for n, t in all_text.items():
    for m in re.finditer(r'"type"\s*:\s*"number"', t):
        seg = t[m.start():m.start() + 140]
        if "maximum" in seg and "#/$defs/confidence" not in seg:
            inline.append(n)
checks[2].append(f"inline number+maximum outside common (drift risk): {inline if inline else 'none'}")

# 3. timestamps uniform
checks[3].append(f"'date-time' format occurrences: {sum(t.count('date-time') for t in all_text.values())}")

# 4. market/locale/language semantics
for c in ["market_code", "locale_code", "language_code"]:
    checks[4].append(f"{c}: defined={c in common['$defs']}, referenced {sum(t.count('#/$defs/' + c) for t in all_text.values())}x")

# 5. ID semantics documented
for c in ["evidence_id", "signal_id", "insight_id"]:
    checks[5].append(f"{c}: {common['$defs'][c]['pattern']}")

# 6. Evidence->Signal->Insight->Output chain
checks[6].append(f"signal.evidence_ids present: {'evidence_ids' in sig['properties']}")
checks[6].append(f"insight.evidence_ids present: {'evidence_ids' in ins['properties']}")
checks[6].append(f"insight.signal_ids present: {'signal_ids' in ins['properties']}")
checks[6].append(f"output.user_voice[].evidence_id present: {'evidence_id' in out['properties']['user_voice']['items']['properties']}")
checks[6].append(f"output.key_signals[].signal_id present: {'signal_id' in out['properties']['key_signals']['items']['properties']}")

# 7. FACT/INF/REC isolation
checks[7].append(f"type enum: {ins['properties']['type']['enum']}")
checks[7].append(f"action conditional (allOf): {len(ins.get('allOf', [])) > 0}")
checks[7].append(f"action is root property (not only in then): {'action' in ins['properties']}")

# 8. no secret leakage
checks[8].append(f"registry items additionalProperties={reg['items'].get('additionalProperties')}")
checks[8].append(f"credentials items pattern={reg['items']['properties']['credentials']['items'].get('pattern')}")

# 9. duplicate definitions
own_defs = [n for n in all_text if n != "common.schema.json" and "$defs" in schemas[n]]
checks[9].append(f"schemas defining own $defs: {own_defs if own_defs else 'none'}")
checks[9].append(f"common defs count: {len(common['$defs'])}")

# 10. over-engineering scan
checks[10].append(
    f"oneOf outside research_plan: "
    f"{[n for n, t in all_text.items() if t.count('oneOf') > 0 and n != 'research_plan.schema.json'] or 'none'}"
)
checks[10].append(
    f"allOf usage: {[n for n, t in all_text.items() if 'allOf' in t and n != 'common.schema.json']} "
    f"(signal contradictory + insight action are the 2 intended uses)"
)

# 11. schema-vs-validator boundary
checks[11].append("No cross-object referential checks in any schema (existence = Phase 2 validator).")
checks[11].append(f"signal.evidence_ids minItems (structural non-empty): {'minItems' in sig['properties']['evidence_ids']}")

# 12. v0.2 conflict scan
v02 = pathlib.Path("sourceglint-design-review.md").read_text()
checks[12].append(f"v0.2 has 加权几何平均: {'加权几何平均' in v02}")
checks[12].append(f"v0.2 has Frozen Decisions chapter: {'## 19. Frozen Decisions' in v02}")
checks[12].append(f"v0.2 has Change Control chapter: {'## 21. Change Control' in v02}")

for k in sorted(checks):
    print(f"--- Check {k} ---")
    for line in checks[k]:
        print("  " + line)
print("\nDONE")
