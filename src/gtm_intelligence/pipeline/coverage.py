"""CoverageReport (Phase 3 §19).

Deterministic, non-LLM metadata artifact that accompanies a pipeline run.
Captures the per-source outcomes, the counts of items flowing through each
stage, the languages/markets covered, and human-readable gaps + warnings.
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
    deduplicated_count: int = 0
    current_window_count: int = 0
    baseline_window_count: int = 0
    languages_covered: tuple[str, ...] = ()
    markets_covered: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def summary(self) -> str:
        return (
            f"requested={len(self.requested_sources)} "
            f"attempted={len(self.attempted_sources)} "
            f"succeeded={len(self.successful_sources)} "
            f"failed={len(self.failed_sources)} "
            f"raw={self.raw_result_count} "
            f"evidence={self.normalized_evidence_count} "
            f"dedup_dropped={self.deduplicated_count} "
            f"current={self.current_window_count} "
            f"baseline={self.baseline_window_count} "
            f"langs={len(self.languages_covered)} "
            f"markets={len(self.markets_covered)} "
            f"gaps={len(self.gaps)} "
            f"warnings={len(self.warnings)}"
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
            "deduplicated_count": self.deduplicated_count,
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
) -> CoverageReport:
    """Build the final CoverageReport from pipeline inputs."""
    req = list(requested_sources)
    att = list(attempted_sources)
    succ, fail = _partition_sources(source_statuses)

    queries_list = list(expanded_queries)
    raw_list = list(raw_results)
    norm_list = list(normalized_evidence)

    languages = _distinct_preserve_first(
        str(q.get("query_language") or "") for q in queries_list
    )
    markets = _distinct_preserve_first(
        str(q.get("market") or "") for q in queries_list
    )

    current_count = sum(
        1 for e in norm_list if str(e.get("window") or "") == "current"
    )
    baseline_count = sum(
        1 for e in norm_list if str(e.get("window") or "") == "baseline"
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
        deduplicated_count=int(deduplicated_dropped),
        current_window_count=current_count,
        baseline_window_count=baseline_count,
        languages_covered=languages,
        markets_covered=markets,
        gaps=tuple(gaps),
        warnings=tuple(warnings),
    )