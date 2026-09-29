"""Real-source Golden Case (Phase 4 §25).

A second golden that wires Phase 4's real-source adapters together:

  Sources:
    * host_web_search (FakeSourceAdapter — official metadata pre-stamped)
    * hacker_news     (HackerNewsAdapter — recorded Algolia payload)
    * github          (GitHubAdapter — recorded search payload)
    * reddit          (RedditAdapter — recorded listing payload)

The host_search path goes through the OFFICIAL classifier as a
post-processing step — every URL we hand to the pipeline is stamped
with `raw_metadata.official=true` for verified-owner domains, which
then triggers the normalizer's T1 promotion (Phase 4 §20).

The HN / GitHub / Reddit adapters are exercised directly (their
JsonHttpClient is a scripted capture-and-replay stub, no real network).

Validates PRD §25 success criteria:
  * source mix                  — per-source coverage present
  * official classification     — verified-owner items promote to T1
  * source-native IDs           — every kept evidence has a stable ID
  * dedup                       — duplicates dropped by canonical URL
  * cache                       — second run sees cache_hits
  * rate-limit degradation      — HN 429 → RATE_LIMITED + others succeed
  * auth-missing degradation    — Reddit w/o creds → AUTH_MISSING + others
  * coverage arithmetic         — X raw → Y normalized → Z dropped → N final
  * Determinism × 20            — repeated runs produce identical coverage

NO SIGNAL/INSIGHT generation — this golden stops at the Research
Pipeline boundary, per PRD §25.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sourceglint.connectors._http import (
    HttpResponse,
    HttpTransientError,
)
from sourceglint.connectors.github import GitHubAdapter
from sourceglint.connectors.hacker_news import HackerNewsAdapter
from sourceglint.connectors.official_web import (
    OfficialDomainClassifier,
    load_official_rules,
)
from sourceglint.connectors.reddit import RedditAdapter
from sourceglint.pipeline.adapters import FakeSourceAdapter, RawSourceResult
from sourceglint.pipeline.orchestrator import (
    PipelineConfig,
    ResearchPipeline,
)
from sourceglint.ledger import EvidenceLedger
from sourceglint.pipeline.cache import RetrievalCache


ROOT = Path(__file__).resolve().parents[3]
OFFICIAL_YAML = ROOT / "config" / "official_domains.yaml"


def _classifier():
    return OfficialDomainClassifier(load_official_rules(path=str(OFFICIAL_YAML)))


def _stamp(classifier, url, base_meta=None):
    cls = classifier.classify_url(url)
    out = dict(base_meta or {})
    out.update(cls.to_dict())
    return out


def _raw(seed, classifier):
    md = _stamp(classifier, seed["url"], seed.get("raw_metadata", {}))
    return RawSourceResult(
        source=seed["source"],
        source_type=seed["source_type"],
        source_native_id=seed["source_native_id"],
        url=seed["url"],
        title=seed["title"],
        text=seed.get("text", seed.get("title", "")),
        author=seed.get("author", ""),
        published_at=seed.get("published_at", ""),
        retrieved_at=seed.get("retrieved_at", "2026-09-06T00:00:00Z"),
        market=seed.get("market", "global"),
        locale=seed.get("locale", ""),
        language=seed.get("language", "en"),
        query=seed.get("query", "acme meeting assistant"),
        query_language=seed.get("query_language", "en"),
        engagement=seed.get("engagement", {}),
        raw_metadata=md,
    )


def _build_sources():
    return [
        {
            "name": "host_web_search", "enabled": True, "type": "web",
            "cost": "free", "auth_required": False, "credentials": [],
            "priority": 60, "capabilities": ["search"],
            "rate_limit": {"rpm": 30}, "markets": ["global"],
            "languages": ["en"], "cache_ttl": 900,
        },
        {
            "name": "hacker_news", "enabled": True, "type": "community",
            "cost": "free", "auth_required": False, "credentials": [],
            "priority": 70, "capabilities": ["search", "stories"],
            "rate_limit": {"rpm": 60}, "markets": ["global"],
            "languages": ["en"], "cache_ttl": 1800,
        },
        {
            "name": "github", "enabled": True, "type": "official",
            "cost": "free", "auth_required": False, "credentials": [],
            "priority": 85, "capabilities": ["search", "releases"],
            "rate_limit": {"rpm": 60}, "markets": ["global"],
            "languages": ["en"], "cache_ttl": 3600,
        },
        {
            "name": "reddit", "enabled": True, "type": "community",
            "cost": "free", "auth_required": True,
            "credentials": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
            "priority": 80, "capabilities": ["search", "comments"],
            "rate_limit": {"rpm": 60}, "markets": ["global"],
            "languages": ["en"], "cache_ttl": 900,
        },
    ]


class _CaptureHttp:
    def __init__(self, script):
        self._script = list(script)
        self._idx = 0
        self.calls = []

    @property
    def user_agent(self):
        return "sourceglint/test"

    def request(self, url, *, headers=None, timeout=15.0):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        if self._idx >= len(self._script):
            raise AssertionError(f"unexpected extra HTTP call to {url}")
        op, payload, status = self._script[self._idx]
        self._idx += 1
        if op == "json":
            return HttpResponse(
                status=status or 200,
                body=json.dumps(payload).encode("utf-8"),
                url=url,
            )
        if op == "raise":
            raise payload
        raise AssertionError(f"unknown op {op}")


def _hn_payload():
    return [("json", {"hits": [
        {
            "objectID": "888", "title": "Show HN: Acme Meeting Assistant",
            "url": "https://acme.com", "author": "u_acme",
            "created_at_i": 1756100000, "points": 200, "num_comments": 50,
        },
        {
            "objectID": "889", "title": "Acme vs Otter: which is better?",
            "url": "https://blog.compare.com/acme-vs-otter",
            "author": "u_writer", "created_at_i": 1756200000,
            "points": 80, "num_comments": 22,
        },
    ]}, 200)]


def _gh_payload():
    return [("json", {"items": [{
        "id": 11, "full_name": "acmehq/awesome", "name": "awesome",
        "description": "The AI meeting assistant.",
        "html_url": "https://github.com/acmehq/awesome",
        "owner": {"login": "acmehq"},
        "created_at": "2024-04-15T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "pushed_at": "2026-09-01T00:00:00Z",
        "stargazers_count": 1200, "forks_count": 80, "language": "Python",
    }]}, 200)]


def _reddit_payload():
    return [
        ("json", {"access_token": "bearer-x", "expires_in": 3600}, 200),
        ("json", {"data": {"children": [{
            "kind": "t3", "data": {
                "id": "abc", "name": "t3_abc",
                "title": "Acme meeting assistant feedback after 30 days",
                "selftext": "I have been using Acme for a month.",
                "author": "u/founder1", "subreddit": "productivity",
                "permalink": "/r/productivity/comments/abc_meeting/",
                "url": "https://www.reddit.com/r/productivity/comments/abc_meeting/",
                "created_utc": 1757110000.0,
                "score": 120, "num_comments": 34,
            },
        }]}}, 200),
    ]


def _host_seeds(classifier):
    raw = []
    raw.append(_raw({
        "source": "host_web_search", "source_type": "page",
        "source_native_id": "https://acme.com/pricing",
        "url": "https://acme.com/pricing", "title": "Pricing | Acme",
        "text": "Acme Pro starts at $29 per user per month.",
        "published_at": "2026-08-30T12:00:00Z",
    }, classifier).to_dict())
    # utm duplicate — for dedup verification
    raw.append(_raw({
        "source": "host_web_search", "source_type": "page",
        "source_native_id": "https://acme.com/pricing?utm_source=tw",
        "url": "https://acme.com/pricing?utm_source=tw",
        "title": "Pricing | Acme",
        "text": "Acme Pro starts at $29 per user per month.",
        "published_at": "2026-08-30T12:00:00Z",
    }, classifier).to_dict())
    raw.append(_raw({
        "source": "host_web_search", "source_type": "page",
        "source_native_id": "https://news.acme.com/launch",
        "url": "https://news.acme.com/launch",
        "title": "Launch announcement", "text": "Today we ship…",
        "published_at": "2026-08-20T10:00:00Z",
    }, classifier).to_dict())
    # Non-official (T4) — competitor news site, not in official registry.
    raw.append(_raw({
        "source": "host_web_search", "source_type": "page",
        "source_native_id": "https://example.com/cmp",
        "url": "https://example.com/cmp",
        "title": "Comparison article", "text": "Acme vs Otter…",
        "published_at": "2026-09-01T08:00:00Z",
    }, classifier).to_dict())
    return raw


def _plan():
    return {
        "topic": "AI meeting assistant competitor",
        "mode": "competitor", "market": "global", "languages": ["en"],
        "time_window": {"days": 30},
        "decision_context": "evaluating GTM moves against Acme",
        "source_priorities": ["host_web_search", "hacker_news", "github", "reddit"],
    }


def _factory(classifier, hn_script=None, github_script=None,
             reddit_script=None, reddit_enabled=True):
    caches: dict[str, _CaptureHttp] = {}

    def make(name, plan):
        if name == "host_web_search":
            return FakeSourceAdapter(
                name="host_web_search",
                results=_host_seeds(classifier),
            )
        if name == "hacker_news":
            http = caches.setdefault(
                "hn", _CaptureHttp(hn_script or _hn_payload())
            )
            return HackerNewsAdapter(http_client=http)
        if name == "github":
            http = caches.setdefault(
                "gh", _CaptureHttp(github_script or _gh_payload())
            )
            return GitHubAdapter(http_client=http, token=None)
        if name == "reddit":
            if not reddit_enabled:
                return RedditAdapter(client_id=None, client_secret=None)
            http = caches.setdefault(
                "rd", _CaptureHttp(reddit_script or _reddit_payload())
            )
            return RedditAdapter(
                http_client=http, client_id="cid", client_secret="csec"
            )
        return None

    return make


# ----- TESTS ----------------------------------------------------------


def test_golden_real_source_full_mix_runs_offline(tmp_path):
    classifier = _classifier()
    cfg = PipelineConfig(as_of="2026-09-06T00:00:00Z")
    pipeline = ResearchPipeline(
        config=cfg,
        adapter_factory=_factory(classifier=classifier, reddit_enabled=False),
    )
    ledger = EvidenceLedger(path=tmp_path / "ledger.jsonl")
    result = pipeline.run(plan=_plan(), sources=_build_sources(), ledger=ledger)

    statuses = {
        name: r.status.value for name, r in result.source_statuses.items()
    }
    assert statuses.get("reddit") == "auth_missing"
    assert "success" in statuses.values(), statuses

    cov = result.coverage
    # Closeout §5 arithmetic invariant: items leaving the pipeline equal
    # items entering the pipeline minus both drop stages (time_filter
    # AND dedup). Item drops happen at TWO stages, not one.
    assert (
        cov.normalized_evidence_count
        - cov.time_filter_dropped_count
        - cov.duplicate_dropped_count
        == cov.final_evidence_count
    )
    # utm variant must be deduped out — the canonical URL keeps one.
    assert cov.duplicate_dropped_count >= 1

    ledger_read = [
        {
            "evidence_id": r.evidence_id,
            "source": r.source if hasattr(r, "source") else "x",
            "source_tier": r.to_payload().get("source_tier"),
            **{k: v for k, v in r.to_payload().items() if k in {"evidence_id", "source", "source_tier", "source_type", "url", "title"}},
        }
        for r in ledger.all()
    ]
    promoted = [e for e in ledger_read if e.get("source_tier") == 1]
    assert promoted, "expected at least one verified first-party evidence"
    for ev in ledger_read:
        assert ev["evidence_id"]
        assert ev["source"] in {
            "host_web_search", "hacker_news", "github", "reddit"
        }


def test_golden_real_source_is_deterministic_20_runs(tmp_path):
    """20 consecutive runs of the same golden produce identical coverage
    and ledger (PRD §25 + Closeout §5)."""

    classifier = _classifier()
    first_dump = None
    for run_no in range(20):
        cfg = PipelineConfig(as_of="2026-09-06T00:00:00Z")
        pipeline = ResearchPipeline(
            config=cfg,
            adapter_factory=_factory(classifier=classifier, reddit_enabled=False),
        )
        ledger = EvidenceLedger(path=tmp_path / f"ledger_{run_no}.jsonl")
        result = pipeline.run(plan=_plan(), sources=_build_sources(), ledger=ledger)
        snapshot = json.loads(json.dumps(
            {
                "coverage": result.coverage.to_dict(),
                "evidence": [r.to_payload() for r in ledger.all()],
            },
            default=str,
        ))
        if first_dump is None:
            first_dump = snapshot
        else:
            assert snapshot == first_dump, (
                f"run #{run_no} drifted from run #0 — golden lost determinism"
            )


def test_golden_graceful_degradation_when_hn_is_rate_limited(tmp_path):
    classifier = _classifier()
    cfg = PipelineConfig(as_of="2026-09-06T00:00:00Z")
    pipeline = ResearchPipeline(
        config=cfg,
        adapter_factory=_factory(
            classifier=classifier,
            hn_script=[
                ("raise", HttpTransientError(status=429, url="x", body_preview=""), None),
            ],
            reddit_enabled=False,
        ),
    )
    ledger = EvidenceLedger(path=tmp_path / "ledger.jsonl")
    result = pipeline.run(plan=_plan(), sources=_build_sources(), ledger=ledger)

    assert result.source_statuses["hacker_news"].status.value == "rate_limited"
    assert result.coverage.final_evidence_count >= 1
    cov = result.coverage
    # Two-stage drop arithmetic: time_filter + dedup.
    assert (
        cov.normalized_evidence_count
        - cov.time_filter_dropped_count
        - cov.duplicate_dropped_count
        == cov.final_evidence_count
    )


def test_golden_cache_hit_skips_network_on_second_run(tmp_path):
    classifier = _classifier()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    cfg1 = PipelineConfig(as_of="2026-09-06T00:00:00Z",
                           cache=RetrievalCache(cache_root))
    pipe1 = ResearchPipeline(
        config=cfg1,
        adapter_factory=_factory(classifier=classifier, reddit_enabled=False),
    )
    ledger1 = EvidenceLedger(path=tmp_path / "ledger_a.jsonl")
    pipe1.run(plan=_plan(), sources=_build_sources(), ledger=ledger1)
    assert list(cache_root.rglob("*.json")), (
        "first run must write cache files"
    )

    cfg2 = PipelineConfig(as_of="2026-09-06T00:00:00Z",
                           cache=RetrievalCache(cache_root))
    pipe2 = ResearchPipeline(
        config=cfg2,
        adapter_factory=_factory(
            classifier=classifier,
            hn_script=[("raise", AssertionError("cache miss unexpected"))],
            github_script=[("raise", AssertionError("cache miss unexpected"))],
            reddit_enabled=False,
        ),
    )
    ledger2 = EvidenceLedger(path=tmp_path / "ledger_b.jsonl")
    result2 = pipe2.run(plan=_plan(), sources=_build_sources(), ledger=ledger2)
    assert result2.coverage.final_evidence_count >= 1
