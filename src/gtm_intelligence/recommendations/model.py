"""Phase 6B §8 — recommendation tasks + response schemas + deterministic fake.

Reuses the Phase 5/6A IntelligenceModel boundary (PRD §7, §8). New task
constants, prompt versions, JSON response schemas and a deterministic
FakeRecommendationModel extend the existing fakes so tests drive the
whole 6A→6B chain offline.

Model owns: candidate action generation, semantic GTM action mapping,
action rationale, actionability assessment (impact / urgency / effort /
feasibility / reversibility), semantic duplicate groups, conflict
interpretation. Code validates everything else (§8).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..insights.model import FakeInsightModel, ModelResponse, ModelStatus
from ..insights.gtm_implications import GTM_DIMENSIONS
from .policy import ACTION_CLASSES, REVERSIBILITY_VALUES
from .ids import derive_recommendation_id

#: Task identifiers (PRD §31 — modular, single-responsibility prompts).
TASK_RECOMMENDATION_GENERATION = "recommendation_generation"
TASK_RECOMMENDATION_ASSESSMENT = "recommendation_assessment"
TASK_RECOMMENDATION_DEDUP = "recommendation_dedup"
TASK_RECOMMENDATION_CONFLICT = "recommendation_conflict"

#: Prompt versions — bump when a .md changes semantics (PRD §31).
PROMPT_VERSIONS: dict[str, str] = {
    TASK_RECOMMENDATION_GENERATION: "recommendation_generation:v1",
    TASK_RECOMMENDATION_ASSESSMENT: "recommendation_assessment:v1",
    TASK_RECOMMENDATION_DEDUP: "recommendation_dedup:v1",
    TASK_RECOMMENDATION_CONFLICT: "recommendation_conflict:v1",
}

#: Conflict kinds (§29).
CONFLICT_TRUE = "true_conflict"
CONFLICT_SEGMENT = "segment_specific"
CONFLICT_HORIZON = "time_horizon_specific"
CONFLICT_KINDS = (CONFLICT_TRUE, CONFLICT_SEGMENT, CONFLICT_HORIZON)


# --- JSON schemas the model output must satisfy (PRD §26) -------------------


def _dimension_items() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "string",
            "enum": sorted(GTM_DIMENSIONS),
        },
        "minItems": 1,
        "maxItems": 3,
        "uniqueItems": True,
    }


RECOMMENDATION_GENERATION_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["recommendations"],
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "statement", "action", "supporting_insight_ids",
                    "confidence", "action_class", "gtm_dimensions",
                    "action_anchor",
                ],
                "properties": {
                    "statement": {"type": "string", "minLength": 1},
                    "action": {"type": "string", "minLength": 1},
                    "supporting_insight_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "action_class": {"type": "string", "enum": list(ACTION_CLASSES)},
                    "gtm_dimensions": _dimension_items(),
                    "action_anchor": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 48,
                    },
                    "rationale": {"type": "string"},
                    "expected_outcome": {"type": "string"},
                },
            },
        }
    },
}

RECOMMENDATION_ASSESSMENT_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": [
        "expected_impact", "urgency", "effort", "feasibility", "reversibility",
    ],
    "properties": {
        "expected_impact": {"type": "number", "minimum": 0, "maximum": 1},
        "urgency": {"type": "number", "minimum": 0, "maximum": 1},
        "effort": {"type": "number", "minimum": 0, "maximum": 1},
        "feasibility": {"type": "number", "minimum": 0, "maximum": 1},
        "reversibility": {"type": "string", "enum": list(REVERSIBILITY_VALUES)},
        "rationale": {"type": "string"},
    },
}

RECOMMENDATION_DEDUP_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["duplicate_groups"],
    "properties": {
        "duplicate_groups": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
            },
        }
    },
}

RECOMMENDATION_CONFLICT_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["conflict_groups"],
    "properties": {
        "conflict_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rec_ids", "kind"],
                "properties": {
                    "rec_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    },
                    "kind": {"type": "string", "enum": list(CONFLICT_KINDS)},
                    "rationale": {"type": "string"},
                    "gtm_dimensions": _dimension_items(),
                },
            },
        }
    },
}


# --- deterministic fake scripts ---------------------------------------------


@dataclass(frozen=True)
class FakeRecommendationScript:
    """One scripted candidate recommendation."""

    statement: str
    action: str
    supporting_insight_ids: tuple[str, ...]
    action_class: str = "experiment"
    gtm_dimensions: tuple[str, ...] = ("pricing",)
    confidence: float = 0.6
    action_anchor: str = "action"
    rationale: str = ""
    expected_outcome: str = ""
    #: Optional scripted assessment returned for this candidate.
    expected_impact: float | None = None
    urgency: float | None = None
    effort: float | None = None
    feasibility: float | None = None
    reversibility: str | None = None
    assessment_rationale: str = ""

    def rec_id(self) -> str:
        return derive_recommendation_id(
            supporting_insight_ids=self.supporting_insight_ids,
            gtm_dimensions=self.gtm_dimensions,
            action_class=self.action_class,
            action_anchor=self.action_anchor,
        )

    def assessment(self) -> dict:
        return {
            "expected_impact": 0.5 if self.expected_impact is None else self.expected_impact,
            "urgency": 0.5 if self.urgency is None else self.urgency,
            "effort": 0.5 if self.effort is None else self.effort,
            "feasibility": 0.5 if self.feasibility is None else self.feasibility,
            "reversibility": "medium" if self.reversibility is None else self.reversibility,
            "rationale": self.assessment_rationale,
        }


@dataclass(frozen=True)
class FakeConflictScript:
    """One scripted conflict group (indices into recommendation scripts)."""

    indices: tuple[int, ...]
    kind: str = CONFLICT_SEGMENT
    rationale: str = ""
    gtm_dimensions: tuple[str, ...] = ()


@dataclass
class FakeRecommendationModel(FakeInsightModel):
    """Deterministic, offline, scripted model for the 6A→6B chain.

    Backward-compatible with FakeInsightModel: 6A insight tasks keep
    working (fact/inference/gtm/dedup), and the four 6B tasks
    (generation / assessment / dedup / conflict) are handled here.
    """

    recommendation_scripts: Sequence[FakeRecommendationScript] = ()
    conflict_scripts: Sequence[FakeConflictScript] = ()
    #: Semantic dedup groups: tuples of script indices judged duplicates.
    dedup_groups: tuple[tuple[int, ...], ...] = ()
    model_id: str = "fake_recommendation:v1"

    def complete_structured(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> ModelResponse:
        self.calls.append({"task": task, "payload": dict(payload)})
        if self.status is not ModelStatus.SUCCESS:
            return ModelResponse(
                task=task, status=self.status, error=f"fake status {self.status.value}"
            )
        if task == TASK_RECOMMENDATION_GENERATION:
            return self._generation()
        if task == TASK_RECOMMENDATION_ASSESSMENT:
            return self._assessment(payload)
        if task == TASK_RECOMMENDATION_DEDUP:
            return self._dedup()
        if task == TASK_RECOMMENDATION_CONFLICT:
            return self._conflict()
        return super().complete_structured(
            task=task, payload=payload, response_schema=response_schema
        )

    def _generation(self) -> ModelResponse:
        recs = [
            {
                "statement": s.statement,
                "action": s.action,
                "supporting_insight_ids": list(s.supporting_insight_ids),
                "confidence": s.confidence,
                "action_class": s.action_class,
                "gtm_dimensions": list(s.gtm_dimensions),
                "action_anchor": s.action_anchor,
                "rationale": s.rationale,
                "expected_outcome": s.expected_outcome,
            }
            for s in self.recommendation_scripts
        ]
        return ModelResponse(
            task=TASK_RECOMMENDATION_GENERATION,
            status=ModelStatus.SUCCESS,
            payload={"recommendations": recs},
        )

    def _assessment(self, payload: Mapping[str, Any]) -> ModelResponse:
        rec_id = str(payload.get("rec_id") or "")
        for script in self.recommendation_scripts:
            if script.rec_id() == rec_id:
                return ModelResponse(
                    task=TASK_RECOMMENDATION_ASSESSMENT,
                    status=ModelStatus.SUCCESS,
                    payload=script.assessment(),
                )
        # Unscripted candidate: neutral defaults, explicit "not assessed".
        return ModelResponse(
            task=TASK_RECOMMENDATION_ASSESSMENT,
            status=ModelStatus.SUCCESS,
            payload={
                "expected_impact": 0.5,
                "urgency": 0.5,
                "effort": 0.5,
                "feasibility": 0.5,
                "reversibility": "medium",
                "rationale": "not assessed",
            },
        )

    def _script_ids(self, indices: tuple[int, ...]) -> list[str]:
        ids: list[str] = []
        for idx in indices:
            if 0 <= idx < len(self.recommendation_scripts):
                ids.append(self.recommendation_scripts[idx].rec_id())
        return ids

    def _dedup(self) -> ModelResponse:
        groups = [
            self._script_ids(g) for g in self.dedup_groups
            if len(g) >= 2
        ]
        return ModelResponse(
            task=TASK_RECOMMENDATION_DEDUP,
            status=ModelStatus.SUCCESS,
            payload={"duplicate_groups": [g for g in groups if len(g) >= 2]},
        )

    def _conflict(self) -> ModelResponse:
        groups = [
            {
                "rec_ids": self._script_ids(c.indices),
                "kind": c.kind,
                "rationale": c.rationale,
                "gtm_dimensions": list(c.gtm_dimensions),
            }
            for c in self.conflict_scripts
            if len(c.indices) >= 2
        ]
        return ModelResponse(
            task=TASK_RECOMMENDATION_CONFLICT,
            status=ModelStatus.SUCCESS,
            payload={"conflict_groups": groups},
        )
