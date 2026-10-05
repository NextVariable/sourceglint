"""Phase 2 Referential Integrity Validator.

Schema validity != referential integrity (see Phase 1 boundary tests).
This module is the deterministic validator that closes the gap.

Validator does not auto-fix missing references. Validation surfaces
problems; fixing them is downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .errors import ReferentialIntegrityError
from .ledger import EvidenceLedger


@dataclass(frozen=True)
class IntegrityIssue:
    object_type: str
    object_id: str
    field: str
    missing_ids: list[str]
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        ids = ",".join(self.missing_ids)
        return (
            f"{self.object_type} {self.object_id!r} field {self.field} "
            f"references missing ids [{ids}]: {self.reason}"
        )


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: list[IntegrityIssue] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if not self.valid:
            bullets = "\n  - ".join(str(i) for i in self.issues)
            raise ReferentialIntegrityError(
                f"referential integrity failed:\n  - {bullets}"
            )


def _missing_in_ledger(
    ledger: EvidenceLedger, ids: Iterable[str]
) -> list[str]:
    return [eid for eid in ids if not ledger.exists(eid)]


def _check_evidence_fields(
    ledger: EvidenceLedger,
    *,
    object_type: str,
    object_id: str,
    payload: Mapping[str, object],
) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    # evidence_ids is expected on signal / insight / output, but treat absent as empty.
    for field_name in (
        "evidence_ids",
        "representative_evidence_ids",
        "supporting_evidence_ids",
        "counter_evidence_ids",
    ):
        ids = payload.get(field_name)
        if not isinstance(ids, list):
            continue
        missing = _missing_in_ledger(ledger, ids)
        if missing:
            issues.append(
                IntegrityIssue(
                    object_type=object_type,
                    object_id=object_id,
                    field=field_name,
                    missing_ids=missing,
                    reason="not in ledger",
                )
            )
    return issues


def validate_signal(
    ledger: EvidenceLedger, signal: Mapping[str, object]
) -> ValidationResult:
    issues = _check_evidence_fields(
        ledger,
        object_type="signal",
        object_id=str(signal.get("signal_id", "<missing>")),
        payload=signal,
    )
    # Semantic rule from Phase 1 signal.schema.json: contradictory signals
    # MUST carry at least one counter evidence id.
    if signal.get("signal_type") == "contradictory":
        counter = signal.get("counter_evidence_ids") or []
        if not counter:
            issues.append(
                IntegrityIssue(
                    object_type="signal",
                    object_id=str(signal.get("signal_id", "<missing>")),
                    field="counter_evidence_ids",
                    missing_ids=[],
                    reason="contradictory signals require at least one counter evidence id",
                )
            )
    return ValidationResult(valid=not issues, issues=issues)


def validate_insight(
    ledger: EvidenceLedger,
    insight: Mapping[str, object],
    *,
    known_signal_ids: Iterable[str] = (),
) -> ValidationResult:
    issues = _check_evidence_fields(
        ledger,
        object_type="insight",
        object_id=str(insight.get("insight_id", "<missing>")),
        payload=insight,
    )
    sig_ids = insight.get("signal_ids") or []
    known = set(known_signal_ids)
    missing_sigs = [s for s in sig_ids if s not in known]
    if missing_sigs:
        issues.append(
            IntegrityIssue(
                object_type="insight",
                object_id=str(insight.get("insight_id", "<missing>")),
                field="signal_ids",
                missing_ids=missing_sigs,
                reason="not in known signals",
            )
        )
    # FACT must have at least one evidence id (FACT/INFERENCE/RECOMMENDATION
    # structural isolation; without backing evidence a "fact" is a hallucination).
    if insight.get("type") == "FACT":
        ev = insight.get("evidence_ids") or []
        if not ev:
            issues.append(
                IntegrityIssue(
                    object_type="insight",
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="evidence_ids",
                    missing_ids=[],
                    reason="FACT must reference at least one evidence",
                )
            )
    return ValidationResult(valid=not issues, issues=issues)


def validate_output(
    ledger: EvidenceLedger,
    output: Mapping[str, object],
    *,
    known_signal_ids: Iterable[str] = (),
) -> ValidationResult:
    """Validate Phase 1 Output contract referential integrity.

    Only the fields Phase 1 Output schema declares are inspected:
      * user_voice[].evidence_id
      * weak_signals[].evidence_ids
    Citations into key_signals flow via signal_id -> insight.linkage
    and are checked at the citation tier (not here).
    recommended_actions[] actions reference insight_id (linkage), not
    evidence_ids directly, per schema. The recommended_actions block is
    validated at the citation tier (see citations.check_citations).
    """
    issues: list[IntegrityIssue] = []
    known = set(known_signal_ids)

    # user_voice[].evidence_id
    user_voice = output.get("user_voice") or []
    for idx, item in enumerate(user_voice):
        if not isinstance(item, Mapping):
            continue
        eid = item.get("evidence_id")
        if not eid:
            continue
        if not ledger.exists(str(eid)):
            issues.append(
                IntegrityIssue(
                    object_type="output",
                    object_id=f"user_voice[{idx}]",
                    field="user_voice[].evidence_id",
                    missing_ids=[str(eid)],
                    reason="not in ledger",
                )
            )

    # weak_signals[].evidence_ids
    weak_signals = output.get("weak_signals") or []
    for idx, item in enumerate(weak_signals):
        if not isinstance(item, Mapping):
            continue
        ids = item.get("evidence_ids") or []
        missing = _missing_in_ledger(ledger, ids)
        if missing:
            issues.append(
                IntegrityIssue(
                    object_type="output",
                    object_id=f"weak_signals[{idx}]",
                    field="weak_signals[].evidence_ids",
                    missing_ids=missing,
                    reason="not in ledger",
                )
            )

    # key_signals[].signal_id consistency (only when known_signal_ids is given).
    key_signals = output.get("key_signals") or []
    for idx, item in enumerate(key_signals):
        if not isinstance(item, Mapping):
            continue
        sid = item.get("signal_id")
        if sid and known and sid not in known:
            issues.append(
                IntegrityIssue(
                    object_type="output",
                    object_id=f"key_signals[{idx}]",
                    field="signal_id",
                    missing_ids=[str(sid)],
                    reason="not in known signals",
                )
            )

    return ValidationResult(valid=not issues, issues=issues)
