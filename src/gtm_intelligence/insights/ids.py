"""Deterministic identity for Insights (PRD §21).

Insight identity is derived by CODE from structural inputs — never from
a model statement. Two runs that build an insight from the same type +
signal set + evidence set get the same insight_id even if the model words
the statement differently.

ID composition:
  type              — FACT and INFERENCE are different identities
  sorted signal_ids — order-independent
  sorted evidence_ids — order-independent

Statement text is deliberately excluded so that minor wording variation
does not cause ID drift. The model may rephrase; the structural identity
is stable.

The id satisfies the frozen `common.schema.json` pattern
`ins_[a-z0-9_]{1,64}`.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

INSIGHT_ID_PREFIX = "ins_"

_ID_BODY_LEN = 32
_INSIGHT_ID_RE = re.compile(r"^ins_[a-z0-9_]{1,64}$")

#: Insight types (frozen insight.schema.json enum).
FACT = "FACT"
INFERENCE = "INFERENCE"
RECOMMENDATION = "RECOMMENDATION"

#: Allowed types for Phase 6A (PRD §2: FACT + INFERENCE only).
PHASE6A_TYPES = frozenset({FACT, INFERENCE})


def _digest(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")  # unit separator — prevents field-boundary collisions
    return h.hexdigest()[:_ID_BODY_LEN]


def derive_insight_id(
    *,
    type: str,
    signal_ids: Iterable[str],
    evidence_ids: Iterable[str],
) -> str:
    """`ins_<sha256(type + sorted signal_ids + sorted evidence_ids)>`.

    Sorting makes the id independent of model output order and of signal
    ordering. Empty signal_ids or evidence_ids is a programming error —
    an insight without structural support cannot exist (PRD §14, §16).

    The `type` is part of the hash so a FACT and an INFERENCE built from
    the same evidence set are distinct insights (PRD §21).
    """
    sig = sorted({str(s) for s in signal_ids if str(s)})
    evi = sorted({str(e) for e in evidence_ids if str(e)})
    if not sig:
        raise ValueError("cannot derive insight id from an empty signal set")
    if not evi:
        raise ValueError("cannot derive insight id from an empty evidence set")
    return f"{INSIGHT_ID_PREFIX}{_digest([type, *sig, *evi])}"


def is_valid_insight_id(value: str) -> bool:
    """True when `value` matches the frozen insight_id pattern."""
    return bool(_INSIGHT_ID_RE.match(value or ""))
