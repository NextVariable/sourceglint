"""HTTP client abstraction for real source connectors (Phase 4 §10, §11, §12).

Why stdlib (urllib.request + socket timeout) rather than a third-party HTTP lib
============================================================================
PRD §10 instructs to confirm stdlib is sufficient FIRST and to record
WHY/TRADE-OFF if introducing a new dependency. We stick with stdlib:

  * NO new dependency → keeps `pip install -e .[dev]` small, matches the
    v0.2 PRD philosophy of "minimal surface, deterministic engines".
  * urllib + json are part of Python's stable stdlib since 3.10 — no
    version-skew concerns across the user's Python distributions.
  * timeout is enforced via socket.setdefaulttimeout() inside the request
    closure — strict upper bound, no surprise long polls.
  * test injection: clients that need to be replaceable (HN, GitHub, …)
    accept any object that quacks like HttpClient. We never reach into
    a third-party HTTP package inside gtm_intelligence's core code.

Trade-offs accepted:
  * No async / connection pooling — fine for our sequential, low-rate
    Research Pipeline runs.
  * No automatic decompression header negotiation beyond what urllib
    does by default.
  * Slightly less ergonomic than a third-party alternative; the gap is
    small (~30 lines per call) and isolated to this single module.

Compliance with PRD:
  * §11 Retry policy — only on transient failures (429 / 5xx / timeout),
    bounded by `max_attempts` (default 3).
  * §12 User-Agent — every connector advertises
    gtm-intelligence/<version> (+ optional contact URL via env if set).
  * §13 Rate limit — connect adapters map 429 → AdapterRateLimited.
  * §14 Auth — never log or include secrets in error reprs.
  * §29 Security — token never stored, never echoed, never enters
    Evidence (those checks live in the connectors; this client merely
    keeps a header dict).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable


DEFAULT_USER_AGENT = "gtm-intelligence/0.2.0"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_ATTEMPTS = 3  # 1 initial + 2 retries (PRD §11: 2-3 attempts)
DEFAULT_BACKOFF_SECONDS = 0.5  # bounded; tests inject a 0 to skip sleeps


# ---------- exception taxonomy ------------------------------------------


class HttpError(Exception):
    """Base class for HTTP errors."""


class HttpTransientError(HttpError):
    """5xx / 429 / timeout — may be retried per PRD §11."""

    def __init__(self, status: int | None, url: str, body_preview: str = "") -> None:
        # Never include the response body in the message text — only a
        # length count, to honor PRD §14 (no secret-shaped values echo).
        body_kb = len(body_preview) if body_preview else 0
        if status is None:
            super().__init__(f"transient error fetching {url} (no status); body {body_kb} bytes")
        else:
            super().__init__(
                f"transient error fetching {url} (status={status}); body {body_kb} bytes"
            )
        self.status = status
        self.url = url


class HttpPermanentError(HttpError):
    """4xx (excluding 429) — must NOT be retried (PRD §11)."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"permanent error fetching {url} (status={status})")
        self.status = status
        self.url = url


class HttpTimeoutError(HttpError):
    """The request exceeded its budget (PRD §11)."""

    def __init__(self, url: str, timeout: float) -> None:
        super().__init__(f"timeout fetching {url} after {timeout}s")
        self.url = url
        self.timeout = timeout


# ---------- response DTO ------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    url: str = ""

    def json(self) -> Any:
        """Parse body as JSON. Raises json.JSONDecodeError on bad data."""

        return json.loads(self.body.decode("utf-8"))

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding)


# ---------- HTTP client protocol ---------------------------------------


@runtime_checkable
class HttpClient(Protocol):
    """A small neutral HTTP contract every real connector speaks.

    Concrete implementations:
      * StdlibHttpClient   — production / live path
      * RecorderHttpClient — test double (PRD fixture-parity pattern)
    """

    user_agent: str

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> HttpResponse:
        ...


# ---------- stdlib implementation ---------------------------------------


@dataclass
class StdlibHttpClient:
    """Production HTTP client using Python's stdlib (urllib + socket)."""

    user_agent: str = DEFAULT_USER_AGENT
    default_timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    # Injectable sleep hook for tests (PRD §11: avoid test sleep).
    sleep: callable = staticmethod(time.sleep)

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        """Issue GET with bounded retry. Backs off only on transient errors."""
        bound_timeout = float(timeout if timeout is not None else self.default_timeout)
        last_exc: Exception | None = None

        for attempt in range(1, max(1, self.max_attempts) + 1):
            try:
                return self._request_once(
                    url, headers=headers, timeout=bound_timeout
                )
            except HttpTransientError as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                # Sleep is injected so tests can pass a no-op.
                try:
                    self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                except Exception:  # pragma: no cover - sleep injection is best-effort
                    pass
                continue
            except (HttpPermanentError,):
                # No retry on permanent client errors (PRD §11).
                raise
            except HttpTimeoutError as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                try:
                    self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                except Exception:  # pragma: no cover
                    pass
                continue
            except HttpTransientError as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                # Sleep is injected so tests can pass a no-op.
                try:
                    self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                except Exception:  # pragma: no cover - sleep injection is best-effort
                    pass
                continue

        assert last_exc is not None
        raise last_exc

    # -- internal -----------------------------------------------------

    def _request_once(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None,
        timeout: float,
    ) -> HttpResponse:
        # Build headers with User-Agent always first.
        merged: dict[str, str] = {"User-Agent": self.user_agent}
        if headers:
            for k, v in headers.items():
                if k.lower() == "user-agent":
                    continue  # never let caller override UA (PRD §12)
                merged[k] = v

        # Enforce timeout at the socket layer — guarantees we cannot hang
        # past the configured budget even if the server is unresponsive.
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            req = urllib.request.Request(url=url, headers=merged, method="GET")
            try:
                with urllib.request.urlopen(req) as resp:
                    status = int(getattr(resp, "status", 200) or 200)
                    body = resp.read()
                    # Map urllib's http.client.HTTPMessage to a plain dict.
                    hdrs: dict[str, str] = {
                        k.lower(): v for k, v in resp.headers.items()
                    }
                    return HttpResponse(
                        status=status,
                        headers=hdrs,
                        body=body,
                        url=url,
                    )
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                body_preview = ""
                try:
                    body_preview = (exc.read() or b"").decode("utf-8", "replace")
                except Exception:  # pragma: no cover - body-read is best-effort
                    body_preview = ""
                if status == 429 or 500 <= status < 600:
                    raise HttpTransientError(
                        status=status,
                        url=url,
                        body_preview=body_preview,
                    ) from exc
                raise HttpPermanentError(status=status, url=url) from exc
            except urllib.error.URLError as exc:
                reason = str(getattr(exc, "reason", exc))
                if "timed out" in reason.lower() or "timeout" in reason.lower():
                    raise HttpTimeoutError(url=url, timeout=timeout) from exc
                raise HttpTransientError(
                    status=None, url=url, body_preview=reason
                ) from exc
            except socket.timeout as exc:
                raise HttpTimeoutError(url=url, timeout=timeout) from exc
        finally:
            socket.setdefaulttimeout(previous_timeout)


# ---------- Re-exports --------------------------------------------------


__all__ = [
    "DEFAULT_USER_AGENT",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BACKOFF_SECONDS",
    "HttpError",
    "HttpTransientError",
    "HttpPermanentError",
    "HttpTimeoutError",
    "HttpResponse",
    "HttpClient",
    "StdlibHttpClient",
]
