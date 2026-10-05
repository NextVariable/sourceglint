"""Bounded Hacker News story and comment retrieval through Algolia.

Keep original HN item URLs and publication timestamps. Runtime topic filtering
balances story/comment lanes and excludes canonical hiring threads unless the
query requests hiring. Failed lanes retain surviving results with limitations.
The HTTP client owns bounded retries and timeout handling; no auth is required.
"""
from __future__ import annotations

from html.parser import HTMLParser
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


class _CommentText(HTMLParser):
    """Decode provider markup without interpreting it as instructions."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _visible_comment(markup: str) -> str:
    parser = _CommentText()
    parser.feed(markup)
    return " ".join(" ".join(parser.parts).split())


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
    require_topic_match: bool = False
    limitations: list[str] = field(default_factory=list, init=False, compare=False)

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

        # Search stories and comments inside the requested publication window.
        # Market/language scope is expressed in query wording, not tag filters.
        from ._recency import search_bounds
        bounds = search_bounds(plan, request)
        search_limit = min(100, limit * 3) if self.require_topic_match else limit
        self.limitations.clear()
        from ._deep import subject_query
        search_query = subject_query(query) if self.require_topic_match else query
        lanes = ("story", "comment") if self.require_topic_match else ("(story,comment)",)
        hits = []
        errors = []
        succeeded = 0
        for lane in lanes:
            params = f"query={_q(search_query)}&hitsPerPage={search_limit}&tags={_q(lane)}"
            if bounds:
                start, end = bounds
                filters = f"created_at_i>={int(start.timestamp())},created_at_i<={int(end.timestamp())}"
                params += "&numericFilters=" + _q(filters)
            try:
                hits.extend(self._search_hits(f"{HN_SEARCH_URL}?{params}"))
                succeeded += 1
            except (AdapterRateLimited, AdapterUnavailable, AdapterTimeout, AdapterInvalidResponse) as exc:
                errors.append(exc)
                self.limitations.append(f"HN {lane} search failed: {type(exc).__name__}")
        if not succeeded:
            raise errors[0]

        out: list[RawSourceResult] = []
        seen = set()
        hiring_dropped = 0
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
            if obj_id in seen:
                continue
            seen.add(obj_id)
            title = str(hit.get("title") or "").strip()
            comment = str(hit.get("comment_text") or "").strip()
            is_comment = bool(comment)
            if is_comment:
                title = str(hit.get("story_title") or title or "Hacker News comment").strip()
            if self.require_topic_match and _hiring_thread(title) and not _hiring_intent(query):
                hiring_dropped += 1
                continue
            url_field = str(hit.get("url") or "").strip()
            if not title:
                # A hit without a title has no story to cite — drop silently
                # rather than fail the batch (some HN hits are comments-only).
                continue
            final_url = f"{HN_ITEM_BASE}{obj_id}"
            visible_body = _visible_comment(comment if is_comment else str(hit.get("story_text") or ""))
            if self.require_topic_match:
                from ._deep import subject_present
                if not subject_present({"title": title, "body": visible_body, "html_url": url_field}, query):
                    continue
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
                    source_type="comment" if is_comment else SOURCE_TYPE,
                    source_native_id=obj_id,
                    url=final_url,
                    title=title,
                    text=visible_body or title,
                    author=author,
                    published_at=published_at,
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement=engagement,
                    raw_metadata={"hn_item_id": obj_id, "hn_story_id": hit.get("story_id"), "external_url": url_field, "hn_comment_html": comment if is_comment else "", "search_query": search_query},
                )
            )

        if hiring_dropped:
            self.limitations.append(f"HN excluded {hiring_dropped} canonical hiring-thread hits for a non-hiring query")
        if not self.require_topic_match:
            return out[:limit]
        # Reserve room for independently published stories and dated comments.
        stories = [row for row in out if row.source_type != "comment"]
        comments = [row for row in out if row.source_type == "comment"]
        from ._deep import intent_rank
        for lane in (stories, comments):
            lane.sort(key=lambda row: intent_rank({"title": row.title, "body": row.text}, query), reverse=True)
        selected = stories[:(limit + 1) // 2] + comments[:limit // 2]
        selected_ids = {row.source_native_id for row in selected}
        selected.extend(row for row in stories + comments if row.source_native_id not in selected_ids)
        return selected[:limit]

    def _search_hits(self, url):
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

        return hits


def _hiring_thread(title: str) -> bool:
    import re
    return bool(re.match(
        r"^ask hn:\s*(?:who(?: is|’s|'s)? hiring|who wants to be hired|freelancer\?\s*seeking freelancer\?)(?:\s*\(|\s*\?|\s*$)",
        title.casefold(),
    ))


def _hiring_intent(query: str) -> bool:
    import re
    return bool(re.search(r"\b(?:jobs?|hiring|hired|recruit\w*|careers?|freelanc\w*)\b|招聘|求职", query.casefold()))


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
