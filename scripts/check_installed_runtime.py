"""Exercise installed runtime resources and the API from outside the checkout.

This is a packaging smoke with synthetic input, not a live research-quality test.
Run with the Python interpreter from the clean wheel installation.
"""
import io
import json

from sourceglint.application.api import run_sourceglint
from sourceglint.application.runtime import default_sources
from sourceglint.host_stdio import StdioHostModel
from sourceglint.insights.prompts import get_insight_prompt
from sourceglint.intelligence.prompts import get_prompt
from sourceglint.pipeline.adapters import FakeSourceAdapter
from sourceglint.pipeline.source_registry import load_registry
from sourceglint.resources import data_path
from sourceglint.source_catalog import load_source_catalog

assert len(load_source_catalog()) >= 50
assert default_sources()
registry = load_registry(path=data_path("config", "sources-host.yaml"))
assert registry.entries
assert get_insight_prompt("fact_synthesis").render()
assert get_prompt("clustering").render()

model = StdioHostModel(io.StringIO(json.dumps({"type": "model_response", "task": "clustering", "payload": {"clusters": []}}) + "\n"), io.StringIO())
item = {"source_type": "post", "source_native_id": "packaging-smoke", "url": "https://example.com/packaging-smoke", "title": "Synthetic packaging check", "text": "Synthetic source observation, not real research.", "published_at": "2026-10-01T00:00:00Z", "language": "en"}
result = run_sourceglint(
    "packaging resource check", model=model, as_of="2026-10-04T00:00:00Z",
    sources=[{"name": "host_web_search", "enabled": True, "type": "web", "cost": "free", "auth_required": False, "credentials": [], "priority": 60, "capabilities": ["search"], "markets": ["global"], "languages": ["en"], "cache_ttl": 0, "max_queries_per_run": 1}],
    adapter_factory=lambda name, plan: FakeSourceAdapter(name, [item]),
)
assert result.diagnostics["evidence_count"] == 1
assert "Synthetic" in result.brief_markdown
assert "2026-10-01" in result.brief_markdown
assert result.diagnostics["recommendation_count"] == 0
print("PASS: installed resources, validation, source normalization, API and evidence fallback")
