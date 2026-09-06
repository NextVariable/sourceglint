"""Cross-reference integrity boundary tests.

Locks the Phase 1 decision (user instruction §5):
"Schema validation does not imply referential integrity."

These tests DOCUMENT that structural schemas deliberately do NOT enforce
cross-object references (evidence_ids existing in ledger, signal_ids existing,
etc.). Referential integrity is a deterministic validator concern (Phase 2),
NOT a JSON Schema concern. If these tests start failing because someone added
referential magic to a schema, that is a Phase 2 scope violation.
"""

from __future__ import annotations

from conftest import validate


class TestSchemaDoesNotCheckReferences:
    def test_signal_referencing_unknown_evidence_passes_schema(self, signal_schema):
        sig = {
            "signal_id": "sig_zzz",
            "topic": "ghost signal",
            "evidence_ids": ["ev_does_not_exist_in_ledger_1"],
            "signal_type": "single_source",
        }
        # Schema must PASS this: existence check belongs to validator.
        validate(sig, signal_schema)

    def test_insight_referencing_unknown_signal_passes_schema(self, insight_schema):
        ins = {
            "insight_id": "ins_zzz",
            "type": "FACT",
            "statement": "references nothing real",
            "signal_ids": ["sig_does_not_exist"],
            "confidence": 0.9,
        }
        validate(ins, insight_schema)

    def test_output_user_voice_referencing_unknown_evidence_passes_schema(self, output_schema):
        out = {
            "user_voice": [{"quote": "q", "evidence_id": "ev_does_not_exist"}],
        }
        validate(out, output_schema)

    def test_representative_ids_not_subset_is_validator_concern(self, signal_schema):
        sig = {
            "signal_id": "sig_1",
            "topic": "t",
            "evidence_ids": ["ev_a"],
            "representative_evidence_ids": ["ev_not_in_evidence_ids"],
            "signal_type": "single_source",
        }
        validate(sig, signal_schema)  # subset semantics = validator (Phase 2)
