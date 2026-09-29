"""Phase 2 Citation Integrity.

Deterministic claim -> evidence traceability checks. This module verifies
that every claim has a structurally complete chain to Evidence Ledger IDs;
it does NOT verify that the evidence actually supports the claim
(semantic judgement belongs to LLM/eval layers; see v0.2 §11).

Contract:
  * FACT
      - must have at least one evidence id
      - every evidence id must exist in the ledger
  * INFERENCE
      - must trace via either evidence_ids OR signal_ids (or both)
      - cited evidence ids must exist in ledger
      - cited signal ids must be in known_signal_ids
  * RECOMMENDATION
      - must carry an action string (schema-level guarantees already exist)
      - traceability can be via signal chain OR direct evidence OR insight
        chain (a strategy recommendation does not need direct evidence; it
        traces the analytical chain upstream)
      - cited evidence ids must exist in ledger
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .errors import CitationIntegrityError
from .ledger import EvidenceLedger
from .validation import IntegrityIssue


def _missing_in_ledger(ledger: EvidenceLedger, ids: Iterable[str]) -> list[str]:
    return [eid for eid in ids if not ledger.exists(eid)]


def _check_insight(
    ledger: EvidenceLedger,
    insight: Mapping[str, object],
    *,
    known_signal_ids: set[str],
    issue_target_object: str,
) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    itype = insight.get("type")
    eids = list(insight.get("evidence_ids") or [])
    sids = list(insight.get("signal_ids") or [])

    # Evidence chain integrity (shared across types).
    missing_e = _missing_in_ledger(ledger, eids)
    if missing_e:
        issues.append(
            IntegrityIssue(
                object_type=issue_target_object,
                object_id=str(insight.get("insight_id", "<missing>")),
                field="evidence_ids",
                missing_ids=missing_e,
                reason="cited evidence ids not in ledger",
            )
        )

    if itype == "FACT":
        if not eids:
            issues.append(
                IntegrityIssue(
                    object_type=issue_target_object,
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="evidence_ids",
                    missing_ids=[],
                    reason="FACT must reference at least one evidence",
                )
            )
    elif itype == "INFERENCE":
        if not eids and not sids:
            issues.append(
                IntegrityIssue(
                    object_type=issue_target_object,
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="evidence_ids/signal_ids",
                    missing_ids=[],
                    reason="INFERENCE must trace via evidence_ids or signal_ids",
                )
            )
        missing_s = [s for s in sids if s not in known_signal_ids]
        if missing_s:
            issues.append(
                IntegrityIssue(
                    object_type=issue_target_object,
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="signal_ids",
                    missing_ids=missing_s,
                    reason="INFERENCE cites unknown signals",
                )
            )
    elif itype == "RECOMMENDATION":
        action = (insight.get("action") or "").strip()
        if not action:
            # This is a schema-level issue but citation integrity checks
            # the chain too; surface as a high-severity issue here.
            issues.append(
                IntegrityIssue(
                    object_type=issue_target_object,
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="action",
                    missing_ids=[],
                    reason="RECOMMENDATION must carry an action",
                )
            )
        # RECOMMENDATION can have no direct evidence (strategy); traceability
        # suffices via signal chain. If both empty, chain is dangling.
        if not eids and not sids:
            issues.append(
                IntegrityIssue(
                    object_type=issue_target_object,
                    object_id=str(insight.get("insight_id", "<missing>")),
                    field="evidence_ids/signal_ids",
                    missing_ids=[],
                    reason="RECOMMENDATION must trace via evidence_ids or signal_ids",
                )
            )
    return issues


def check_citations(
    ledger: EvidenceLedger,
    insights: Iterable[Mapping[str, object]],
    *,
    known_signal_ids: Iterable[str] = (),
    known_insight_ids: Iterable[str] = (),
    output_recommended_actions: Mapping[str, object] | None = None,
) -> ValidationResult:
    """Verify structural claim -> evidence chains.

    Two entry points:
      * `insights`: a list of insight mappings (FACT/INFERENCE/RECOMMENDATION).
      * `output_recommended_actions`: the Phase 1 Output contract's
        `recommended_actions` block (with now/next/watch buckets); each
        action carries `action` + optional `insight_id`. Citation tier
        verifies the `insight_id` exists in `known_insight_ids` (when the
        set is non-empty) -- evidence traceability flows through the
        insight, per Phase 1 Output schema.
    """
    issues: list[IntegrityIssue] = []
    known_signals = set(known_signal_ids)
    known_insights = set(known_insight_ids)

    for ins in insights:
        issues.extend(
            _check_insight(
                ledger,
                ins,
                known_signal_ids=known_signals,
                issue_target_object="insight",
            )
        )

    if output_recommended_actions is not None:
        # Phase 1 schema: recommended_actions = {now: [], next: [], watch: []}
        for bucket_name, items in [
            ("now", output_recommended_actions.get("now", []) or []),
            ("next", output_recommended_actions.get("next", []) or []),
            ("watch", output_recommended_actions.get("watch", []) or []),
        ]:
            for idx, action in enumerate(items):
                if not isinstance(action, Mapping):
                    continue
                if not (action.get("action") or "").strip():
                    issues.append(
                        IntegrityIssue(
                            object_type="output_recommendation",
                            object_id=f"recommended_actions.{bucket_name}[{idx}]",
                            field="action",
                            missing_ids=[],
                            reason="empty action",
                        )
                    )
                iid = action.get("insight_id")
                if not iid:
                    issues.append(
                        IntegrityIssue(
                            object_type="output_recommendation",
                            object_id=f"recommended_actions.{bucket_name}[{idx}]",
                            field="insight_id",
                            missing_ids=[],
                            reason="no insight linkage; action cannot trace to evidence chain",
                        )
                    )
                elif known_insights and str(iid) not in known_insights:
                    issues.append(
                        IntegrityIssue(
                            object_type="output_recommendation",
                            object_id=f"recommended_actions.{bucket_name}[{idx}]",
                            field="insight_id",
                            missing_ids=[str(iid)],
                            reason="output action references unknown insight",
                        )
                    )
                elif not known_insights:
                    # Strict fallback: no known_insight_ids provided, so any
                    # non-empty insight_id reference is unverified.
                    issues.append(
                        IntegrityIssue(
                            object_type="output_recommendation",
                            object_id=f"recommended_actions.{bucket_name}[{idx}]",
                            field="insight_id",
                            missing_ids=[],
                            reason="insight_id referenced but no known_insight_ids supplied",
                        )
                    )

    return CitationValidationResult(valid=not issues, issues=issues)


@dataclass(frozen=True)
class CitationValidationResult:
    """Citation-tier result. `raise_if_invalid` raises CitationIntegrityError."""

    valid: bool
    issues: list

    def raise_if_invalid(self) -> None:
        if not self.valid:
            bullets = "\n  - ".join(str(i) for i in self.issues)
            raise CitationIntegrityError(
                f"citation integrity failed:\n  - {bullets}"
            )
