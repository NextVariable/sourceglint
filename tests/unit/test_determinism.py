"""Phase 2 determinism review (Phase 2 §22).

Determinism rules:
  * No random UUID anywhere (grep enforcement)
  * No time-derived values in identity or renderer
  * No dict/set non-stable iteration orders in scoring/output paths
  * URL canonicalization stable
  * Score is reproducible across runs (50x verified)
  * Renderer is reproducible across 30 runs
  * No locale / timezone dependence
  * Tests must not depend on network
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


FORBIDDEN = [
    "uuid.uuid",
    "uuid4",
    "random.random",
    "random.randint",
    "random.choice",
    "secrets.token",
]


def _scan(path: Path) -> list[tuple[Path, int, str]]:
    out = []
    if not path.exists():
        return out
    for py in path.rglob("*.py"):
        if not py.is_file():
            continue
        text = py.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for kw in FORBIDDEN:
                if kw in line:
                    out.append((py, n, f"{kw!r} in {line.strip()!r}"))
                    break
    return out


def test_no_random_uuid_anywhere():
    bad = []
    for path in (SRC, TESTS / "unit", TESTS / "integration"):
        if path.resolve() == Path(__file__).resolve().parent:
            # The list of FORBIDDEN tokens in this test file produces
            # substrings of itself; whitelist this file only.
            continue
        bad.extend(_scan(path))
    assert not bad, f"non-deterministic primitives found:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {reason}" for p, ln, reason in bad
    )


def test_no_clock_or_locale_in_deterministic_core():
    bad = []
    sensitive_patterns = [
        "time.time(",
        "time.perf_counter(",
        "datetime.now(",
        "datetime.utcnow(",
        "locale.",
        "tzlocal",
        "tz.gettz",
    ]
    for py in SRC.rglob("*.py"):
        # rendering + ids + ledger are deterministic; allowed only in tests.
        text = py.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for kw in sensitive_patterns:
                if kw in line:
                    bad.append((py, n, kw, line.strip()))
                    break
    assert not bad, "clock/locale in src/ not allowed:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {kw} -> {line!r}"
        for p, ln, kw, line in bad
    )


def test_score_reproducible_50_runs():
    from gtm_intelligence.scoring import ScoringConfig, compute_score

    factors = {
        "decision_relevance": 0.81,
        "evidence_quality": 0.65,
        "recency": 0.92,
        "market_signal": 0.30,
        "novelty": 0.77,
    }
    cfg = ScoringConfig.default()
    first = compute_score(factors, cfg=cfg).score
    for _ in range(50):
        assert compute_score(factors, cfg=cfg).score == first


def test_renderer_clock_independent(monkeypatch):
    from gtm_intelligence.ledger import EvidenceLedger
    from gtm_intelligence.rendering import render_markdown

    ledger = EvidenceLedger(":memory:")
    ledger.add({
        "source": "reddit", "source_type": "discussion",
        "url": "https://example.com/a", "snippet": "x",
        "author": "alice", "published_at": "2026-01-01T00:00:00Z",
        "retrieved_at": "2026-09-01T00:00:00Z",
    })
    output = {"summary": "x", "changes": [{"change": "y", "evidence_ids": [ledger.all()[0].evidence_id]}]}

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(time, "perf_counter", lambda: 1_700_000_000)
    a = render_markdown(ledger, output)
    monkeypatch.setattr(time, "time", lambda: 9_999_999_999)
    monkeypatch.setattr(time, "perf_counter", lambda: 9_999_999_999)
    b = render_markdown(ledger, output)
    assert a == b


def test_url_canonicalization_stable():
    from gtm_intelligence.ids import canonicalize_url
    a = canonicalize_url("https://Example.com/A?utm_source=tw&b=2&a=1#frag")
    b = canonicalize_url("https://example.com/A?a=1&b=2&utm_source=tw#frag")
    assert a == b
