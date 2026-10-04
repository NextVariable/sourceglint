"""Host-model bridge for an agent running the Skill in an interactive terminal.

The engine stays provider-neutral. Each semantic call is emitted as one JSON
line; the host agent supplies the corresponding structured response on stdin.
No model credentials or vendor client are required inside this package.
"""
from __future__ import annotations

import json
import sys
import atexit
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


def prepare_stdio_terminal() -> None:
    """Avoid OS canonical-line truncation of long JSON responses on a PTY."""
    if not sys.stdin.isatty():
        return
    try:
        import termios
        import tty
        descriptor = sys.stdin.fileno()
        original = termios.tcgetattr(descriptor)
        tty.setcbreak(descriptor)
        def restore():
            try:
                termios.tcsetattr(descriptor, termios.TCSADRAIN, original)
            except (OSError, termios.error):
                pass
        atexit.register(restore)
    except (ImportError, OSError):
        # Windows and redirected pipes do not use POSIX canonical PTY input.
        pass


def build_model() -> StdioHostModel:
    """Factory for ``--model sourceglint.host_stdio:build_model``."""
    prepare_stdio_terminal()
    return StdioHostModel()


@dataclass
class StdioHostSource:
    """Ask the host to retrieve one source query with its own tools."""

    name: str
    input_stream: TextIO = field(default_factory=lambda: sys.stdin)
    output_stream: TextIO = field(default_factory=lambda: sys.stdout)

    searched_targets: list[dict[str, str]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    unanswered_parts: list[str] = field(default_factory=list)
    coverage_reported: bool = False

    def retrieve(
        self, plan: Mapping[str, object], request: Mapping[str, object]
    ) -> list[RawSourceResult]:
        message: dict[str, Any] = {
            "type": "source_request", "source": self.name,
            "plan": dict(plan), "request": dict(request),
            "allowed_source_types": ["post", "comment", "review", "page", "release"],
            "coverage_response_fields": {
                "searched_targets": "array of {name, status: success|no_results|unavailable}",
                "limitations": "array of factual retrieval limitations",
                "unanswered_parts": "array of requested aspects without usable evidence",
            },
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
        targets = response.get("searched_targets")
        if targets is not None:
            if not isinstance(targets, list):
                raise AdapterInvalidResponse(self.name, "searched_targets must be an array")
            self.coverage_reported = True
            for target in targets:
                if (not isinstance(target, dict) or not target.get("name")
                        or target.get("status") not in {"success", "no_results", "unavailable"}):
                    raise AdapterInvalidResponse(self.name, "invalid searched target status")
                self.searched_targets.append({
                    "name": str(target["name"]), "status": str(target["status"]),
                })
        for field_name in ("limitations", "unanswered_parts"):
            values = response.get(field_name, [])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise AdapterInvalidResponse(self.name, f"{field_name} must be an array of strings")
            getattr(self, field_name).extend(values)
        items = response.get("results")
        if not isinstance(items, list):
            raise AdapterInvalidResponse(self.name, "results must be an array")
        out: list[RawSourceResult] = []
        for item in items:
            if not isinstance(item, dict):
                raise AdapterInvalidResponse(self.name, "result must be an object")
            try:
                source_type = str(item["source_type"])
                if source_type not in {"post", "comment", "review", "page", "release"}:
                    raise AdapterInvalidResponse(
                        self.name,
                        "source_type must be one of post, comment, review, page, release",
                    )
                out.append(RawSourceResult(
                    source=self.name,
                    source_type=source_type,
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
