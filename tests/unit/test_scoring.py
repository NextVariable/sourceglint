"""Phase 2 Signal Score tests (TDD)."""
import math
import textwrap

import pytest

from gtm_intelligence.errors import ScoringConfigError
from gtm_intelligence.scoring import (
    DEFAULT_FACTORS,
    ScoreBreakdown,
    ScoringConfig,
    compute_score,
    load_scoring_config,
)


# ----------------------------- ScoringConfig -----------------------------


class TestScoringConfig:
    def test_default_config_loads(self):
        cfg = ScoringConfig.default()
        assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9
        assert cfg.min_factor == 0.05
        assert set(cfg.weights) == set(DEFAULT_FACTORS)

    def test_load_from_yaml_deterministic(self, tmp_path):
        yaml = textwrap.dedent(
            """\
            version: 1
            min_factor: 0.05
            weights:
              decision_relevance: 0.35
              evidence_quality: 0.20
              recency: 0.15
              market_signal: 0.15
              novelty: 0.15
            """
        )
        p = tmp_path / "scoring.yaml"
        p.write_text(yaml, encoding="utf-8")
        cfg = load_scoring_config(p)
        assert cfg.min_factor == 0.05
        assert cfg.weights["decision_relevance"] == 0.35

    def test_weights_must_sum_to_one(self):
        # Construction itself enforces the sum invariant.
        with pytest.raises(ScoringConfigError, match="weights must sum"):
            ScoringConfig(
                weights={
                    "decision_relevance": 0.5,
                    "evidence_quality": 0.2,
                    "recency": 0.1,
                    "market_signal": 0.1,
                    "novelty": 0.05,
                },
                min_factor=0.05,
            )

    def test_weight_out_of_range(self):
        with pytest.raises(ScoringConfigError):
            ScoringConfig(
                weights={
                    "decision_relevance": 1.5,
                    "evidence_quality": -0.1,
                    "recency": 0.1,
                    "market_signal": 0.1,
                    "novelty": 0.4,
                },
                min_factor=0.05,
            )

    def test_missing_factor_in_payload(self):
        with pytest.raises(ScoringConfigError, match="missing"):
            compute_score(
                {
                    "decision_relevance": 0.8,
                    "evidence_quality": 0.7,
                    "recency": 0.6,
                    "novelty": 0.4,
                    # market_signal missing
                },
                cfg=ScoringConfig.default(),
            )

    def test_unknown_factor_in_payload_ignored(self):
        # Phase 2 is forward-compatible: unknown keys are ignored with no score
        # contribution. This protects against future Phase 5 adding factors.
        s = compute_score(
            {
                "decision_relevance": 0.8,
                "evidence_quality": 0.7,
                "recency": 0.6,
                "market_signal": 0.5,
                "novelty": 0.4,
                "extra_future_factor": 1.0,
            },
            cfg=ScoringConfig.default(),
        )
        assert isinstance(s, ScoreBreakdown)

    def test_min_factor_must_be_in_zero_one(self):
        with pytest.raises(ScoringConfigError):
            ScoringConfig(
                weights={
                    "decision_relevance": 0.35,
                    "evidence_quality": 0.20,
                    "recency": 0.15,
                    "market_signal": 0.15,
                    "novelty": 0.15,
                },
                min_factor=0.0,
            )
        with pytest.raises(ScoringConfigError):
            ScoringConfig(
                weights={
                    "decision_relevance": 0.35,
                    "evidence_quality": 0.20,
                    "recency": 0.15,
                    "market_signal": 0.15,
                    "novelty": 0.15,
                },
                min_factor=1.0,
            )


# ----------------------------- ScoreBreakdown -----------------------------


class TestScoreBreakdownShape:
    @pytest.fixture
    def one_breakdown(self):
        return compute_score(
            {
                "decision_relevance": 0.8,
                "evidence_quality": 0.7,
                "recency": 0.6,
                "market_signal": 0.5,
                "novelty": 0.4,
            },
            cfg=ScoringConfig.default(),
        )

    def test_breakdown_returns_dict_and_score(self, one_breakdown):
        assert isinstance(one_breakdown, ScoreBreakdown)
        assert 0.0 <= one_breakdown.score <= 1.0

    def test_breakdown_carries_components(self, one_breakdown):
        comps = one_breakdown.components
        assert set(comps) == set(DEFAULT_FACTORS)
        for f, c in comps.items():
            assert "raw" in c and "clamped_value" in c
            assert 0.0 <= c["clamped_value"] <= 1.0

    def test_breakdown_carries_weights(self, one_breakdown):
        assert one_breakdown.weights == ScoringConfig.default().weights

    def test_breakdown_carries_formula_and_clamp_floor(self, one_breakdown):
        assert one_breakdown.min_factor == 0.05
        assert "geometric" in one_breakdown.formula


# ----------------------------- Numeric behavior -----------------------------


class TestScoreSemantics:
    def _all_high(self):
        return {
            "decision_relevance": 1.0,
            "evidence_quality": 1.0,
            "recency": 1.0,
            "market_signal": 1.0,
            "novelty": 1.0,
        }

    def test_all_high_gives_one(self):
        b = compute_score(self._all_high(), cfg=ScoringConfig.default())
        assert b.score == pytest.approx(1.0, abs=1e-9)

    def test_all_low_at_floor(self):
        factors = {k: 0.01 for k in DEFAULT_FACTORS}  # all below floor -> clamp
        b = compute_score(factors, cfg=ScoringConfig.default())
        # Score is strictly > 0 because of floor clamping
        assert b.score > 0.0
        # And every component should report raw=0.01, clamped_value=0.05
        for c in b.components.values():
            assert c["raw"] == pytest.approx(0.01, abs=1e-9)
            assert c["clamped_value"] == pytest.approx(0.05, abs=1e-9)
            assert c["was_clamped"] is True

    def test_below_floor_factor_clamped_flagged(self):
        b = compute_score(
            {
                "decision_relevance": 1.0,
                "evidence_quality": 1.0,
                "recency": 1.0,
                "market_signal": 0.01,
                "novelty": 1.0,
            },
            cfg=ScoringConfig.default(),
        )
        assert b.components["market_signal"]["was_clamped"] is True
        # The score reflects the clamp and is non-zero:
        assert b.score > 0.0

    def test_boundary_zero_normalized(self):
        # 0 factors through configuration with min_factor=0.05 -> effectively 0.05
        # But a strict mode is not exposed via this surface (ScoreRange is fixed).
        # Verify raw 0 maps to clamped_value 0.05:
        b = compute_score(
            {
                "decision_relevance": 0.0,
                "evidence_quality": 0.0,
                "recency": 0.0,
                "market_signal": 0.0,
                "novelty": 0.0,
            },
            cfg=ScoringConfig.default(),
        )
        assert all(c["clamped_value"] == pytest.approx(0.05) for c in b.components.values())

    def test_invalid_factor_neg(self):
        with pytest.raises(ScoringConfigError):
            compute_score(
                {
                    "decision_relevance": -0.1,
                    "evidence_quality": 0.5,
                    "recency": 0.5,
                    "market_signal": 0.5,
                    "novelty": 0.5,
                },
                cfg=ScoringConfig.default(),
            )

    def test_invalid_factor_above_one(self):
        with pytest.raises(ScoringConfigError):
            compute_score(
                {
                    "decision_relevance": 1.5,
                    "evidence_quality": 0.5,
                    "recency": 0.5,
                    "market_signal": 0.5,
                    "novelty": 0.5,
                },
                cfg=ScoringConfig.default(),
            )


# ----------------------- Determinism & Weak-signal -----------------------


class TestScoreDeterminism:
    def test_same_input_same_output(self):
        f = {
            "decision_relevance": 0.81,
            "evidence_quality": 0.65,
            "recency": 0.92,
            "market_signal": 0.30,
            "novelty": 0.77,
        }
        a = compute_score(f, cfg=ScoringConfig.default())
        b = compute_score(f, cfg=ScoringConfig.default())
        assert a.score == b.score
        for f_name in DEFAULT_FACTORS:
            assert a.components[f_name] == b.components[f_name]

    def test_repeat_runs_consistent(self):
        f = {
            "decision_relevance": 0.6,
            "evidence_quality": 0.7,
            "recency": 0.5,
            "market_signal": 0.9,
            "novelty": 0.6,
        }
        scores = [compute_score(f, cfg=ScoringConfig.default()).score for _ in range(50)]
        first = scores[0]
        assert all(abs(s - first) < 1e-15 for s in scores)


class TestScoreWeakSignalCompatibility:
    """Weak signal = low engagement + high novelty + high decision_relevance.
    Must still receive a meaningful score so it isn't structurally killed
    by the engagement-first ranking. v0.2 §13."""

    def test_weak_signal_outperforms_loud_noise(self):
        weak = {
            "decision_relevance": 0.95,
            "evidence_quality": 0.85,
            "recency": 0.95,
            "market_signal": 0.02,   # very low engagement -> below floor
            "novelty": 0.95,
        }
        loud_noise = {
            "decision_relevance": 0.20,
            "evidence_quality": 0.30,
            "recency": 0.30,
            "market_signal": 1.00,
            "novelty": 0.10,
        }
        a = compute_score(weak, cfg=ScoringConfig.default()).score
        b = compute_score(loud_noise, cfg=ScoringConfig.default()).score
        assert a > b, f"weak={a} loud={b}"

    def test_weak_signal_score_meaningful(self):
        weak = {
            "decision_relevance": 1.0,
            "evidence_quality": 1.0,
            "recency": 1.0,
            "market_signal": 0.0,
            "novelty": 1.0,
        }
        a = compute_score(weak, cfg=ScoringConfig.default()).score
        # Should be much higher than the floor (== 0.05 ^ sum-weights).
        assert a > 0.3


# ----------------------------- Custom weights ----------------------------


class TestCustomWeights:
    def test_custom_weights_validated(self):
        cfg = ScoringConfig(
            weights={
                "decision_relevance": 0.5,
                "evidence_quality": 0.2,
                "recency": 0.1,
                "market_signal": 0.1,
                "novelty": 0.1,
            },
            min_factor=0.05,
        )
        b = compute_score(
            {k: 1.0 for k in DEFAULT_FACTORS},
            cfg=cfg,
        )
        assert b.score == pytest.approx(1.0, abs=1e-9)

    def test_shifting_weight_changes_ranking(self):
        f_a = {
            "decision_relevance": 0.95,
            "evidence_quality": 0.5,
            "recency": 0.5,
            "market_signal": 0.5,
            "novelty": 0.5,
        }
        f_b = {
            "decision_relevance": 0.5,
            "evidence_quality": 0.95,
            "recency": 0.5,
            "market_signal": 0.5,
            "novelty": 0.5,
        }
        cfg_dr_high = ScoringConfig(
            weights={
                "decision_relevance": 0.5,
                "evidence_quality": 0.15,
                "recency": 0.10,
                "market_signal": 0.10,
                "novelty": 0.15,
            },
            min_factor=0.05,
        )
        cfg_eq_high = ScoringConfig(
            weights={
                "decision_relevance": 0.15,
                "evidence_quality": 0.5,
                "recency": 0.10,
                "market_signal": 0.10,
                "novelty": 0.15,
            },
            min_factor=0.05,
        )
        # With DR-heavy weights, A (high DR) outranks B (high EQ).
        assert compute_score(f_a, cfg=cfg_dr_high).score > compute_score(f_b, cfg=cfg_dr_high).score
        assert compute_score(f_a, cfg=cfg_eq_high).score < compute_score(f_b, cfg=cfg_eq_high).score
