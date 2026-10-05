"""Phase 2 Signal Score (configurable, transparent, deterministic).

v0.2 Architecture Baseline:
  * Formula (D9, weighted geometric mean):
        score = product_f  (max(f, min_factor)) ** weight[f]
    Min_factor=0.05 (architecture-decision: transparent clamp at 0.05
    plus factor_was_clamped=True in components).
  * Decision Relevance weight = 0.35 (highest).
  * Engagement is NOT importance: market_signal is one factor among five.
  * No engagement-only ranking.

This module is deterministic code. It MUST produce byte-identical output
across machines and runs given the same config + same factors.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from .errors import ScoringConfigError


DEFAULT_FACTORS: tuple[str, ...] = (
    "decision_relevance",
    "evidence_quality",
    "recency",
    "market_signal",
    "novelty",
)


# v0.2 §10 / D9 frozen defaults.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "decision_relevance": 0.35,
    "evidence_quality": 0.20,
    "recency": 0.15,
    "market_signal": 0.15,
    "novelty": 0.15,
}
DEFAULT_MIN_FACTOR = 0.05

_FLOAT_EPS = 1e-9


@dataclass(frozen=True)
class ScoringConfig:
    """The single source of truth for signal scoring parameters."""

    weights: Mapping[str, float]
    min_factor: float

    @classmethod
    def default(cls) -> "ScoringConfig":
        return cls(weights=dict(DEFAULT_WEIGHTS), min_factor=DEFAULT_MIN_FACTOR)

    def __post_init__(self) -> None:
        keys = set(self.weights)
        missing = [k for k in DEFAULT_FACTORS if k not in keys]
        if missing:
            raise ScoringConfigError(
                f"weights missing required factors: {missing}"
            )
        for k, v in self.weights.items():
            if not (0.0 <= v <= 1.0):
                raise ScoringConfigError(
                    f"weight for {k} out of [0,1]: {v}"
                )
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ScoringConfigError(
                f"weights must sum to 1.0 (got {total:.6f})"
            )
        if not (0.0 < self.min_factor < 1.0):
            raise ScoringConfigError(
                f"min_factor must be in (0, 1) (got {self.min_factor})"
            )


@dataclass(frozen=True)
class ScoreBreakdown:
    """Transparent, testable, renderable result of compute_score()."""

    score: float
    formula: str
    min_factor: float
    weights: dict
    components: dict  # {factor: {"raw": float, "clamped_value": float, "was_clamped": bool}}

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "formula": self.formula,
            "min_factor": self.min_factor,
            "weights": dict(self.weights),
            "components": {
                k: {"raw": v["raw"], "clamped_value": v["clamped_value"],
                     "was_clamped": bool(v.get("was_clamped", False))}
                for k, v in self.components.items()
            },
        }


def load_scoring_config(path: Path) -> ScoringConfig:
    with Path(path).open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    weights = {**DEFAULT_WEIGHTS, **(doc.get("weights") or {})}
    min_factor = float(doc.get("min_factor", DEFAULT_MIN_FACTOR))
    return ScoringConfig(weights=weights, min_factor=min_factor)


def _validate_factor(name: str, value: object) -> float:
    if not isinstance(value, (int, float)):
        raise ScoringConfigError(f"factor {name} is not numeric: {value!r}")
    v = float(value)
    if math.isnan(v) or v < 0.0 or v > 1.0:
        raise ScoringConfigError(
            f"factor {name} must be in [0,1] (got {v})"
        )
    return v


def compute_score(
    factors: Mapping[str, object],
    *,
    cfg: ScoringConfig | None = None,
) -> ScoreBreakdown:
    """Compute a deterministic weighted-geometric signal score.

    Args:
        factors: A mapping of factor_name -> raw 0..1 value. Unknown keys
            (e.g. future Phase 5 additions) are silently ignored, so this
            module remains forward-compatible.
        cfg: Optional ScoringConfig override. Defaults to v0.2 D9 frozen
            weights + 0.05 floor.

    Returns:
        ScoreBreakdown with score, weights, components, and the formula
        identifier used.
    """
    cfg = cfg or ScoringConfig.default()

    components: dict = {}
    # Phase-2 forward-compat: only known factors contribute.
    for factor_name in DEFAULT_FACTORS:
        if factor_name not in factors:
            raise ScoringConfigError(
                f"factor payload missing required key: {factor_name}"
            )
        raw = _validate_factor(factor_name, factors[factor_name])
        clamped_value = max(raw, cfg.min_factor)
        components[factor_name] = {
            "raw": raw,
            "clamped_value": clamped_value,
            "was_clamped": clamped_value > raw + _FLOAT_EPS,
        }

    # Weighted geometric mean.
    log_score = 0.0
    total_weight = 0.0
    for factor_name, comp in components.items():
        w = float(cfg.weights[factor_name])
        log_score += w * math.log(comp["clamped_value"])
        total_weight += w
    # Defensive in case future customization adds zero-weight factors.
    if abs(total_weight) > _FLOAT_EPS:
        score = math.exp(log_score / total_weight) if total_weight else 0.0
    else:
        score = 0.0

    return ScoreBreakdown(
        score=float(score),
        formula="weighted_geometric_mean_with_floor",
        min_factor=cfg.min_factor,
        weights={k: float(v) for k, v in cfg.weights.items()},
        components=components,
    )
