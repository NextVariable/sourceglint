"""Error taxonomy (Phase 2 §13).

Small, deliberate. Distinct exception classes only when the failure mode is
distinct enough that callers can usefully branch on it.
"""
from __future__ import annotations


class GtmIntelligenceError(Exception):
    """Base class for all sourceglint deterministic-core errors."""


class SchemaValidationError(GtmIntelligenceError):
    """A payload did not satisfy a JSON Schema (structure invalid)."""


class EvidenceConflictError(GtmIntelligenceError):
    """The same evidence_id is being added with materially different content."""


class EvidenceMalformedError(GtmIntelligenceError):
    """The ledger storage (JSONL) contained a corrupt or unreadable line."""


class ReferentialIntegrityError(GtmIntelligenceError):
    """An object references evidence/signal/insight IDs that do not exist."""


class ScoringConfigError(GtmIntelligenceError):
    """Scoring config (weights/clamps) is invalid."""


class CitationIntegrityError(GtmIntelligenceError):
    """A claim lacks the required evidence traceability chain."""


class ConfigValidationError(GtmIntelligenceError):
    """A config file (e.g. sources.yaml, scoring.yaml) failed validation."""
