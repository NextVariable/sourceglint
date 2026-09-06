"""Official-domain classification (Phase 4 §6).

The classifier is a deterministic, configuration-driven matcher. PRD §6
forbids letting the model decide "looks like an official site" — instead,
this matcher takes explicit config and applies strict label-aligned
matching so spoof attempts are reliably rejected.

Integration model:
  * Host Web Search hits, GitHub repository releases, etc. flow through
    `classify_url(url)`. The result is attached to RawSourceResult.raw_metadata
    as `{"official": bool, "official_owner": str | None}`.
  * The Phase 3 normalizer reads that metadata and upgrades
    `source_tier` / `evidence_quality` for true official matches — without
    touching the frozen Evidence Contract (both fields are optional, and
    tier upgrades map cleanly to T1=1.0 in the existing tier table).

Spoof scenarios enumerated by PRD §6:
  * exact domain
  * subdomain (`docs.company.com` for owner `company`)
  * `company.com.evil.org`  → NOT official (label-aligned required)
  * `evilcompany.com`       → NOT official (exact-match required;
                              `com` alone must not match `company.com`)
  * uppercase host          → official (lowercase normalisation)
  * `www.company.com`       → official (www stripped)
  * `:8080` port present    → official (port stripped)
  * GitHub official owner   → official for that owner
  * GitHub unrelated repo   → NOT official
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OfficialRule:
    """One rule mapping an entity to its verified public surface."""

    owner: str
    domains: tuple[str, ...] = ()
    github_owners: tuple[str, ...] = ()


@dataclass(frozen=True)
class OfficialClassification:
    is_official: bool
    owner: str | None = None
    matched_kind: str | None = None  # "domain" / "github" / None
    matched_value: str | None = None

    def to_dict(self) -> dict:
        return {
            "official": self.is_official,
            "official_owner": self.owner,
            "official_kind": self.matched_kind,
            "official_value": self.matched_value,
        }


# ---------- URL parsing helpers (label-aligned) ---------------------------


def _normalise_host(host: str) -> str:
    """Strip port + lowercase. No further transformations.

    Suffix matching is left to the caller so we can keep the rule
    semantics crisp (label-aligned).
    """
    if not host:
        return ""
    # urlsplit already strips userinfo; if a port is present it's in
    # `port`. urlsplit().hostname already excludes the port for URLs.
    return (host or "").strip().lower()


def _split_www(host: str) -> str:
    if host.startswith("www."):
        return host[4:]
    return host


def _domain_matches(host: str, rule_domain: str) -> bool:
    """Return True iff `host` is exactly `rule_domain` OR a strict subdomain.

    Label-aligned: `company.com.evil.org` is never treated as matching
    `company.com` — the rule_domain must own a whole label boundary.
    """
    rule = _normalise_host(rule_domain)
    h = _normalise_host(host)
    if not rule or not h:
        return False
    if rule.startswith("."):
        # Misconfigured rule — we accept leading dots explicitly because
        # we want config to be forgiving, but trim them off.
        rule = rule.lstrip(".")
    if h == rule:
        return True
    # Subdomain match: h ends with "." + rule, and rule is at least 2 labels
    # so we don't accept single-label rules like "com".
    if "." not in rule:
        return False
    return h.endswith("." + rule)


def _github_owner_matches(url: str, owners: Iterable[str]) -> tuple[str, str] | None:
    """If url points to a GitHub repo owned by one of `owners`, return
    a (owner, full_path) tuple. Else None.

    Path shape: github.com/<owner>/<repo>[/...] — the <owner> segment is
    case-insensitive and must equal exactly one of the configured owners.
    """
    if not owners:
        return None
    try:
        split = urlsplit(url)
    except (ValueError, TypeError):
        return None
    if not split.netloc:
        return None
    host = _normalise_host(_split_www(split.netloc.split(":")[0]))
    if host != "github.com":
        return None
    if not split.path or split.path == "/":
        return None
    parts = [p for p in split.path.split("/") if p]
    if len(parts) < 2:
        return None
    candidate = parts[0].lower()
    for o in owners:
        if o.strip().lower() == candidate:
            return (o, "/".join(parts[:2]))
    return None


# ---------- Classifier ---------------------------------------------------


class OfficialDomainClassifier:
    """Deterministic matcher over a list of OfficialRule entries."""

    def __init__(self, rules: Iterable[OfficialRule]) -> None:
        self._rules: tuple[OfficialRule, ...] = tuple(rules)

    @property
    def rules(self) -> tuple[OfficialRule, ...]:
        return self._rules

    def classify_url(self, url: str) -> OfficialClassification:
        if not url:
            return OfficialClassification(is_official=False)
        try:
            split = urlsplit(url)
        except (ValueError, TypeError):
            return OfficialClassification(is_official=False)
        host_with_port = split.netloc or ""
        host_no_port = host_with_port.split(":")[0]
        host = _split_www(_normalise_host(host_no_port))

        # --- GitHub owner path takes precedence when host == github.com
        for rule in self._rules:
            if not rule.github_owners:
                continue
            hit = _github_owner_matches(url, rule.github_owners)
            if hit is not None:
                return OfficialClassification(
                    is_official=True,
                    owner=rule.owner,
                    matched_kind="github",
                    matched_value=hit[1],
                )

        # --- Domain / subdomain match
        for rule in self._rules:
            for d in rule.domains:
                if _domain_matches(host, d):
                    return OfficialClassification(
                        is_official=True,
                        owner=rule.owner,
                        matched_kind="domain",
                        matched_value=d,
                    )

        return OfficialClassification(is_official=False)


# ---------- YAML loader --------------------------------------------------


import yaml  # noqa: E402  — imported lazily so test imports stay light


def load_official_rules(
    *,
    path: str | None = None,
    yaml_text: str | None = None,
) -> tuple[OfficialRule, ...]:
    """Load official rules from a YAML file or in-memory text.

    Schema (intentionally tiny — we are NOT smuggling this into the
    frozen Source Registry schema):
        - owner: acme
          domains: [acme.com, acme.io]
          github_owners: [acmehq, acme-public]
        - owner: balloon_co
          domains: [balloon.co.jp]

    Any unknown top-level fields are dropped silently.
    """
    if path is not None and yaml_text is not None:
        raise ValueError("pass either path or yaml_text, not both")
    if yaml_text is None:
        if path is None:
            raise ValueError("must supply path or yaml_text")
        text = open(path, "r", encoding="utf-8").read()
    else:
        text = yaml_text
    data = yaml.safe_load(text) or []
    if not isinstance(data, list):
        raise ValueError("official rules YAML root must be a list")
    out: list[OfficialRule] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        owner = str(entry.get("owner") or "").strip()
        if not owner:
            continue
        domains = tuple(str(d).strip() for d in (entry.get("domains") or []))
        gh_owners = tuple(str(o).strip() for o in (entry.get("github_owners") or []))
        out.append(
            OfficialRule(
                owner=owner,
                domains=tuple(d for d in domains if d),
                github_owners=tuple(o for o in gh_owners if o),
            )
        )
    return tuple(out)


# ---------- Re-exports ---------------------------------------------------


__all__ = [
    "OfficialRule",
    "OfficialClassification",
    "OfficialDomainClassifier",
    "load_official_rules",
    "_domain_matches",
    "_github_owner_matches",
]
