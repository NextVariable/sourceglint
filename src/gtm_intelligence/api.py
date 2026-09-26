"""Phase 7 §16 — canonical public entry point.

Single import surface hosts and the CLI use:

    from gtm_intelligence.api import run_gtm_intelligence
"""
from .application.api import run_gtm_intelligence

__all__ = ["run_gtm_intelligence"]
