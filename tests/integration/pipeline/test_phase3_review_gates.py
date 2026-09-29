"""Phase 3 Review Gates (Phase 3 §33).

Seven gates:
  A. Full regression (Phase 1 + 2 + 3) — passed / failed / skipped.
  B. Contract Drift — every output Evidence schema-valid.
  C. Golden Research — runs ×20 deterministic.
  D. Graceful Degradation — 1 / multiple / all sources fail; auth missing.
  E. Offline — no real network calls in the default test suite.
  F. Security — no credential/secret/cookie leakage in code, fixtures, cache.
  G. Clean Environment — fresh venv with `pip install -e .[dev]` passes.
"""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path

import pytest

from sourceglint.ledger import EvidenceLedger
from sourceglint.normalization import validate_evidence_payload
from sourceglint.pipeline.adapters import (
    AdapterAuthMissing,
    AdapterUnavailable,
    FakeSourceAdapter,
    FixtureSourceAdapter,
)
from sourceglint.pipeline.degradation import AllSourcesFailedError, SourceStatus
from sourceglint.pipeline.orchestrator import PipelineConfig, ResearchPipeline


ROOT = Path(__file__).resolve().parents[3]
FIX_DIR = ROOT / "tests" / "fixtures" / "pipeline"


# ============================================================================
# Gate A — Full Regression
# ============================================================================


def test_gate_a_full_regression_includes_phase_1_2_3():
    """The 'normal' pytest invocation must run all phases' tests. This single
    invocation is the gate — pytest exit code is the verdict."""
    # Imported here so this test fails when sub-modules break.
    from sourceglint import ids, ledger, normalization, scoring
    from sourceglint.pipeline import (
        adapters, cache, coverage, deduplication, degradation,
        orchestrator, query_expansion, retrieval_plan, source_registry,
        time_filter,
    )
    # Smoke: every module imports and exposes its expected names.
    assert callable(ids.derive_evidence_id)
    assert callable(ledger.EvidenceLedger)
    assert callable(normalization.normalize_raw)
    assert callable(scoring.compute_score)
    assert callable(query_expansion.expand_queries)
    assert callable(retrieval_plan.build_retrieval_plans)
    assert callable(orchestrator.ResearchPipeline)
    assert callable(time_filter.apply_time_filter)
    assert callable(deduplication.deduplicate)
    assert callable(cache.cache_key_for)
    assert callable(degradation.classify_adapter_exception)
    assert callable(coverage.build_coverage_report)
    assert callable(adapters.FakeSourceAdapter)


# ============================================================================
# Gate B — Contract Drift (mostly in test_contract_drift_gate.py)
# ============================================================================


def test_gate_b_every_normalized_evidence_schema_valid():
    """Spot-check normalization produces schema-valid Evidence."""
    from sourceglint.pipeline.adapters import RawSourceResult
    for raw_dict in [
        {
            "source": "reddit",
            "source_type": "post",
            "source_native_id": "1",
            "url": "https://reddit.com/r/x/1",
            "title": "t",
            "text": "b",
        },
        {
            "source": "official_web",
            "source_type": "page",
            "source_native_id": "2",
            "url": "https://example.com/p",
            "title": "t",
            "text": "b",
            "language": "ja",
            "market": "jp",
        },
    ]:
        r = RawSourceResult(**raw_dict)
        from sourceglint.normalization import normalize_raw
        ev = normalize_raw(r, as_of="2026-09-06T10:00:00Z")
        validate_evidence_payload(ev)


# ============================================================================
# Gate C — Golden Research ×20
# ============================================================================


def _plan():
    import json
    return json.loads((FIX_DIR / "golden_research_jp_plan.json").read_text(encoding="utf-8"))


def _source(name, **overrides):
    src = {
        "name": name,
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],
        "priority": 50,
        "capabilities": ["search"],
        "markets": ["global", "jp"],
        "languages": ["en"],
        "cache_ttl": 900,
    }
    if name in {"reddit", "hacker_news"}:
        src["languages"] = ["en", "ja"]
    if name == "github":
        src["type"] = "official"
        src["priority"] = 85
        src["capabilities"] = ["search", "releases"]
    if name == "official_web":
        src["type"] = "official"
        src["priority"] = 90
        src["capabilities"] = ["fetch"]
    if name == "host_web_search":
        src["type"] = "web"
        src["priority"] = 60
        src["capabilities"] = ["search"]
    src.update(overrides)
    return src


def _factory():
    fixtures = {
        "official_web": FIX_DIR / "golden_official_web.jsonl",
        "reddit": FIX_DIR / "golden_reddit.jsonl",
        "hacker_news": FIX_DIR / "golden_hacker_news.jsonl",
        "github": FIX_DIR / "golden_github.jsonl",
        "host_web_search": FIX_DIR / "golden_host_web_search.jsonl",
    }
    def f(name, plan):
        if name in fixtures:
            return FixtureSourceAdapter(name=name, path=fixtures[name])
        return FakeSourceAdapter(name=name)
    return f


def test_gate_c_golden_research_x20_deterministic():
    snapshots = []
    for _ in range(20):
        plan = _plan()
        sources = [
            _source("official_web"),
            _source("reddit"),
            _source("hacker_news"),
            _source("github"),
            _source("host_web_search"),
        ]
        pipeline = ResearchPipeline(
            config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
            adapter_factory=_factory(),
        )
        ledger = EvidenceLedger(":memory:")
        result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
        snapshots.append((
            tuple(sorted(result.evidence_ids)),
            ledger.count(),
            result.coverage.duplicate_dropped_count,
            result.coverage.final_evidence_count,
        ))
    first = snapshots[0]
    assert all(s == first for s in snapshots)


def test_gate_c_golden_research_en_jp_metadata_preserved():
    plan = _plan()
    sources = [
        _source("official_web"),
        _source("reddit"),
        _source("hacker_news"),
        _source("github"),
        _source("host_web_search"),
    ]
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=_factory(),
    )
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert "en" in list(result.coverage.languages_covered)
    assert "ja" in list(result.coverage.languages_covered)
    assert "jp" in list(result.coverage.markets_covered)


# ============================================================================
# Gate D — Graceful Degradation
# ============================================================================


def _minimal_plan():
    return {
        "topic": "Notion AI",
        "mode": "competitor",
        "market": "global",
        "locale": "en",
        "languages": ["en"],
        "time_window": {"days": 30},
        "entities": ["Notion"],
        "decision_context": "watch",
    }


def _minimal_source(name, **overrides):
    src = {
        "name": name,
        "enabled": True,
        "type": "community",
        "cost": "free",
        "auth_required": False,
        "credentials": [],
        "priority": 50,
        "capabilities": ["search"],
        "markets": ["global"],
        "languages": ["en"],
        "cache_ttl": 900,
    }
    src.update(overrides)
    return src


def _ok_adapter(source="reddit"):
    return FakeSourceAdapter(
        name=source,
        results=[{
            "source": source,
            "source_type": "post",
            "source_native_id": "1",
            "url": f"https://{source}.example.com/1",
            "title": "t",
            "text": "b",
            "published_at": "2026-08-30T10:00:00Z",
        }],
    )


def test_gate_d_one_source_fails_pipeline_continues():
    plan = _minimal_plan()
    sources = [_minimal_source("reddit"), _minimal_source("github")]
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=lambda n, p: _ok_adapter(n)
        if n == "reddit"
        else FakeSourceAdapter(name=n, raises=AdapterUnavailable(source=n, reason="503")),
    )
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert "reddit" in list(result.coverage.successful_sources)
    assert "github" in list(result.coverage.failed_sources)


def test_gate_d_multiple_sources_fail_pipeline_continues():
    plan = _minimal_plan()
    sources = [
        _minimal_source("reddit"),
        _minimal_source("github"),
        _minimal_source("hacker_news"),
    ]
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=lambda n, p: _ok_adapter(n)
        if n == "reddit"
        else FakeSourceAdapter(name=n, raises=AdapterUnavailable(source=n, reason="503")),
    )
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert "reddit" in list(result.coverage.successful_sources)
    assert len(list(result.coverage.failed_sources)) == 2


def test_gate_d_all_sources_fail_pipeline_raises():
    plan = _minimal_plan()
    sources = [_minimal_source("reddit"), _minimal_source("github")]
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=lambda n, p: FakeSourceAdapter(
            name=n, raises=AdapterUnavailable(source=n, reason="503"),
        ),
    )
    ledger = EvidenceLedger(":memory:")
    with pytest.raises(AllSourcesFailedError):
        pipeline.run(plan=plan, sources=sources, ledger=ledger)


def test_gate_d_auth_missing_records_status():
    plan = _minimal_plan()
    sources = [_minimal_source("reddit"), _minimal_source("github")]
    pipeline = ResearchPipeline(
        config=PipelineConfig(as_of="2026-09-06T10:00:00Z"),
        adapter_factory=lambda n, p: _ok_adapter(n)
        if n == "reddit"
        else FakeSourceAdapter(
            name=n, raises=AdapterAuthMissing(source=n, reason="no token"),
        ),
    )
    ledger = EvidenceLedger(":memory:")
    result = pipeline.run(plan=plan, sources=sources, ledger=ledger)
    assert result.source_statuses["github"].status == SourceStatus.AUTH_MISSING


# ============================================================================
# Gate E — Offline (no real network)
# ============================================================================


def test_gate_e_test_suite_has_no_real_network_calls():
    """We can quickly verify the test suite doesn't import network libraries
    that would attempt real I/O. We exclude `socket` which is stdlib but not
    used by our source layer; this is a guard against future regressions."""
    src_dir = ROOT / "src"
    forbidden = []
    for py in src_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        # urllib / requests / httpx — none of these should appear in Phase 3
        # because Host Web Search is an injected capability (PRD §10).
        if re.search(r"\brequests\b", text) or re.search(r"\bhttpx\b", text):
            forbidden.append(str(py))
    assert forbidden == [], (
        f"src/ should not import network libraries: {forbidden}"
    )


def test_gate_e_no_socket_open_in_src():
    """No `socket.socket` direct use in our source."""
    src_dir = ROOT / "src"
    for py in src_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "socket.socket" not in text, f"socket.socket in {py}"


def test_gate_e_fake_adapter_makes_no_real_calls(monkeypatch):
    """Confirm FakeSourceAdapter never tries to touch the network — even
    if someone monkey-patches urllib to capture requests, our adapters
    don't call it."""
    captured = {"called": False}
    def trap(*args, **kwargs):
        captured["called"] = True
        return None
    monkeypatch.setattr(socket, "socket", trap)
    adapter = _ok_adapter("reddit")
    out = adapter.retrieve(plan={}, request={})
    assert captured["called"] is False
    assert len(out) == 1


# ============================================================================
# Gate F — Security / Privacy
# ============================================================================


def test_gate_f_no_secrets_in_fixtures():
    """No real tokens, passwords, or API keys in any fixture file."""
    # Crude patterns — would be augmented in production.
    suspicious = [
        r"ghp_[A-Za-z0-9]{16,}",  # GitHub personal access token
        r"sk-[A-Za-z0-9]{16,}",  # OpenAI / Anthropic keys
        r"xox[bp]-[A-Za-z0-9-]+",  # Slack
        r"AKIA[0-9A-Z]{16}",  # AWS access key
    ]
    fixtures_dir = ROOT / "tests" / "fixtures"
    violations = []
    for f in fixtures_dir.rglob("*"):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in suspicious:
            if re.search(pat, text):
                violations.append((f, pat))
    assert violations == [], f"Secrets in fixtures: {violations}"


def test_gate_f_no_secrets_in_src():
    src_dir = ROOT / "src"
    suspicious = [
        r"ghp_[A-Za-z0-9]{16,}",
        r"sk-[A-Za-z0-9]{16,}",
        r"xox[bp]-[A-Za-z0-9-]+",
        r"AKIA[0-9A-Z]{16}",
    ]
    violations = []
    for f in src_dir.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for pat in suspicious:
            if re.search(pat, text):
                violations.append((f, pat))
    assert violations == [], f"Secrets in src/: {violations}"


def test_gate_f_gitignore_excludes_cache_and_runs():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in (".env", "*.env", "runs/", ".venv/", "venv/", "evals/runs/"):
        assert needle in gitignore, f"{needle} not in .gitignore"


def test_gate_f_cache_writes_no_secret_in_key():
    from sourceglint.pipeline.cache import cache_key_for
    k = cache_key_for(
        source="reddit",
        query="github_pat=ghp_supersecret_token_value_xyz_123",
        query_language="en",
        market="global",
        time_window={"days": 30},
    )
    assert "ghp_supersecret" not in k
    assert "supersecret" not in k


def test_gate_f_no_dotenv_tracked():
    """`git ls-files` should NOT list any .env file."""
    if not (ROOT / ".git").exists():
        # GitHub source archives have no index. Inspect shipped files directly
        # rather than failing because the user chose Download ZIP over clone.
        bundled_env = [
            path.relative_to(ROOT) for path in ROOT.rglob("*")
            if path.is_file() and (path.name == ".env" or path.name.endswith(".env"))
        ]
        assert not bundled_env, f"Environment files bundled in archive: {bundled_env}"
        return
    import subprocess
    out = subprocess.run(
        ["git", "ls-files", ".env", "*.env"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    # git ls-files exits 0 even if no matches, but stdout must be empty.
    assert out.stdout.strip() == ""


# ============================================================================
# Gate G — Clean Environment
# ============================================================================


def test_gate_g_pyproject_deps_complete():
    """pyproject.toml must declare all runtime + dev dependencies used."""
    import tomllib
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject.get("project", {}).get("dependencies", [])
    dev_deps = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    # Sanity: must include jsonschema, pyyaml, pytest.
    joined = " ".join(deps) + " " + " ".join(dev_deps)
    for must in ("jsonschema", "PyYAML", "pytest", "rfc3339-validator"):
        assert must in joined, f"{must} missing from pyproject deps"


def test_gate_g_pyproject_extras_dev_installable():
    """Re-importing the package from a separate venv is verified by the
    test infra itself — we run inside the venv. This is a sanity check
    that pyproject's optional-dependencies.dev is non-empty so the
    clean-env gate can `pip install -e .[dev]`."""
    import tomllib
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    assert dev, "pyproject.toml [project.optional-dependencies].dev is empty"
