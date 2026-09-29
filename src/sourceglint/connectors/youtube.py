"""YouTube recent-video discovery through the local ``yt-dlp`` CLI.

It executes an argv list without a shell, disables browser-cookie loading, and
returns only metadata.  It does not download video or audio.  Public web search
remains the fallback when the executable is absent or YouTube blocks the host.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import shutil
import subprocess
from typing import Callable, Mapping, Sequence

from ._command import CommandResult, run_command
from ..pipeline.adapters import (
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    RawSourceResult,
)


SOURCE_NAME = "youtube"
SOURCE_TYPE = "post"
DEFAULT_MAX_PER_QUERY = 8
DEFAULT_TIMEOUT_SECONDS = 120.0


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _published_at(payload: Mapping[str, object]) -> str:
    timestamp = payload.get("timestamp") or payload.get("release_timestamp")
    if timestamp is not None:
        try:
            return datetime.fromtimestamp(
                float(timestamp), tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OSError):
            pass
    raw = str(payload.get("upload_date") or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T00:00:00Z"
    return ""


@dataclass(frozen=True)
class YouTubeAdapter:
    executable: str | None = None
    runner: Callable[[Sequence[str], float], CommandResult] = run_command
    max_per_query: int = DEFAULT_MAX_PER_QUERY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    source_name: str = SOURCE_NAME

    def __post_init__(self) -> None:
        if self.executable is None:
            object.__setattr__(self, "executable", shutil.which("yt-dlp"))

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
                self.source_name, "retrieval request missing query"
            )
        if not self.executable:
            raise AdapterUnavailable(self.source_name, "yt-dlp is not installed")
        try:
            requested_limit = int(request.get("limit") or self.max_per_query)
        except (TypeError, ValueError):
            requested_limit = self.max_per_query
        limit = max(1, min(requested_limit, self.max_per_query, 50))
        command = [
            self.executable,
            "--ignore-config",
            "--no-cookies-from-browser",
            f"ytsearch{limit}:{query}",
            "--dump-json",
            "--no-warnings",
            "--no-download",
        ]
        try:
            result = self.runner(command, self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise AdapterTimeout(
                self.source_name, f"yt-dlp exceeded {self.timeout_seconds:g}s"
            ) from exc
        except FileNotFoundError as exc:
            raise AdapterUnavailable(
                self.source_name, "yt-dlp is not installed"
            ) from exc
        except Exception as exc:
            raise AdapterUnavailable(
                self.source_name, f"yt-dlp failed: {type(exc).__name__}"
            ) from exc

        if result.returncode != 0 and not result.stdout.strip():
            detail = result.stderr.lower()
            if any(marker in detail for marker in ("429", "rate limit", "not a bot")):
                raise AdapterRateLimited(self.source_name, "youtube blocked yt-dlp")
            if "timed out" in detail or "timeout" in detail:
                raise AdapterTimeout(self.source_name, "youtube yt-dlp timed out")
            raise AdapterUnavailable(
                self.source_name,
                f"yt-dlp exited with status {result.returncode}",
            )

        language = str(request.get("query_language") or "")
        market = str(request.get("market") or "")
        output: list[RawSourceResult] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AdapterInvalidResponse(
                    self.source_name, "yt-dlp returned non-JSON output"
                ) from exc
            if not isinstance(item, Mapping):
                continue
            video_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not video_id or not title:
                continue
            description = str(item.get("description") or "").strip()
            output.append(
                RawSourceResult(
                    source=self.source_name,
                    source_type=SOURCE_TYPE,
                    source_native_id=video_id,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    title=title,
                    text=description or title,
                    author=str(item.get("channel") or item.get("uploader") or ""),
                    published_at=_published_at(item),
                    language=language or "en",
                    market=market or "global",
                    query=query,
                    query_language=language,
                    engagement={
                        "views": _count(item.get("view_count")),
                        "likes": _count(item.get("like_count")),
                        "comments": _count(item.get("comment_count")),
                    },
                    raw_metadata={"duration_seconds": _count(item.get("duration"))},
                )
            )
        return output


__all__ = [
    "CommandResult",
    "DEFAULT_MAX_PER_QUERY",
    "DEFAULT_TIMEOUT_SECONDS",
    "SOURCE_NAME",
    "SOURCE_TYPE",
    "YouTubeAdapter",
]
