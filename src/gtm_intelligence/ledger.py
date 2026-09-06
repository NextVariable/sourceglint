"""Append-oriented JSONL Evidence Ledger (Phase 2 §5).

Design notes:
  * Storage is JSONL: one evidence JSON object per line. Append-only on disk.
  * In-memory index keyed by evidence_id for O(1) lookup.
  * Identity is determined by `gtm_intelligence.ids.derive_evidence_id`. The
    ledger does not reimplement canonicalization.
  * Duplicate policy: same canonical evidence => idempotent re-add (no
    duplicate entry, enrichment ignored). If a caller pins an evidence_id and
    re-uses it for a different payload, raise EvidenceConflictError.
  * Iteration order is stable: id-ascending (deterministic for tests and
    reproducible output).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .errors import EvidenceConflictError, EvidenceMalformedError
from .ids import canonicalize_url, derive_evidence_id


# Required fields enforced at ledger-load time. These match the schema-required
# fields in Phase 1 evidence.schema.json plus evidence_id (always required in
# the ledger, even when schema allowed omission).
LEDGER_REQUIRED = (
    "evidence_id",
    "source",
    "source_type",
    "url",
    "retrieved_at",
)


@dataclass(frozen=True)
class EvidenceRecord:
    """A canonical snapshot of one ledger entry."""

    evidence_id: str
    source: str
    source_type: str
    url: str
    retrieved_at: str
    published_at: str = ""
    author: str = ""
    title: str = ""
    snippet: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "EvidenceRecord":
        for key in LEDGER_REQUIRED:
            if not payload.get(key):
                raise EvidenceMalformedError(
                    f"record missing required field: {key}"
                )
        known = {
            k: payload[k] for k in LEDGER_REQUIRED if k in payload  # type: ignore[literal-required]
        }
        return cls(
            evidence_id=str(payload["evidence_id"]),
            source=str(payload["source"]),
            source_type=str(payload["source_type"]),
            url=str(payload["url"]),
            retrieved_at=str(payload["retrieved_at"]),
            published_at=str(payload.get("published_at") or ""),
            author=str(payload.get("author") or ""),
            title=str(payload.get("title") or ""),
            snippet=str(payload.get("snippet") or ""),
            extra={k: v for k, v in payload.items()
                   if k
                   not in (
                       "evidence_id", "source", "source_type", "url",
                       "retrieved_at", "published_at", "author", "title",
                       "snippet",
                   )},
        )

    def to_payload(self) -> dict:
        payload = {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "source_type": self.source_type,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
        }
        for opt in ("published_at", "author", "title", "snippet"):
            val = getattr(self, opt)
            if val:
                payload[opt] = val
        payload.update(self.extra)
        return payload


class EvidenceLedger:
    """JSONL-backed evidence ledger."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, EvidenceRecord] = {}
        self._load_existing()

    # --- public API ---------------------------------------------------------

    def add(self, evidence: Mapping[str, object]) -> EvidenceRecord:
        """Add canonical evidence. Idempotent for identical content.

        Returns the persisted EvidenceRecord (either newly added or existing
        on dedup hit).
        """
        payload = dict(evidence)

        # Persist URL in canonical form so dedup survives tracking params,
        # fragments, casing, and trailing slashes.
        if payload.get("url"):
            payload["url"] = canonicalize_url(str(payload["url"]))

        # Idempotent dedup path: derive canonical id and inspect the index.
        derived_id = derive_evidence_id(payload)
        pinned_id = payload.get("evidence_id")
        if pinned_id and pinned_id != derived_id:
            # Caller pinned an id that disagrees with the canonical id.
            existing = self._index.get(pinned_id)
            if existing is not None:
                # Same pinned id, but content differs: conflict.
                if not _records_equal(existing, payload):
                    raise EvidenceConflictError(
                        f"evidence_id {pinned_id} already exists with different content"
                    )
                return existing
            # Pinned id is new but disagrees with canonical: assert the
            # canonical id is also absent (otherwise surprise collision).
            if derived_id in self._index:
                raise EvidenceConflictError(
                    f"pinned evidence_id {pinned_id} collides with canonical "
                    f"id {derived_id} of an existing record"
                )
            evidence_id = str(pinned_id)
        else:
            evidence_id = derived_id

        # Re-attach normalized id and required audit field.
        payload["evidence_id"] = evidence_id
        payload.setdefault("retrieved_at", payload.get("retrieved_at", ""))

        record = EvidenceRecord.from_payload(payload)
        existing = self._index.get(evidence_id)
        if existing is not None:
            if not _records_equal(existing, payload):
                raise EvidenceConflictError(
                    f"evidence_id {evidence_id} already exists with different content"
                )
            return existing
        self._index[evidence_id] = record
        self._append_line(record)
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._index.get(evidence_id)

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self._index

    def count(self) -> int:
        return len(self._index)

    def all(self) -> list[EvidenceRecord]:
        return list(self)

    def __iter__(self) -> Iterator[EvidenceRecord]:
        for eid in sorted(self._index):
            yield self._index[eid]

    def __len__(self) -> int:
        return self.count()

    # --- internal -----------------------------------------------------------

    def _append_line(self, record: EvidenceRecord) -> None:
        line = json.dumps(record.to_payload(), ensure_ascii=False, sort_keys=True)
        # Append atomically: open in append mode, write line + newline.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for ln_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EvidenceMalformedError(
                        f"malformed JSON at {self.path}:{ln_no}: {exc}"
                    ) from exc
                if not isinstance(obj, dict):
                    raise EvidenceMalformedError(
                        f"expected object at {self.path}:{ln_no}, got {type(obj).__name__}"
                    )
                try:
                    rec = EvidenceRecord.from_payload(obj)
                except EvidenceMalformedError:
                    raise
                if rec.evidence_id in self._index:
                    if not _records_equal(self._index[rec.evidence_id], obj):
                        raise EvidenceMalformedError(
                            f"conflicting duplicate at {self.path}:{ln_no}"
                        )
                    continue
                self._index[rec.evidence_id] = rec


def _records_equal(existing: EvidenceRecord, payload: Mapping[str, object]) -> bool:
    """Determine whether a candidate payload is materially equal to the stored
    record. Enrichment fields (engagement, query, tags, evidence_quality) are
    not part of identity, so they may differ; we only check the identity fields
    plus a fixed subset of enrichment fields that ought to round-trip."""
    identity_fields = ("source", "source_type", "url", "title", "snippet",
                       "author", "published_at")
    for fld in identity_fields:
        existing_val = getattr(existing, fld, "") or ""
        new_val = str(payload.get(fld, "") or "")
        # URL is canonicalized before reaching this point; equality still
        # passes if canonicalization was a no-op.
        if new_val and fld == "url":
            new_val = canonicalize_url(new_val)
        if existing_val != new_val:
            return False
    return True
