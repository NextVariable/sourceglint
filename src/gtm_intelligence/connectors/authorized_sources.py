"""Official, credential-gated connectors for high-value discovery sources."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping
from urllib.parse import urlencode

from ..pipeline.adapters import (
    AdapterAuthMissing,
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
from ._query import compact_search_query


def _limit(request: Mapping[str, object], maximum: int = 20) -> int:
    try:
        value = int(request.get("limit") or maximum)
    except (TypeError, ValueError):
        value = maximum
    return max(1, min(value, maximum))


def _query(request: Mapping[str, object], source: str) -> str:
    value = str(request.get("query") or "").strip()
    if not value:
        raise AdapterInvalidResponse(source, "retrieval request missing query")
    return compact_search_query(value)


def _as_of(request: Mapping[str, object], source: str) -> datetime:
    raw = str(request.get("retrieved_at") or "").strip()
    if not raw:
        raise AdapterInvalidResponse(source, "retrieved_at is required")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise AdapterInvalidResponse(source, "retrieved_at is not RFC3339") from exc


def _days(plan: Mapping[str, object]) -> int:
    window = plan.get("time_window")
    if isinstance(window, Mapping):
        try:
            return max(1, min(int(window.get("days") or 30), 365))
        except (TypeError, ValueError):
            pass
    return 30


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class XAdapter:
    bearer_token: str | None = None
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "x"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def _search(self, endpoint: str, params: Mapping[str, object]):
        url = f"{endpoint}?{urlencode(params)}"
        try:
            return self.http_client.request(
                url,
                headers={"Authorization": f"Bearer {self.bearer_token}"},
            )
        except HttpTransientError as exc:
            if exc.status == 429:
                raise AdapterRateLimited(self.source_name, "X API rate limit") from exc
            raise AdapterUnavailable(self.source_name, f"X API transient {exc.status}") from exc
        except HttpTimeoutError as exc:
            raise AdapterTimeout(self.source_name, str(exc)) from exc

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        if not self.bearer_token:
            raise AdapterAuthMissing(self.source_name, "X_BEARER_TOKEN is required")
        query = _query(request, self.source_name)
        requested_limit = _limit(request, self.max_per_query)
        end = _as_of(request, self.source_name)
        start = end - timedelta(days=_days(plan))
        common: dict[str, object] = {
            "query": f"({query}) -is:retweet",
            "max_results": max(10, min(requested_limit, 100)),
            "start_time": _iso(start),
            "end_time": _iso(end),
            "tweet.fields": "created_at,lang,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        route = "full_archive"
        coverage_days = _days(plan)
        try:
            response = self._search("https://api.x.com/2/tweets/search/all", common)
        except HttpPermanentError as exc:
            if exc.status == 401:
                raise AdapterAuthMissing(self.source_name, "X bearer token rejected") from exc
            if exc.status not in (402, 403):
                raise AdapterInvalidResponse(self.source_name, f"X API returned {exc.status}") from exc
            route = "recent"
            coverage_days = min(7, _days(plan))
            recent_params = dict(common)
            recent_params["start_time"] = _iso(end - timedelta(days=coverage_days))
            try:
                response = self._search("https://api.x.com/2/tweets/search/recent", recent_params)
            except HttpPermanentError as recent_exc:
                if recent_exc.status in (401, 403):
                    raise AdapterAuthMissing(self.source_name, "X API access is not authorized") from recent_exc
                if recent_exc.status == 402:
                    raise AdapterUnavailable(self.source_name, "X API credits are unavailable") from recent_exc
                raise AdapterInvalidResponse(self.source_name, f"X API returned {recent_exc.status}") from recent_exc
        try:
            payload = response.json()
        except Exception as exc:
            raise AdapterInvalidResponse(self.source_name, "X API body was not JSON") from exc
        if not isinstance(payload, Mapping):
            raise AdapterInvalidResponse(self.source_name, "X API payload was not an object")
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise AdapterInvalidResponse(self.source_name, "X API data was not a list")
        includes = payload.get("includes") if isinstance(payload.get("includes"), Mapping) else {}
        users = includes.get("users") if isinstance(includes.get("users"), list) else []
        handles = {
            str(user.get("id")): str(user.get("username"))
            for user in users if isinstance(user, Mapping) and user.get("id") and user.get("username")
        }
        output: list[RawSourceResult] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            post_id = str(row.get("id") or "")
            text = str(row.get("text") or "").strip()
            published = str(row.get("created_at") or "")
            author_id = str(row.get("author_id") or "")
            handle = handles.get(author_id, "")
            if not post_id or not text or not published or not handle:
                continue
            metrics = row.get("public_metrics") if isinstance(row.get("public_metrics"), Mapping) else {}
            output.append(RawSourceResult(
                source=self.source_name, source_type="post", source_native_id=post_id,
                url=f"https://x.com/{handle}/status/{post_id}", title=text[:120], text=text,
                author=handle, published_at=published,
                market=str(request.get("market") or "global"),
                language=str(row.get("lang") or request.get("query_language") or "en"),
                query=query, query_language=str(request.get("query_language") or "en"),
                engagement={
                    "likes": _count(metrics.get("like_count")),
                    "comments": _count(metrics.get("reply_count")),
                    "upvotes": _count(metrics.get("retweet_count")) + _count(metrics.get("quote_count")),
                },
                raw_metadata={"route": route, "coverage_days": coverage_days, "author_id": author_id},
            ))
            if len(output) >= requested_limit:
                break
        return output


@dataclass(frozen=True)
class ProductHuntAdapter:
    token: str | None = None
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "product_hunt"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        if not self.token:
            raise AdapterAuthMissing(self.source_name, "PRODUCT_HUNT_TOKEN is required")
        query = _query(request, self.source_name)
        limit = _limit(request, self.max_per_query)
        end = _as_of(request, self.source_name)
        start = end - timedelta(days=_days(plan))
        graphql = """
        query RecentPosts($first: Int!, $postedAfter: DateTime!, $postedBefore: DateTime!) {
          posts(first: $first, order: NEWEST, postedAfter: $postedAfter, postedBefore: $postedBefore) {
            nodes { id name tagline description url website votesCount commentsCount createdAt user { username } }
          }
        }
        """
        try:
            response = self.http_client.request(
                "https://api.producthunt.com/v2/api/graphql",
                method="POST",
                headers={"Authorization": f"Bearer {self.token}"},
                json_data={
                    "query": graphql,
                    "variables": {
                        "first": min(100, max(20, limit * 5)),
                        "postedAfter": _iso(start),
                        "postedBefore": _iso(end),
                    },
                },
            )
        except HttpTransientError as exc:
            if exc.status == 429:
                raise AdapterRateLimited(self.source_name, "Product Hunt rate limit") from exc
            raise AdapterUnavailable(self.source_name, f"Product Hunt transient {exc.status}") from exc
        except HttpTimeoutError as exc:
            raise AdapterTimeout(self.source_name, str(exc)) from exc
        except HttpPermanentError as exc:
            if exc.status in (401, 403):
                raise AdapterAuthMissing(self.source_name, "Product Hunt token rejected") from exc
            raise AdapterInvalidResponse(self.source_name, f"Product Hunt returned {exc.status}") from exc
        try:
            payload = response.json()
        except Exception as exc:
            raise AdapterInvalidResponse(self.source_name, "Product Hunt body was not JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise AdapterInvalidResponse(self.source_name, "Product Hunt GraphQL returned errors")
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
        posts = data.get("posts") if isinstance(data.get("posts"), Mapping) else {}
        nodes = posts.get("nodes") if isinstance(posts.get("nodes"), list) else None
        if nodes is None:
            raise AdapterInvalidResponse(self.source_name, "Product Hunt payload missing posts.nodes")
        terms = [term.casefold() for term in query.split() if len(term) > 1]
        output: list[RawSourceResult] = []
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            post_id = str(node.get("id") or "")
            name = str(node.get("name") or "").strip()
            tagline = str(node.get("tagline") or "").strip()
            description = str(node.get("description") or "").strip()
            haystack = f"{name} {tagline} {description}".casefold()
            if terms and not any(term in haystack for term in terms):
                continue
            url = str(node.get("url") or "").strip()
            published = str(node.get("createdAt") or "").strip()
            if not post_id or not name or not url or not published:
                continue
            user = node.get("user") if isinstance(node.get("user"), Mapping) else {}
            output.append(RawSourceResult(
                source=self.source_name, source_type="post", source_native_id=post_id,
                url=url, title=name, text=description or tagline or name,
                author=str(user.get("username") or ""), published_at=published,
                market="global", language="en", query=query,
                query_language=str(request.get("query_language") or "en"),
                engagement={"upvotes": _count(node.get("votesCount")), "comments": _count(node.get("commentsCount"))},
                raw_metadata={"tagline": tagline, "website": str(node.get("website") or ""), "filter": "local_recent_posts"},
            ))
            if len(output) >= limit:
                break
        return output


__all__ = ["ProductHuntAdapter", "XAdapter"]
