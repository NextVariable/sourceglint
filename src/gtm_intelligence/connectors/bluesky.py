"""Bluesky public post-search adapter.

Most ``app.bsky.*`` GET endpoints are public through the Bluesky AppView.
This adapter uses only the documented ``app.bsky.feed.searchPosts`` endpoint;
it does not log in, scrape HTML, or access private account data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote_plus

from ..pipeline.adapters import (
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    RawSourceResult,
)
from ._http import (
    HttpClient,
    HttpPermanentError,
    HttpTimeoutError,
    HttpTransientError,
    StdlibHttpClient,
)


SOURCE_NAME = "bluesky"
SOURCE_TYPE = "post"
BLUESKY_SEARCH_URL = (
    "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
)
DEFAULT_MAX_PER_QUERY = 20


def _count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _post_url(handle: str, uri: str) -> str:
    rkey = uri.rsplit("/", 1)[-1] if uri else ""
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


@dataclass(frozen=True)
class BlueskyAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    source_name: str = SOURCE_NAME

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        query = str(request.get("query") or "").strip()
        if not query:
            raise AdapterInvalidResponse(
                source=self.source_name, reason="retrieval request missing query"
            )
        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")
        try:
            requested_limit = int(request.get("limit") or self.max_per_query)
        except (TypeError, ValueError):
            requested_limit = self.max_per_query
        limit = max(1, min(requested_limit, self.max_per_query, 100))
        url = (
            f"{BLUESKY_SEARCH_URL}?q={quote_plus(query)}"
            f"&limit={limit}&sort=latest"
        )
        if language:
            url += f"&lang={quote_plus(language)}"

        try:
            response = self.http_client.request(url)
        except HttpTransientError as exc:
            if exc.status == 429:
                raise AdapterRateLimited(self.source_name, "bluesky 429")
            raise AdapterUnavailable(
                self.source_name, f"bluesky transient {exc.status}"
            )
        except HttpTimeoutError as exc:
            raise AdapterTimeout(self.source_name, str(exc))
        except HttpPermanentError as exc:
            raise AdapterInvalidResponse(
                self.source_name, f"bluesky returned {exc.status}"
            )
        except Exception as exc:
            raise AdapterUnavailable(
                self.source_name, f"{type(exc).__name__}: {exc}"
            )

        if response.status != 200:
            raise AdapterInvalidResponse(
                self.source_name, f"bluesky returned status {response.status}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise AdapterInvalidResponse(
                self.source_name, f"bluesky body not JSON: {exc}"
            )
        posts = payload.get("posts") if isinstance(payload, Mapping) else None
        if not isinstance(posts, list):
            raise AdapterInvalidResponse(
                self.source_name, "bluesky payload missing posts array"
            )

        out: list[RawSourceResult] = []
        for post in posts:
            if not isinstance(post, Mapping):
                continue
            uri = str(post.get("uri") or "").strip()
            cid = str(post.get("cid") or "").strip()
            author = post.get("author")
            record = post.get("record")
            if (
                not uri
                or not cid
                or not isinstance(author, Mapping)
                or not isinstance(record, Mapping)
            ):
                raise AdapterInvalidResponse(
                    self.source_name,
                    "bluesky post missing uri/cid/author/record",
                )
            handle = str(author.get("handle") or "").strip()
            text = str(record.get("text") or "").strip()
            published_at = str(record.get("createdAt") or "").strip()
            if not handle or not text or not published_at:
                continue
            out.append(
                RawSourceResult(
                    source=self.source_name,
                    source_type=SOURCE_TYPE,
                    source_native_id=cid,
                    url=_post_url(handle, uri),
                    title=text[:120],
                    text=text,
                    author=handle,
                    published_at=published_at,
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement={
                        "likes": _count(post.get("likeCount")),
                        "comments": _count(post.get("replyCount")),
                        "upvotes": _count(post.get("repostCount")),
                    },
                    raw_metadata={"bluesky_uri": uri},
                )
            )
        return out


__all__ = [
    "BLUESKY_SEARCH_URL",
    "BlueskyAdapter",
    "DEFAULT_MAX_PER_QUERY",
    "SOURCE_NAME",
    "SOURCE_TYPE",
]
