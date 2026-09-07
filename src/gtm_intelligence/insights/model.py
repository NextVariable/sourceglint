"""Phase 6A §7 — reuse IntelligenceModel boundary.

The insights package reuses the Phase 5 IntelligenceModel protocol
without modification (PRD §7). New task constants, response schemas,
and a deterministic FakeInsightModel (backward-compatible extension
of FakeIntelligenceModel) are added so unit tests can drive the insight
pipeline offline.

No commercial LLM provider is named, imported, or depended on (PRD §7,
ADR-0001 D2). Host integrations implement IntelligenceModel outside
this repository.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..intelligence.model import (
    FakeIntelligenceModel,
    ModelResponse,
    ModelStatus,
)
from ..intelligence.dtos import CONTRADICTION_NONE

#: Task identifiers (PRD §29 — modular, single-responsibility prompts).
TASK_FACT_SYNTHESIS = "fact_synthesis"
TASK_INFERENCE_SYNTHESIS = "inference_synthesis"
TASK_GTM_IMPLICATIONS = "gtm_implications"
TASK_INSIGHT_DEDUP = "insight_dedup"

#: Prompt versions — bump when the .md changes semantics (PRD §29).
PROMPT_VERSIONS: dict[str, str] = {
    TASK_FACT_SYNTHESIS: "fact_synthesis:v1",
    TASK_INFERENCE_SYNTHESIS: "inference_synthesis:v1",
    TASK_GTM_IMPLICATIONS: "gtm_implications:v1",
    TASK_INSIGHT_DEDUP: "insight_dedup:v1",
}


# --- JSON schemas the model output must satisfy (PRD §26) -------------------

FACT_SYNTHESIS_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement", "signal_ids", "evidence_ids", "confidence"],
                "properties": {
                    "statement": {"type": "string", "minLength": 1},
                    "signal_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

INFERENCE_SYNTHESIS_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["inferences"],
    "properties": {
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement", "fact_ids", "signal_ids", "evidence_ids", "confidence"],
                "properties": {
                    "statement": {"type": "string", "minLength": 1},
                    "fact_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "signal_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                    "inference_distance": {"type": "integer", "minimum": 0, "maximum": 2},
                },
            },
        }
    },
}

GTM_IMPLICATIONS_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["implications"],
    "properties": {
        "implications": {
            "type": "object",
            "additionalProperties": {"type": ["string", "null"]},
        }
    },
}


# --- deterministic fake scripts ---------------------------------------------


@dataclass(frozen=True)
class FakeFactScript:
    """One scripted FACT: what the fake model will say about signals."""

    signal_ids: tuple[str, ...]
    statement: str
    evidence_ids: tuple[str, ...]
    confidence: float = 0.8
    rationale: str = ""

    def matches(self, payload_signal_ids: set[str]) -> bool:
        return set(self.signal_ids) <= payload_signal_ids


@dataclass(frozen=True)
class FakeInferenceScript:
    """One scripted INFERENCE: what the fake model will say about facts."""

    fact_ids: tuple[str, ...]
    signal_ids: tuple[str, ...]
    statement: str
    evidence_ids: tuple[str, ...]
    confidence: float = 0.6
    rationale: str = ""
    inference_distance: int = 1


@dataclass(frozen=True)
class FakeGTMImplicationScript:
    """One scripted GTM implication set for an insight."""

    insight_id: str
    implications: Mapping[str, str | None]


# --- deterministic fake insight model (PRD §40 step 2) ----------------------


@dataclass
class FakeInsightModel(FakeIntelligenceModel):
    """Deterministic, offline, scripted insight model.

    Backward-compatible with FakeIntelligenceModel: Phase 5 tasks
    (clustering, contradiction, semantic_factors) continue to work
    through the parent class. New insight tasks (fact_synthesis,
    inference_synthesis, gtm_implications) are handled here.

    Used by every unit test and the Phase 6A golden case — the default
    suite is 100% offline (PRD §5, Gate K).
    """

    fact_scripts: Sequence[FakeFactScript] = ()
    inference_scripts: Sequence[FakeInferenceScript] = ()
    gtm_scripts: Sequence[FakeGTMImplicationScript] = ()
    model_id: str = "fake_insight:v1"

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
        if task == TASK_FACT_SYNTHESIS:
            return self._fact_synthesis()
        if task == TASK_INFERENCE_SYNTHESIS:
            return self._inference_synthesis()
        if task == TASK_GTM_IMPLICATIONS:
            return self._gtm_implications(payload)
        if task == TASK_INSIGHT_DEDUP:
            return ModelResponse(
                task=task, status=ModelStatus.SUCCESS,
                payload={"duplicate_groups": []},
            )
        # Delegate to parent for Phase 5 tasks
        return super().complete_structured(
            task=task, payload=payload, response_schema=response_schema
        )

    def _fact_synthesis(self) -> ModelResponse:
        facts = [
            {
                "statement": s.statement,
                "signal_ids": list(s.signal_ids),
                "evidence_ids": list(s.evidence_ids),
                "confidence": s.confidence,
                "rationale": s.rationale,
            }
            for s in self.fact_scripts
        ]
        return ModelResponse(
            task=TASK_FACT_SYNTHESIS,
            status=ModelStatus.SUCCESS,
            payload={"facts": facts},
        )

    def _inference_synthesis(self) -> ModelResponse:
        inferences = [
            {
                "statement": s.statement,
                "fact_ids": list(s.fact_ids),
                "signal_ids": list(s.signal_ids),
                "evidence_ids": list(s.evidence_ids),
                "confidence": s.confidence,
                "rationale": s.rationale,
                "inference_distance": s.inference_distance,
            }
            for s in self.inference_scripts
        ]
        return ModelResponse(
            task=TASK_INFERENCE_SYNTHESIS,
            status=ModelStatus.SUCCESS,
            payload={"inferences": inferences},
        )

    def _gtm_implications(self, payload: Mapping[str, Any]) -> ModelResponse:
        insight_id = str(payload.get("insight_id") or "")
        for script in self.gtm_scripts:
            if script.insight_id == insight_id:
                return ModelResponse(
                    task=TASK_GTM_IMPLICATIONS,
                    status=ModelStatus.SUCCESS,
                    payload={"implications": dict(script.implications)},
                )
        return ModelResponse(
            task=TASK_GTM_IMPLICATIONS,
            status=ModelStatus.SUCCESS,
            payload={"implications": {}},
        )
