"""Source Adapter interface and RawSourceResult DTO (Phase 3 §7, §8).

The adapter layer is the boundary between source-specific retrieval logic
and the source-AGNOSTIC downstream pipeline (normalization, dedup, ledger).
Adapters MUST NOT:
  * write to EvidenceLedger
  * derive evidence_id
  * score evidence
  * call LLM

Adapters SHOULD raise one of the Adapter*Error taxonomy on failure. The
orchestrator decides whether to degrade the source or fail the pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable


# ---------- Adapter exception taxonomy -----------------------------------


class AdapterError(Exception):
    """Base class for source-adapter errors.

    Attributes:
      source : which source emitted the error (snake_case name from registry).
      reason : human-readable detail.
    """

    def __init__(self, source: str, reason: str = "") -> None:
        super().__init__(f"[{source}] {reason}" if reason else f"[{source}] adapter error")
        self.source = source
        self.reason = reason


class AdapterUnavailable(AdapterError):
    """The source is unreachable (DNS, 5xx, network, etc.)."""


class AdapterAuthMissing(AdapterError):
    """The source requires credentials that were not provided."""


class AdapterRateLimited(AdapterError):
    """The source reported rate-limit / quota exhaustion."""


class AdapterTimeout(AdapterError):
    """The source did not respond within the configured budget."""


class AdapterInvalidResponse(AdapterError):
    """The source returned a payload the adapter cannot parse or trust."""


# ---------- RawSourceResult DTO ------------------------------------------


@dataclass(frozen=True)
class RawSourceResult:
    """One raw retrieval result. Phase-3-internal DTO.

    Not a Phase 1 Evidence. Normalizer converts Raw -> Evidence.
    """

    source: str
    source_type: str  # "post" | "comment" | "review" | "page" | "release"
    source_native_id: str
    url: str
    title: str
    text: str
    author: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    market: str = ""
    locale: str = ""
    language: str = ""
    query: str = ""
    query_language: str = ""
    engagement: Mapping[str, object] = field(default_factory=dict)
    raw_metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "source_native_id": self.source_native_id,
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "author": self.author,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "market": self.market,
            "locale": self.locale,
            "language": self.language,
            "query": self.query,
            "query_language": self.query_language,
            "engagement": dict(self.engagement),
            "raw_metadata": dict(self.raw_metadata),
        }


# ---------- SourceAdapter Protocol ---------------------------------------


@runtime_checkable
class SourceAdapter(Protocol):
    """The single source-adapter contract Phase 3 enforces.

    Concrete adapters may add implementation-specific kwargs via **kwargs in
    their retrieve signature, but they MUST accept the canonical
    (research_plan, retrieval_request) shape and return list[RawSourceResult].
    """

    name: str

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        ...


# ---------- FakeSourceAdapter --------------------------------------------


@dataclass
class FakeSourceAdapter:
    """Deterministic in-process adapter for tests.

    Returns a configured list of result dicts (converted to RawSourceResult).
    Optional `raises` lets a test inject a failure mode without I/O.
    """

    name: str
    results: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    raises: Exception | None = None

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        if self.raises is not None:
            raise self.raises
        out: list[RawSourceResult] = []
        for raw in self.results:
            # Carry query/query_language from request into the result if not
            # already pinned on the raw mapping — useful for fixture authoring.
            merged = dict(raw)
            if not merged.get("query") and request.get("query"):
                merged["query"] = str(request["query"])
            if not merged.get("query_language") and request.get("query_language"):
                merged["query_language"] = str(request["query_language"])
            if not merged.get("retrieved_at") and request.get("retrieved_at"):
                merged["retrieved_at"] = str(request["retrieved_at"])
            out.append(_coerce_raw(merged, default_source=self.name))
        return out


# ---------- FixtureSourceAdapter -----------------------------------------


@dataclass
class FixtureSourceAdapter:
    """Loads raw results from a JSONL fixture file.

    Each non-blank line is a JSON object matching RawSourceResult.to_dict().
    Used for golden-research scenarios and offline regression tests.
    """

    name: str
    path: Path

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        if not self.path.exists():
            raise AdapterInvalidResponse(
                source=self.name,
                reason=f"fixture not found: {self.path}",
            )
        out: list[RawSourceResult] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for ln_no, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AdapterInvalidResponse(
                        source=self.name,
                        reason=f"malformed JSON at line {ln_no}: {exc}",
                    ) from exc
                if not isinstance(obj, dict):
                    raise AdapterInvalidResponse(
                        source=self.name,
                        reason=f"line {ln_no} is not an object",
                    )
                out.append(_coerce_raw(obj, default_source=self.name))
        return out


# ---------- helpers ------------------------------------------------------


_REQUIRED_RAW_FIELDS = ("source_type", "source_native_id", "url", "title", "text")


def _coerce_raw(payload: Mapping[str, object], default_source: str) -> RawSourceResult:
    """Build a RawSourceResult from a free-form mapping.

    Missing required keys raise AdapterInvalidResponse. Optional keys fall
    back to safe empty defaults — the normalizer downstream decides whether
    each optional field flows into Evidence.
    """
    for key in _REQUIRED_RAW_FIELDS:
        if key not in payload or payload[key] in (None, ""):
            raise AdapterInvalidResponse(
                source=str(payload.get("source") or default_source),
                reason=f"raw result missing required field: {key}",
            )
    engagement = payload.get("engagement") or {}
    if not isinstance(engagement, Mapping):
        engagement = {}
    raw_metadata = payload.get("raw_metadata") or {}
    if not isinstance(raw_metadata, Mapping):
        raw_metadata = {}
    return RawSourceResult(
        source=str(payload.get("source") or default_source),
        source_type=str(payload["source_type"]),
        source_native_id=str(payload["source_native_id"]),
        url=str(payload["url"]),
        title=str(payload["title"]),
        text=str(payload["text"]),
        author=str(payload.get("author") or ""),
        published_at=str(payload.get("published_at") or ""),
        retrieved_at=str(payload.get("retrieved_at") or ""),
        market=str(payload.get("market") or ""),
        locale=str(payload.get("locale") or ""),
        language=str(payload.get("language") or ""),
        query=str(payload.get("query") or ""),
        query_language=str(payload.get("query_language") or ""),
        engagement=dict(engagement),
        raw_metadata=dict(raw_metadata),
    )