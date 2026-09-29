"""Phase 7 §16 — canonical public entry point.

Single import surface hosts and the CLI use:

    from sourceglint.api import run_sourceglint
"""
from .application.api import run_sourceglint

__all__ = ["run_sourceglint"]
