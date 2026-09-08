"""Phase 6A §12–§13, §37 — code-side FACT grounding validation.

The model owns statement wording; code rejects statements that assert
more than the evidence owned by the cited signals can support. All four
guards operate on the union of evidence BELONGING TO THE CITED SIGNALS
(signal pool), not only on the subset of evidence_ids the FACT cites
(consistent with §10 passing signal-level summaries and §34's subset
rule): a number / causal link / generalization / future claim is
grounded when the signal pool's own evidence carries it.

Guards:
  * Unsupported quantification (§12, §37) — every number in the
    statement must be backed by (a) the text of evidence owned by the
    cited signals, (b) a code-computed current/baseline count of a
    cited signal, or (c) the code-known size of the cited signal /
    evidence sets. "several users complained" + "80% of users
    complained" → reject.
  * Unsupported causality (§12) — a causal connective ("caused",
    "because of", ...) must also appear in the signal pool's evidence
    text, otherwise the model is asserting a causal link the sources
    did not make.
  * Unsupported universality (§13) — a blanket generalization ("users
    generally", "the market shows", ...) must be grounded in the
    evidence text; small samples must keep calibrated wording
    ("Several sampled community posts..." not "Users generally...").
  * Unsupported future (§12) — a predictive assertion ("will
    dominate", "is expected to", ...) must be grounded in the evidence.

VOC exception (§28): statements that REPORT user speech (begin with a
reporting prefix such as "users say" / "one source reports") describe
what users or sources claim — the textual guards (causality /
universality / future) do not apply because the model is not asserting
the link itself. Numeric grounding still applies: a number inside a
quoted claim must exist in the signal pool or be code-computed.

This module never edits a draft. It only returns violation strings;
callers reject the draft (§32 — no silent repair).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

#: Reporting prefixes that mark a statement as reported speech (§28).
#: Shared with the recommendation-leakage guard (facts.py imports this).
VOC_PREFIXES: tuple[str, ...] = (
    "users say", "users report", "users mention", "users claim",
    "users state", "users write", "users complain", "users note",
    "community members say", "one source reports", "one user reports",
    "one user says", "one customer reports", "several sources report",
    "several users report", "customers say", "customers report",
    "two sampled community posts report",
)

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Causal connectives (§12). Longest-first matters only for readability;
#: membership is substring-based on the lowercased statement.
_CAUSAL_PHRASES: tuple[str, ...] = (
    "as a result of", "can be attributed to", "a consequence of",
    "brought on by", "triggered by", "stemming from", "stem from",
    "explains why", "because of", "resulted in", "results from",
    "the reason for", "caused", "due to", "led to", "leads to",
    "driven by",
)

#: Blanket generalizations (§13) — forbidden with small, sampled evidence.
_UNIVERSAL_PHRASES: tuple[str, ...] = (
    "the market shows", "the market is", "the market has",
    "market-wide", "all users", "every user", "every customer",
    "everyone", "nobody", "users generally", "customers generally",
    "most users", "most customers", "widespread", "universally",
    "in general", "broadly",
)

#: Predictive/future assertions (§12).
_FUTURE_PHRASES: tuple[str, ...] = (
    "will dominate", "will take over", "will overtake", "will replace",
    "will win", "will lead", "will become", "is poised to", "is set to",
    "is expected to", "is projected to", "is going to",
    "in the future", "over the coming", "next quarter will",
)


def _lowered(statement: str) -> str:
    return statement.lower()


def _starts_with_voc(statement: str) -> bool:
    lower = statement.lower()
    return any(lower.startswith(prefix) for prefix in VOC_PREFIXES)


def _normalize_number(token: str) -> str:
    """Canonical number form: '1,200' / '1200.0' / '1200' → '1200'."""
    plain = token.replace(",", "")
    try:
        value = float(plain)
    except ValueError:  # pragma: no cover - regex guarantees numeric shape
        return plain
    if value.is_integer():
        return str(int(value))
    return format(value, ".6f").rstrip("0").rstrip(".")


def _numbers(text: str) -> set[str]:
    return {_normalize_number(t) for t in _NUM_RE.findall(text)}


def _evidence_text(ev: Mapping[str, Any] | None) -> str:
    if not ev:
        return ""
    parts = []
    for key in ("snippet", "title", "text", "content", "summary"):
        value = ev.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return " ".join(parts)


def _signal_pool_numbers_and_text(
    signal_ids: Iterable[str],
    signal_evidence_map: Mapping[str, set[str]],
    evidence_by_id: Mapping[str, Any],
) -> tuple[set[str], str]:
    """Collect numbers + concatenated text from all evidence owned by the
    cited signals (the grounding pool)."""
    numbers: set[str] = set()
    texts: list[str] = []
    seen: set[str] = set()
    for sid in signal_ids:
        for eid in signal_evidence_map.get(sid, ()):
            if eid in seen or eid not in evidence_by_id:
                continue
            seen.add(eid)
            text = _evidence_text(evidence_by_id.get(eid))
            if text:
                texts.append(text)
                numbers |= _numbers(text)
    return numbers, " ".join(texts)


def check_fact_grounding(
    statement: str,
    *,
    signal_ids: Iterable[str],
    evidence_ids: Iterable[str],
    signal_evidence_map: Mapping[str, set[str]],
    evidence_by_id: Mapping[str, Any],
    code_counts: Mapping[str, tuple[int, int]] | None = None,
) -> list[str]:
    """Return grounding violations for a FACT statement (empty = grounded).

    Parameters mirror the facts-layer context so a caller can pass the
    exact same maps used for referential checks.
    """
    if not statement or not statement.strip():
        return []

    lower = _lowered(statement)
    violations: list[str] = []

    # --- 1. Unsupported quantification (§12, §37) ---------------------------
    pool_numbers, pool_text = _signal_pool_numbers_and_text(
        signal_ids, signal_evidence_map, evidence_by_id
    )
    allowed: set[str] = set(pool_numbers)
    counts = code_counts or {}
    for sid in signal_ids:
        pair = counts.get(sid)
        if pair is not None:
            allowed.add(str(pair[0]))
            allowed.add(str(pair[1]))
    sig_ids = [s for s in signal_ids if str(s)]
    ev_ids = [e for e in evidence_ids if str(e)]
    allowed.add(str(len(sig_ids)))
    allowed.add(str(len(ev_ids)))

    for token in sorted(_numbers(statement)):
        if _normalize_number(token) not in allowed:
            violations.append(
                f"unsupported quantification: {token} not backed by "
                f"cited evidence text or code-computed counts"
            )

    # --- 2–4. Textual guards (causality / universality / future) ------------
    # VOC-reported statements describe user speech; the model is not
    # asserting the causal/universal/future link itself (§28).
    if not _starts_with_voc(statement):
        pool_lower = pool_text.lower()
        for phrase in _CAUSAL_PHRASES:
            if phrase in lower and phrase not in pool_lower:
                violations.append(
                    f"unsupported causality: '{phrase}' not present in cited evidence"
                )
        for phrase in _UNIVERSAL_PHRASES:
            if phrase in lower and phrase not in pool_lower:
                violations.append(
                    f"unsupported universality: '{phrase}' not present in cited evidence"
                )
        for phrase in _FUTURE_PHRASES:
            if phrase in lower and phrase not in pool_lower:
                violations.append(
                    f"unsupported future: '{phrase}' not present in cited evidence"
                )

    return violations
