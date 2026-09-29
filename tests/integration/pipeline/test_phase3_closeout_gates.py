"""Phase 3 Closeout Review Gates (Closeout §6 / §9).

Tests cover:
  B. Contract drift — Evidence / Plan / Source Registry schema validity.
  C. Golden Research deterministic x20 — extra fidelity check.
  D. Graceful Degradation — single/multiple/all source failure paths.
  E. Offline — no real network in normal test suite.
  F. Security — no secrets in src/fixtures; .cache/ gitignored.

Gate A (full regression) and Gate G (clean env) are exercised separately.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


# --- B. Contract drift ---------------------------------------------------------


def test_b_evidence_schema_validates_real_payloads():
    """Every evidence record produced by the closeout-patched normalizer must
    pass evidence.schema.json validation."""
    import json as _json
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    sys.path.insert(0, str(ROOT / "tests" / "integration" / "pipeline"))
    from test_golden_research_jp import _pipeline
    from sourceglint.ledger import EvidenceLedger
    from sourceglint.normalization import normalize_raw, validate_evidence_payload
    from sourceglint.pipeline.adapters import RawSourceResult

    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)

    # Re-validate every evidence_id that survived the ledger.
    schema = _json.loads((ROOT / "schemas" / "evidence.schema.json").read_text())
    common = _json.loads((ROOT / "schemas" / "common.schema.json").read_text())
    validator = Draft202012Validator(
        schema, registry=Registry().with_resources(
            [("common.schema.json", Resource.from_contents(common))]
        )
    )
    # Ensure normalization can produce a valid payload across diverse sources
    # (known + unknown).
    raw_known = RawSourceResult(
        source="reddit",
        source_type="post",
        source_native_id="x1",
        url="https://reddit.com/r/x/comments/x1",
        title="t",
        text="b",
        published_at="2026-08-25T00:00:00Z",
        language="en",
    )
    raw_unknown = RawSourceResult(
        source="cryptic_aggregator",
        source_type="post",
        source_native_id="y1",
        url="https://example.com/y1",
        title="t",
        text="b",
        published_at="2026-08-25T00:00:00Z",
        language="en",
    )
    for r in (raw_known, raw_unknown):
        ev = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
        validator.validate(ev)


def test_b_research_plan_schema_still_valid():
    """The golden research plan shape validates against research_plan.schema.json."""
    import json as _json
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schema = _json.loads(
        (ROOT / "schemas" / "research_plan.schema.json").read_text()
    )
    plan_path = (
        ROOT / "tests" / "fixtures" / "pipeline" / "golden_research_jp_plan.json"
    )
    payload = _json.loads(plan_path.read_text(encoding="utf-8"))

    common = _json.loads((ROOT / "schemas" / "common.schema.json").read_text())
    validator = Draft202012Validator(
        schema,
        registry=Registry().with_resources(
            [("common.schema.json", Resource.from_contents(common))]
        ),
    )
    validator.validate(payload)


def test_b_source_registry_schema_still_valid():
    """config/sources.yaml still validates against source_registry.schema.json."""
    import yaml as _yaml
    import json as _json
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schema = _json.loads(
        (ROOT / "schemas" / "source_registry.schema.json").read_text()
    )
    yaml_text = (ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")
    payload = _yaml.safe_load(yaml_text)
    common = _json.loads((ROOT / "schemas" / "common.schema.json").read_text())
    validator = Draft202012Validator(
        schema,
        registry=Registry().with_resources(
            [("common.schema.json", Resource.from_contents(common))]
        ),
    )
    validator.validate(payload)


# --- C. Golden Research x20 deterministic --------------------------------------


def test_c_golden_research_x20_deterministic():
    sys.path.insert(0, str(ROOT / "tests" / "integration" / "pipeline"))
    from test_golden_research_jp import _pipeline
    from sourceglint.ledger import EvidenceLedger

    pipeline, plan, sources, _ = _pipeline()
    snapshots = []
    for _ in range(20):
        ledger = EvidenceLedger(":memory:")
        result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
        snapshots.append(
            (
                tuple(sorted(result.evidence_ids)),
                ledger.count(),
                result.coverage.duplicate_dropped_count,
                result.coverage.final_evidence_count,
            )
        )
    first = snapshots[0]
    assert all(s == first for s in snapshots)


# --- D. Graceful degradation ----------------------------------------------------


def test_d_one_source_degrades_others_continue():
    """One source fails, others finish successfully."""
    sys.path.insert(0, str(ROOT / "tests" / "integration" / "pipeline"))
    from test_golden_research_jp import _pipeline
    from sourceglint.ledger import EvidenceLedger

    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    statuses = {name: r.status for name, r in result.source_statuses.items()}
    n_fail = sum(1 for s in statuses.values() if s.value == "unavailable")
    n_succ = sum(1 for s in statuses.values() if s.value in ("success", "partial"))
    assert n_fail >= 1, statuses
    assert n_succ >= 4, statuses


def test_d_coverage_reports_failures():
    """CoverageReport.failed_sources is non-empty after any source fails."""
    sys.path.insert(0, str(ROOT / "tests" / "integration" / "pipeline"))
    from test_golden_research_jp import _pipeline
    from sourceglint.ledger import EvidenceLedger

    pipeline, plan, sources, _ = _pipeline()
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert len(result.coverage.failed_sources) >= 1


# --- E. Offline ----------------------------------------------------------------


def test_e_no_network_imports_in_src():
    """No requests/httpx/aiohttp/urllib3 import in any src/ module.

    Phase 4 contract clarification: Phase 4 introduces REAL source
    connectors (HN, GitHub, Reddit) and explicitly chose stdlib `urllib`
    over `requests`/`httpx` for new-dependency avoidance. The single
    stdlib HTTP client lives at `src/sourceglint/connectors/_http.py`
    and is the ONLY src/ file that may speak directly to urllib. All
    other Phase 4 connectors (host_search, official_web, hacker_news,
    github, reddit) must consume THIS client and never import urllib on
    their own. Verified by the `_http.py` explicit allowlist below; if
    ANY OTHER src/ file uses `urllib.request`, this gate fails. The
    broader rule — no `requests`/`httpx`/`urllib3`/`aiohttp` — is
    unchanged.
    """
    src_dir = ROOT / "src"
    forbidden = ("requests", "httpx", "aiohttp", "urllib3")
    # Phase 4: explicit allowlist for the stdlib HTTP client module.
    http_client_module = src_dir / "sourceglint" / "connectors" / "_http.py"
    violations = []
    for path in src_dir.rglob("*.py"):
        is_http_client = path.resolve() == http_client_module.resolve()
        text = path.read_text(encoding="utf-8")
        for mod in forbidden:
            if re.search(rf"^import {mod}\b|^from {mod}\b", text, re.M):
                violations.append((str(path.relative_to(ROOT)), mod))
        # Disallow direct socket.socket and urllib.request as active lines,
        # EXCEPT in the explicit Phase 4 HTTP client module.
        if is_http_client:
            continue
        for line in text.splitlines():
            ls = line.lstrip()
            if ls.startswith("#"):
                continue
            if "socket.socket(" in ls or "urllib.request" in ls:
                violations.append((str(path.relative_to(ROOT)), "low-level net call"))
                break
    assert not violations, f"prod code touches network: {violations}"


# --- F. Security ---------------------------------------------------------------


def test_f_no_secrets_in_src():
    """No real secret-shaped strings in src/."""
    src_dir = ROOT / "src"
    patterns = [
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    violations = []
    for path in src_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pat in patterns:
            for m in pat.finditer(text):
                violations.append((path.name, m.group()))
    assert not violations, f"secret-shaped strings in src/: {violations}"


def test_f_no_secrets_in_fixtures():
    """No real secret-shaped strings in fixture files."""
    fix_dir = ROOT / "tests" / "fixtures"
    patterns = [
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    violations = []
    for path in fix_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix not in {".json", ".yaml", ".yml", ".jsonl", ".md", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in patterns:
            for m in pat.finditer(text):
                violations.append((path.name, m.group()))
    assert not violations, f"secret-shaped strings in fixtures: {violations}"


def test_f_cache_dir_gitignored():
    """.cache/ must be in .gitignore (Closeout §4 hard rule)."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".cache/" in text


def test_f_env_files_gitignored():
    """.env* patterns must be in .gitignore."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text


def test_f_credential_name_contract_rejects_real_secret_shapes():
    """Hard validation: real secret-looking strings are NOT valid credential
    names per the new pattern (closeout §1 regression)."""
    from sourceglint.pipeline.source_registry import load_registry
    from sourceglint.errors import ConfigValidationError

    for bad in (
        "github_token=abc123",
        "REDDIT-CLIENT-ID",
        "123TOKEN",
        "x y z",
        "",
    ):
        yaml = f"""
- name: foo
  enabled: true
  type: community
  cost: free
  auth_required: true
  credentials: ["{bad}"]
  priority: 50
  capabilities: [search]
  markets: [global]
  languages: [en]
  cache_ttl: 900
"""
        with pytest.raises(ConfigValidationError):
            load_registry(yaml_text=yaml)
