"""Deterministic stub model for raw-payload negative tests.

FakeRecommendationModel cannot emit hallucinated ids or malformed
groups (it filters them), so negative-path tests (dedup / conflict)
drive a bare stub that returns an exact payload for every structured
call.
"""
from __future__ import annotations

from typing import Any, Mapping

from sourceglint.insights.model import ModelResponse, ModelStatus


class StubModel:
    """Minimal model returning a scripted payload per structured call."""

    def __init__(
        self,
        *,
        payload: Mapping[str, Any] | None = None,
        status: ModelStatus = ModelStatus.SUCCESS,
        error: str = "stub failure",
        model_id: str = "stub:v1",
    ):
        self._payload = dict(payload or {})
        self.status = status
        self.error = error
        self.model_id = model_id
        self.calls: list[dict] = []

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
                task=task, status=self.status, error=self.error
            )
        return ModelResponse(
            task=task, status=ModelStatus.SUCCESS, payload=self._payload
        )
