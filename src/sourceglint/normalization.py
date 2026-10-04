"""RawSourceResult -> Evidence normalization (Phase 3 §12).

Strictly consumes Phase 1 evidence.schema.json (additionalProperties:false).
Optional fields are ABSENT (not 'unknown'/'N/A'/'null') when raw lacks them.

source_tier / evidence_quality are derived deterministically from a small
mapping table — not a fuzzy inference. Real cross-source verification will
be wired in later phases.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import jsonschema
from rfc3339_validator import validate_rfc3339

from .errors import SchemaValidationError
from .ids import canonicalize_url, derive_evidence_id
from .pipeline.adapters import RawSourceResult
from .resources import data_path


_EVIDENCE_VALID_SOURCE_TYPES = {"post", "comment", "review", "page", "release"}
_EVIDENCE_VALID_WINDOWS = {"current", "baseline"}
_EVIDENCE_VALID_ENGAGEMENT_KEYS = {"upvotes", "comments", "likes", "views", "points"}


# Source -> tier (initial). Phase 3 MVP heuristic; Phase 4 may replace with
# richer source classification.
_TIER_MAP: Mapping[str, int] = {
    "official_web": 1,
    "github": 1,
    "reddit": 2,
    "hacker_news": 2,
    "bluesky": 2,
    "youtube": 2,
    # T3 marketplace is reserved for Phase 4.
    "host_web_search": 4,
    # Web search from host capability counts as T4 secondary.
}

# Source -> initial evidence_quality (v0.2 §9: T1=1.0, T3=0.8, T2=0.6, T4=0.3).
_QUALITY_MAP: Mapping[int, float] = {1: 1.0, 2: 0.6, 3: 0.8, 4: 0.3}


_SNIPPET_MAX = 280  # evidence.schema.json says maxLength: 280


class EvidenceNormalizationError(Exception):
    """Raised when raw -> evidence conversion fails."""


@dataclass(frozen=True)
class Normalizer:
    """Stateless normalizer with a pinned as_of (deterministic time injection)."""

    as_of: str
    window: str = "current"

    def normalize(self, raw: RawSourceResult) -> dict:
        return normalize_raw(raw, as_of=self.as_of, window=self.window)


def _validate_url(url: str) -> None:
    if not url:
        raise EvidenceNormalizationError("raw.url missing")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise EvidenceNormalizationError(
            f"raw.url scheme must be http(s); got {url[:16]}"
        )


def _validate_iso(value: str, field: str) -> None:
    if not validate_rfc3339(value):
        raise EvidenceNormalizationError(
            f"raw.{field} is not RFC3339: {value!r}"
        )


def _validate_engagement(eng: Mapping[str, object]) -> dict:
    if not isinstance(eng, Mapping):
        raise EvidenceNormalizationError("raw.engagement must be an object")
    out: dict[str, int] = {}
    for k, v in eng.items():
        if k not in _EVIDENCE_VALID_ENGAGEMENT_KEYS:
            # Drop silently per Phase 3 §12 (we don't pollute the ledger).
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            raise EvidenceNormalizationError(
                f"raw.engagement.{k} must be int (got {type(v).__name__})"
            )
        if v < 0:
            raise EvidenceNormalizationError(
                f"raw.engagement.{k} must be non-negative (got {v})"
            )
        out[k] = v
    return out


def _known_tier(source: str) -> int | None:
    """Return the deterministic tier for known sources, or None for unknown.

    Unknown sources must NEVER receive a synthetic neutral score (PRD
    Closeout §3). The Phase 1 evidence schema declares source_tier and
    evidence_quality as OPTIONAL — unknown sources omit both fields.
    """
    return _TIER_MAP.get(source)


def _known_quality(tier: int) -> float:
    """Tier -> quality for KNOWN sources only.

    Caller MUST check `_known_tier(source)` first; this helper assumes
    the tier is already a real 1-4 value (never None).
    """
    return _QUALITY_MAP.get(tier, 0.5)


def _truncate(text: str, n: int) -> str:
    """Truncate to ≤ n Unicode code points (matches JSON Schema maxLength).

    JSON Schema `maxLength` counts code points, not bytes. Python's
    `len()` and slice operator are both code-point-counted, so `text[:n]`
    is the correct truncation. We do NOT add ellipsis or otherwise
    summarize — the deterministic first-n slice preserves auditability.
    """
    if not text:
        return text
    if len(text) <= n:
        return text
    return text[:n]


def normalize_raw(
    raw: RawSourceResult,
    *,
    as_of: str,
    window: str = "current",
) -> dict:
    """Convert RawSourceResult -> Evidence dict.

    Strict Phase 1 evidence schema compliance. Optional fields are ABSENT
    (not 'unknown'/'N/A'/'null') when raw lacks them.
    """
    if window not in _EVIDENCE_VALID_WINDOWS:
        raise EvidenceNormalizationError(f"invalid window: {window!r}")

    canonical_url = canonicalize_url(raw.url)
    if not canonical_url:
        raise EvidenceNormalizationError("raw.url missing (canonicalized empty)")
    if not (canonical_url.startswith("http://") or canonical_url.startswith("https://")):
        raise EvidenceNormalizationError(
            f"raw.url scheme must be http(s); got {canonical_url[:16]}"
        )

    if raw.source_type not in _EVIDENCE_VALID_SOURCE_TYPES:
        raise EvidenceNormalizationError(
            f"raw.source_type must be one of "
            f"{sorted(_EVIDENCE_VALID_SOURCE_TYPES)}; got {raw.source_type!r}"
        )

    canonical_url = canonicalize_url(raw.url)
    tier = _known_tier(raw.source)
    quality = _known_quality(tier) if tier is not None else None

    # Phase 4 §6 + §20: when raw_metadata declares an official-domain match,
    # the verified-owner flag wins over the source-tier heuristic. The
    # official flag is itself the verification, so we promote to T1 even
    # for sources not in our tier map. This is a tier-resolution tweak; no
    # new Evidence field is added (both `source_tier` and `evidence_quality`
    # remain optional in the Phase 1 schema).
    if bool(raw.raw_metadata.get("official")):
        tier = 1
        quality = 1.0

    out: dict[str, Any] = {
        "evidence_id": derive_evidence_id(
            {
                "source": raw.source,
                "url": canonical_url,
                "author": raw.author,
                "published_at": raw.published_at,
                "snippet": raw.text,
            }
        ),
        "source": raw.source,
        "source_type": raw.source_type,
        "url": canonical_url,
        "title": raw.title,
        "snippet": _truncate(raw.text, _SNIPPET_MAX),
        "retrieved_at": as_of,
        "language": raw.language or "en",
        "window": window,
    }
    if tier is not None:
        out["source_tier"] = tier
    if quality is not None:
        out["evidence_quality"] = quality

    if raw.author:
        out["author"] = raw.author
    if raw.published_at:
        _validate_iso(raw.published_at, "published_at")
        out["published_at"] = raw.published_at
    if raw.market:
        out["market"] = raw.market
    if raw.locale:
        out["locale"] = raw.locale
    if raw.query:
        out["query"] = raw.query
    if raw.query_language:
        out["query_language"] = raw.query_language

    engagement = _validate_engagement(raw.engagement)
    if engagement:
        out["engagement"] = engagement

    return out


# -------- schema validation helper --------------------------------------------


def _evidence_schema() -> dict:
    # src/sourceglint/normalization.py → repo root = parents[2]
    path = data_path("schemas", "evidence.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _common_schema() -> dict:
    path = data_path("schemas", "common.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_validator() -> jsonschema.Draft202012Validator:
    from referencing import Registry, Resource
    reg = (
        Registry()
        .with_resources(
            [("common.schema.json", Resource.from_contents(_common_schema()))]
        )
    )
    return jsonschema.Draft202012Validator(_evidence_schema(), registry=reg)


def validate_evidence_payload(payload: Mapping[str, object]) -> None:
    """Validate an Evidence dict against the Phase 1 contract.

    Raises jsonschema.ValidationError on schema violation.
    Raises SchemaValidationError if the schema validator itself is broken.
    """
    try:
        _evidence_validator().validate(payload)
    except jsonschema.ValidationError as exc:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise SchemaValidationError(f"evidence validator failed: {exc}") from exc
