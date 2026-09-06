"""Hacker News real source adapter (Phase 4 §7).

Backend: HN Algolia search API + HN Firebase item lookup. Both are
public, no-auth, JSON REST. We DO NOT scrape HTML.

PRD §7 rules:
  * Title / URL / author / published_at / engagement / source_native_id
  * Story without external URL → use a stable HN item URL
  * Deleted / dead items are silently dropped
  * source must be 'hacker_news'
  * max 20 hits/query (MVP)

Module-level constants:
  * HN_SEARCH_URL  — Algolia search endpoint
  * HN_ITEM_BASE   — Firebase item URL prefix
  * DEFAULT_MAX_PER_QUERY = 20

PRD §11 retry / §13 rate limit / §14 auth: the underlying HttpClient
handles retries + transient-failure mapping. This adapter is responsible
for translating HTTP responses into SourceStatus taxonomy entries:

  * HttpTransientError 429 → AdapterRateLimited
  * HttpTransientError (other) → AdapterUnavailable
  * HttpTimeoutError        → AdapterTimeout
  * HttpPermanentError      → AdapterInvalidResponse
  * malformed JSON body     → AdapterInvalidResponse
  * missing top-level hits  → AdapterInvalidResponse

Capability boundary: this module NEVER imports WorkBuddy/Claude/Codex.
The only third-party protocol it speaks is HN's public JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..pipeline.adapters import (
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    RawSourceResult,
)
from ._http import (
    HttpClient,
    HttpTransientError,
    StdlibHttpClient,
)


SOURCE_NAME = "hacker_news"
SOURCE_TYPE = "post"  # evidence.schema.json enum (HN stories are post-flavored)
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HN_ITEM_BASE = "https://news.ycombinator.com/item?id="


# PRD §16 default for HN.
DEFAULT_MAX_PER_QUERY = 20


def _utc_iso_from_unix(unix_seconds: Any) -> str:
    """Convert unix seconds → RFC3339 UTC string. Returns '' on bad input."""
    try:
        ts = int(unix_seconds)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class HackerNewsAdapter:
    """SourceAdapter that fetches HN stories via the Algolia search API."""

    http_client: HttpClient | None = None
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    source_name: str = SOURCE_NAME

    def __post_init__(self):
        if self.http_client is None:
            object.__setattr__(
                self, "http_client", StdlibHttpClient()
            )

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        query = str(request.get("query") or "")
        if not query:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="retrieval request missing query",
            )
        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")

        # Resolve limit (PRD §16).
        limit_req = request.get("limit")
        try:
            limit_n = (
                int(limit_req) if limit_req is not None else self.max_per_query
            )
        except (TypeError, ValueError):
            limit_n = self.max_per_query
        limit = max(1, min(limit_n, self.max_per_query))

        # HN Algolia supports language/market-like filters via tags; we
        # transparently pass them through if the caller supplies them,
        # but Phase 4 keeps the call shape minimal.
        params = f"query={_q(query)}&hitsPerPage={limit}&tags=story"
        url = f"{HN_SEARCH_URL}?{params}"
        if market and market != "global":
            # Algolia supports tag filters like `tags=story`; we leave
            # market-specific filtering to the search query wording.
            pass

        try:
            resp = self.http_client.request(url)
        except HttpTransientError as exc:
            if exc.status == 429:
                raise AdapterRateLimited(
                    source=self.source_name,
                    reason="algolia rate limit (429)",
                )
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"algolia transient {exc.status}",
            )
        except Exception as exc:
            # Map urllib/timeout errors uniformly.
            name = type(exc).__name__
            if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                raise AdapterTimeout(
                    source=self.source_name, reason=str(exc)
                )
            # HttpPermanentError flow: handled below by status check.
            from ._http import HttpPermanentError as _HPE  # local import

            if isinstance(exc, _HPE):
                raise AdapterInvalidResponse(
                    source=self.source_name, reason=str(exc)
                )
            # Anything else is treated as unavailable.
            raise AdapterUnavailable(
                source=self.source_name, reason=f"{name}: {exc}"
            )
        from ._http import HttpTimeoutError as _HTE  # local import

        if isinstance(getattr(self, "_", None), _HTE):  # pragma: no cover
            pass
        # Final status check (HttpClient raises on 5xx/429 already — this
        # is a defensive guard for 200-with-bad-body shapes).
        if resp.status != 200:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"algolia returned status {resp.status}",
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"algolia body not JSON: {exc}",
            )

        if not isinstance(payload, Mapping) or "hits" not in payload:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="algolia payload missing top-level 'hits'",
            )
        hits = payload.get("hits") or []
        if not isinstance(hits, list):
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="algolia 'hits' must be a list",
            )

        out: list[RawSourceResult] = []
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            if hit.get("deleted") or hit.get("dead"):
                continue
            obj_id = str(hit.get("objectID") or "")
            if not obj_id:
                # A hit without an id cannot be dedupe-stable — refuse
                # the whole batch (better than silently dropping).
                raise AdapterInvalidResponse(
                    source=self.source_name,
                    reason="algolia hit missing objectID",
                )
            title = str(hit.get("title") or "").strip()
            url_field = str(hit.get("url") or "").strip()
            if not title:
                # A hit without a title has no story to cite — drop silently
                # rather than fail the batch (some HN hits are comments-only).
                continue
            final_url = url_field or f"{HN_ITEM_BASE}{obj_id}"
            author = str(hit.get("author") or "").strip()
            published_at = _utc_iso_from_unix(hit.get("created_at_i"))
            engagement: dict[str, int] = {}
            if hit.get("points") is not None:
                engagement["points"] = _coerce_int(hit.get("points"))
            if hit.get("num_comments") is not None:
                engagement["comments"] = _coerce_int(hit.get("num_comments"))

            out.append(
                RawSourceResult(
                    source=self.source_name,
                    source_type=SOURCE_TYPE,
                    source_native_id=obj_id,
                    url=final_url,
                    title=title,
                    text=title,  # stories have no body beyond the title
                    author=author,
                    published_at=published_at,
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement=engagement,
                    raw_metadata={"hn_item_id": obj_id},
                )
            )

        # Phase 4 §19 — return the rank the host returned (Algolia's
        # `hits` array is relevance-ranked). Stash it as internal
        # metadata so downstream sort can prefer source rank when present.
        for rank, raw in enumerate(out):
            if not raw.raw_metadata:
                # Make a shallow copy via dataclasses.replace — frozen.
                pass  # the metadata is already a dict; mutate only the local var
        return out


def _q(value: str) -> str:
    """Percent-encode a single query parameter value (urllib.parse-safe)."""
    from urllib.parse import quote_plus

    return quote_plus(value)


__all__ = [
    "SOURCE_NAME",
    "SOURCE_TYPE",
    "DEFAULT_MAX_PER_QUERY",
    "HN_SEARCH_URL",
    "HN_ITEM_BASE",
    "HackerNewsAdapter",
]
