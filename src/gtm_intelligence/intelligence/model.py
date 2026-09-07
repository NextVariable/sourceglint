"""Phase 5 §5 / §27 / §40 — the host-neutral IntelligenceModel boundary.

The core defines a NEUTRAL protocol. No commercial LLM provider is
named, imported, or depended on anywhere in this package (enforced by a
regression test). Host integrations implement the protocol outside this
repository and inject an instance at runtime; swapping the provider must
not require a single change to the intelligence core (PRD §40).

Implementation order mandated by PRD §40:
    1. protocol           → this module
    2. fake model         → FakeIntelligenceModel
    3. fixture model      → FixtureIntelligenceModel
    4. pipeline           → pipeline.py
    5. tests
    6. optional host model example (NOT in this repo)

Failure semantics (PRD §27): model problems are reported as a STATUS,
never as an exception that escapes into the deterministic core.
`IntelligencePipelineError` is raised only when a *required* step
(clustering) has no usable output at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .dtos import CONTRADICTION_NONE
from .ids import derive_cluster_id
from .prompts import TASK_CLUSTERING, TASK_CONTRADICTION, TASK_SEMANTIC_FACTORS


class ModelStatus(str, Enum):
    """PRD §27 status taxonomy."""

    SUCCESS = "success"
    INVALID_OUTPUT = "invalid_output"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class IntelligencePipelineError(RuntimeError):
    """Raised when a REQUIRED intelligence step cannot proceed."""


@dataclass(frozen=True)
class ModelResponse:
    task: str
    status: ModelStatus
    payload: Mapping[str, Any] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ModelStatus.SUCCESS and self.payload is not None


@runtime_checkable
class IntelligenceModel(Protocol):
    """Host-neutral structured-completion contract.

    `complete_structured` must return a ModelResponse — it must NOT raise
    for ordinary model failure. Structured output is mandatory (PRD §26):
    the caller supplies `response_schema` and the implementation is
    responsible for producing output that conforms to it (or reporting
    INVALID_OUTPUT).
    """

    @property
    def model_id(self) -> str: ...

    def complete_structured(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> ModelResponse: ...


# --- JSON schemas the model output must satisfy (PRD §26) -------------------

CLUSTERING_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["clusters"],
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "claim", "evidence_ids"],
                "properties": {
                    "label": {"type": "string", "minLength": 1},
                    "claim": {"type": "string", "minLength": 1},
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

CONTRADICTION_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["supporting_evidence_ids", "counter_evidence_ids"],
    "properties": {
        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "counter_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "kind": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
}

SEMANTIC_FACTORS_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["decision_relevance"],
    "properties": {
        "decision_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "decision_relevance_rationale": {"type": "string"},
        "semantic_novelty": {"type": "number", "minimum": 0, "maximum": 1},
        "commercial_intent": {"type": "number", "minimum": 0, "maximum": 1},
        "early_signal": {"type": "boolean"},
    },
}


# --- deterministic fake (PRD §40 step 2) -----------------------------------


@dataclass(frozen=True)
class FakeClusterScript:
    """One scripted cluster: what the fake model will say about it.

    `decision_relevance` defaults to 0.0 meaning "not assessed" — the
    fake never invents a neutral 0.5 (Phase 3 Closeout §3 invariant).
    """

    label: str
    claim: str
    evidence_ids: tuple[str, ...]
    confidence: float = 0.8
    rationale: str = ""
    decision_relevance: float = 0.0
    decision_relevance_rationale: str = ""
    semantic_novelty: float | None = None
    commercial_intent: float | None = None
    early_signal: bool | None = None
    supporting_evidence_ids: tuple[str, ...] | None = None
    counter_evidence_ids: tuple[str, ...] = ()
    contradiction_kind: str = CONTRADICTION_NONE
    contradiction_confidence: float = 0.0
    contradiction_rationale: str = ""


@dataclass
class FakeIntelligenceModel:
    """Deterministic, offline, scripted model. Used by every unit test and
    by the Phase 5 golden case — the default suite is 100% offline
    (PRD §5, Gate I).
    """

    scripts: Sequence[FakeClusterScript] = ()
    status: ModelStatus = ModelStatus.SUCCESS
    model_id: str = "fake:v1"
    calls: list[dict[str, Any]] = field(default_factory=list)

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
        if task == TASK_CLUSTERING:
            return self._clustering()
        if task == TASK_CONTRADICTION:
            return self._contradiction(payload)
        if task == TASK_SEMANTIC_FACTORS:
            return self._factors(payload)
        return ModelResponse(
            task=task,
            status=ModelStatus.INVALID_OUTPUT,
            error=f"unknown task: {task}",
        )

    # -- script lookup ---------------------------------------------------

    def _script_for(self, payload: Mapping[str, Any]) -> FakeClusterScript | None:
        cluster_id = str(payload.get("cluster_id") or "")
        if cluster_id:
            for script in self.scripts:
                if derive_cluster_id(script.evidence_ids) == cluster_id:
                    return script
        return None

    # -- tasks -----------------------------------------------------------

    def _clustering(self) -> ModelResponse:
        clusters = [
            {
                "label": s.label,
                "claim": s.claim,
                "evidence_ids": list(s.evidence_ids),
                "confidence": s.confidence,
                "rationale": s.rationale,
            }
            for s in self.scripts
        ]
        return ModelResponse(
            task=TASK_CLUSTERING,
            status=ModelStatus.SUCCESS,
            payload={"clusters": clusters},
        )

    def _contradiction(self, payload: Mapping[str, Any]) -> ModelResponse:
        script = self._script_for(payload)
        all_ids = [str(i) for i in (payload.get("evidence_ids") or [])]
        if script is None:
            # Unscripted cluster: everything supports, nothing contradicts.
            return ModelResponse(
                task=TASK_CONTRADICTION,
                status=ModelStatus.SUCCESS,
                payload={
                    "supporting_evidence_ids": all_ids,
                    "counter_evidence_ids": [],
                    "kind": CONTRADICTION_NONE,
                    "confidence": 0.0,
                    "rationale": "",
                },
            )
        support = (
            list(script.supporting_evidence_ids)
            if script.supporting_evidence_ids is not None
            else [i for i in all_ids if i not in set(script.counter_evidence_ids)]
        )
        return ModelResponse(
            task=TASK_CONTRADICTION,
            status=ModelStatus.SUCCESS,
            payload={
                "supporting_evidence_ids": support,
                "counter_evidence_ids": list(script.counter_evidence_ids),
                "kind": script.contradiction_kind,
                "confidence": script.contradiction_confidence,
                "rationale": script.contradiction_rationale,
            },
        )

    def _factors(self, payload: Mapping[str, Any]) -> ModelResponse:
        script = self._script_for(payload)
        if script is None:
            return ModelResponse(
                task=TASK_SEMANTIC_FACTORS,
                status=ModelStatus.SUCCESS,
                payload={
                    "decision_relevance": 0.0,
                    "decision_relevance_rationale": "not assessed",
                },
            )
        out: dict[str, Any] = {
            "decision_relevance": script.decision_relevance,
            "decision_relevance_rationale": script.decision_relevance_rationale,
        }
        if script.semantic_novelty is not None:
            out["semantic_novelty"] = script.semantic_novelty
        if script.commercial_intent is not None:
            out["commercial_intent"] = script.commercial_intent
        if script.early_signal is not None:
            out["early_signal"] = script.early_signal
        return ModelResponse(
            task=TASK_SEMANTIC_FACTORS, status=ModelStatus.SUCCESS, payload=out
        )


@dataclass
class FixtureIntelligenceModel:
    """Fixture-driven model: scripts are plain dicts so they can be loaded
    from a JSON/YAML fixture file (PRD §40 step 3). Same code path as
    FakeIntelligenceModel — there is no separate test-only parsing.
    """

    fixtures: Mapping[str, Any]
    status: ModelStatus = ModelStatus.SUCCESS
    model_id: str = "fixture:v1"
    calls: list[dict[str, Any]] = field(default_factory=list)

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
                task=task, status=self.status, error=f"fixture status {self.status.value}"
            )
        body = self.fixtures.get(task)
        if body is None:
            return ModelResponse(
                task=task,
                status=ModelStatus.INVALID_OUTPUT,
                error=f"no fixture for task {task}",
            )
        return ModelResponse(
            task=task, status=ModelStatus.SUCCESS, payload=dict(body)
        )


@dataclass
class FailingIntelligenceModel:
    """Always reports a failure status — used to prove degradation paths."""

    status: ModelStatus = ModelStatus.UNAVAILABLE
    model_id: str = "failing:v1"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete_structured(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> ModelResponse:
        self.calls.append({"task": task, "payload": dict(payload)})
        return ModelResponse(
            task=task, status=self.status, error=f"forced {self.status.value}"
        )
