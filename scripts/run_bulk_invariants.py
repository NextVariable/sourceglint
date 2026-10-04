"""Seeded bulk invariants for evidence handling; not live/model quality tests."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
import time

from sourceglint.excerpts import MARKER, select_excerpt
from sourceglint.intelligence.dtos import PreparedEvidence, ValidatedCluster
from sourceglint.intelligence.features import derive_features
from sourceglint.intelligence.preparation import model_payloads
from sourceglint.pipeline.deduplication import deduplicate


def run(seed=20261005, cases=5000):
    rng = random.Random(seed)
    counts = {}
    for _ in range(cases):
        budget = rng.randint(150, 6000)
        prefix = rng.choice(["ß", "İ", "中文🙂", "日本語", "ordinary filler "])
        subject = rng.choice(["MCP security", "Obsidian plugins", "安全漏洞", "会議要約"])
        before = prefix * rng.randint(budget, budget * 3)
        after = prefix * rng.randint(budget, budget * 3)
        body = before + " " + subject + " substantive observation. " + after
        result = select_excerpt(body, subject, budget)
        assert len(result) <= budget, (seed, counts, "excerpt budget")
        assert subject in result, (seed, counts, "topic lost")
        assert MARKER in result, (seed, counts, "omission undisclosed")
        assert all(part in body for part in result.split(MARKER)), (seed, counts, "nonliteral text")
        assert result == select_excerpt(body, subject, budget), (seed, counts, "nondeterminism")
        counts["multilingual_excerpt_cases"] = counts.get("multilingual_excerpt_cases", 0) + 1

    for index in range(max(1, cases // 5)):
        # One physical record exposed under two route/native aliases.
        a = {"evidence_id": "ev-a", "url": f"https://a.example/{index}",
             "source": "reddit", "source_native_id": str(index), "snippet": "Actual quote"}
        b = {**a, "evidence_id": "ev-b", "url": f"https://b.example/{index}",
             "content": "Actual quote plus context " * rng.randint(2, 10)}
        c = {**b, "evidence_id": "ev-c", "source": "host_web_search", "source_native_id": ""}
        out = deduplicate([a, b, c, {**c, "query": "alternate query"}])
        assert out.kept_count == 1 and out.duplicate_count == 3
        assert out.kept[0]["snippet"] == "Actual quote"
        assert out.kept[0]["content"] == b["content"]
        assert out.provenance["ev-a"].retrieval_count == 4
        assert "content" not in a
        counts["cross_route_dedup_cases"] = counts.get("cross_route_dedup_cases", 0) + 1

    for index in range(max(1, cases // 5)):
        body = " ".join(f"observation-{index}-{j}" for j in range(rng.randint(20, 60)))
        a = PreparedEvidence("ev-a", "web", "page", "current", content=body, url="https://a.example/1")
        b = replace(a, evidence_id="ev-b", content=" \n".join(body.upper().split()), url="https://b.example/2")
        cluster = ValidatedCluster("cl-test", "Copied reporting", "a bounded claim", ("ev-a", "ev-b"), .8)
        features = derive_features(cluster, {"ev-a": a, "ev-b": b})
        assert features.independent_source_count == 1
        assert features.evidence_count == 2 and len(features.unique_domains) == 2
        counts["copied_origin_cases"] = counts.get("copied_origin_cases", 0) + 1

    for count in [1, 2, 8, 20, 50, 100, 200, 500, 1000]:
        items = [PreparedEvidence(str(i), "web", "page", "current",
                                 content="filler " * 1200 + " MCP security " + "tail " * 1200)
                 for i in range(count)]
        payload = model_payloads(items, topic="MCP security")
        assert sum(len(p.get("content", "")) for p in payload) <= 48000
        assert len(payload) == count
        if count <= 200:
            assert all("MCP security" in p["content"] for p in payload)
        counts["model_batch_budget_cases"] = counts.get("model_batch_budget_cases", 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--cases", type=int, default=5000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cases < 1:
        parser.error("--cases must be positive")
    started = time.monotonic()
    counts = run(args.seed, args.cases)
    result = {"seed": args.seed, "cases": counts, "total_cases": sum(counts.values()),
              "seconds": round(time.monotonic() - started, 3), "status": "PASS",
              "boundary": "Synthetic invariant tests; no live research or model reasoning is evaluated."}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
