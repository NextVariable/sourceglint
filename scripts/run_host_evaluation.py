"""Archive a real host-operated research run and its structured bridge trace.

Retrieval and reasoning must be supplied by the host; no canned answers are
generated here. Do not use this recording command with private material when
the destination will be committed publicly.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from sourceglint.application.api import run_sourceglint
from sourceglint.application.runtime import default_adapter_factory
from sourceglint.host_stdio import (
    StdioHostModel,
    StdioHostSource,
    prepare_stdio_terminal,
)
from sourceglint.resources import data_path
from sourceglint.ledger import EvidenceLedger


class CaptureStream:
    def __init__(self, stream, trace, direction, compact=False):
        self.stream, self.trace, self.direction = stream, trace, direction
        self.compact = compact

    def write(self, value):
        if value.strip():
            self.trace.write(
                json.dumps(
                    {
                        "monotonic_seconds": time.monotonic(),
                        "direction": self.direction,
                        "data": json.loads(value),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self.trace.flush()
            if self.compact and self.direction == "request":
                data = json.loads(value)
                if data.get("type") == "model_request":
                    summary = {
                        "type": "recorded_model_request",
                        "task": data["task"],
                        "trace": self.trace.name,
                        "response_schema": data["response_schema"],
                        "note": "Read the last request in the trace for the complete model payload before responding.",
                    }
                    return self.stream.write(
                        json.dumps(summary, ensure_ascii=False) + "\n"
                    )
        return self.stream.write(value)

    def flush(self):
        self.stream.flush()

    def readline(self):
        value = self.stream.readline()
        if value.strip():
            self.trace.write(
                json.dumps(
                    {
                        "monotonic_seconds": time.monotonic(),
                        "direction": self.direction,
                        "data": json.loads(value),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self.trace.flush()
        return value


parser = argparse.ArgumentParser()
parser.add_argument("--query", required=True)
parser.add_argument("--name", required=True)
parser.add_argument("--directory", required=True)
parser.add_argument("--as-of", required=True)
parser.add_argument("--decision-support", action="store_true")
parser.add_argument(
    "--direct-sources",
    default="",
    help="Comma-separated built-in sources; default is host-only.",
)
parser.add_argument(
    "--registry",
    help="Explicit source registry; allows the actual hybrid Skill profile.",
)
parser.add_argument(
    "--compact-requests",
    action="store_true",
    help="Print model-request summaries; full requests remain in the trace and must be read by the host.",
)
args = parser.parse_args()
prepare_stdio_terminal()
directory = Path(args.directory)
directory.mkdir(parents=True, exist_ok=True)
with (directory / (args.name + ".trace.jsonl")).open("w", encoding="utf-8") as trace:
    incoming = CaptureStream(sys.stdin, trace, "response")
    outgoing = CaptureStream(sys.stdout, trace, "request", args.compact_requests)
    model = StdioHostModel(incoming, outgoing)
    sources = yaml.safe_load(data_path("config", "sources-host.yaml").read_text())
    if args.registry:
        sources = yaml.safe_load(Path(args.registry).read_text())
    if args.direct_sources:
        requested = set(args.direct_sources.split(","))
        registry = (
            sources
            if args.registry
            else yaml.safe_load(data_path("config", "sources.yaml").read_text())
        )
        sources = [entry for entry in registry if entry["name"] in requested]
        unknown = requested - {entry["name"] for entry in sources}
        if unknown:
            parser.error("unknown direct sources: " + ", ".join(sorted(unknown)))
    ledger_path = directory / (args.name + ".evidence.jsonl")
    if ledger_path.exists() and ledger_path.stat().st_size:
        parser.error("choose a fresh --name; its evidence ledger already exists")
    ledger = EvidenceLedger(ledger_path)
    started = time.monotonic()

    def adapter_factory(name, plan):
        if args.direct_sources and name not in ("host_web_search", "official_web"):
            return default_adapter_factory(name, plan)
        return StdioHostSource(name, incoming, outgoing)

    result = run_sourceglint(
        args.query,
        as_of=args.as_of,
        model=model,
        sources=sources,
        adapter_factory=adapter_factory,
        decision_support=args.decision_support,
        ledger=ledger,
        raw_output=str(directory / (args.name + ".raw.jsonl")),
    )
    elapsed = time.monotonic() - started
artifact = {
    "query": args.query,
    "as_of": args.as_of,
    "model": "Codex current-session reasoning via host-stdio:v1",
    "elapsed_seconds": round(elapsed, 3),
    "latency_note": "Includes host search, reasoning and waiting between interactive bridge responses; not autonomous engine latency.",
    "result": result.to_dict(),
}
(directory / (args.name + ".json")).write_text(
    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(directory / (args.name + ".md")).write_text(result.brief_markdown, encoding="utf-8")
print(
    json.dumps(
        {
            "type": "evaluation_complete",
            "name": args.name,
            "status": result.status.value,
            "diagnostics": dict(result.diagnostics),
        },
        ensure_ascii=False,
    ),
    flush=True,
)
