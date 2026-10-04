"""Modular, versioned prompt registry (PRD §9, §29).

Each prompt is a separate markdown file with a single responsibility:
no giant monolithic prompt, and no prompt text living inside SKILL.md.

Version strings are EXPLICIT and feed the semantic cache key (PRD §28),
so editing a prompt invalidates cached model output instead of silently
reusing stale semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"

TASK_CLUSTERING = "clustering"
TASK_CONTRADICTION = "contradiction"
TASK_SEMANTIC_FACTORS = "semantic_factors"

#: Bump these whenever the corresponding .md changes semantics.
PROMPT_VERSIONS: dict[str, str] = {
    TASK_CLUSTERING: "clustering:v2",
    TASK_CONTRADICTION: "contradiction:v1",
    TASK_SEMANTIC_FACTORS: "semantic_factors:v1",
}


@dataclass(frozen=True)
class PromptTemplate:
    task: str
    version: str
    path: Path

    def render(self) -> str:
        return self.path.read_text(encoding="utf-8")


def get_prompt(task: str) -> PromptTemplate:
    if task not in PROMPT_VERSIONS:
        raise KeyError(f"unknown prompt task: {task}")
    path = PROMPT_DIR / f"{task}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing for task {task}: {path}")
    return PromptTemplate(task=task, version=PROMPT_VERSIONS[task], path=path)


def prompt_version(task: str) -> str:
    if task not in PROMPT_VERSIONS:
        raise KeyError(f"unknown prompt task: {task}")
    return PROMPT_VERSIONS[task]
