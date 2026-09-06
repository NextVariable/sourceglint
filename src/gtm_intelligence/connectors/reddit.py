"""Reddit real source adapter (Phase 4 §9).

LEGAL / POLICY posture
---------------------
Reddit's official API requires OAuth2 authentication since 2023. This
adapter uses the official `client_credentials` grant, against the LEGITIMATE
endpoint `https://www.reddit.com/api/v1/access_token`. We do NOT scrape
HTML, do NOT extract cookies, do NOT reverse-engineer private endpoints,
and do NOT store user credentials. PRD §9 priority #1 is "Official
Reddit API / OAuth" — that is exactly what this module implements.

Phase 4 §9 also accepts the OUTCOME where a Reddit connector cannot be
implemented safely. We chose to implement the legal path. If a future
harness policy change breaks this, the adapter is expected to raise
`AdapterAuthMissing` until credentials are configured again — there is NO
fallback to cookie scraping or private endpoints.

PRD §9 rules in scope:
  * NO cookie / session theft — explicit.
  * NO login automation, CAPTCHA bypass, proxy circumvention — explicit.
  * `client_id` / `client_secret` are injected via constructor; the module
    itself never reads environment variables (matches the host-agnostic
    boundary from PRD §5).
  * Score is recorded as engagement metadata, never as evidence_quality.

Failure-mode mapping (Phase 3 AdapterError taxonomy):
  * missing client_id/client_secret        → AdapterAuthMissing
  * HTTP 401 on token endpoint             → AdapterAuthMissing
  * HTTP 401 / 403 on search endpoint      → AdapterAuthMissing
  * HTTP 429 on either endpoint            → AdapterRateLimited
  * HTTP 5xx on either endpoint            → AdapterUnavailable
  * HttpTimeoutError                       → AdapterTimeout
  * HttpPermanentError (other 4xx)         → AdapterInvalidResponse
  * malformed search response              → AdapterInvalidResponse
  * missing required field on a listing    → AdapterInvalidResponse
  * deleted content `[deleted]`            → silently dropped
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

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


SOURCE_NAME = "reddit"
SOURCE_TYPE = "post"

# Official endpoints.
REDDIT_ACCESS_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_SEARCH_URL = "https://oauth.reddit.com/search"


# PRD §16 default for Reddit search.
DEFAULT_MAX_PER_QUERY = 20


# ---------- token cache -------------------------------------------------


@dataclass
class _Token:
    access_token: str
    expires_at: float  # unix seconds; refresh when now >= expires_at - 30s


def _utc_iso_from_unix(unix_seconds: Any) -> str:
    try:
        ts = float(unix_seconds)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    token = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


# ---------- adapter -----------------------------------------------------


@dataclass
class RedditAdapter:
    """SourceAdapter for Reddit search using the official OAuth flow.

    Args:
      http_client  — injected; defaults to StdlibHttpClient.
      client_id    — Reddit app client_id (constructor injection).
      client_secret — Reddit app client_secret (constructor injection).
      max_per_query — clamp value (PRD §16).
      source_name  — registry name; defaults to "reddit".
      token_ttl_default — used when access_token has no `expires_in`.

    Auth posture: when client_id / client_secret are missing or empty, the
    adapter refuses to issue any HTTP request and raises AdapterAuthMissing.
    That keeps the orchestrator from running doomed-to-fail calls and
    keeps the auth surface auditable.
    """

    http_client: HttpClient | None = None
    client_id: str | None = None
    client_secret: str | None = None
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    source_name: str = SOURCE_NAME
    token_ttl_default: int = 3600
    # Injectable clock (Phase 4 determinism). When None the token cache
    # is best-effort: refreshing only when missing — host integrations
    # supply a real wall-clock provider. Tests inject a fixed callable.
    now_provider: "Callable[[], float] | None" = None
    _token: _Token | None = field(default=None, init=False, repr=False)

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
        client_id = (self.client_id or "").strip()
        client_secret = (self.client_secret or "").strip()
        if not client_id or not client_secret:
            # Per PRD §9: explicit auth-missing; never attempt HTTP.
            raise AdapterAuthMissing(
                source=self.source_name,
                reason=(
                    "reddit requires REDDIT_CLIENT_ID and "
                    "REDDIT_CLIENT_SECRET (PRD §9 legal OAuth path)"
                ),
            )

        query = str(request.get("query") or "")
        if not query:
            raise AdapterInvalidResponse(
                source=self.source_name, reason="retrieval request missing query"
            )
        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")

        # Limit clamp.
        limit_req = request.get("limit")
        try:
            limit_n = int(limit_req) if limit_req is not None else self.max_per_query
        except (TypeError, ValueError):
            limit_n = self.max_per_query
        limit = max(1, min(limit_n, self.max_per_query))

        # Acquire (or refresh) the bearer token.
        token = self._ensure_token(client_id, client_secret)
        auth_header = f"Bearer {token.access_token}"

        # Compose the search URL.
        from urllib.parse import quote_plus

        q = quote_plus(query)
        url = (
            f"{REDDIT_SEARCH_URL}?q={q}&limit={limit}&sort=new&restrict_sr=&type=link,sr"
        )
        headers = {
            "Authorization": auth_header,
            "User-Agent": "gtm-intelligence:research:v0.2 (by /u/gtm-research)",
        }

        try:
            resp = self.http_client.request(url, headers=headers)
        except HttpTransientError as exc:
            if exc.status == 429:
                raise AdapterRateLimited(
                    source=self.source_name,
                    reason=f"reddit 429: {exc}",
                )
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"reddit transient {exc.status}",
            )
        except HttpPermanentError as exc:
            if exc.status in (401, 403):
                # Token revoked or wrong-scope — surface as AuthMissing so
                # the orchestrator records AUTH_MISSING, not INVALID.
                self._token = None  # drop the bad token
                raise AdapterAuthMissing(
                    source=self.source_name,
                    reason=f"reddit search {exc.status}",
                )
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"reddit search {exc.status}",
            )
        except HttpTimeoutError as exc:
            raise AdapterTimeout(
                source=self.source_name, reason=str(exc)
            )
        except Exception as exc:
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"{type(exc).__name__}: {exc}",
            )

        if resp.status != 200:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"reddit search returned status {resp.status}",
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"reddit body not JSON: {exc}",
            )

        if not isinstance(payload, Mapping) or "data" not in payload:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="reddit payload missing top-level 'data'",
            )
        data = payload.get("data") or {}
        if not isinstance(data, Mapping) or "children" not in data:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="reddit payload missing 'data.children'",
            )
        children = data.get("children") or []
        if not isinstance(children, list):
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="reddit 'children' must be a list",
            )

        out: list[RawSourceResult] = []
        for wrapper in children:
            if not isinstance(wrapper, Mapping):
                continue
            inner = wrapper.get("data")
            if not isinstance(inner, Mapping):
                raise AdapterInvalidResponse(
                    source=self.source_name,
                    reason="reddit child has no inner data mapping",
                )
            name = str(inner.get("name") or "").strip()
            title = str(inner.get("title") or "").strip()
            permalink = str(inner.get("permalink") or "").strip()
            author = str(inner.get("author") or "").strip()
            subreddit = str(inner.get("subreddit") or "").strip()
            url_field = str(inner.get("url") or "").strip()
            selftext = str(inner.get("selftext") or "").strip()

            if not name or not title or not permalink:
                raise AdapterInvalidResponse(
                    source=self.source_name,
                    reason="reddit child missing required field (name/title/permalink)",
                )

            # PRD §9: deleted content dropped silently.
            if title == "[deleted]" or author == "[deleted]" or author == "[removed]":
                continue

            final_url = url_field or f"https://www.reddit.com{permalink}"
            created = _utc_iso_from_unix(inner.get("created_utc"))
            if not created:
                # Unknown timestamp: skip (Closeout §3: omit, do not
                # pretend it's known).
                continue

            engagement: dict[str, int] = {}
            if "score" in inner:
                engagement["upvotes"] = _coerce_int(inner.get("score"))
            if "num_comments" in inner:
                engagement["comments"] = _coerce_int(inner.get("num_comments"))

            out.append(
                RawSourceResult(
                    source=self.source_name,
                    source_type=SOURCE_TYPE,
                    source_native_id=name,
                    url=final_url,
                    title=title,
                    text=(selftext[:280] if selftext else title),
                    author=author,
                    published_at=created,
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement=engagement,
                    raw_metadata={
                        "subreddit": subreddit,
                        "permalink": permalink,
                        "kind": str(wrapper.get("kind") or ""),
                    },
                )
            )
        return out

    # ----- token management ------------------------------------------

    def _ensure_token(self, client_id: str, client_secret: str) -> _Token:
        existing = self._token
        # Clock must come from the injected provider; we never invoke wall clock
        # wall clock inside src/ (deterministic-engine invariant). When
        # no provider is configured we fall back to 0.0 so the TTL math
        # stays deterministic and degrades to a per-process acquire.
        now_fn = self.now_provider
        now = now_fn() if now_fn is not None else 0.0
        if existing is not None and now < existing.expires_at - 30:
            return existing
        # Acquire a new token.
        basic = _basic_auth_header(client_id, client_secret)
        body = "grant_type=client_credentials"
        try:
            resp = self.http_client.request(
                REDDIT_ACCESS_TOKEN_URL,
                headers={
                    "Authorization": basic,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "gtm-intelligence:research:v0.2 (by /u/gtm-research)",
                },
            )
        except HttpTransientError as exc:
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"reddit token transient {exc.status}",
            )
        except HttpPermanentError as exc:
            if exc.status in (401, 403):
                raise AdapterAuthMissing(
                    source=self.source_name,
                    reason=f"reddit token {exc.status}",
                )
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"reddit token {exc.status}",
            )
        except HttpTimeoutError as exc:
            raise AdapterTimeout(
                source=self.source_name, reason=str(exc)
            )
        except Exception as exc:
            raise AdapterUnavailable(
                source=self.source_name,
                reason=f"reddit token {type(exc).__name__}: {exc}",
            )

        if resp.status != 200:
            raise AdapterAuthMissing(
                source=self.source_name,
                reason=f"reddit token endpoint {resp.status}",
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason=f"reddit token body not JSON: {exc}",
            )
        if not isinstance(payload, Mapping):
            raise AdapterInvalidResponse(
                source=self.source_name,
                reason="reddit token body not a mapping",
            )
        access = str(payload.get("access_token") or "").strip()
        if not access:
            raise AdapterAuthMissing(
                source=self.source_name,
                reason="reddit token response missing access_token",
            )
        expires_in = payload.get("expires_in")
        try:
            ttl = int(expires_in) if expires_in is not None else self.token_ttl_default
        except (TypeError, ValueError):
            ttl = self.token_ttl_default
        ttl = max(60, ttl)  # never trust a sub-minute TTL
        token = _Token(access_token=access, expires_at=now + ttl)
        self._token = token
        return token


__all__ = [
    "SOURCE_NAME",
    "SOURCE_TYPE",
    "REDDIT_ACCESS_TOKEN_URL",
    "REDDIT_SEARCH_URL",
    "DEFAULT_MAX_PER_QUERY",
    "RedditAdapter",
]
