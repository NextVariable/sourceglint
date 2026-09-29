"""Phase 5 §28 — semantic cache for model calls.

Cache key = task + prompt_version + model_id + sorted evidence ids +
research context. It deliberately EXCLUDES free-text: two runs over the
same evidence set with the same prompt version must hit, regardless of
how the evidence was worded at call time (all text lives inside
`evidence_items`, and any text change means a different evidence id set —
there is no way to edit text without editing ids).

Only SUCCESS responses are stored. Failures are never cached (a transient
unavailability must not poison a later retry).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .model import ModelResponse, ModelStatus


def _canonical(obj: Any) -> str:
    if isinstance(obj, Mapping):
        return json.dumps(
            {str(k): _canonical(v) for k, v in sorted(obj.items())},
            sort_keys=True,
            ensure_ascii=False,
        )
    if isinstance(obj, (list, tuple)):
        return json.dumps([_canonical(v) for v in obj], ensure_ascii=False)
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, float)):
        return json.dumps(obj, ensure_ascii=False)
    return json.dumps(str(obj), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_cache_key(
    *,
    task: str,
    prompt_version: str,
    model_id: str,
    evidence_ids: Iterable[str],
    research_context: Mapping[str, Any],
) -> str:
    """Deterministic cache key (PRD §28). Evidence id order does not matter."""
    sorted_ids = sorted({str(eid) for eid in evidence_ids})
    parts = [
        f"task={task}",
        f"version={prompt_version}",
        f"model={model_id}",
        f"ids={_canonical(sorted_ids)}",
        f"ctx={_canonical(research_context)}",
    ]
    return _digest("\x1f".join(parts))


@dataclass
class SemanticCache:
    """In-memory store. A host may subclass or replace it with persistence;
    the protocol is just get/put."""

    _store: dict[str, ModelResponse] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._store is None:
            self._store = {}

    @property
    def size(self) -> int:
        return len(self._store)

    def get(self, key: str) -> ModelResponse | None:
        """Return a cached response, or None on miss."""
        return self._store.get(key)

    def put(self, key: str, response: ModelResponse) -> ModelResponse:
        """Store a SUCCESS response. Non-success responses are ignored and
        returned as-is, so the caller can keep one code path."""
        if response.status is ModelStatus.SUCCESS and response.payload is not None:
            self._store[key] = response
        return response

    def clear(self) -> None:
        self._store.clear()
