"""Phase 5 §12–§13, §18 — code-computed cluster features.

Everything in this module is pure counting — NO model call (PRD §4, §12):

  * source independence (PRD §13): two items are independent reports only
    when they come from DIFFERENT canonical origins. Two threads on the
    same host (e.g. two hacker_news items) are ONE origin. A canonical
    origin is the url host with scheme/path/www dropped; when a record has
    no url at all we fall back to its `source` name (marked with the
    `origin_fallback` kind so downstream knows the count is weaker).
  * windows (PRD §18): a cluster may contain `current` and `baseline`
    evidence. `appeared_only_current` is ONLY inferred when the ledger
    actually contains baseline evidence somewhere — with no baseline
    anywhere, "only current" would be a false positive (nothing to compare
    against).
  * tier buckets: `source_tier` is T1 first-party / T2 community /
    T3 marketplace / T4 secondary (evidence.schema.json). `first_party_count`
    counts T1, `community_count` counts T2. Missing tier counts nowhere.

Engagement (PRD §23): raw counter sum only — engagement is NOT treated as
a market signal here; that decision belongs to signal classification.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .dtos import (
    WINDOW_BASELINE,
    PreparedEvidence,
    SignalFeatures,
    ValidatedCluster,
)

#: Kinds recorded in `SignalFeatures.independence_kinds`.
KIND_MULTI_ORIGIN = "multi_origin"
KIND_SINGLE_ORIGIN = "single_origin"
KIND_ORIGIN_FALLBACK = "origin_fallback"

_FIRST_PARTY_TIER = 1
_COMMUNITY_TIER = 2


def canonical_domain(url: str) -> str:
    """Lower-cased hostname without scheme, path, port, or leading www.

    Empty / unparseable input yields "" — never a guessed domain.
    """
    if not url:
        return ""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return ""
    if not host:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _origin_key(ev: PreparedEvidence) -> tuple[str, bool]:
    """`(origin_key, used_fallback)` for one prepared item."""
    domain = canonical_domain(ev.url)
    if domain:
        return domain, False
    # No url: fall back to the source name so distinct sources are not
    # silently collapsed into one origin.
    return f"src:{ev.source}", True


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({v for v in values if v}))


def derive_features(
    cluster: ValidatedCluster,
    evidence_by_id: Mapping[str, PreparedEvidence],
) -> SignalFeatures:
    """Compute every countable feature for one cluster.

    `evidence_by_id` maps evidence_id → PreparedEvidence for the whole
    prepared set (build once with `build_evidence_index`). Members whose id
    is absent from the index are ignored — they cannot happen after
    `validate_clusters`, and this keeps the function total.
    """
    members = [
        evidence_by_id[eid] for eid in cluster.evidence_ids if eid in evidence_by_id
    ]
    if not members:
        return SignalFeatures(cluster_id=cluster.cluster_id)

    windows = [m.window for m in members]
    baseline_count = windows.count(WINDOW_BASELINE)
    current_count = len(windows) - baseline_count

    sources = [m.source for m in members]
    source_types = [m.source_type for m in members]
    tiers = sorted({t for t in (m.source_tier for m in members) if t is not None})
    domains = _sorted_unique(canonical_domain(m.url) for m in members)

    origins: list[tuple[str, bool]] = [_origin_key(m) for m in members]
    origin_keys = {key for key, _ in origins}
    used_fallback = any(fallback for _, fallback in origins)
    independent = len(origin_keys)

    kinds: list[str] = []
    if independent >= 2:
        kinds.append(KIND_MULTI_ORIGIN)
    else:
        kinds.append(KIND_SINGLE_ORIGIN)
    if used_fallback:
        kinds.append(KIND_ORIGIN_FALLBACK)

    engagement_total = sum(
        value for m in members for value in m.engagement.values() if value > 0
    )

    # Global baseline presence guards the "appeared only current" flag.
    has_baseline_data = any(
        item.window == WINDOW_BASELINE for item in evidence_by_id.values()
    )

    return SignalFeatures(
        cluster_id=cluster.cluster_id,
        evidence_count=len(members),
        unique_sources=_sorted_unique(sources),
        unique_source_types=_sorted_unique(source_types),
        source_tiers=tuple(tiers),
        unique_domains=domains,
        independent_source_count=independent,
        independence_kinds=tuple(kinds),
        current_count=current_count,
        baseline_count=baseline_count,
        appeared_only_current=bool(current_count and not baseline_count and has_baseline_data),
        appeared_only_baseline=bool(baseline_count and not current_count),
        has_baseline_data=has_baseline_data,
        engagement_total=engagement_total,
        languages=_sorted_unique(m.language for m in members),
        markets=_sorted_unique(m.market for m in members),
        first_party_count=sum(1 for m in members if m.source_tier == _FIRST_PARTY_TIER),
        community_count=sum(1 for m in members if m.source_tier == _COMMUNITY_TIER),
    )


def build_evidence_index(
    prepared: Iterable[PreparedEvidence],
) -> dict[str, PreparedEvidence]:
    """One index per pipeline run; pass it to every `derive_features` call."""
    return {item.evidence_id: item for item in prepared}


def derive_all_features(
    clusters: Sequence[ValidatedCluster],
    prepared: Iterable[PreparedEvidence],
) -> list[SignalFeatures]:
    """Batch helper — same order as `clusters`. Index is built once."""
    index = build_evidence_index(prepared)
    return [derive_features(cluster, index) for cluster in clusters]
