"""Phase 6C unit-test support — fixture builders (mirrors 6A/6B)."""
from __future__ import annotations

from sourceglint.brief.dtos import BriefContext, BriefInput
from sourceglint.ledger import EvidenceLedger


def make_ledger(*records: dict) -> EvidenceLedger:
    ledger = EvidenceLedger(":memory:")
    for rec in records:
        ledger.add(dict(rec))
    return ledger


def evidence(eid: str, *, source: str = "official", url: str = "https://x.example/a") -> dict:
    return {
        "source": source,
        "source_type": "page",
        "url": url,
        "snippet": "snippet",
        "published_at": "2026-08-20T09:00:00Z",
        "retrieved_at": "2026-09-07T00:00:00Z",
        "market": "jp",
        "language": "en",
        "window": "current",
    }


def fact(iid: str, statement: str, *, evidence_ids=(), signal_ids=(), confidence=0.9, **kw) -> dict:
    return {
        "insight_id": iid,
        "type": "FACT",
        "statement": statement,
        "confidence": confidence,
        "signal_ids": list(signal_ids),
        "evidence_ids": list(evidence_ids),
        **kw,
    }


def inference(iid: str, statement: str, *, evidence_ids=(), signal_ids=(), confidence=0.6, **kw) -> dict:
    return {
        "insight_id": iid,
        "type": "INFERENCE",
        "statement": statement,
        "confidence": confidence,
        "signal_ids": list(signal_ids),
        "evidence_ids": list(evidence_ids),
        **kw,
    }


def recommendation(iid: str, action: str, *, priority: str = "now", confidence: float = 0.6,
                   evidence_ids=(), **kw) -> dict:
    return {
        "insight_id": iid,
        "type": "RECOMMENDATION",
        "statement": "internal statement",
        "confidence": confidence,
        "action": {"action": action, "priority": priority},
        "signal_ids": [],
        "evidence_ids": list(evidence_ids),
        **kw,
    }


def signal(sid: str, *, signal_type: str = "cross_source", evidence_ids=(), score: float = 0.7,
           confidence: float = 0.8, topic: str = "", **kw) -> dict:
    return {
        "signal_id": sid,
        "topic": topic or sid,
        "evidence_ids": list(evidence_ids),
        "signal_type": signal_type,
        "score": score,
        "confidence": confidence,
        **kw,
    }


def context(**kw) -> BriefContext:
    base = dict(
        query="AI meeting assistants in Japan",
        mode="trend",
        market="jp",
        languages=("en", "ja"),
        time_window="Last 30 days",
        as_of="2026-09-09",
        entities=("vendor",),
        decision_context="entry-price strategy",
    )
    base.update(kw)
    return BriefContext(**base)


def diag(insight_id: str, **kw) -> dict:
    base = {"insight_id": insight_id}
    base.update(kw)
    return base
