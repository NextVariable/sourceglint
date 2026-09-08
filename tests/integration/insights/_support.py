"""Phase 6A integration test support — fixture loaders."""
from __future__ import annotations

import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    parts = name.split("/")
    path = FIXTURE_DIR.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(name: str) -> list[dict]:
    parts = name.split("/")
    path = FIXTURE_DIR.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_phase6a_jsonl(name: str) -> list[dict]:
    """Load from tests/fixtures/phase6a/."""
    return load_jsonl(f"phase6a/{name}")
