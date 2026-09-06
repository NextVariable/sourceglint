"""Deterministic evidence identity (Phase 2).

Contract (v0.2 §9 + Phase 1 evidence schema):
  * ID format: "ev_" + 32-char base32 lowercase (128 bits of sha256 truncated).
    Total 35 chars. Deterministic; never random.
  * Identity fields (in canonical order):
      1. source (the origin platform identifier)
      2. canonical URL (see canonicalize_url)
      3. author handle (when available; "" otherwise)
      4. published_at (ISO 8601, when available; "" otherwise)
      5. content_signature: sha256 of normalized snippet (NFKC + collapse ws)
  * Enrichment metadata that MUST NOT affect identity:
      retrieved_at, engagement, evidence_quality, query, tags, language/locale

Why this design:
  Same canonical evidence (same story URL + same publication + same words) MUST
  yield the same evidence_id across re-retrievals. Engagement, query, tags,
  and retrieval timestamp are downstream enrichments and would silently break
  dedup if they were folded into identity.
"""
from __future__ import annotations

import base64
import hashlib
import unicodedata
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Tracking parameters that are dropped during URL canonicalization.
# Phase 2 MVP scope. Don't grow this list without a target reason.
_DROPPED_QUERY_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "gbraid", "wbraid", "yclid",
        "ref", "ref_src", "ref_url",
        "_hsenc", "_hsmi", "__tn__",
    }
)


def canonicalize_url(url: str) -> str:
    """Return a stable URL representation.

    Rules (MVP):
      * Lower-case scheme and host.
      * Strip fragment.
      * Sort query parameters by key (case-sensitive ASCII order).
      * Drop known tracking parameters (utm_*, fbclid, gclid, gbraid, wbraid,
        yclid, ref, ref_src, ref_url, _hsenc, _hsmi, __tn__).
      * Collapse consecutive '/' in path; strip trailing '/' unless path is '/'.
      * Leave userinfo, port, and unrelated query params untouched.
    """
    if not isinstance(url, str):
        raise TypeError(f"url must be str, got {type(url).__name__}")

    parts = urlsplit(url.strip())

    # Lower-case scheme + host (do not touch path/query).
    scheme = parts.scheme.lower()
    netloc = parts.netloc
    # Strip userinfo if empty after @ (defensive); keep otherwise.
    if "@" in netloc:
        userinfo, _, hostpart = netloc.rpartition("@")
        netloc = hostpart.lower()
        if userinfo:
            netloc = f"{userinfo}@{netloc}"
    else:
        netloc = netloc.lower()

    # Filter + sort query params.
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    pairs = [(k, v) for k, v in pairs if k not in _DROPPED_QUERY_PARAMS]
    pairs.sort()
    query = urlencode(pairs, doseq=False)

    # Collapse // and drop trailing slash.
    raw_path = parts.path
    path = "/".join(seg for seg in raw_path.split("/") if seg != "" or raw_path == "/")
    if not path:
        path = "/"

    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_text(text: str) -> str:
    """Normalize free text for content_signature. NFKC + collapse whitespace."""
    if not isinstance(text, str):
        text = str(text)
    nfkc = unicodedata.normalize("NFKC", text)
    return " ".join(nfkc.split())


def _sig(inputs: list[str]) -> str:
    h = hashlib.sha256()
    for piece in inputs:
        h.update(piece.encode("utf-8"))
        h.update(b"\x1f")  # unit separator between fields
    return h.hexdigest()


def derive_evidence_id(evidence: Mapping[str, object]) -> str:
    """Return the deterministic evidence_id for an evidence mapping.

    Required: at least one of (url, content). The phase-1 schema requires url,
    so missing-url is a hard error rather than a silent fallback.
    """
    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be a mapping")

    source = evidence.get("source", "")
    url = evidence.get("url", "")
    author = evidence.get("author", "") or ""
    published_at = evidence.get("published_at", "") or ""
    snippet = evidence.get("snippet", "") or evidence.get("content", "") or ""

    if not source:
        raise ValueError("evidence.source missing")
    if not url:
        raise ValueError("evidence.url missing (cannot derive stable identity)")

    canonical_url = canonicalize_url(url)
    canonical_text = normalize_text(snippet)
    digest = _sig(
        [
            str(source),
            canonical_url,
            str(author),
            str(published_at),
            canonical_text,
        ]
    )

    # Take a stable 32-char base32 lowercase prefix from sha256.
    import base64 as _b
    sig = _b.b32encode(bytes.fromhex(digest)).decode("ascii").lower().rstrip("=")
    return f"ev_{sig[:32]}"
