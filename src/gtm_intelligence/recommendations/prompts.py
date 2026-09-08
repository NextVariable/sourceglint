"""Phase 6B §31 — modular, versioned prompt registry for recommendation tasks.

Mirrors the Phase 6A registry pattern: each prompt is a separate markdown
file with a single responsibility. Version strings feed the semantic
cache key (§32).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import PROMPT_VERSIONS

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class RecommendationPromptTemplate:
    task: str
    version: str
    path: Path

    def render(self) -> str:
        return self.path.read_text(encoding="utf-8")


def get_recommendation_prompt(task: str) -> RecommendationPromptTemplate:
    if task not in PROMPT_VERSIONS:
        raise KeyError(f"unknown recommendation prompt task: {task}")
    path = PROMPT_DIR / f"{task}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing for task {task}: {path}")
    return RecommendationPromptTemplate(
        task=task, version=PROMPT_VERSIONS[task], path=path
    )
