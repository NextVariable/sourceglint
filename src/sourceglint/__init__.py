"""sourceglint: evidence-linked recent research with opt-in decision support.

The application layer composes retrieval, host reasoning and validation.
The public API is sourceglint.api.run_sourceglint.
"""
from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("sourceglint")

__all__ = ["__version__"]
