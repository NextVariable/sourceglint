"""Phase 2 Integration tests (deterministic pipeline regression)."""
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
    """Run the deterministic chain once for the module.

    Returns dict with: ledger, signals (with id), insights (with id),
    output (with id-resolved urls).
    """
    ledger = EvidenceLedger(":memory:")
    eids = []
    for ev in golden["evidence"]:
        rec = ledger.add(ev)
        eids.append(rec.evidence_id)
    return {
        "ledger": ledger,
        "evidence_ids": eids,
        "raw": golden,
    }


def _resolve_indices_to_ids(pipeline_obj, item_list, key="evidence_indices"):
    """Translate fixture-local numeric indices into deterministic ledger ids."""
    return [
        dict(item, **{key.replace("_indices", "_ids"): [
            pipeline_obj["evidence_ids"][i] for i in item[key]
        ]})
        for item in item_list
    ]


class TestPipelineEvidenceToLedger:
    def test_ledger_canonicalizes_and_assigns_ids(self, pipeline, golden):
        assert len(pipeline["evidence_ids"]) == len(golden["evidence"])
        for eid in pipeline["evidence_ids"]:
            assert eid.startswith("ev_")
            assert pipeline["ledger"].get(eid) is not None


class TestPipelineSignalValidation:
    def test_signal_passes_referential_integrity(self, pipeline, golden):
        cfg = ScoringConfig.default()
        signals_with_ids = _resolve_indices_to_ids(pipeline, golden["signals"])
        # Score first
        scored_signal_ids = []
        for i, sig in enumerate(signals_with_ids):
            sig["id"] = f"sig_{i}"
            breakdown = compute_score(sig["factors"], cfg=cfg)
            sig["score"] = breakdown.score
            signals_with_ids[i] = sig
            scored_signal_ids.append(sig["id"])
        # Run phase 2 validator on each
        for sig in signals_with_ids:
            res = validate_signal(pipeline["ledger"], sig)
            res.raise_if_invalid()


class TestPipelineInsightValidation:
    def test_insight_chain_intact(self, pipeline, golden):
        all_signals = _resolve_indices_to_ids(pipeline, golden["signals"])
        known_signal_ids = {f"sig_{i}" for i in range(len(all_signals))}
        all_insights = _resolve_indices_to_ids(pipeline, golden["insights"])
        # Add claim-level recommended_actions to relevant insights: filled separately
        for i, ins in enumerate(all_insights):
            ins["insight_id"] = f"ins_{i}"
            res = validate_insight(
                pipeline["ledger"], ins, known_signal_ids=known_signal_ids
            )
            res.raise_if_invalid()


class TestPipelineOutputValidation:
    def test_output_passes_referential_validator(self, pipeline, golden):
        out = golden["output"]
        # resolve evidence_indices to ids
        changes = _resolve_indices_to_ids(pipeline, out.get("changes", []))
        key_signals = _resolve_indices_to_ids(pipeline, out.get("key_signals", []))
        user_voice_raw = out.get("user_voice") or []
        user_voice = [
            {**uv, "evidence_id":
                pipeline["evidence_ids"][uv["evidence_indices"][0]]
                if uv.get("evidence_indices") else None}
            for uv in user_voice_raw
        ]
        # weak_signals
        weak_signals = _resolve_indices_to_ids(pipeline, out.get("weak_signals", []))
        # competitive_movement
        cm = out.get("competitive_movement")
        cm_resolved = None
        if isinstance(cm, dict):
            cm_resolved = {
                **cm,
                "evidence_ids": [pipeline["evidence_ids"][i]
                                 for i in cm.get("evidence_indices", [])],
            }
        # recommended_actions
        actions_raw = out.get("recommended_actions", [])
        actions = _resolve_indices_to_ids(pipeline, actions_raw)

        output_resolved = {
            "summary": out.get("summary"),
            "changes": changes,
            "key_signals": [
                {**ks, "signal_id": f"sig_{i}"}
                for i, ks in enumerate(key_signals)
            ],
            "user_voice": user_voice,
            "competitive_movement": cm_resolved,
            "weak_signals": weak_signals,
            "recommended_actions": actions,
            "confidence": out.get("confidence"),
            "gaps": out.get("gaps"),
            "coverage": out.get("coverage"),
        }
        res = validate_output(
            pipeline["ledger"],
            output_resolved,
            known_signal_ids={f"sig_{i}" for i in range(len(key_signals))},
        )
        res.raise_if_invalid()


class TestPipelineCitationTier:
    def test_all_insights_pass_citation_check(self, pipeline, golden):
        signals = _resolve_indices_to_ids(pipeline, golden["signals"])
        insights = _resolve_indices_to_ids(pipeline, golden["insights"])
        result = check_citations(
            pipeline["ledger"],
            insights=insights,
            known_signal_ids={f"sig_{i}" for i in range(len(signals))},
            known_insight_ids=set(),
        )
        result.raise_if_invalid()


class TestGoldenRenderByteStable:
    EXPECTED = (
        FIXTURES / "golden_pricing_change.expected.md"
    )

    def _render_full(self, pipeline, golden):
        """Drive the entire fixture through the deterministic chain."""
        out = golden["output"]
        # Resolve all indices to ids
        resolved_output = {
            "summary": out.get("summary"),
            "changes": [
                {**c, "evidence_ids": [
                    pipeline["evidence_ids"][i] for i in c["evidence_indices"]
                ]}
                for c in (out.get("changes") or [])
            ],
            "key_signals": [
                {**ks, "signal_id": f"sig_{i}", "evidence_ids": [
                    pipeline["evidence_ids"][i] for i in ks["evidence_indices"]
                ]}
                for i, ks in enumerate(out.get("key_signals") or [])
            ],
            "user_voice": [
                {
                    **uv,
                    "evidence_id": pipeline["evidence_ids"][uv["evidence_indices"][0]],
                }
                for uv in (out.get("user_voice") or [])
            ],
            "competitive_movement": (
                {
                    **out["competitive_movement"],
                    "evidence_ids": [
                        pipeline["evidence_ids"][i]
                        for i in out["competitive_movement"].get("evidence_indices", [])
                    ],
                }
                if isinstance(out.get("competitive_movement"), dict) else None
            ),
            "weak_signals": [
                {**w, "evidence_ids": [
                    pipeline["evidence_ids"][i] for i in w["evidence_indices"]
                ]}
                for w in (out.get("weak_signals") or [])
            ],
            "recommended_actions": [
                {**a, "evidence_ids": [
                    pipeline["evidence_ids"][i] for i in a["evidence_indices"]
                ]}
                for a in (out.get("recommended_actions") or [])
            ],
            "confidence": out.get("confidence"),
            "gaps": out.get("gaps"),
            "coverage": out.get("coverage"),
        }
        return render_markdown(pipeline["ledger"], resolved_output)

    def test_renders_expected_snapshot(self, pipeline, golden):
        rendered = self._render_full(pipeline, golden)
        expected = self.EXPECTED.read_text(encoding="utf-8")
        assert rendered == expected, (
            f"rendered output diverged from golden snapshot\n"
            f"--- rendered head ---\n{rendered[:400]}\n"
            f"--- expected head ---\n{expected[:400]}"
        )

    def test_repeat_renders_byte_identical(self, pipeline, golden):
        first = self._render_full(pipeline, golden)
        for _ in range(20):
            assert self._render_full(pipeline, golden) == first

    def test_from_empty_ledger_reproduces_chain(self, golden):
        # Re-build the ledger from scratch; the chain produces the same ids
        # and same rendered output.
        from gtm_intelligence.ids import canonicalize_url  # local for clarity

        def build_pipeline():
            ledger = EvidenceLedger(":memory:")
            eids = []
            for ev in golden["evidence"]:
                eids.append(ledger.add(ev).evidence_id)
            return {"ledger": ledger, "evidence_ids": eids}

        p_a = build_pipeline()
        p_b = build_pipeline()
        # Determinism across rebuilds: same fixture => identical ordered eids.
        assert p_a["evidence_ids"] == p_b["evidence_ids"]
        # And the rendered pipeline from either build is identical.
        rendered_a = self._render_full(p_a, golden)
        rendered_b = self._render_full(p_b, golden)
        assert rendered_a == rendered_b
        for ev in golden["evidence"]:
            canonical = canonicalize_url(ev["url"])
            assert canonical.startswith("https://")
