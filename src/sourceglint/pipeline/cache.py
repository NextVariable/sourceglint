"""Local retrieval cache (Phase 3 §17).

JSON-file cache keyed by (source, query, query_language, market, time_window).
* Deterministic key (sha256-derived, no raw values embedded).
* TTL respected via injected as_of.
* Corrupt files: silently treated as miss.
* Disposable. Local. Not committed.
* No secrets stored. Cache values are the adapter's RawSourceResult dicts.

This is a file-based cache by design (Phase 3 says no Redis, no DB).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class CacheMiss(Exception):
    """Signals an explicit cache miss (used by helpers that want to throw)."""


def _normalize_query(q: str) -> str:
    return " ".join((q or "").split())


def _normalize_window(w: Mapping[str, object]) -> str:
    """Stable canonical string for a time_window mapping."""
    if "days" in w:
        return f"days:{int(w['days'])}"
    if "start" in w and "end" in w:
        return f"start:{w['start']}|end:{w['end']}"
    return f"raw:{json.dumps(w, sort_keys=True, default=str)}"


def cache_key_for(
    *,
    source: str,
    query: str,
    query_language: str,
    market: str,
    time_window: Mapping[str, object],
) -> str:
    """Return a deterministic hex cache key.

    The returned string is a 16-char hex prefix of sha256 over the canonical
    tuple — raw values are NEVER embedded in the key, so secret-shaped query
    strings cannot leak via filesystem listings.
    """
    parts = [
        _normalize_query(query),
        str(query_language or ""),
        str(market or ""),
        _normalize_window(time_window or {}),
        str(source or ""),
    ]
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    digest = h.hexdigest()
    return f"c_{digest[:32]}"


class RetrievalCache:
    """File-backed retrieval cache. All times are injected (no system clock)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Two-level directory: c_<2 chars>/<key>.json — keeps dirs small.
        if not key.startswith("c_") or len(key) < 4:
            raise ValueError(f"invalid cache key: {key!r}")
        sub = key[2:4]
        return self.root / sub / f"{key}.json"

    def get(self, key: str, *, as_of: str) -> list | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            # Corrupt cache — silently delete and treat as miss.
            try:
                path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(payload, dict):
            try:
                path.unlink()
            except OSError:
                pass
            return None
        expires_at = str(payload.get("expires_at") or "")
        if not expires_at:
            return None
        if _utc_seconds(as_of) >= _utc_seconds(expires_at):
            try:
                path.unlink()
            except OSError:
                pass
            return None
        value = payload.get("value")
        return value if isinstance(value, list) else None

    def set(
        self,
        key: str,
        value: list,
        *,
        ttl_seconds: int,
        as_of: str,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError(f"ttl_seconds must be non-negative; got {ttl_seconds}")
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        expires_at = _iso_after(as_of, seconds=ttl_seconds)
        body = {"expires_at": expires_at, "value": value}
        path.write_text(
            json.dumps(body, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def invalidate(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def make_cache(root: Path | str) -> RetrievalCache:
    return RetrievalCache(root)


def _utc_seconds(iso: str) -> int:
    """Return Unix seconds from an RFC3339 string, accepting offsets."""
    if not iso:
        return 0
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())


def _iso_after(iso: str, *, seconds: int) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    out = dt.timestamp() + seconds
    return datetime.fromtimestamp(out, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )