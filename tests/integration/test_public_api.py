"""The public entry point must preserve honest outcomes across stage boundaries."""

from datetime import datetime, timezone

import pytest

from gtm_intelligence.application.api import run_gtm_intelligence
from gtm_intelligence.intelligence.model import FakeIntelligenceModel, ModelResponse, ModelStatus
from gtm_intelligence.interface.result import Status
from gtm_intelligence.pipeline.adapters import FakeSourceAdapter
from gtm_intelligence.recommendations.model import FakeRecommendationModel


SOURCE = {
    "name": "hacker_news",
    "enabled": True,
    "type": "community",
    "cost": "free",
    "auth_required": False,
    "credentials": [],
    "priority": 70,
    "capabilities": ["search"],
    "markets": ["global"],
    "languages": ["en"],
    "cache_ttl": 900,
}
AS_OF = datetime(2026, 9, 9, tzinfo=timezone.utc)


class OneFactModel(FakeRecommendationModel):
    """Use references supplied by the preceding stage, as a host model would."""

    def complete_structured(self, *, task, payload, response_schema):
        if task == "clustering":
            ids = [item["evidence_id"] for item in payload["evidence_items"]]
            return ModelResponse(task=task, status=ModelStatus.SUCCESS, payload={
                "clusters": [{"label": "AI product discussion", "claim": "AI product discussion",
                              "evidence_ids": ids, "confidence": 0.8}],
            })
        if task == "fact_synthesis":
            signal = payload["signals"][0]
            return ModelResponse(task=task, status=ModelStatus.SUCCESS, payload={
                "facts": [{"statement": "A new AI product was discussed by users.",
                           "signal_ids": [signal["signal_id"]],
                           "evidence_ids": signal["evidence_ids"], "confidence": 0.7}],
            })
        if task == "recommendation_generation":
            insight_id = payload["insights"][0]["insight_id"]
            return ModelResponse(task=task, status=ModelStatus.SUCCESS, payload={
                "recommendations": [{
                    "statement": "Validate interest in the new AI product.",
                    "action": "Interview users about the AI product.",
                    "supporting_insight_ids": [insight_id],
                    "action_class": "validate", "gtm_dimensions": ["product"],
                    "confidence": 0.5, "action_anchor": "user interviews",
                }],
            })
        return super().complete_structured(task=task, payload=payload,
                                           response_schema=response_schema)


def test_api_requires_host_timestamp():
    with pytest.raises(ValueError, match="as_of is required"):
        run_gtm_intelligence("Recent AI products", model=FakeIntelligenceModel())


def test_api_reports_no_evidence_without_inventing_a_finding():
    result = run_gtm_intelligence(
        "Recent AI products",
        model=FakeIntelligenceModel(),
        sources=[SOURCE],
        adapter_factory=lambda name, plan: FakeSourceAdapter(name=name),
        as_of=AS_OF,
    )
    assert result.status is Status.NO_EVIDENCE
    assert "No usable evidence was retrieved" in result.brief_markdown
    assert result.diagnostics["evidence_count"] == 0
    assert result.stage_statuses["signals"] == "skipped"


def test_discovery_only_no_evidence_uses_research_title():
    result = run_gtm_intelligence(
        "What new AI tools are people discussing?", discovery_only=True,
        model=FakeIntelligenceModel(), sources=[SOURCE],
        adapter_factory=lambda name, plan: FakeSourceAdapter(name=name),
        as_of=AS_OF,
    )
    assert result.status is Status.NO_EVIDENCE
    assert result.brief_markdown.startswith("# Recent Intelligence Brief")
    assert result.stage_statuses["recommendations"] == "skipped"


def test_api_keeps_evidence_when_no_signal_is_supported():
    adapter = FakeSourceAdapter(
        name="hacker_news",
        results=[{
            "source": "hacker_news",
            "source_type": "post",
            "source_native_id": "123",
            "url": "https://news.ycombinator.com/item?id=123",
            "title": "AI product discussion",
            "text": "A new AI product was discussed by users.",
            "published_at": "2026-09-08T12:00:00Z",
        }],
    )
    result = run_gtm_intelligence(
        "Recent AI products",
        model=FakeIntelligenceModel(),
        sources=[SOURCE],
        adapter_factory=lambda name, plan: adapter,
        as_of=AS_OF,
    )
    assert result.status is Status.PARTIAL
    assert result.diagnostics["evidence_count"] == 1
    assert result.diagnostics["signal_count"] == 0
    assert result.brief_markdown


def test_public_api_runs_evidence_through_to_a_cited_brief():
    adapter = FakeSourceAdapter(name="hacker_news", results=[{
        "source": "hacker_news", "source_type": "post", "source_native_id": "123",
        "url": "https://news.ycombinator.com/item?id=123",
        "title": "AI product discussion",
        "text": "A new AI product was discussed by users.",
        "published_at": "2026-09-08T12:00:00Z",
    }])
    result = run_gtm_intelligence(
        "Recent AI products", model=OneFactModel(), sources=[SOURCE],
        adapter_factory=lambda name, plan: adapter, as_of=AS_OF,
    )
    assert result.diagnostics["evidence_count"] == 1
    assert result.diagnostics["signal_count"] == 1
    assert result.diagnostics["insight_count"] == 1
    assert result.diagnostics["recommendation_count"] == 1
    assert "A new AI product was discussed by users." in result.brief_markdown
    assert "Interview users about the AI product." in result.brief_markdown
    assert "https://news.ycombinator.com/item?id=123" in result.brief_markdown


def test_discovery_only_preserves_findings_without_unrequested_action():
    adapter = FakeSourceAdapter(name="hacker_news", results=[{
        "source": "hacker_news", "source_type": "post", "source_native_id": "123",
        "url": "https://news.ycombinator.com/item?id=123",
        "title": "AI product discussion",
        "text": "A new AI product was discussed by users.",
        "published_at": "2026-09-08T12:00:00Z",
    }])
    result = run_gtm_intelligence(
        "What new AI products are people discussing?",
        discovery_only=True, model=OneFactModel(), sources=[SOURCE],
        adapter_factory=lambda name, plan: adapter, as_of=AS_OF,
    )
    assert result.diagnostics["evidence_count"] == 1
    assert result.diagnostics["insight_count"] == 1
    assert result.diagnostics["recommendation_count"] == 0
    assert result.stage_statuses["recommendations"] == "skipped"
    assert result.brief_markdown.startswith("# Recent Intelligence Brief")
    assert "A new AI product was discussed by users." in result.brief_markdown
    assert "Interview users about the AI product." not in result.brief_markdown
    assert "No recommendation met the support threshold" not in result.brief_markdown
    assert "https://news.ycombinator.com/item?id=123" in result.brief_markdown
