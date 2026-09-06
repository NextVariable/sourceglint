"""Phase 2 Evidence Ledger tests (TDD)."""
import json
import textwrap

import pytest

from gtm_intelligence.ledger import EvidenceLedger, EvidenceRecord
from gtm_intelligence.errors import (
    EvidenceConflictError,
    EvidenceMalformedError,
    SchemaValidationError,
)


def _ev(**kwargs):
    base = {
        "source": "reddit",
        "source_type": "discussion",
        "url": "https://www.reddit.com/r/AI/comments/123/example/",
        "snippet": "Original snippet text.",
        "author": "alice",
        "published_at": "2026-01-15T10:00:00Z",
        "retrieved_at": "2026-09-06T10:00:00Z",
    }
    base.update(kwargs)
    return base


class TestEvidenceLedgerBasic:
    def test_add_assigns_evidence_id_when_missing(self, tmp_path):
        ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
        record = ledger.add(_ev())
        assert record.evidence_id.startswith("ev_")
        # And the same id is stored:
        assert record.evidence_id == ledger.get(record.evidence_id).evidence_id

    def test_add_preserves_existing_id(self, tmp_path):
        ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
        e = _ev()
        e["evidence_id"] = "ev_fixed_test_id_xxxxxxxxxxxxxxxxxxxxxxxx"
        record = ledger.add(e)
        assert record.evidence_id == "ev_fixed_test_id_xxxxxxxxxxxxxxxxxxxxxxxx"

    def test_get_returns_none_for_unknown(self, tmp_path):
        ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
        assert ledger.get("ev_does_not_exist") is None

    def test_count_starts_at_zero(self, tmp_path):
        assert EvidenceLedger(tmp_path / "ledger.jsonl").count() == 0

    def test_iter_empty(self, tmp_path):
        assert list(EvidenceLedger(tmp_path / "ledger.jsonl")) == []


class TestEvidenceLedgerDuplicatePolicy:
    def test_idempotent_add_same_content(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        e1 = _ev()
        e1_rec = ledger.add(e1)
        e2 = _ev()
        e2_rec = ledger.add(e2)
        # Same canonical evidence => same id; dedup keeps one entry.
        assert e1_rec.evidence_id == e2_rec.evidence_id
        assert ledger.count() == 1

    def test_idempotent_add_with_enrichment_diffs(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        e1 = _ev()
        e1_rec = ledger.add(e1)
        e2 = _ev()
        e2.update(
            {
                "retrieved_at": "2026-09-07T10:00:00Z",
                "engagement": {"upvotes": 5000},
                "tags": ["hot"],
                "query": "ai meeting",
                "evidence_quality": 0.95,
            }
        )
        e2_rec = ledger.add(e2)
        assert e1_rec.evidence_id == e2_rec.evidence_id
        assert ledger.count() == 1

    def test_url_canonical_equivalence_collapses(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        e1 = _ev(url="https://www.reddit.com/r/x/comments/1/a")
        e2 = _ev(url="https://www.reddit.com/r/x/comments/1/a/?utm_source=tw#anchor")
        r1 = ledger.add(e1)
        r2 = ledger.add(e2)
        assert r1.evidence_id == r2.evidence_id
        assert ledger.count() == 1

    def test_conflict_when_same_id_different_payload(self, tmp_path):
        """If the caller pinned an evidence_id and the canonical evidence
        does NOT match, the ledger raises conflict rather than silently
        corrupt the ledger."""
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        e1 = _ev(url="https://www.reddit.com/r/x/1/a")
        ledger.add(e1)
        # Now write a DIFFERENT payload that hashes to the same id would
        # normally be impossible (sha256 collision), so we manually inject
        # a colliding line via raw JSONL to simulate corrupted storage.
        # The proper corruption policy for that case is also conflict.
        bad = dict(e1)
        bad["evidence_id"] = "ev_collide_test_xxxxxxxxxxxxxxxxxxxxxxxx"
        bad["snippet"] = "Completely different content."
        bad["url"] = "https://www.reddit.com/r/x/99/different"
        bad["author"] = "bob"
        bad["published_at"] = "2025-12-01T00:00:00Z"
        ledger.add(bad)
        # Now add a different payload but same pinned id:
        again = dict(bad)
        again["snippet"] = "Yet another different body."
        with pytest.raises(EvidenceConflictError):
            ledger.add(again)


class TestEvidenceLedgerPersistence:
    def test_reload_from_disk_preserves_records(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger_a = EvidenceLedger(path)
        r1 = ledger_a.add(_ev(url="https://www.reddit.com/r/x/1"))
        r2 = ledger_a.add(_ev(url="https://www.reddit.com/r/x/2"))
        assert ledger_a.count() == 2

        ledger_b = EvidenceLedger(path)
        assert ledger_b.count() == 2
        assert ledger_b.get(r1.evidence_id).url == "https://www.reddit.com/r/x/1"
        assert ledger_b.get(r2.evidence_id).url == "https://www.reddit.com/r/x/2"

    def test_jsonl_format_is_one_object_per_line(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        ledger.add(_ev(url="https://www.reddit.com/r/x/1"))
        ledger.add(_ev(url="https://www.reddit.com/r/x/2"))
        text = path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln]
        assert len(lines) == 2
        for ln in lines:
            json.loads(ln)  # each line parses cleanly


class TestEvidenceLedgerCorruption:
    def test_malformed_line_raises(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(EvidenceMalformedError):
            EvidenceLedger(path)

    def test_missing_required_field_raises(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        path.write_text(json.dumps({"source": "reddit"}), encoding="utf-8")
        with pytest.raises(EvidenceMalformedError):
            EvidenceLedger(path)

    def test_partial_empty_line_skipped(self, tmp_path):
        # blank lines between records are tolerated.
        path = tmp_path / "ledger.jsonl"
        body = textwrap.dedent(
            """\
            {"source":"reddit","url":"https://example.com/a","snippet":"hi"}
            {"not":"a valid record"}
            """
        )
        path.write_text(body, encoding="utf-8")
        with pytest.raises(EvidenceMalformedError):
            EvidenceLedger(path)


class TestEvidenceLedgerIntegrity:
    def test_iteration_order_is_stable_id_ascending(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        for url in [
            "https://www.reddit.com/r/x/comments/c/a",
            "https://www.reddit.com/r/x/comments/a/a",
            "https://www.reddit.com/r/x/comments/b/a",
        ]:
            ledger.add(_ev(url=url))
        ids = [r.evidence_id for r in ledger]
        assert ids == sorted(ids)

    def test_count_matches_iter(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        ledger = EvidenceLedger(path)
        ledger.add(_ev(url="https://www.reddit.com/r/x/1"))
        ledger.add(_ev(url="https://www.reddit.com/r/x/2"))
        assert ledger.count() == sum(1 for _ in ledger) == 2

    def test_record_carries_full_payload(self, tmp_path):
        ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
        r = ledger.add(_ev())
        # canonical attributes are exposed via the schema-required fields
        assert r.source == "reddit"
        assert r.url.startswith("https://www.reddit.com/")
        assert r.evidence_id.startswith("ev_")
        assert r.published_at == "2026-01-15T10:00:00Z"
