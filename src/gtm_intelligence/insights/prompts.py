"""Phase 6A §29 — modular, versioned prompt registry for insight tasks.

Each prompt is a separate markdown file with a single responsibility:
no giant monolithic prompt (PRD §29).

Version strings are EXPLICIT and feed the semantic cache key (PRD §30),
so editing a prompt invalidates cached model output instead of silently
reusing stale semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import PROMPT_VERSIONS

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class InsightPromptTemplate:
    task: str
    version: str
    path: Path

    def render(self) -> str:
        return self.path.read_text(encoding="utf-8")


def get_insight_prompt(task: str) -> InsightPromptTemplate:
    if task not in PROMPT_VERSIONS:
        raise KeyError(f"unknown insight prompt task: {task}")
    path = PROMPT_DIR / f"{task}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing for task {task}: {path}")
    return InsightPromptTemplate(
        task=task, version=PROMPT_VERSIONS[task], path=path
    )


def insight_prompt_version(task: str) -> str:
    if task not in PROMPT_VERSIONS:
        raise KeyError(f"unknown insight prompt task: {task}")
    return PROMPT_VERSIONS[task]
