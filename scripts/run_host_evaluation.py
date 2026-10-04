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
from sourceglint.host_stdio import StdioHostModel, StdioHostSource, prepare_stdio_terminal
from sourceglint.resources import data_path


class CaptureStream:
    def __init__(self, stream, trace, direction):
        self.stream, self.trace, self.direction = stream, trace, direction

    def write(self, value):
        if value.strip():
            self.trace.write(json.dumps({"direction": self.direction, "data": json.loads(value)}, ensure_ascii=False) + "\n")
            self.trace.flush()
        return self.stream.write(value)

    def flush(self):
        self.stream.flush()

    def readline(self):
        value = self.stream.readline()
        if value.strip():
            self.trace.write(json.dumps({"direction": self.direction, "data": json.loads(value)}, ensure_ascii=False) + "\n")
            self.trace.flush()
        return value


parser = argparse.ArgumentParser()
parser.add_argument("--query", required=True)
parser.add_argument("--name", required=True)
parser.add_argument("--directory", required=True)
parser.add_argument("--as-of", required=True)
parser.add_argument("--decision-support", action="store_true")
args = parser.parse_args()
prepare_stdio_terminal()
directory = Path(args.directory)
directory.mkdir(parents=True, exist_ok=True)
with (directory / (args.name + ".trace.jsonl")).open("w", encoding="utf-8") as trace:
    incoming = CaptureStream(sys.stdin, trace, "response")
    outgoing = CaptureStream(sys.stdout, trace, "request")
    model = StdioHostModel(incoming, outgoing)
    sources = yaml.safe_load(data_path("config", "sources-host.yaml").read_text())
    started = time.monotonic()
    result = run_sourceglint(
        args.query, as_of=args.as_of, model=model, sources=sources,
        adapter_factory=lambda name, plan: StdioHostSource(name, incoming, outgoing),
        decision_support=args.decision_support,
    )
    elapsed = time.monotonic() - started
artifact = {"query": args.query, "as_of": args.as_of, "model": "Codex current-session reasoning via host-stdio:v1", "elapsed_seconds": round(elapsed, 3), "latency_note": "Includes host search, reasoning and waiting between interactive bridge responses; not autonomous engine latency.", "result": result.to_dict()}
(directory / (args.name + ".json")).write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(directory / (args.name + ".md")).write_text(result.brief_markdown, encoding="utf-8")
print(json.dumps({"type": "evaluation_complete", "name": args.name, "status": result.status.value, "diagnostics": dict(result.diagnostics)}, ensure_ascii=False), flush=True)
