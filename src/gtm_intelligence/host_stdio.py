"""Host-model bridge for an agent running the Skill in an interactive terminal.

The engine stays provider-neutral. Each semantic call is emitted as one JSON
line; the host agent supplies the corresponding structured response on stdin.
No model credentials or vendor client are required inside this package.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping, TextIO

import jsonschema

from .intelligence.model import ModelResponse, ModelStatus
from .pipeline.adapters import AdapterInvalidResponse, AdapterUnavailable, RawSourceResult


@dataclass
class StdioHostModel:
    input_stream: TextIO = field(default_factory=lambda: sys.stdin)
    output_stream: TextIO = field(default_factory=lambda: sys.stdout)
    model_id: str = "host-stdio:v1"

    def complete_structured(
        self,
        *,
        task: str,
        payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> ModelResponse:
        request = {
            "type": "model_request",
            "task": task,
            "payload": dict(payload),
            "response_schema": dict(response_schema),
        }
        self.output_stream.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.output_stream.flush()

        line = self.input_stream.readline()
        if not line:
            return ModelResponse(task=task, status=ModelStatus.UNAVAILABLE,
                                 error="host input closed before a model response")
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            return ModelResponse(task=task, status=ModelStatus.INVALID_OUTPUT,
                                 error="host response was not JSON")
        if not isinstance(response, dict) or response.get("type") != "model_response":
            return ModelResponse(task=task, status=ModelStatus.INVALID_OUTPUT,
                                 error="expected a model_response object")
        if response.get("task") != task:
            return ModelResponse(task=task, status=ModelStatus.INVALID_OUTPUT,
                                 error="host response task did not match request")
        if response.get("error"):
            return ModelResponse(task=task, status=ModelStatus.UNAVAILABLE,
                                 error=str(response["error"]))
        answer = response.get("payload")
        if not isinstance(answer, dict):
            return ModelResponse(task=task, status=ModelStatus.INVALID_OUTPUT,
                                 error="host response payload must be an object")
        try:
            jsonschema.validate(answer, response_schema)
        except jsonschema.ValidationError as exc:
            return ModelResponse(task=task, status=ModelStatus.INVALID_OUTPUT,
                                 error=f"host response failed schema: {exc.message}")
        return ModelResponse(task=task, status=ModelStatus.SUCCESS, payload=answer)


def build_model() -> StdioHostModel:
    """Factory for ``--model gtm_intelligence.host_stdio:build_model``."""
    return StdioHostModel()


@dataclass
class StdioHostSource:
    """Ask the host to retrieve one source query with its own tools."""

    name: str
    input_stream: TextIO = field(default_factory=lambda: sys.stdin)
    output_stream: TextIO = field(default_factory=lambda: sys.stdout)

    def retrieve(
        self, plan: Mapping[str, object], request: Mapping[str, object]
    ) -> list[RawSourceResult]:
        message: dict[str, Any] = {
            "type": "source_request", "source": self.name,
            "plan": dict(plan), "request": dict(request),
        }
        if self.name == "host_web_search":
            try:
                from .source_catalog import (
                    load_source_catalog,
                    select_host_search_targets,
                )

                targets = select_host_search_targets(
                    load_source_catalog(),
                    mode=str(plan.get("mode") or "general"),
                    market=str(plan.get("market") or "global"),
                    language=str(request.get("query_language") or "en"),
                )
                message["targets"] = [t.to_host_request() for t in targets]
            except Exception as exc:
                # Catalog enrichment must not make the original host bridge
                # unusable. The final report will still show actual coverage.
                message["target_warning"] = f"source catalog unavailable: {type(exc).__name__}"
        self.output_stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.output_stream.flush()
        line = self.input_stream.readline()
        if not line:
            raise AdapterUnavailable(self.name, "host input closed")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterInvalidResponse(self.name, "host response was not JSON") from exc
        if not isinstance(response, dict) or response.get("type") != "source_response":
            raise AdapterInvalidResponse(self.name, "expected source_response")
        if response.get("source") != self.name:
            raise AdapterInvalidResponse(self.name, "source name mismatch")
        if response.get("error"):
            raise AdapterUnavailable(self.name, str(response["error"]))
        items = response.get("results")
        if not isinstance(items, list):
            raise AdapterInvalidResponse(self.name, "results must be an array")
        out: list[RawSourceResult] = []
        for item in items:
            if not isinstance(item, dict):
                raise AdapterInvalidResponse(self.name, "result must be an object")
            try:
                out.append(RawSourceResult(
                    source=self.name,
                    source_type=str(item["source_type"]),
                    source_native_id=str(item["source_native_id"]),
                    url=str(item["url"]),
                    title=str(item["title"]),
                    text=str(item["text"]),
                    author=str(item.get("author") or ""),
                    published_at=str(item.get("published_at") or ""),
                    market=str(item.get("market") or ""),
                    language=str(item.get("language") or ""),
                    query=str(request.get("query") or ""),
                    query_language=str(request.get("query_language") or ""),
                    raw_metadata={"official": self.name == "official_web"},
                ))
            except KeyError as exc:
                raise AdapterInvalidResponse(self.name, f"missing result field: {exc}") from exc
        return out
