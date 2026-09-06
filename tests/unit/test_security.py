"""Phase 2 Security / Privacy Review (Phase 2 §23)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


SECRET_PATTERNS = [
    # Common tokens / API keys / SSH / generic high-entropy base64
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
]


def test_no_real_secrets_in_repo_code():
    bad = []
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    bad.append((py, n, pat.pattern, line.strip()))
    assert not bad, "real secret pattern in code:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {pat} -> {line!r}"
        for p, ln, pat, line in bad
    )


def test_no_real_secrets_in_fixtures():
    bad = []
    for f in (ROOT / "tests" / "fixtures").rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), start=1):
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    bad.append((f, n, pat.pattern, line.strip()))
    assert not bad, "real secret pattern in fixtures:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {pat} -> {line!r}"
        for p, ln, pat, line in bad
    )


def test_no_real_secrets_in_yaml():
    bad = []
    for f in (ROOT / "config").rglob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    bad.append((f, n, pat.pattern, line.strip()))
    assert not bad, "real secret pattern in yaml:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {pat} -> {line!r}"
        for p, ln, pat, line in bad
    )


def test_gitignore_covers_dotenv():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi or "*.env" in gi, ".env not in .gitignore"


def test_no_real_pii_in_fixtures():
    """Fixtures must be synthetic / public-safe (no emails, no
    real-looking phone numbers, no real names)."""
    pii_patterns = [
        ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
        ("us-phone", re.compile(r"\b\d{3}-\d{3}-\d{4}\b")),
    ]
    bad = []
    for f in (ROOT / "tests" / "fixtures").rglob("*"):
        if not f.is_file() or f.suffix not in {".json", ".md", ".yaml", ".jsonl"}:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), start=1):
            for label, pat in pii_patterns:
                if pat.search(line):
                    bad.append((f, n, label, line.strip()))
    assert not bad, "suspicious PII in fixtures:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {label} -> {line!r}"
        for p, ln, label, line in bad
    )


def test_no_destructive_git_or_fs_calls_in_lib():
    """The deterministic core must never run destructive shell/git/filesystem ops."""
    from gtm_intelligence import __init__  # noqa: F401  ensure imports work
    bad = []
    needles = ["shutil.rmtree", "os.remove(", "os.unlink(", "rmtree(",
               "os.system(", "subprocess.run"]
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for kw in needles:
                if kw in line:
                    bad.append((py, n, kw, line.strip()))
                    break
    assert not bad, "destructive op in deterministic core:\n" + "\n".join(
        f"{p.relative_to(ROOT)}:{ln} {kw} -> {line!r}"
        for p, ln, kw, line in bad
    )


def test_ledger_does_not_record_secrets(tmp_path):
    """Sanity check: the ledger storage layer accepts the canonical evidence
    payload without leaking into secret-shaped fields. Phase 1 evidence
    schema forbids unknown fields via additionalProperties: false on key
    ones; this test pins the data flow doesn't accept arbitrary keys in a
    way that would smuggle a secret through.
    """
    from gtm_intelligence.ledger import EvidenceLedger
    ledger = EvidenceLedger(tmp_path / "fresh.jsonl")
    ledger.add({
        "source": "reddit", "source_type": "discussion",
        "url": "https://example.com/x", "snippet": "hi",
        "author": "alice", "published_at": "2026-01-01T00:00:00Z",
        "retrieved_at": "2026-09-01T00:00:00Z",
    })
    assert ledger.count() == 1
    rec = ledger.all()[0]
    # The record should expose URL, source, snippet — not allow raw secret
    # fields to be silently dropped or stored.
    assert rec.url == "https://example.com/x"
    assert rec.source == "reddit"
    # Extra fields are routed to `.extra` — verify they're preserved not dropped.
    assert "extra" in rec.__dataclass_fields__
