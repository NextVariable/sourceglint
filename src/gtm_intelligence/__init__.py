"""gtm-intelligence: deterministic core for GTM recent market intelligence.

Layer boundaries (per v0.2 Architecture Baseline):
  * This package: deterministic primitives only (Phase 2).
  * Phase 3 introduces Planner / Retrieval / Clustering (NOT here).
  * LLM calls live ONLY at the Query Expansion / Insight boundary (NOT here).
"""
from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("gtm-intelligence")

__all__ = ["__version__"]
