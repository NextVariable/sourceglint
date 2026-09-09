"""Phase 7 §20–§21, §56 — SkillResult contract.

Normalized external status taxonomy (never 15 internal states):

    SUCCESS      usable brief rendered
    PARTIAL      usable brief rendered with upstream degradation
    NO_EVIDENCE  research retrieved nothing usable (§19)
    FAILED       invalid request / pipeline could not produce a result

``SkillResult.brief_markdown`` is the artifact hosts display by default.
``diagnostics`` is optional / debug-only — never shown to a normal host.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .request import ParsedRequest


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NO_EVIDENCE = "NO_EVIDENCE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SkillResult:
    """One engine call's normalized result for a host (§56)."""

    status: Status
    brief_markdown: str = ""
    request: ParsedRequest | None = None
    research_plan: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    stage_statuses: Mapping[str, str] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)  # debug only

    @property
    def ok(self) -> bool:
        return self.status in (Status.SUCCESS, Status.PARTIAL, Status.NO_EVIDENCE)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status.value,
            "brief_markdown": self.brief_markdown,
            "warnings": list(self.warnings),
            "stage_statuses": dict(self.stage_statuses),
        }
        if self.request is not None:
            out["request"] = {
                "query": self.request.query,
                "mode": self.request.mode,
                "market": self.request.market,
                "languages": list(self.request.languages),
                "time_window": self.request.time_window,
                "time_window_text": self.request.time_window_text,
                "entities": list(self.request.entities),
                "query_language": self.request.query_language,
                "needs_clarification": self.request.needs_clarification,
            }
        if self.research_plan is not None:
            out["research_plan"] = dict(self.research_plan)
        if self.diagnostics:
            out["diagnostics"] = dict(self.diagnostics)
        return out
