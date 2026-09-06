"""Host Web Search capability adapter (Phase 4 §4-§5).

Architecture:

    Host / Harness
        ↓
    SearchCapability              ← neutral Protocol
        ↓
    HostWebSearchAdapter          ← maps capability → SourceAdapter
        ↓
    RawSourceResult               ← Phase 3 DTO

The CORE repository defines only the neutral capability contract. Harness-
specific implementations live in the host integration layer and inject
their capability into the pipeline.

Compliance with PRD:
  * No harness-vendor-specific imports inside this module.
  * Adapter does NOT generate evidence_id, write to ledger, score, or
    call any LLM — those are all downstream.
  * Failure modes map to the existing AdapterError taxonomy:
      - capability missing/unavailable  → AdapterUnavailable
      - capability times out            → AdapterTimeout
      - capability returns malformed    → AdapterInvalidResponse
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..pipeline.adapters import (
    AdapterError,
    AdapterInvalidResponse,
    AdapterTimeout,
    AdapterUnavailable,
    RawSourceResult,
    SourceAdapter,
)


SOURCE_NAME = "host_web_search"
SOURCE_TYPE = "page"  # evidence.schema.json enum


# ---------- Neutral capability contract --------------------------------


@dataclass(frozen=True)
class WebSearchHit:
    """One neutral hit from a host-injected search capability.

    Fields are deliberately permissive: not every search backend exposes
    language / published_at. The adapter downgrades silently rather than
    failing the whole retrieval.
    """

    url: str
    title: str
    snippet: str = ""
    published_at: str = ""
    language: str = ""
    market: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class SearchCapability(Protocol):
    """Neutral capability contract for whatever web-search backend the host
    injects. Real implementations (any vendor-provided search tool) live
    OUTSIDE this repository and adapt themselves to this Protocol.

    The contract is intentionally small: a single synchronous `search`
    call. Async backends can wrap themselves.
    """

    def search(
        self,
        query: str,
        *,
        language: str = "",
        market: str = "",
        start: str = "",
        end: str = "",
        limit: int = 10,
    ) -> list[WebSearchHit]:
        ...


class SearchCapabilityUnavailable(AdapterError):
    """Raised when SearchCapability raises or returns no usable result."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(source=source, reason=f"capability unavailable: {reason}")


class SearchCapabilityTimeout(AdapterError):
    """Raised when the capability hit its configured timeout budget."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(source=source, reason=f"capability timeout: {reason}")


# ---------- Adapter -----------------------------------------------------


# PRD §16: MVP default max-per-query for Host Web Search.
DEFAULT_MAX_PER_QUERY = 20


@dataclass
class HostWebSearchAdapter:
    """Adapter that delegates to a host-injected SearchCapability.

    Args:
      capability        — injected by the host integration layer. Pass None
                          to force AdapterUnavailable on every retrieve.
      max_per_query     — hard cap; values above this are clamped (PRD §16).
      source_name       — defaults to "host_web_search"; pass alternate for
                          testing both SourceAdapter.name shims (kept stable
                          to match the source registry entry).
    """

    capability: SearchCapability | None
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    source_name: str = SOURCE_NAME

    @property
    def name(self) -> str:  # noqa: D401 — short property
        return self.source_name

    # ------------------------------------------------------------------

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        if self.capability is None:
            raise AdapterUnavailable(
                source=self.source_name,
                reason="no SearchCapability injected by host",
            )

        query = str(request.get("query") or "")
        if not query:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="retrieval request missing query",
            )

        # PRD §6: official classification is a SEPARATE stage; the host
        # web search adapter must NOT decide first-party-ness on its own.
        # We just pass market / language through unchanged.
        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")

        # Resolve the limit. PRD §16 default + per-source override.
        limit_req = request.get("limit")
        try:
            limit_n = int(limit_req) if limit_req is not None else self.max_per_query
        except (TypeError, ValueError):
            limit_n = self.max_per_query
        limit = max(1, min(limit_n, self.max_per_query))

        # Hit the capability; map host-specific failures to our taxonomy.
        try:
            hits = self.capability.search(
                query,
                language=language,
                market=market,
                start=str(request.get("start") or ""),
                end=str(request.get("end") or ""),
                limit=limit,
            )
        except SearchCapabilityTimeout as exc:
            # Capability already classified the timeout — re-raise.
            raise AdapterTimeout(source=self.source_name, reason=str(exc))
        except Exception as exc:
            # Anything else from the capability: treat as unavailable.
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"capability raised: {type(exc).__name__}: {exc}",
            )

        if hits is None:
            # Defensive: a capability returning None is malformed behaviour.
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="capability returned None instead of list",
            )

        out: list[RawSourceResult] = []
        for idx, hit in enumerate(hits):
            out.append(_hit_to_raw(hit, source_name=self.source_name, query=query, query_language=language, idx=idx))
        return out


# ---------- Helper ------------------------------------------------------


def _hit_to_raw(
    hit: Any,
    *,
    source_name: str,
    query: str,
    query_language: str,
    idx: int,
) -> RawSourceResult:
    """Convert one neutral WebSearchHit into a RawSourceResult.

    A hit that lacks url or title is a hard error from the capability — we
    surface it as AdapterInvalidResponse rather than silently dropping,
    because silently dropping would hide a contract violation by the host.
    """
    if not isinstance(hit, WebSearchHit):
        raise AdapterInvalidResponse(
            source=source_name,
            reason=f"hit #{idx} is not a WebSearchHit (got {type(hit).__name__})",
        )
    if not hit.url or not hit.title:
        raise AdapterInvalidResponse(
            source=source_name,
            reason=(
                f"hit #{idx} missing required fields: "
                f"url={'set' if hit.url else 'MISSING'} "
                f"title={'set' if hit.title else 'MISSING'}"
            ),
        )
    return RawSourceResult(
        source=source_name,
        source_type=SOURCE_TYPE,
        source_native_id=hit.url,  # URLs are stable enough for MVP dedup-key
        url=hit.url,
        title=hit.title,
        text=hit.snippet or "",
        published_at=hit.published_at or "",
        language=hit.language or "",
        market=hit.market or "",
        query=query,
        query_language=query_language,
        raw_metadata=dict(hit.extra) if hit.extra else {},
    )


# ---------- Re-exports for callers --------------------------------------


__all__ = [
    "SOURCE_NAME",
    "SOURCE_TYPE",
    "DEFAULT_MAX_PER_QUERY",
    "WebSearchHit",
    "SearchCapability",
    "SearchCapabilityUnavailable",
    "SearchCapabilityTimeout",
    "HostWebSearchAdapter",
]
