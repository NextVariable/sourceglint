"""Deterministic identity for clusters and signals (PRD §10).

Cluster identity is derived by CODE from the SORTED evidence-id set —
never from a model label. Two runs that group the same evidence set get
the same cluster id even if the model words the label differently.

Signal identity is derived from the cluster id, so it inherits the same
stability: the same evidence set always yields the same signal id.

Both ids satisfy the frozen `common.schema.json` patterns
(`sig_[a-z0-9_]{1,64}`); `cl_` is internal-only and never reaches a
frozen schema.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

CLUSTER_ID_PREFIX = "cl_"
SIGNAL_ID_PREFIX = "sig_"

_ID_BODY_LEN = 32
_SIGNAL_ID_RE = re.compile(r"^sig_[a-z0-9_]{1,64}$")
_CLUSTER_ID_RE = re.compile(r"^cl_[a-z0-9_]{1,64}$")


def _digest(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")  # unit separator — prevents field-boundary collisions
    return h.hexdigest()[:_ID_BODY_LEN]


def derive_cluster_id(evidence_ids: Iterable[str]) -> str:
    """`cl_<sha256(sorted evidence ids)>`.

    Sorting makes the id independent of model output order and of
    retrieval order. Empty input is a programming error — a cluster with
    no evidence cannot exist (PRD §11).
    """
    ids = sorted({str(eid) for eid in evidence_ids if str(eid)})
    if not ids:
        raise ValueError("cannot derive cluster id from an empty evidence set")
    return f"{CLUSTER_ID_PREFIX}{_digest(ids)}"


def derive_signal_id(cluster_id: str) -> str:
    """`sig_<sha256(cluster_id)>` — 1:1 with the cluster (PRD §10)."""
    if not str(cluster_id):
        raise ValueError("cannot derive signal id from an empty cluster id")
    return f"{SIGNAL_ID_PREFIX}{_digest([str(cluster_id)])}"


def is_valid_cluster_id(value: str) -> bool:
    return bool(_CLUSTER_ID_RE.match(value or ""))


def is_valid_signal_id(value: str) -> bool:
    """True when `value` matches the frozen signal_id pattern."""
    return bool(_SIGNAL_ID_RE.match(value or ""))
