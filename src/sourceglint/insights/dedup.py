"""Phase 6A §22 — insight deduplication.

Detects semantic duplicates via:
1. structural overlap (same insight_id → same type + sorted signals + sorted evidence)
2. signal overlap plus identical evidence and statement → duplicate

Not string similarity only (§22). For MVP, structural + signal overlap
is the primary mechanism. Model semantic dedup is optional (the task
constant exists; the pipeline may call it but does not require it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


# --- signal overlap (§22: structural → signal → semantic) ------------------


def _signal_overlap(ids_a: Iterable[str], ids_b: Iterable[str]) -> float:
    """Jaccard similarity of two signal-id sets (0.0–1.0)."""
    set_a = {str(i) for i in ids_a if str(i)}
    set_b = {str(i) for i in ids_b if str(i)}
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


#: Threshold for signal-overlap-based dedup (§22: "supporting signal overlap").
SIGNAL_OVERLAP_THRESHOLD = 0.5


# --- result ----------------------------------------------------------------


@dataclass(frozen=True)
class DedupResult:
    """Output of deduplicate_insights()."""
    kept: tuple[dict, ...] = ()
    removed: tuple[dict, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "kept": [dict(i) for i in self.kept],
            "removed": [dict(i) for i in self.removed],
            "warnings": list(self.warnings),
        }


# --- deduplication (§22) ---------------------------------------------------


def deduplicate_insights(
    insights: Sequence[Mapping[str, object]],
    *,
    signal_overlap_threshold: float = SIGNAL_OVERLAP_THRESHOLD,
) -> DedupResult:
    """Remove structural and signal-overlap duplicates (PRD §22).

    Two-pass dedup:
      1. Structural: same insight_id → exact duplicate, first kept.
      2. Signal overlap: >threshold Jaccard on signal_ids AND same type,
         identical evidence IDs, and identical normalized statement →
         duplicate; keep higher confidence (first breaks ties).

    A shared signal alone cannot establish duplicate meaning: separate
    evidence items may support distinct FACTs within one signal.

    Does NOT use string similarity (§22: "不要只用字符串相似度").
    Does NOT merge different types (FACT ≠ INFERENCE even with same signals).
    """
    if not insights:
        return DedupResult()

    kept: list[dict] = []
    removed: list[dict] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()

    # Sort by insight_id for determinism (first occurrence = canonical)
    ordered = sorted(insights, key=lambda i: str(i.get("insight_id") or ""))

    # Pass 1: structural dedup (same insight_id)
    for ins in ordered:
        ins_id = str(ins.get("insight_id") or "")
        if ins_id in seen_ids:
            removed.append(dict(ins))
            warnings.append(f"dedup: structural duplicate removed: {ins_id}")
            continue
        seen_ids.add(ins_id)
        kept.append(dict(ins))

    # Pass 2: signal overlap dedup (same type + high signal overlap)
    final: list[dict] = []
    for candidate in kept:
        is_dup = False
        for survivor in final:
            if str(candidate.get("type")) != str(survivor.get("type")):
                continue
            overlap = _signal_overlap(
                candidate.get("signal_ids") or [],
                survivor.get("signal_ids") or [],
            )
            same_evidence = set(candidate.get("evidence_ids") or []) == set(
                survivor.get("evidence_ids") or []
            )
            same_statement = " ".join(
                str(candidate.get("statement") or "").casefold().split()
            ) == " ".join(
                str(survivor.get("statement") or "").casefold().split()
            )
            if overlap > signal_overlap_threshold and same_evidence and same_statement:
                # Keep higher confidence; first breaks ties
                cand_conf = float(candidate.get("confidence") or 0.0)
                surv_conf = float(survivor.get("confidence") or 0.0)
                if cand_conf > surv_conf:
                    # Candidate wins — replace survivor
                    removed.append(dict(survivor))
                    warnings.append(
                        f"dedup: signal-overlap duplicate removed: "
                        f"{survivor.get('insight_id')} (overlap={overlap:.2f})"
                    )
                    final.remove(survivor)
                    final.append(candidate)
                else:
                    removed.append(dict(candidate))
                    warnings.append(
                        f"dedup: signal-overlap duplicate removed: "
                        f"{candidate.get('insight_id')} (overlap={overlap:.2f})"
                    )
                is_dup = True
                break
        if not is_dup:
            final.append(candidate)

    # Deterministic order: insight_id ascending
    final.sort(key=lambda i: str(i.get("insight_id") or ""))

    return DedupResult(
        kept=tuple(final),
        removed=tuple(removed),
        warnings=tuple(warnings),
    )
