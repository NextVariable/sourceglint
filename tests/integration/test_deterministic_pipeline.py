"""Phase 2 Integration tests (strict Phase 1 Output contract)."""
import json
from pathlib import Path

import pytest

from gtm_intelligence.citations import check_citations
from gtm_intelligence.ledger import EvidenceLedger
from gtm_intelligence.rendering import render_markdown
from gtm_intelligence.scoring import ScoringConfig, compute_score
from gtm_intelligence.validation import (
    validate_insight,
    validate_output,
    validate_signal,
)


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="module")
def golden():
    return json.loads((FIXTURES / "golden_pricing_change.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pipeline(golden):
    ledger = EvidenceLedger(":memory:")
    eids = []
    for ev in golden["evidence"]:
        eids.append(ledger.add(ev).evidence_id)
    return {"ledger": ledger, "evidence_ids": eids, "raw": golden}


def _ids(pipeline_obj, indices):
    return [pipeline_obj["evidence_ids"][i] for i in indices]


class TestPipelineEvidenceToLedger:
    def test_ledger_canonicalizes_and_assigns_ids(self, pipeline, golden):
        assert len(pipeline["evidence_ids"]) == len(golden["evidence"])
        for eid in pipeline["evidence_ids"]:
            assert eid.startswith("ev_")
            assert pipeline["ledger"].get(eid) is not None


class TestPipelineSignalValidation:
    def test_signal_passes_referential_integrity(self, pipeline, golden):
        cfg = ScoringConfig.default()
        scored = []
        for i, sig in enumerate(golden["signals"]):
            breakdown = compute_score(sig["factors"], cfg=cfg)
            scored.append({
                "signal_id": f"sig_{i}",
                "topic": sig["topic"],
                "signal_type": sig["signal_type"],
                "evidence_ids": _ids(pipeline, sig["evidence_indices"]),
                "representative_evidence_ids": _ids(pipeline, sig["representative_evidence_indices"]),
                "supporting_evidence_ids": _ids(pipeline, sig["supporting_evidence_indices"]),
                "counter_evidence_ids": _ids(pipeline, sig["counter_evidence_indices"]),
                "score": breakdown.score,
                "confidence": sig["confidence"],
                "recency": sig["recency"],
                "novelty": sig["novelty"],
                "volume": sig["volume"],
                "source_diversity": sig["source_diversity"],
            })
        for sig in scored:
            res = validate_signal(pipeline["ledger"], sig)
            res.raise_if_invalid()


class TestPipelineCitationTier:
    def test_all_insights_pass_citation_check(self, pipeline, golden):
        scored_signal_ids = [f"sig_{i}" for i in range(len(golden["signals"]))]
        # Reference insight_ids from the fixture.
        known_insight_ids = {ins["insight_id"] for ins in golden["insights"]}
        insights_resolved = []
        for ins in golden["insights"]:
            insights_resolved.append({
                **ins,
                "evidence_ids": _ids(pipeline, ins["evidence_indices"]),
            })
        result = check_citations(
            pipeline["ledger"],
            insights=insights_resolved,
            known_signal_ids=set(scored_signal_ids),
            known_insight_ids=known_insight_ids,
            output_recommended_actions=golden["output"]["recommended_actions"],
        )
        result.raise_if_invalid()


class TestPipelineOutputValidation:
    def test_output_passes_validator(self, pipeline, golden):
        out = golden["output"]
        eids = pipeline["evidence_ids"]
        output_resolved = {
            "executive_intelligence": out.get("executive_intelligence"),
            "changes": out.get("changes"),
            "key_signals": [
                {**ks, "signal_id": f"sig_{i}"}
                for i, ks in enumerate(out.get("key_signals") or [])
            ],
            "user_voice": [
                {**uv, "evidence_id": eids[uv["evidence_indices"][0]]}
                for uv in (out.get("user_voice") or [])
            ],
            "competitive_movement": out.get("competitive_movement"),
            "weak_signals": [
                {**w, "evidence_ids": _ids(pipeline, w["evidence_indices"])}
                for w in (out.get("weak_signals") or [])
            ],
            "recommended_actions": out.get("recommended_actions"),
            "confidence": out.get("confidence"),
            "gaps": out.get("gaps"),
            "coverage": out.get("coverage"),
        }
        res = validate_output(
            pipeline["ledger"],
            output_resolved,
            known_signal_ids={f"sig_{i}" for i in range(len(out.get("key_signals") or []))},
        )
        res.raise_if_invalid()


class TestGoldenRenderByteStable:
    EXPECTED = FIXTURES / "golden_pricing_change.expected.md"

    def _render_full(self, pipeline, golden):
        out = golden["output"]
        eids = pipeline["evidence_ids"]
        resolved = {
            "executive_intelligence": out.get("executive_intelligence"),
            "changes": out.get("changes"),
            "key_signals": [
                {**ks, "signal_id": f"sig_{i}"}
                for i, ks in enumerate(out.get("key_signals") or [])
            ],
            "user_voice": [
                {**uv, "evidence_id": eids[uv["evidence_indices"][0]]}
                for uv in (out.get("user_voice") or [])
            ],
            "competitive_movement": out.get("competitive_movement"),
            "weak_signals": [
                {**w, "evidence_ids": _ids(pipeline, w["evidence_indices"])}
                for w in (out.get("weak_signals") or [])
            ],
            "recommended_actions": out.get("recommended_actions"),
            "confidence": out.get("confidence"),
            "gaps": out.get("gaps"),
            "coverage": out.get("coverage"),
        }
        return render_markdown(pipeline["ledger"], resolved)

    def test_renders_expected_snapshot(self, pipeline, golden):
        rendered = self._render_full(pipeline, golden)
        expected = self.EXPECTED.read_text(encoding="utf-8")
        assert rendered == expected, (
            "rendered output diverged from golden snapshot\n"
            f"--- rendered (head) ---\n{rendered[:400]}\n"
            f"--- expected (head) ---\n{expected[:400]}"
        )

    def test_repeat_renders_byte_identical(self, pipeline, golden):
        first = self._render_full(pipeline, golden)
        for _ in range(20):
            assert self._render_full(pipeline, golden) == first

    def test_from_empty_ledger_reproduces_chain(self, golden):
        from gtm_intelligence.ids import canonicalize_url  # local for clarity

        def build_pipeline():
            ledger = EvidenceLedger(":memory:")
            eids = []
            for ev in golden["evidence"]:
                eids.append(ledger.add(ev).evidence_id)
            return {"ledger": ledger, "evidence_ids": eids}

        p_a = build_pipeline()
        p_b = build_pipeline()
        assert p_a["evidence_ids"] == p_b["evidence_ids"]
        rendered_a = self._render_full(p_a, golden)
        rendered_b = self._render_full(p_b, golden)
        assert rendered_a == rendered_b
        for ev in golden["evidence"]:
            canonical = canonicalize_url(ev["url"])
            assert canonical.startswith("https://")
