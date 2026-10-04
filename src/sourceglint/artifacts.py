"""Opt-in raw source recording, separate from validated, retained evidence."""
from __future__ import annotations

import json
from pathlib import Path


class RecordedSource:
    """Keep the retrieved body and provider metadata before normalization.

    Forward host coverage and adapter attributes unchanged. These raw records
    may be outside the time window or unusable; they are not validated findings.
    """

    def __init__(self, adapter, path: Path):
        self.adapter, self.path = adapter, path

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def retrieve(self, plan, request):
        results = self.adapter.retrieve(plan=plan, request=request)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            for item in results:
                record = {"record_kind": "unvalidated_source_observation", "retrieved_at": request.get("retrieved_at"), "query": request.get("query"), "record": item.to_dict()}
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return results


def recording_factory(factory, path: str | Path):
    target = Path(path)
    if target.exists() and target.stat().st_size:
        raise ValueError("raw output must be empty or new; choose a fresh path for this research run")

    def build(name, plan):
        adapter = factory(name, plan)
        return RecordedSource(adapter, target) if adapter is not None else None

    return build
