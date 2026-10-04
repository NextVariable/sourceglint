"""Earlier retrieval gaps must survive clean later query variants."""
import pytest

from sourceglint.ledger import EvidenceLedger
from sourceglint.pipeline.adapters import AdapterRateLimited, RawSourceResult
from sourceglint.pipeline.degradation import SourceStatus
from sourceglint.pipeline.orchestrator import PipelineConfig, ResearchPipeline


@pytest.mark.parametrize("first_empty,last_error", [(False, False), (True, False), (False, True)])
def test_each_query_limit_is_preserved(monkeypatch, first_empty, last_error):
    import sourceglint.pipeline.orchestrator as module
    from types import SimpleNamespace
    monkeypatch.setattr(module, "build_retrieval_plans", lambda *args: [
        SimpleNamespace(source="reddit", query=q, query_language="en", market="global")
        for q in ("first", "later")
    ])

    class Adapter:
        limitations = []

        def retrieve(self, plan, request):
            self.limitations.clear()
            if request["query"] == "first":
                self.limitations.append("first query comments unavailable")
                if first_empty:
                    return []
            if request["query"] == "later" and last_error:
                self.limitations.append("later query rate limit")
                raise AdapterRateLimited(source="reddit", reason="429")
            return [RawSourceResult(source="reddit", source_type="post", source_native_id=request["query"],
                url="https://www.reddit.com/r/test/comments/" + request["query"],
                title="MCP security", text="MCP security report", published_at="2026-09-25T00:00:00Z")]

    source = {"name": "reddit", "enabled": True, "type": "community", "cost": "free",
        "auth_required": False, "credentials": [], "priority": 50, "capabilities": ["search"],
        "markets": ["global"], "languages": ["en"], "cache_ttl": 0}
    result = ResearchPipeline(config=PipelineConfig(as_of="2026-10-05T00:00:00Z"),
        adapter_factory=lambda *args: Adapter()).run(
        plan={"topic": "MCP security", "mode": "general", "languages": ["en"], "time_window": {"days": 30}},
        sources=[source], ledger=EvidenceLedger(":memory:"))
    report = result.source_statuses["reddit"]
    assert report.status == SourceStatus.PARTIAL
    assert "first query comments unavailable" in report.warnings
    if last_error:
        assert "later query rate limit" in report.warnings
    assert any("first query comments unavailable" in gap for gap in result.coverage.gaps)


def test_cached_retrieval_is_disclosed_and_partial_results_not_cached(monkeypatch):
    import sourceglint.pipeline.orchestrator as module
    from types import SimpleNamespace
    monkeypatch.setattr(module, "build_retrieval_plans", lambda *args: [
        SimpleNamespace(source="reddit", query=q, query_language="en", market="global", time_window={"days": 30})
        for q in ("cached", "live")
    ])
    row = RawSourceResult(source="reddit", source_type="post", source_native_id="cached",
        url="https://www.reddit.com/r/test/comments/cached", title="MCP security",
        text="MCP security report", published_at="2026-09-25T00:00:00Z")

    class Cache:
        writes = []
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return [row.to_dict()] if self.calls == 1 else None

        def set(self, *args, **kwargs):
            self.writes.append(args)

    class Adapter:
        limitations = []

        def retrieve(self, plan, request):
            assert request["query"] == "live"
            self.limitations.append("comments incomplete")
            return []

    cache = Cache()
    source = {"name": "reddit", "enabled": True, "type": "community", "cost": "free",
        "auth_required": False, "credentials": [], "priority": 50, "capabilities": ["search"],
        "markets": ["global"], "languages": ["en"], "cache_ttl": 900}
    result = ResearchPipeline(config=PipelineConfig(as_of="2026-10-05T00:00:00Z", cache=cache),
        adapter_factory=lambda *args: Adapter()).run(
        plan={"topic": "MCP security", "mode": "general", "languages": ["en"], "time_window": {"days": 30}},
        sources=[source], ledger=EvidenceLedger(":memory:"))
    assert not cache.writes
    assert any("cached retrieval" in gap for gap in result.coverage.gaps)
    assert any("comments incomplete" in gap for gap in result.coverage.gaps)
    assert result.coverage.to_dict()["research_quality"] == "LIMITED"
