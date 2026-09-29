"""CoverageReport (Phase 3 §19, Closeout §5).

Deterministic, non-LLM metadata artifact that accompanies a pipeline run.
Captures the per-source outcomes, the counts of items flowing through each
stage, the languages/markets covered, and human-readable gaps + warnings.

Semantic clarity (Closeout §5):
  * `duplicate_dropped_count`   — items the dedup stage REMOVED (≥ 0)
  * `final_evidence_count`      — items KEPT after dedup (≥ 0)
  * `normalized_evidence_count` — items that landed in normalization (BEFORE
                                   time filter and dedup).
  * `raw_result_count`          — items from adapters BEFORE normalization.

  Arithmetic invariant (always enforced by tests):
      normalized_evidence_count
        - time_filter_dropped_count
        - duplicate_dropped_count
        == final_evidence_count

  X raw → Y normalized → Z duplicates dropped → N final
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .degradation import SourceStatus, SourceStatusReport


@dataclass(frozen=True)
class CoverageReport:
    """Final coverage metadata for one research run."""

    requested_sources: tuple[str, ...] = ()
    attempted_sources: tuple[str, ...] = ()
    successful_sources: tuple[str, ...] = ()
    failed_sources: tuple[str, ...] = ()
    query_count: int = 0
    raw_result_count: int = 0
    normalized_evidence_count: int = 0
    duplicate_dropped_count: int = 0
    time_filter_dropped_count: int = 0
    final_evidence_count: int = 0
    current_window_count: int = 0
    baseline_window_count: int = 0
    languages_covered: tuple[str, ...] = ()
    markets_covered: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def deduplicated_count(self) -> int:
        """Back-compat alias for `duplicate_dropped_count`.

        The previous name was ambiguous (could be read as either the count
        of items dropped or the count of items retained). CoverageReport is
        Phase 3 internal DTO — this alias keeps existing call sites working
        while the new field name is the canonical one (Closeout §5).
        """
        return self.duplicate_dropped_count

    def summary(self) -> str:
        return (
            f"raw={self.raw_result_count} "
            f"normalized={self.normalized_evidence_count} "
            f"time_drop={self.time_filter_dropped_count} "
            f"dedup_drop={self.duplicate_dropped_count} "
            f"final={self.final_evidence_count}"
        )

    def to_dict(self) -> dict:
        return {
            "requested_sources": list(self.requested_sources),
            "attempted_sources": list(self.attempted_sources),
            "successful_sources": list(self.successful_sources),
            "failed_sources": list(self.failed_sources),
            "query_count": self.query_count,
            "raw_result_count": self.raw_result_count,
            "normalized_evidence_count": self.normalized_evidence_count,
            "duplicate_dropped_count": self.duplicate_dropped_count,
            "time_filter_dropped_count": self.time_filter_dropped_count,
            "final_evidence_count": self.final_evidence_count,
            "current_window_count": self.current_window_count,
            "baseline_window_count": self.baseline_window_count,
            "languages_covered": list(self.languages_covered),
            "markets_covered": list(self.markets_covered),
            "gaps": list(self.gaps),
            "warnings": list(self.warnings),
        }


def _distinct_preserve_first(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return tuple(out)


def _partition_sources(
    statuses: Mapping[str, SourceStatusReport],
) -> tuple[list[str], list[str]]:
    """Split statuses into (succeeded, failed) per Phase 3 §19 semantics.

    Succeeded = status in {SUCCESS, PARTIAL}.
    Failed    = status in {UNAVAILABLE, AUTH_MISSING, RATE_LIMITED,
                            TIMEOUT, INVALID_RESPONSE}.
    """
    succeeded: list[str] = []
    failed: list[str] = []
    for name, rep in statuses.items():
        if rep.status in (SourceStatus.SUCCESS, SourceStatus.PARTIAL):
            succeeded.append(name)
        else:
            failed.append(name)
    return succeeded, failed


def build_coverage_report(
    *,
    requested_sources: Iterable[str],
    attempted_sources: Iterable[str],
    source_statuses: Mapping[str, SourceStatusReport],
    expanded_queries: Iterable[Mapping[str, object]],
    raw_results: Iterable[Mapping[str, object]],
    normalized_evidence: Iterable[Mapping[str, object]],
    deduplicated_dropped: int,
    dropped_by_time_filter: int,
    kept_evidence: Iterable[Mapping[str, object]] | None = None,
) -> CoverageReport:
    """Build the final CoverageReport from pipeline inputs.

    Stage accounting (Closeout §5):

      X  raw_result_count
      Y  normalized_evidence_count (after normalization, BEFORE time filter)
      Y - dropped_by_time_filter = items entering dedup
      items_entering_dedup - duplicate_dropped_count = final_evidence_count
    """
    req = list(requested_sources)
    att = list(attempted_sources)
    succ, fail = _partition_sources(source_statuses)

    queries_list = list(expanded_queries)
    raw_list = list(raw_results)
    norm_list = list(normalized_evidence)
    kept = list(kept_evidence) if kept_evidence is not None else norm_list

    languages = _distinct_preserve_first(
        str(q.get("query_language") or "") for q in queries_list
    )
    markets = _distinct_preserve_first(
        str(q.get("market") or "") for q in queries_list
    )

    # User-facing window counts describe evidence that survived the time
    # filter and deduplication. Pre-filter counts produced contradictions such
    # as "12 evidence items; current window 64" in a real report.
    current_count = sum(
        1 for e in kept if str(e.get("window") or "") == "current"
    )
    baseline_count = sum(
        1 for e in kept if str(e.get("window") or "") == "baseline"
    )

    gaps: list[str] = []
    if not norm_list:
        gaps.append("no evidence collected from any source")

    warnings: list[str] = []
    if dropped_by_time_filter:
        warnings.append(f"time_filter_dropped={dropped_by_time_filter}")

    return CoverageReport(
        requested_sources=tuple(req),
        attempted_sources=tuple(att),
        successful_sources=tuple(succ),
        failed_sources=tuple(fail),
        query_count=len(queries_list),
        raw_result_count=len(raw_list),
        normalized_evidence_count=len(norm_list),
        duplicate_dropped_count=int(deduplicated_dropped),
        time_filter_dropped_count=int(dropped_by_time_filter),
        final_evidence_count=len(kept),
        current_window_count=current_count,
        baseline_window_count=baseline_count,
        languages_covered=languages,
        markets_covered=markets,
        gaps=tuple(gaps),
        warnings=tuple(warnings),
    )
