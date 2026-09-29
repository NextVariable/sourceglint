"""Phase 6C — deterministic Markdown renderer (§22–§25, §41).

Byte-stable composition of the section builders in fixed order:

    1. Research Context    6. Watchouts
    2. Executive Summary   7. Emerging Signals
    3. What We Know        8. Coverage
    4. What It Likely Means  9. Sources
    5. Recommended Actions

Empty sections are dropped (§25). Plain Python string ops, no Jinja2,
no clock/locale/random, no model, no network (Gate K). Reuses the Phase 2
formatting layer via `sections` (heading/citation helpers imported from
`sourceglint.rendering`).
"""
from __future__ import annotations

from typing import Any

from . import sections
from .dtos import SelectedBrief

__all__ = ["render_brief_markdown", "render_no_evidence_markdown"]


def render_brief_markdown(
    selected: SelectedBrief, ledger: Any = None
) -> str:
    """Render a fully selected brief to deterministic Markdown.

    `selected` is the output of the selection layer (already ranked,
    capped, resolved); the renderer only formats it. `ledger` (an
    EvidenceLedger) supplies canonical [source](url) citations.
    """
    lookup = sections._evidence_lookup(ledger) if ledger is not None else {}
    parts = [
        sections.research_context(selected.context),
        sections.executive(selected),
        sections.facts(selected, lookup),
        sections.inferences(selected, lookup),
        sections.actions(selected, lookup),
        sections.watchouts(selected, lookup),
        sections.emerging(selected, lookup),
        sections.recent_items(selected, ledger),
        sections.coverage(selected),
        sections.sources(selected, lookup),
    ]
    return "".join(parts).rstrip() + "\n"


def render_no_evidence_markdown(context: Any = None) -> str:
    """The fixed no-evidence document (Phase 6C §20)."""
    return sections.no_evidence_markdown(context)
