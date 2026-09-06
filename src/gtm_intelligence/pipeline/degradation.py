"""Source-status taxonomy and graceful degradation (Phase 3 §18, §20).

The orchestrator wraps every source-adapter call in try/except and produces a
SourceStatusReport per source. The pipeline continues when individual
sources fail; only when ALL sources fail does the pipeline fail loudly.

We never embed raw credential VALUES in warnings. Only credential NAMES
are surfaced (per source_registry contract).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from .adapters import (
    AdapterAuthMissing,
    AdapterError,
    AdapterInvalidResponse,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)


class SourceStatus(str, Enum):
    """Per-source status taxonomy (PRD §18)."""

    SUCCESS = "success"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    AUTH_MISSING = "auth_missing"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


class AllSourcesFailedError(Exception):
    """Raised when every eligible source failed during a pipeline run."""

    def __init__(self, per_source: Mapping[str, "SourceStatusReport"]) -> None:
        statuses = ", ".join(
            f"{name}:{rep.status.value}" for name, rep in per_source.items()
        )
        super().__init__(f"all sources failed: [{statuses}]")
        self.per_source = dict(per_source)


class InvalidResearchPlanError(Exception):
    """Raised when the Research Plan is malformed BEFORE any retrieval starts."""


class InvalidSourceRegistryError(Exception):
    """Raised when sources.yaml fails schema/structural validation."""


@dataclass
class SourceStatusReport:
    """Per-source outcome of one pipeline run."""

    source: str
    status: SourceStatus = SourceStatus.SUCCESS
    count: int = 0
    warnings: list[str] = field(default_factory=list)

    def append_warning(self, message: str) -> None:
        if message and message not in self.warnings:
            self.warnings.append(message)

    def summary(self) -> str:
        return f"{self.source} status={self.status.value} count={self.count} warnings={len(self.warnings)}"

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return self.summary()


def classify_adapter_exception(exc: BaseException) -> SourceStatus:
    """Map an AdapterError subclass (or other exception) to a SourceStatus."""
    if isinstance(exc, AdapterAuthMissing):
        return SourceStatus.AUTH_MISSING
    if isinstance(exc, AdapterRateLimited):
        return SourceStatus.RATE_LIMITED
    if isinstance(exc, AdapterTimeout):
        return SourceStatus.TIMEOUT
    if isinstance(exc, AdapterInvalidResponse):
        return SourceStatus.INVALID_RESPONSE
    if isinstance(exc, AdapterUnavailable):
        return SourceStatus.UNAVAILABLE
    if isinstance(exc, AdapterError):
        return SourceStatus.UNAVAILABLE
    return SourceStatus.UNAVAILABLE


def build_status_report(
    *,
    source: str,
    results: Iterable[Mapping[str, object]],
    warnings: Iterable[str] = (),
) -> SourceStatusReport:
    """Build a per-source status report.

    status rules:
      * warnings non-empty + results > 0 → PARTIAL
      * warnings non-empty + results == 0 → PARTIAL (degraded but explicit)
      * otherwise → SUCCESS
    """
    results_list = list(results)
    warnings_list = [w for w in warnings if w]
    if warnings_list:
        status = SourceStatus.PARTIAL
    else:
        status = SourceStatus.SUCCESS
    rep = SourceStatusReport(
        source=source,
        status=status,
        count=len(results_list),
    )
    for w in warnings_list:
        rep.append_warning(w)
    return rep