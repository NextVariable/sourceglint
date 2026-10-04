"""GitHub real source adapter (Phase 4 §8).

Backend: GitHub REST API. NO HTML scraping. We DO NOT call any unofficial
endpoint, do NOT store credentials, and DO NOT log or echo tokens.

PRD §8 rules:
  * public anonymous API works (60 req/h). `GITHUB_TOKEN` is optional
    and lifts the budget to 5000 req/h.
  * MVP scope (PRD §15 + §8): search repositories. The sources config
    was aligned to this reality (Phase 4 §44): the github entry lists
    only `search` — it must never out-claim the adapter. A future
    adapter may add `releases`, but that is intentionally out of scope
    for this commit (PRD §8 explicitly says "doesn't need all GitHub
    objects at once").
  * `created_at` ≠ `published_at` ≠ `updated_at`. We use `created_at`
    for the canonical published date unless missing (in which case the
    item is dropped — Closeout §3 invariant: unknown ≠ neutral).
  * No rounding / smoothing of star/issue counters — raw ints only.

Failure-mode mapping:
  * HTTP 401 (with token) → AdapterAuthMissing
  * HTTP 403/429         → AdapterRateLimited
  * HTTP 5xx             → AdapterUnavailable
  * HttpTimeoutError     → AdapterTimeout
  * HttpPermanentError   → AdapterInvalidResponse
  * malformed JSON       → AdapterInvalidResponse
  * missing top-level 'items' → AdapterInvalidResponse
  * missing id/full_name → AdapterInvalidResponse (silent drops hide
                                 contract violations)

Capability boundary:
  * No WorkBuddy/Claude/Codex imports.
  * The token comes in via constructor injection only. We never read the
    environment directly inside this module — host integration layers
    decide how to source it (matches PRD §5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

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
    HttpTransientError,
    StdlibHttpClient,
)


SOURCE_NAME = "github"
# Repository creation is page metadata, not a release event.
SOURCE_TYPE = "page"


GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"


# PRD §16 default for GitHub search.
DEFAULT_MAX_PER_QUERY = 20


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class GitHubAdapter:
    """SourceAdapter that hits GitHub's search/repositories endpoint."""

    http_client: HttpClient | None = None
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    source_name: str = SOURCE_NAME
    # Token in constructor only — never read environment here (PRD §5 boundary).
    token: str | None = None
    include_discussions: bool = False
    limitations: list[str] = field(default_factory=list, compare=False)

    def __post_init__(self):
        if self.http_client is None:
            object.__setattr__(self, "http_client", StdlibHttpClient())

    @property
    def name(self) -> str:
        return self.source_name

    # ------------------------------------------------------------------

    def retrieve(
        self,
        plan: Mapping[str, object],
        request: Mapping[str, object],
    ) -> list[RawSourceResult]:
        query = str(request.get("query") or "")
        if not query:
            raise AdapterInvalidResponse(
                source=self.source_name, reason="retrieval request missing query"
            )
        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")

        # Limit clamp per PRD §16.
        limit_req = request.get("limit")
        try:
            limit_n = int(limit_req) if limit_req is not None else self.max_per_query
        except (TypeError, ValueError):
            limit_n = self.max_per_query
        per_page = max(1, min(limit_n, self.max_per_query))

        # Compose the URL. PRD §8: simple search-by-query, sort by
        # updated_at (most recently active first is the natural MVP
        # read for competitor monitoring).
        from urllib.parse import quote_plus

        from ._recency import search_bounds
        bounds = search_bounds(plan, request)
        if bounds:
            start, end = bounds
            query_filter = f"{query} created:{start.date().isoformat()}..{end.date().isoformat()}"
        else:
            query_filter = query
        q = quote_plus(query_filter)
        url = (
            f"{GITHUB_SEARCH_URL}?q={q}&per_page={per_page}&sort=updated&order=desc"
        )

        # Build headers. Token presence → authenticated.
        token = (self.token or "").strip()
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Issue the request. Map HTTP-level errors to our taxonomy.
        try:
            resp = self.http_client.request(url, headers=headers)
        except HttpTransientError as exc:
            # GitHub says 403 here is almost always abuse-detection
            # (rate limit / secondary rate limit). Treat as rate limited.
            if exc.status in (403, 429):
                raise AdapterRateLimited(
                    source=self.source_name,
                    reason=f"github {exc.status}",
                )
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"github transient {exc.status}",
            )
        except Exception as exc:
            from ._http import HttpPermanentError as _HPE, HttpTimeoutError as _HTE

            if isinstance(exc, _HPE) and exc.status == 401:
                # With a token, 401 means the token is bad; with no
                # token it would be received as a transient 401. We
                # only classify AuthMissing when a token was sent —
                # otherwise the orchestrator should see it as
                # AuthMissing too (private repos for an unauth'd call).
                raise AdapterAuthMissing(
                    source=self.source_name,
                    reason="github returned 401",
                )
            if isinstance(exc, _HTE):
                raise AdapterTimeout(
                    source=self.source_name, reason=str(exc)
                )
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"{type(exc).__name__}: {exc}",
            )

        if resp.status != 200:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"github returned status {resp.status}",
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"github body not JSON: {exc}",
            )

        if not isinstance(payload, Mapping) or "items" not in payload:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="github payload missing top-level 'items'",
            )
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="github 'items' must be a list",
            )

        out: list[RawSourceResult] = []
        for repo in items:
            if not isinstance(repo, Mapping):
                continue
            full_name = str(repo.get("full_name") or "").strip()
            repo_id = repo.get("id")
            if not full_name or repo_id is None:
                # Silent drop would hide a contract violation. Refuse
                # the whole batch to surface the upstream inconsistency.
                raise AdapterInvalidResponse(
                    source=self.source_name,
                    reason="github item missing full_name/id",
                )
            html_url = str(repo.get("html_url") or f"https://github.com/{full_name}")
            description = str(repo.get("description") or "").strip()

            owner_login = ""
            owner = repo.get("owner")
            if isinstance(owner, Mapping):
                owner_login = str(owner.get("login") or "").strip()

            # Publish the actual repository creation date. Updated metadata
            # is retained separately and must not be presented as a release.
            created_at = str(repo.get("created_at") or "").strip()
            if not created_at:
                # Closeout §3: unknown ≠ neutral. Skip the repo rather
                # than emit "" as a published date.
                continue

            engagement: dict[str, int] = {}
            if "stargazers_count" in repo:
                engagement["upvotes"] = _coerce_int(repo.get("stargazers_count"))

            out.append(
                RawSourceResult(
                    source=self.source_name,
                    source_type=SOURCE_TYPE,
                    source_native_id=full_name,
                    url=html_url,
                    title=full_name,
                    text=description,
                    author=owner_login,
                    published_at=created_at,
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement=engagement,
                    raw_metadata={
                        "github_full_name": full_name,
                        "github_repo_id": repo_id,
                        "github_language": str(repo.get("language") or ""),
                        "github_pushed_at": str(repo.get("pushed_at") or ""),
                        "github_updated_at": str(repo.get("updated_at") or ""),
                        "github_forks_count": _coerce_int(repo.get("forks_count")),
                    },
                )
            )

        if self.include_discussions:
            from ._deep import issue_results
            out.extend(issue_results(self.http_client, str(request.get("query") or ""), plan, request, headers, self.limitations, per_page))
        return out


__all__ = [
    "SOURCE_NAME",
    "SOURCE_TYPE",
    "GITHUB_SEARCH_URL",
    "DEFAULT_MAX_PER_QUERY",
    "GitHubAdapter",
]
