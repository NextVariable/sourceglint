"""Resolve bundled runtime data in editable checkouts and installed wheels."""
from pathlib import Path


def data_path(*parts: str) -> Path:
    package = Path(__file__).resolve().parent
    bundled = package / "_data"
    if bundled.is_dir():
        return bundled.joinpath(*parts)
    return package.parents[1].joinpath(*parts)
