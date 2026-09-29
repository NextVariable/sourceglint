"""Credential-free connectors for public research and developer APIs.

Each adapter performs a real topic search and maps only fields returned by the
upstream API.  The adapters deliberately share transport/error handling while
keeping source-specific request and mapping logic explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlencode
from xml.etree import ElementTree

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
    return value


def _days(plan: Mapping[str, object]) -> int:
    window = plan.get("time_window")
    if isinstance(window, Mapping):
        try:
            return max(1, min(int(window.get("days") or 30), 365))
        except (TypeError, ValueError):
            pass
    return 30


def _as_of(request: Mapping[str, object]) -> datetime | None:
    raw = str(request.get("retrieved_at") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _date_start(plan: Mapping[str, object], request: Mapping[str, object]) -> datetime | None:
    end = _as_of(request)
    return end - timedelta(days=_days(plan)) if end else None


def _rfc3339(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return ""
    raw = str(value).strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        raw += "T00:00:00Z"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _get(http: HttpClient, source: str, url: str):
    try:
        return http.request(url)
    except HttpTransientError as exc:
        if exc.status == 429:
            raise AdapterRateLimited(source, "upstream rate limit") from exc
        raise AdapterUnavailable(source, f"upstream transient error {exc.status}") from exc
    except HttpTimeoutError as exc:
        raise AdapterTimeout(source, str(exc)) from exc
    except HttpPermanentError as exc:
        raise AdapterInvalidResponse(source, str(exc)) from exc
    except Exception as exc:
        raise AdapterUnavailable(source, f"{type(exc).__name__}: {exc}") from exc


def _get_with_headers(
    http: HttpClient,
    source: str,
    url: str,
    headers: Mapping[str, str],
):
    try:
        return http.request(url, headers=headers)
    except HttpTransientError as exc:
        if exc.status == 429:
            raise AdapterRateLimited(source, "upstream rate limit") from exc
        raise AdapterUnavailable(source, f"upstream transient error {exc.status}") from exc
    except HttpTimeoutError as exc:
        raise AdapterTimeout(source, str(exc)) from exc
    except HttpPermanentError as exc:
        raise AdapterInvalidResponse(source, str(exc)) from exc
    except Exception as exc:
        raise AdapterUnavailable(source, f"{type(exc).__name__}: {exc}") from exc


def _json(http: HttpClient, source: str, url: str) -> Any:
    response = _get(http, source, url)
    if response.status != 200:
        raise AdapterInvalidResponse(source, f"upstream returned {response.status}")
    try:
        return response.json()
    except Exception as exc:
        raise AdapterInvalidResponse(source, "upstream body was not JSON") from exc


@dataclass(frozen=True)
class StackOverflowAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "stack_overflow"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        params: dict[str, object] = {
            "site": "stackoverflow",
            "q": query,
            "sort": "creation",
            "order": "desc",
            "pagesize": _limit(request, self.max_per_query),
        }
        start = _date_start(plan, request)
        if start:
            params["fromdate"] = int(start.timestamp())
        payload = _json(self.http_client, self.source_name, f"https://api.stackexchange.com/2.3/search/advanced?{urlencode(params)}")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
            raise AdapterInvalidResponse(self.source_name, "payload missing items")
        out: list[RawSourceResult] = []
        for item in payload["items"]:
            if not isinstance(item, Mapping):
                continue
            native_id = str(item.get("question_id") or "")
            title = str(item.get("title") or "").strip()
            url = str(item.get("link") or "").strip()
            published = _rfc3339(item.get("creation_date"))
            if not native_id or not title or not url or not published:
                continue
            owner = item.get("owner") if isinstance(item.get("owner"), Mapping) else {}
            out.append(RawSourceResult(
                source=self.source_name, source_type="post", source_native_id=native_id,
                url=url, title=title, text=title, author=str(owner.get("display_name") or ""),
                published_at=published, market=str(request.get("market") or "global"),
                language=str(request.get("query_language") or "en"), query=query,
                query_language=str(request.get("query_language") or "en"),
                engagement={"points": _integer(item.get("score")), "comments": _integer(item.get("answer_count")), "views": _integer(item.get("view_count"))},
                raw_metadata={"tags": list(item.get("tags") or []), "is_answered": bool(item.get("is_answered"))},
            ))
        return out


@dataclass(frozen=True)
class DevToAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "devto"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        params = {"q": query, "top": _days(plan), "per_page": _limit(request, self.max_per_query)}
        payload = _json(self.http_client, self.source_name, f"https://dev.to/api/articles/search?{urlencode(params)}")
        if not isinstance(payload, list):
            raise AdapterInvalidResponse(self.source_name, "payload was not a list")
        out: list[RawSourceResult] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            native_id = str(item.get("id") or "")
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            published = _rfc3339(item.get("published_timestamp") or item.get("published_at"))
            if not native_id or not title or not url or not published:
                continue
            user = item.get("user") if isinstance(item.get("user"), Mapping) else {}
            text = str(item.get("description") or title).strip()
            out.append(RawSourceResult(
                source=self.source_name, source_type="post", source_native_id=native_id,
                url=url, title=title, text=text, author=str(user.get("username") or user.get("name") or ""),
                published_at=published, market=str(request.get("market") or "global"), language="en",
                query=query, query_language=str(request.get("query_language") or "en"),
                engagement={"likes": _integer(item.get("public_reactions_count") or item.get("positive_reactions_count")), "comments": _integer(item.get("comments_count"))},
                raw_metadata={"tags": item.get("tag_list") or item.get("tags") or []},
            ))
        return out


@dataclass(frozen=True)
class HuggingFaceAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "hugging_face"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        params = {"search": query, "sort": "lastModified", "direction": -1, "limit": _limit(request, self.max_per_query), "full": "true"}
        payload = _json(self.http_client, self.source_name, f"https://huggingface.co/api/models?{urlencode(params)}")
        if not isinstance(payload, list):
            raise AdapterInvalidResponse(self.source_name, "payload was not a list")
        out: list[RawSourceResult] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            native_id = str(item.get("modelId") or item.get("id") or "").strip()
            published = _rfc3339(item.get("lastModified") or item.get("createdAt"))
            if not native_id or not published:
                continue
            pipeline_tag = str(item.get("pipeline_tag") or "").strip()
            out.append(RawSourceResult(
                source=self.source_name, source_type="page", source_native_id=native_id,
                url=f"https://huggingface.co/{native_id}", title=native_id,
                text=(f"{native_id} — {pipeline_tag}" if pipeline_tag else native_id),
                author=native_id.split("/", 1)[0] if "/" in native_id else "",
                published_at=published, market="global", language="en", query=query,
                query_language=str(request.get("query_language") or "en"),
                engagement={"likes": _integer(item.get("likes"))},
                raw_metadata={"downloads": _integer(item.get("downloads")), "pipeline_tag": pipeline_tag, "tags": list(item.get("tags") or [])},
            ))
        return out


@dataclass(frozen=True)
class PackageRegistriesAdapter:
    """Topic search over npm's public registry search API.

    The catalog groups several package registries under one source name.  This
    first direct lane is npm only; PyPI and crates.io remain host-search
    fallbacks until they expose an equivalent supported full-text API.
    """

    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "package_registries"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        params = {"text": query, "size": _limit(request, self.max_per_query)}
        payload = _json(self.http_client, self.source_name, f"https://registry.npmjs.org/-/v1/search?{urlencode(params)}")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("objects"), list):
            raise AdapterInvalidResponse(self.source_name, "payload missing objects")
        out: list[RawSourceResult] = []
        for wrapper in payload["objects"]:
            if not isinstance(wrapper, Mapping) or not isinstance(wrapper.get("package"), Mapping):
                continue
            package = wrapper["package"]
            name = str(package.get("name") or "").strip()
            version = str(package.get("version") or "").strip()
            published = _rfc3339(package.get("date"))
            links = package.get("links") if isinstance(package.get("links"), Mapping) else {}
            url = str(links.get("npm") or (f"https://www.npmjs.com/package/{name}" if name else ""))
            if not name or not version or not published or not url:
                continue
            author = package.get("author") if isinstance(package.get("author"), Mapping) else {}
            publisher = package.get("publisher") if isinstance(package.get("publisher"), Mapping) else {}
            score = wrapper.get("score") if isinstance(wrapper.get("score"), Mapping) else {}
            out.append(RawSourceResult(
                source=self.source_name, source_type="release",
                source_native_id=f"npm:{name}@{version}", url=url,
                title=f"{name} {version}", text=str(package.get("description") or name),
                author=str(author.get("name") or publisher.get("username") or ""),
                published_at=published, market="global", language="en", query=query,
                query_language=str(request.get("query_language") or "en"),
                raw_metadata={"registry": "npm", "package": name, "version": version, "search_score": score.get("final")},
            ))
        return out


@dataclass(frozen=True)
class SemanticScholarAdapter:
    http_client: HttpClient | None = None
    api_key: str | None = None
    max_per_query: int = 20
    source_name: str = "semantic_scholar"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        if not self.api_key:
            from ..pipeline.adapters import AdapterAuthMissing
            raise AdapterAuthMissing(
                self.source_name,
                "SEMANTIC_SCHOLAR_API_KEY is required for a reliable live route",
            )
        query = _query(request, self.source_name).replace("-", " ")
        params: dict[str, object] = {"query": query, "limit": _limit(request, self.max_per_query), "fields": "title,url,abstract,authors,publicationDate,citationCount,externalIds"}
        end = _as_of(request)
        if end:
            params["year"] = f"{(end - timedelta(days=_days(plan))).year}-{end.year}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{urlencode(params)}"
        response = _get_with_headers(
            self.http_client,
            self.source_name,
            url,
            {"x-api-key": self.api_key},
        )
        try:
            payload = response.json()
        except Exception as exc:
            raise AdapterInvalidResponse(self.source_name, "upstream body was not JSON") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise AdapterInvalidResponse(self.source_name, "payload missing data")
        out: list[RawSourceResult] = []
        for item in payload["data"]:
            if not isinstance(item, Mapping):
                continue
            native_id = str(item.get("paperId") or "")
            title = str(item.get("title") or "").strip()
            published = _rfc3339(item.get("publicationDate"))
            if not native_id or not title or not published:
                continue
            authors = item.get("authors") if isinstance(item.get("authors"), list) else []
            names = [str(x.get("name")) for x in authors if isinstance(x, Mapping) and x.get("name")]
            out.append(RawSourceResult(
                source=self.source_name, source_type="page", source_native_id=native_id,
                url=str(item.get("url") or f"https://www.semanticscholar.org/paper/{native_id}"),
                title=title, text=str(item.get("abstract") or title), author=", ".join(names[:4]),
                published_at=published, market="global", language="en", query=query,
                query_language=str(request.get("query_language") or "en"),
                raw_metadata={"citation_count": _integer(item.get("citationCount")), "external_ids": dict(item.get("externalIds") or {})},
            ))
        return out


@dataclass(frozen=True)
class QiitaAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "qiita"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        start = _date_start(plan, request)
        api_query = f"{query} created:>={start.date().isoformat()}" if start else query
        params = {"query": api_query, "page": 1, "per_page": _limit(request, self.max_per_query)}
        payload = _json(self.http_client, self.source_name, f"https://qiita.com/api/v2/items?{urlencode(params)}")
        if not isinstance(payload, list):
            raise AdapterInvalidResponse(self.source_name, "payload was not a list")
        out: list[RawSourceResult] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            native_id = str(item.get("id") or "")
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            published = _rfc3339(item.get("created_at"))
            if not native_id or not title or not url or not published:
                continue
            user = item.get("user") if isinstance(item.get("user"), Mapping) else {}
            out.append(RawSourceResult(
                source=self.source_name, source_type="post", source_native_id=native_id,
                url=url, title=title, text=str(item.get("body") or title),
                author=str(user.get("id") or user.get("name") or ""), published_at=published,
                market="jp", language="ja", query=query,
                query_language=str(request.get("query_language") or "ja"),
                engagement={"likes": _integer(item.get("likes_count") or item.get("reactions_count")), "comments": _integer(item.get("comments_count")), "views": _integer(item.get("page_views_count"))},
                raw_metadata={"tags": [str(x.get("name")) for x in item.get("tags", []) if isinstance(x, Mapping) and x.get("name")], "stocks": _integer(item.get("stocks_count"))},
            ))
        return out


@dataclass(frozen=True)
class ArxivAdapter:
    http_client: HttpClient | None = None
    max_per_query: int = 20
    source_name: str = "arxiv"

    def __post_init__(self) -> None:
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    def retrieve(self, plan: Mapping[str, object], request: Mapping[str, object]) -> list[RawSourceResult]:
        query = _query(request, self.source_name)
        expression = f'all:"{query}"'
        start = _date_start(plan, request)
        end = _as_of(request)
        if start and end:
            expression += f" AND submittedDate:[{start.strftime('%Y%m%d%H%M')} TO {end.strftime('%Y%m%d%H%M')}]"
        params = {"search_query": expression, "start": 0, "max_results": _limit(request, self.max_per_query), "sortBy": "submittedDate", "sortOrder": "descending"}
        response = _get(self.http_client, self.source_name, f"https://export.arxiv.org/api/query?{urlencode(params)}")
        try:
            root = ElementTree.fromstring(response.body)
        except ElementTree.ParseError as exc:
            raise AdapterInvalidResponse(self.source_name, "upstream body was not Atom XML") from exc
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out: list[RawSourceResult] = []
        for entry in root.findall("a:entry", ns):
            native_url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
            native_id = native_url.rsplit("/", 1)[-1]
            title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
            published = _rfc3339(entry.findtext("a:published", default="", namespaces=ns))
            if not native_id or not native_url or not title or not published:
                continue
            authors = [x.findtext("a:name", default="", namespaces=ns) for x in entry.findall("a:author", ns)]
            summary = " ".join((entry.findtext("a:summary", default="", namespaces=ns) or title).split())
            out.append(RawSourceResult(
                source=self.source_name, source_type="page", source_native_id=native_id,
                url=native_url.replace("http://", "https://"), title=title, text=summary,
                author=", ".join(x for x in authors[:4] if x), published_at=published,
                market="global", language="en", query=query,
                query_language=str(request.get("query_language") or "en"),
            ))
        return out
