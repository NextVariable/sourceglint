"""Phase 6A §16 — support_strength computation tests."""
from __future__ import annotations

import pytest

from sourceglint.insights.support import (
    compute_support_strength,
    distinct_source_count,
)


def _ev(eid, url="", source="reddit"):
    return {"evidence_id": eid, "url": url, "source": source}


class TestDistinctSourceCount:
    def test_different_urls_on_one_domain_count_as_one_origin(self):
        ev = {
            "a": _ev("a", url="https://x.example/1"),
            "b": _ev("b", url="https://x.example/2"),
            "c": _ev("c", url="https://x.example/1"),  # duplicate url
        }
        assert distinct_source_count(("a", "b", "c"), ev) == 1

    def test_falls_back_to_source_name_when_no_url(self):
        ev = {"a": _ev("a"), "b": _ev("b")}
        assert distinct_source_count(("a", "b"), ev) == 1

    def test_missing_evidence_ignored(self):
        assert distinct_source_count(("a", "ghost"), {"a": _ev("a", url="u1")}) == 1


class TestComputeSupportStrength:
    def test_fact_minimum_positive(self):
        # 1 signal, 1 evidence, 1 source → still > 0.
        s = compute_support_strength(
            insight_type="FACT", n_signals=1, n_evidence=1, n_sources=1
        )
        assert 0.0 < s < 1.0

    def test_more_support_never_lowers(self):
        base = compute_support_strength(
            insight_type="FACT", n_signals=1, n_evidence=1, n_sources=1
        )
        stronger = compute_support_strength(
            insight_type="FACT", n_signals=3, n_evidence=6, n_sources=4
        )
        assert stronger >= base

    def test_contradiction_lowers_strength(self):
        base = compute_support_strength(
            insight_type="INFERENCE", n_signals=2, n_evidence=2,
            n_sources=2, n_facts=1,
        )
        mixed = compute_support_strength(
            insight_type="INFERENCE", n_signals=2, n_evidence=2,
            n_sources=2, n_facts=1, contradiction_preserved=True,
        )
        assert mixed == round(base - 0.10, 3)

    def test_weak_signal_lowers_strength(self):
        base = compute_support_strength(
            insight_type="FACT", n_signals=1, n_evidence=1, n_sources=1
        )
        weak = compute_support_strength(
            insight_type="FACT", n_signals=1, n_evidence=1,
            n_sources=1, weak_signal=True,
        )
        assert weak == round(base - 0.10, 3)

    def test_inference_with_two_facts_is_stronger_than_one(self):
        one = compute_support_strength(
            insight_type="INFERENCE", n_signals=2, n_evidence=4,
            n_sources=3, n_facts=1,
        )
        two = compute_support_strength(
            insight_type="INFERENCE", n_signals=2, n_evidence=4,
            n_sources=3, n_facts=2,
        )
        assert two > one

    def test_clamped_at_upper_bound(self):
        s = compute_support_strength(
            insight_type="INFERENCE", n_signals=10, n_evidence=10,
            n_sources=10, n_facts=10,
        )
        assert s <= 1.0

    def test_clamped_at_lower_bound(self):
        s = compute_support_strength(
            insight_type="FACT", n_signals=1, n_evidence=1, n_sources=1,
            contradiction_preserved=True, weak_signal=True,
        )
        assert s >= 0.0

    def test_deterministic(self):
        kwargs = dict(insight_type="FACT", n_signals=2, n_evidence=3, n_sources=2)
        assert compute_support_strength(**kwargs) == compute_support_strength(**kwargs)
