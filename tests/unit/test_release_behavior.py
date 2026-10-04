import io
import json

from sourceglint.host_stdio import StdioHostSource
from sourceglint.pipeline.coverage import build_coverage_report
from sourceglint.brief.sections import _ref
from sourceglint.brief.selection import _coverage_lines


def test_bridge_reports_execution_without_treating_routed_targets_as_searched():
    answer = {"type": "source_response", "source": "host_web_search", "results": [],
              "searched_targets": [{"name": "reddit", "status": "no_results"}],
              "unanswered_parts": ["user complaints"], "limitations": ["No dated complaints found."]}
    output = io.StringIO()
    source = StdioHostSource("host_web_search", io.StringIO(json.dumps(answer)+"\n"), output)
    source.retrieve({"mode": "general"}, {"query": "AI agents", "query_language": "en"})
    assert source.coverage_reported
    assert source.searched_targets == [{"name": "reddit", "status": "no_results"}]
    assert source.unanswered_parts == ["user complaints"]
    assert "hacker_news" in {x["name"] for x in json.loads(output.getvalue())["targets"]}


def test_single_platform_and_unanswered_aspects_are_visible_in_coverage():
    records = [{"url": "https://www.producthunt.com/products/a", "window": "current"},
               {"url": "https://www.producthunt.com/products/b", "window": "current"}]
    report = build_coverage_report(
        requested_sources=["host_web_search"], attempted_sources=["host_web_search"],
        source_statuses={}, expanded_queries=[], raw_results=records,
        normalized_evidence=records, deduplicated_dropped=0, dropped_by_time_filter=0,
        kept_evidence=records, host_observations=[{"coverage_reported": True,
            "searched_targets": [{"name": "reddit", "status": "no_results"}],
            "unanswered_parts": ["user complaints"]}],
    )
    assert report.original_platforms == ("Product Hunt",)
    assert report.to_dict()["research_quality"] == "LIMITED"
    display = "\n".join(_coverage_lines(report))
    assert "user complaints" in display and "no independent cross-platform" in display
    assert "reddit" in display


def test_public_citation_preserves_original_platform_and_publication_date():
    citation = _ref({"ev1": {"source": "host_web_search", "url": "https://www.reddit.com/r/a/comments/1", "published_at": "2026-10-01T00:00:00Z"}}, "ev1")
    assert "[Reddit]" in citation
    assert "2026-10-01" in citation
    assert "host_web_search" not in citation
