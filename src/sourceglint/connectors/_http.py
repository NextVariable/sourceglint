"""Injectable stdlib HTTP transport for public-source connectors.

Requests use a per-call socket timeout and bounded retries for transient errors.
The timeout is not a total wall-clock deadline. Response bodies stay out of error
messages; adapters handle authorization and map transport failures to source status.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


DEFAULT_USER_AGENT = "sourceglint/0.2.0"
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
        method: str = "GET",
        json_data: Mapping[str, object] | None = None,
        form_data: Mapping[str, str] | None = None,
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
        method: str = "GET",
        json_data: Mapping[str, object] | None = None,
        form_data: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Issue a bounded HTTP request; retry only transient failures."""
        if json_data is not None and form_data is not None:
            raise ValueError("json_data and form_data are mutually exclusive")
        bound_timeout = float(timeout if timeout is not None else self.default_timeout)
        last_exc: Exception | None = None

        for attempt in range(1, max(1, self.max_attempts) + 1):
            try:
                return self._request_once(
                    url,
                    headers=headers,
                    timeout=bound_timeout,
                    method=method,
                    json_data=json_data,
                    form_data=form_data,
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
        assert last_exc is not None
        raise last_exc

    # -- internal -----------------------------------------------------

    def _request_once(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None,
        timeout: float,
        method: str,
        json_data: Mapping[str, object] | None,
        form_data: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        # Build headers with User-Agent always first.
        merged: dict[str, str] = {"User-Agent": self.user_agent}
        if headers:
            for k, v in headers.items():
                if k.lower() == "user-agent":
                    continue  # never let caller override UA (PRD §12)
                merged[k] = v
        body: bytes | None = None
        if json_data is not None:
            body = json.dumps(dict(json_data), separators=(",", ":")).encode("utf-8")
            merged.setdefault("Content-Type", "application/json")
        elif form_data is not None:
            body = urlencode(form_data).encode("utf-8")
            merged.setdefault("Content-Type", "application/x-www-form-urlencoded")

        # Keep timeout state local to this request, including parallel enrichments.
        req = urllib.request.Request(
            url=url,
            headers=merged,
            data=body,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
